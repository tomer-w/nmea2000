from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .ioclient import (
    AsyncIOClient,
    EByteNmea2000Gateway,
    PythonCanAsyncIOClient,
    State,
    TextNmea2000Gateway,
    WaveShareNmea2000Gateway,
)
from .input_formats import N2KFormat
from .message import IsoName, NMEA2000Field, NMEA2000Message

logger = logging.getLogger(__name__)

MessageCallback = Callable[[NMEA2000Message], Awaitable[None]]
StatusCallback = Callable[[State], Awaitable[None]]

MANAGEMENT_PGNS = frozenset({59392, 59904, 60928, 126208, 126464, 126993, 126996, 126998})


@dataclass
class DiscoveredDevice:
    """State tracked for another device observed on the NMEA 2000 bus."""

    source: int
    last_seen: datetime | None = None
    address_claim: NMEA2000Message | None = None
    product_information: NMEA2000Message | None = None
    configuration_information: NMEA2000Message | None = None


class N2KDevice:
    """High-level async NMEA 2000 device wrapper with address-claim handling."""

    def __init__(
        self,
        client: AsyncIOClient,
        *,
        preferred_address: int = 100, # A commonly unused address
        unique_number: int | None = None, 
        manufacturer_code: int = 999, # A nonexistent manufacturer code
        device_function: int = 130, # PC Gateway
        device_class: int = 25, # Inter/Intra Network Device
        device_instance_lower: int = 0,
        device_instance_upper: int = 0,
        system_instance: int = 0,
        industry_group: int = 4, # Marine
        arbitrary_address_capable: bool = True,
        product_code: int = 667,
        nmea2000_version: int = 1300,
        model_id: str = "nmea2000",
        model_version: str = "nmea2000",
        model_serial_code: str | None = None,
        software_version_code: str | None = None,
        certification_level: int = 0,
        load_equivalency: int = 1,
        installation_description1: str = "",
        installation_description2: str = "",
        manufacturer_information: str = "",
        transmit_pgns: list[int] | None = None,
        address_claim_detection_time: float = 5.0,
        address_claim_startup_delay: float = 1.0,
        heartbeat_interval: float = 60.0,
        persistence_path: str | Path | None = None,
        persistence_key: str = "default",
        disable_naks: bool = False,
    ):
        """Create a device around an async transport client and local device identity."""
        self.client = client
        self.client.set_receive_callback(self._handle_client_message)
        self.client.set_status_callback(self._handle_client_status)

        self._receive_callback: MessageCallback | None = None
        self._raw_receive_callback: MessageCallback | None = None
        self._status_callback: StatusCallback | None = None

        self.disable_naks = disable_naks
        self.address_claim_detection_time = address_claim_detection_time
        self.address_claim_startup_delay = address_claim_startup_delay
        self.heartbeat_interval = heartbeat_interval
        self._started = False
        self._ready = False
        self._ready_event = asyncio.Event()
        self._startup_task: asyncio.Task[None] | None = None
        self._claim_ready_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._closing = False
        self.heartbeat_counter = 0
        self.devices: dict[int, DiscoveredDevice] = {}

        self.persistence_path = self._resolve_persistence_path(persistence_path, persistence_key)
        persisted = self._load_persistence_data()
        self.unique_number = unique_number if unique_number is not None else int(persisted.get("uniqueNumber", self._generate_unique_number()))
        self.address = int(persisted.get("lastAddress", preferred_address))

        self.manufacturer_code = manufacturer_code
        self.device_function = device_function
        self.device_class = device_class
        self.device_instance_lower = device_instance_lower
        self.device_instance_upper = device_instance_upper
        self.system_instance = system_instance
        self.industry_group = industry_group
        self.arbitrary_address_capable = arbitrary_address_capable
        self._own_name = IsoName.pack_name_from_message(self._build_address_claim_message())

        self.product_code = product_code
        self.nmea2000_version = nmea2000_version
        self.model_id = model_id
        self.model_version = model_version
        self.model_serial_code = model_serial_code or str(self.unique_number)
        self.software_version_code = software_version_code or self._get_package_version()
        self.certification_level = certification_level
        self.load_equivalency = load_equivalency
        self.installation_description1 = installation_description1
        self.installation_description2 = installation_description2
        self.manufacturer_information = manufacturer_information
        self.transmit_pgns = sorted(set(transmit_pgns or ()).union(MANAGEMENT_PGNS))

        self._persist(unique_number=self.unique_number)

    @property
    def state(self) -> State:
        """Return the current connection state of the underlying client."""
        return self.client.state

    @property
    def ready(self) -> bool:
        """Return ``True`` once the device has claimed an address and is ready to send."""
        return self._ready

    def set_receive_callback(self, callback: Optional[MessageCallback]) -> None:
        """Register a callback for non-management messages delivered to this device."""
        self._receive_callback = callback

    def set_raw_receive_callback(self, callback: Optional[MessageCallback]) -> None:
        """Register a callback for every received message before management handling."""
        self._raw_receive_callback = callback

    def set_status_callback(self, callback: Optional[StatusCallback]) -> None:
        """Register a callback for underlying client state changes."""
        self._status_callback = callback

    @classmethod
    def for_ebyte(
        cls,
        host: str,
        port: int,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> "N2KDevice":
        """Create a device that communicates through an EByte TCP gateway."""
        client = EByteNmea2000Gateway(host, port, **cls._prepare_client_options(client_options))
        return cls(client, **device_options)

    @classmethod
    def for_text_gateway(
        cls,
        host: str,
        port: int,
        format: "N2KFormat",
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> "N2KDevice":
        """Create a device that communicates through a text/line-based TCP gateway.

        Args:
            host: Server hostname or IP address.
            port: Server port number.
            format: The N2KFormat used by the gateway (e.g. CAN_FRAME_ASCII, N2K_ASCII_RAW).
        """
        client = TextNmea2000Gateway(host, port, format=format, **cls._prepare_client_options(client_options))
        return cls(client, **device_options)

    @classmethod
    def for_waveshare(
        cls,
        port: str,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> "N2KDevice":
        """Create a device that communicates through a Waveshare USB-CAN gateway."""
        client = WaveShareNmea2000Gateway(port, **cls._prepare_client_options(client_options))
        return cls(client, **device_options)

    @classmethod
    def for_python_can(
        cls,
        interface: str,
        channel: str,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> "N2KDevice":
        """Create a device that communicates through a ``python-can`` interface."""
        client_kwargs = cls._prepare_client_options(client_options)
        client = PythonCanAsyncIOClient(interface, channel, **client_kwargs)
        return cls(client, **device_options)

    @classmethod
    def for_n2k_ascii(
        cls,
        host: str,
        port: int,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> "N2KDevice":
        """Convenience shortcut for ``for_text_gateway`` with N2K_ASCII_RAW format."""
        from .input_formats import N2KFormat
        return cls.for_text_gateway(host, port, N2KFormat.N2K_ASCII_RAW,
                                    client_options=client_options, **device_options)

    async def start(self) -> None:
        """Connect the client and begin the device startup/address-claim sequence."""
        self._started = True
        await self.client.connect()

    async def close(self) -> None:
        """Stop background tasks, mark the device not ready, and close the client."""
        self._closing = True
        self._started = False
        self._set_not_ready()
        await self._cancel_task(self._startup_task)
        await self._cancel_task(self._claim_ready_task)
        await self._cancel_task(self._heartbeat_task)
        await self.client.close()

    async def wait_ready(self, timeout: float | None = None) -> bool:
        """Wait until the device has successfully claimed an address."""
        if timeout is None:
            await self._ready_event.wait()
            return True
        await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        return True

    async def send(self, nmea2000_message: NMEA2000Message) -> None:
        """Send a message, substituting the claimed source address when ``source`` is ``0``."""
        if not self.ready:
            raise RuntimeError("Device has not claimed an address yet")
        if nmea2000_message.source == 0:
            nmea2000_message.source = self.address
        await self.client.send(nmea2000_message)

    async def _handle_client_status(self, state: State) -> None:
        if state != State.CONNECTED:
            self._set_not_ready()
            await self._cancel_task(self._claim_ready_task)
            await self._cancel_task(self._heartbeat_task)

        if state == State.CONNECTED and self._started and not self._closing:
            await self._schedule_startup_claim()

        if self._status_callback is not None:
            try:
                await self._status_callback(state)
            except Exception as exc:
                logger.error("Error in device status callback: %s", exc, exc_info=True)

    async def _handle_client_message(self, message: NMEA2000Message) -> None:
        self._remember_device(message)

        if self._raw_receive_callback is not None:
            try:
                await self._raw_receive_callback(message)
            except Exception as exc:
                logger.error("Error in raw receive callback: %s", exc, exc_info=True)

        if message.PGN in MANAGEMENT_PGNS:
            await self._handle_management_message(message)
            return

        if self._receive_callback is not None:
            try:
                await self._receive_callback(message)
            except Exception as exc:
                logger.error("Error in receive callback: %s", exc, exc_info=True)

    async def _handle_management_message(self, message: NMEA2000Message) -> None:
        if message.PGN == 60928:
            await self._handle_iso_address_claim(message)
            return

        if message.PGN == 126996:
            self._get_or_create_discovered_device(message.source).product_information = message
            return

        if message.PGN == 126998:
            self._get_or_create_discovered_device(message.source).configuration_information = message
            return

        if not self._should_process_management_message(message):
            return

        if message.PGN == 59904 and self.ready:
            await self._handle_iso_request(message)
            return

        if message.PGN == 126208 and self.ready:
            await self._handle_group_function(message)

    async def _schedule_startup_claim(self) -> None:
        await self._cancel_task(self._startup_task)
        self._startup_task = asyncio.create_task(self._startup_claim_sequence())

    async def _startup_claim_sequence(self) -> None:
        self._set_not_ready()
        await self._cancel_task(self._claim_ready_task)
        await self._cancel_task(self._heartbeat_task)
        await self.client.send(self._build_iso_request_message(60928, source=254))
        if self.address_claim_startup_delay > 0:
            await asyncio.sleep(self.address_claim_startup_delay)
        await self._send_address_claim()

    async def _send_address_claim(self) -> None:
        if self._address_is_occupied(self.address):
            self._increase_address()

        await self.client.send(self._build_address_claim_message())
        await self._cancel_task(self._claim_ready_task)
        self._claim_ready_task = asyncio.create_task(self._mark_ready_after_claim())

    async def _mark_ready_after_claim(self) -> None:
        if self.address_claim_detection_time > 0:
            await asyncio.sleep(self.address_claim_detection_time)

        self._ready = True
        self._ready_event.set()
        self._persist(lastAddress=self.address)
        await self._announce_startup_messages()
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _announce_startup_messages(self) -> None:
        await self.client.send(self._build_product_information_message())
        if self._has_configuration_information():
            await self.client.send(self._build_configuration_information_message())

    async def _heartbeat_loop(self) -> None:
        while self._started and not self._closing:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._started or self._closing:
                return
            if self.ready:
                await self.client.send(self._build_heartbeat_message())

    async def _handle_iso_request(self, message: NMEA2000Message) -> None:
        requested_pgn = message.get_field_int_value_by_id("pgn")
        if requested_pgn == 60928:
            await self.client.send(self._build_address_claim_message())
            return
        if requested_pgn == 126996:
            await self.client.send(self._build_product_information_message())
            return
        if requested_pgn == 126998 and self._has_configuration_information():
            await self.client.send(self._build_configuration_information_message())
            return
        if requested_pgn == 126464:
            await self.client.send(self._build_pgn_list_message(message.source))
            return
        if not self.disable_naks:
            await self.client.send(self._build_iso_nak_message(message.source, requested_pgn))

    async def _handle_group_function(self, message: NMEA2000Message) -> None:
        if self.disable_naks:
            return
        if message.id not in {"nmeaRequestGroupFunction", "nmeaCommandGroupFunction"}:
            return
        requested_pgn = message.get_field_int_value_by_id("pgn")
        await self.client.send(self._build_group_function_ack_message(message.source, requested_pgn))

    async def _handle_iso_address_claim(self, message: NMEA2000Message) -> None:
        source = message.source
        if not self.ready or source != self.address:
            discovered = self._get_or_create_discovered_device(source)
            discovered.address_claim = message
            return

        received_name = IsoName.pack_name_from_message(message)
        if self._own_name < received_name:
            await self._send_address_claim()
        elif self._own_name > received_name:
            discovered = self._get_or_create_discovered_device(source)
            discovered.address_claim = message
            self._increase_address()
            await self._send_address_claim()

    def _should_process_management_message(self, message: NMEA2000Message) -> bool:
        return message.destination == 255 or (self.ready and message.destination == self.address)

    def _remember_device(self, message: NMEA2000Message) -> None:
        discovered = self._get_or_create_discovered_device(message.source)
        discovered.last_seen = message.timestamp

    def _get_or_create_discovered_device(self, source: int) -> DiscoveredDevice:
        discovered = self.devices.get(source)
        if discovered is None:
            discovered = DiscoveredDevice(source=source)
            self.devices[source] = discovered
        return discovered

    def _address_is_occupied(self, address: int) -> bool:
        discovered = self.devices.get(address)
        if discovered is None or discovered.address_claim is None:
            return False
        return IsoName.pack_name_from_message(discovered.address_claim) != self._own_name

    def _increase_address(self) -> None:
        start_address = self.address
        while True:
            self.address = (self.address + 1) % 253
            if self.address == start_address or not self._address_is_occupied(self.address):
                return

    def _set_not_ready(self) -> None:
        self._ready = False
        self._ready_event.clear()

    def _build_iso_request_message(self, requested_pgn: int, *, source: int | None = None, destination: int = 255) -> NMEA2000Message:
        return NMEA2000Message(
            PGN=59904,
            id="isoRequest",
            description="ISO Request",
            source=self.address if source is None else source,
            destination=destination,
            priority=6,
            fields=[NMEA2000Field("pgn", value=requested_pgn, raw_value=requested_pgn)],
        )

    def _build_address_claim_message(self) -> NMEA2000Message:
        yes_no = 1 if self.arbitrary_address_capable else 0
        return NMEA2000Message(
            PGN=60928,
            id="isoAddressClaim",
            description="ISO Address Claim",
            source=self.address,
            destination=255,
            priority=6,
            fields=[
                NMEA2000Field("uniqueNumber", value=self.unique_number, raw_value=self.unique_number),
                NMEA2000Field("manufacturerCode", value=self.manufacturer_code, raw_value=self.manufacturer_code),
                NMEA2000Field("deviceInstanceLower", value=self.device_instance_lower, raw_value=self.device_instance_lower),
                NMEA2000Field("deviceInstanceUpper", value=self.device_instance_upper, raw_value=self.device_instance_upper),
                NMEA2000Field("deviceFunction", value=self.device_function, raw_value=self.device_function),
                NMEA2000Field("spare", value=1, raw_value=1),
                NMEA2000Field("deviceClass", value=self.device_class, raw_value=self.device_class),
                NMEA2000Field("systemInstance", value=self.system_instance, raw_value=self.system_instance),
                NMEA2000Field("industryGroup", value=self.industry_group, raw_value=self.industry_group),
                NMEA2000Field("arbitraryAddressCapable", value=yes_no, raw_value=yes_no),
            ],
        )

    def _build_heartbeat_message(self) -> NMEA2000Message:
        self.heartbeat_counter = (self.heartbeat_counter + 1) % 253
        return NMEA2000Message(
            PGN=126993,
            id="heartbeat",
            description="Heartbeat",
            source=self.address,
            destination=255,
            priority=6,
            fields=[
                NMEA2000Field("dataTransmitOffset", value=self.heartbeat_interval, raw_value=self.heartbeat_interval),
                NMEA2000Field("sequenceCounter", value=self.heartbeat_counter, raw_value=self.heartbeat_counter),
                NMEA2000Field("controller1State", value=None, raw_value=3),
                NMEA2000Field("controller2State", value=None, raw_value=3),
                NMEA2000Field("equipmentStatus", value=0, raw_value=0),
                NMEA2000Field("reserved_30", value=None, raw_value=(1 << 34) - 1),
            ],
        )

    def _build_product_information_message(self) -> NMEA2000Message:
        return NMEA2000Message(
            PGN=126996,
            id="productInformation",
            description="Product Information",
            source=self.address,
            destination=255,
            priority=6,
            fields=[
                NMEA2000Field(
                    "nmea2000Version",
                    value=self.nmea2000_version / 1000,
                    raw_value=self.nmea2000_version,
                ),
                NMEA2000Field("productCode", value=self.product_code, raw_value=self.product_code),
                NMEA2000Field("modelId", value=self.model_id, raw_value=self.model_id),
                NMEA2000Field("softwareVersionCode", value=self.software_version_code, raw_value=self.software_version_code),
                NMEA2000Field("modelVersion", value=self.model_version, raw_value=self.model_version),
                NMEA2000Field("modelSerialCode", value=self.model_serial_code, raw_value=self.model_serial_code),
                NMEA2000Field("certificationLevel", value=self.certification_level, raw_value=self.certification_level),
                NMEA2000Field("loadEquivalency", value=self.load_equivalency, raw_value=self.load_equivalency),
            ],
        )

    def _build_configuration_information_message(self) -> NMEA2000Message:
        return NMEA2000Message(
            PGN=126998,
            id="configurationInformation",
            description="Configuration Information",
            source=self.address,
            destination=255,
            priority=6,
            fields=[
                NMEA2000Field("installationDescription1", value=self.installation_description1, raw_value=self.installation_description1),
                NMEA2000Field("installationDescription2", value=self.installation_description2, raw_value=self.installation_description2),
                NMEA2000Field("manufacturerInformation", value=self.manufacturer_information, raw_value=self.manufacturer_information),
            ],
        )

    def _build_iso_nak_message(self, destination: int, requested_pgn: int) -> NMEA2000Message:
        return NMEA2000Message(
            PGN=59392,
            id="isoAcknowledgement",
            description="ISO Acknowledgement",
            source=self.address,
            destination=destination,
            priority=6,
            fields=[
                NMEA2000Field("control", value=1, raw_value=1),
                NMEA2000Field("groupFunction", value=255, raw_value=255),
                NMEA2000Field("reserved_16", value=0, raw_value=0),
                NMEA2000Field("pgn", value=requested_pgn, raw_value=requested_pgn),
            ],
        )

    def _build_group_function_ack_message(self, destination: int, requested_pgn: int) -> NMEA2000Message:
        return NMEA2000Message(
            PGN=126208,
            id="nmeaAcknowledgeGroupFunction",
            description="NMEA - Acknowledge group function",
            source=self.address,
            destination=destination,
            priority=6,
            fields=[
                NMEA2000Field("pgn", value=requested_pgn, raw_value=requested_pgn),
                NMEA2000Field("pgnErrorCode", value=1, raw_value=1),
                NMEA2000Field("transmissionIntervalPriorityErrorCode", value=0, raw_value=0),
                NMEA2000Field("numberOfParameters", value=0, raw_value=0),
                NMEA2000Field("parameter", value=0, raw_value=0),
            ],
        )

    def _build_pgn_list_message(self, destination: int) -> NMEA2000Message:
        payload = b"".join(pgn.to_bytes(3, byteorder="little", signed=False) for pgn in self.transmit_pgns)
        return NMEA2000Message(
            PGN=126464,
            id="pgnListTransmitAndReceive",
            description="PGN List (Transmit and Receive)",
            source=self.address,
            destination=destination,
            priority=6,
            fields=[
                NMEA2000Field("functionCode", value=0, raw_value=0),
                NMEA2000Field("data", value=payload, raw_value=payload),
            ],
        )

    def _has_configuration_information(self) -> bool:
        return any(
            [
                self.installation_description1,
                self.installation_description2,
                self.manufacturer_information,
            ]
        )

    def _resolve_persistence_path(self, persistence_path: str | Path | None, persistence_key: str) -> Path:
        if persistence_path is not None:
            return Path(persistence_path)
        return Path.home() / ".nmea2000" / f"{persistence_key}.json"

    def _load_persistence_data(self) -> dict[str, Any]:
        if not self.persistence_path.exists():
            return {}
        try:
            return json.loads(self.persistence_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read persistence file %s: %s", self.persistence_path, exc)
            return {}

    def _persist(self, **values: Any) -> None:
        current = self._load_persistence_data()
        current.update(values)
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        self.persistence_path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")

    def _generate_unique_number(self) -> int:
        return random.randint(0, 2097151)

    def _get_package_version(self) -> str:
        try:
            return version("nmea2000")
        except PackageNotFoundError:
            return "nmea2000"

    @staticmethod
    async def _cancel_task(task: asyncio.Task[None] | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    @staticmethod
    def _prepare_client_options(client_options: dict[str, Any] | None) -> dict[str, Any]:
        options = dict(client_options or {})
        include_pgns = list(options.get("include_pgns", []))
        exclude_pgns = list(options.get("exclude_pgns", []))

        for pgn in MANAGEMENT_PGNS:
            while pgn in exclude_pgns:
                exclude_pgns.remove(pgn)
            if include_pgns and pgn not in include_pgns:
                include_pgns.append(pgn)

        options["include_pgns"] = include_pgns
        options["exclude_pgns"] = exclude_pgns
        options["build_network_map"] = True
        return options
