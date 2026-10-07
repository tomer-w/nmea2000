"""High-level device abstraction built on top of asynchronous NMEA 2000 clients."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

from . import _canboat as canboat
from . import backend
from .input_formats import N2KFormat
from .ioclient import (
    ActisenseBstNmea2000Gateway,
    EByteNmea2000Gateway,
    PythonCanAsyncIOClient,
    State,
    TextNmea2000Gateway,
    WaveShareNmea2000Gateway,
)
from .message import IsoName, NMEA2000Field, NMEA2000Message

logger = logging.getLogger(__name__)

# The NAME's reserved bit, which nmea2000 has always set: NAMEs are compared
# whole, so keeping it lets older nmea2000 devices settle conflicts the same way.
_NAME_SPARE_BIT = 1 << 48

MessageCallback = Callable[[NMEA2000Message], Awaitable[None]]
StatusCallback = Callable[[State], Awaitable[None]]


class N2KClient(Protocol):
    """Transport interface required by N2KDevice for bus communication."""

    @property
    def state(self) -> State:
        """Return the current connection state of the transport."""
        ...  # pylint: disable=unnecessary-ellipsis

    def set_receive_callback(self, callback: MessageCallback | None) -> None:
        """Register the callback invoked for received messages."""
        ...  # pylint: disable=unnecessary-ellipsis

    def set_status_callback(self, callback: StatusCallback | None) -> None:
        """Register the callback invoked when transport state changes."""
        ...  # pylint: disable=unnecessary-ellipsis

    async def connect(self) -> None:
        """Open the underlying transport connection."""
        ...  # pylint: disable=unnecessary-ellipsis

    async def close(self) -> None:
        """Close the underlying transport connection."""
        ...  # pylint: disable=unnecessary-ellipsis

    async def send(self, message: NMEA2000Message, /) -> None:
        """Send one NMEA 2000 message through the transport."""
        ...  # pylint: disable=unnecessary-ellipsis


MANAGEMENT_PGNS = frozenset(
    {59392, 59904, 60928, 126208, 126464, 126993, 126996, 126998}
)

# canboat frames: (priority, pgn, source, destination, data)
Frame = tuple[int, int, int, int, bytes]


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


@dataclass
class DiscoveredDevice:
    """State tracked for another device observed on the NMEA 2000 bus."""

    source: int
    last_seen: datetime | None = None
    address_claim: NMEA2000Message | None = None
    product_information: NMEA2000Message | None = None
    configuration_information: NMEA2000Message | None = None


class N2KDevice:
    """High-level async NMEA 2000 device wrapper with address-claim handling.

    Address claiming (ISO 11783-5: scan, claim, NAME arbitration, moving to a
    free address on a lost contest) and the standard responses (product
    information, heartbeat, PGN lists, ISO NAKs) come from canboat's node
    implementation; this class drives them from the asyncio loop and sends
    what they produce through the client.
    """

    def __init__(
        self,
        client: N2KClient,
        *,
        preferred_address: int = 100,  # A commonly unused address
        unique_number: int | None = None,
        manufacturer_code: int = 999,  # A nonexistent manufacturer code
        device_function: int = 130,  # PC Gateway
        device_class: int = 25,  # Inter/Intra Network Device
        device_instance_lower: int = 0,
        device_instance_upper: int = 0,
        system_instance: int = 0,
        industry_group: int = 4,  # Marine
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
        address_claim_detection_time: float | None = None,
        address_claim_startup_delay: float | None = None,
        heartbeat_interval: float = 60.0,
        persistence_path: str | Path | None = None,
        persistence_key: str = "default",
        disable_naks: bool = False,
    ):
        """Create a device around an async transport client and local device identity.

        Address claiming follows the standard's timings: the device listens
        for other devices' claims for 1 s, then uses its address once its
        claim has stood unchallenged for 250 ms (ISO 11783-5 / J1939-81).
        ``address_claim_startup_delay`` and ``address_claim_detection_time``
        are deprecated and ignored.
        """
        for name, value in (
            ("address_claim_startup_delay", address_claim_startup_delay),
            ("address_claim_detection_time", address_claim_detection_time),
        ):
            if value is not None:
                warnings.warn(
                    f"N2KDevice's {name} is deprecated and no longer respected: "
                    "address claiming uses the standard's timings (a 1 s scan, "
                    "then 250 ms for a claim to settle)",
                    FutureWarning,
                    stacklevel=2,
                )
        self.client = client
        self.client.set_receive_callback(self._handle_client_message)
        self.client.set_status_callback(self._handle_client_status)

        self._receive_callback: MessageCallback | None = None
        self._raw_receive_callback: MessageCallback | None = None
        self._status_callback: StatusCallback | None = None

        self.disable_naks = disable_naks
        self.heartbeat_interval = heartbeat_interval
        self._started = False
        self._ready_event = asyncio.Event()
        self._claim_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._closing = False
        self.heartbeat_counter = 0
        self.devices: dict[int, DiscoveredDevice] = {}

        self.persistence_path = self._resolve_persistence_path(
            persistence_path, persistence_key
        )
        persisted = self._load_persistence_data()
        self.unique_number = (
            unique_number
            if unique_number is not None
            else int(persisted.get("uniqueNumber", self._generate_unique_number()))
        )
        self.preferred_address = int(persisted.get("lastAddress", preferred_address))

        self.manufacturer_code = manufacturer_code
        self.device_function = device_function
        self.device_class = device_class
        self.device_instance_lower = device_instance_lower
        self.device_instance_upper = device_instance_upper
        self.system_instance = system_instance
        self.industry_group = industry_group
        self.arbitrary_address_capable = arbitrary_address_capable
        self._own_name = (
            canboat.iso_name(
                manufacturer_code,
                self.unique_number,
                device_function=device_function,
                device_class=device_class,
                device_instance=(device_instance_upper << 3) | device_instance_lower,
                system_instance=system_instance,
                industry_group=industry_group,
                arbitrary_address_capable=arbitrary_address_capable,
            )
            | _NAME_SPARE_BIT
        )
        self._claimer = self._new_claimer()
        # Set when a claim starts outside the loop, to wake it early
        self._claimer_wake = asyncio.Event()

        self.product_code = product_code
        self.nmea2000_version = nmea2000_version
        self.model_id = model_id
        self.model_version = model_version
        self.model_serial_code = model_serial_code or str(self.unique_number)
        self.software_version_code = (
            software_version_code or self._get_package_version()
        )
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
        return self._started and self._claimer.send_address is not None

    @property
    def address(self) -> int:
        """The claimed source address (the preferred one until a claim is made)."""
        claimed = self._claimer.address
        return self.preferred_address if claimed is None else claimed

    def set_receive_callback(self, callback: MessageCallback | None) -> None:
        """Register a callback for non-management messages delivered to this device."""
        self._receive_callback = callback

    def set_raw_receive_callback(self, callback: MessageCallback | None) -> None:
        """Register a callback for every received message before management handling."""
        self._raw_receive_callback = callback

    def set_status_callback(self, callback: StatusCallback | None) -> None:
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
    ) -> N2KDevice:
        """Create a device that communicates through an EByte TCP gateway."""
        client = EByteNmea2000Gateway(
            host, port, **cls._prepare_client_options(client_options)
        )
        return cls(client, **device_options)

    @classmethod
    def for_text_gateway(
        cls,
        host: str,
        port: int,
        output_format: N2KFormat,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> N2KDevice:
        """Create a device that communicates through a text/line-based TCP gateway.

        Args:
            host: Server hostname or IP address.
            port: Server port number.
            output_format: The N2KFormat used by the gateway (e.g. CAN_FRAME_ASCII, N2K_ASCII_RAW).
        """
        client = TextNmea2000Gateway(
            host,
            port,
            output_format=output_format,
            **cls._prepare_client_options(client_options),
        )
        return cls(client, **device_options)

    @classmethod
    def for_waveshare(
        cls,
        port: str,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> N2KDevice:
        """Create a device that communicates through a Waveshare USB-CAN gateway."""
        client = WaveShareNmea2000Gateway(
            port, **cls._prepare_client_options(client_options)
        )
        return cls(client, **device_options)

    @classmethod
    def for_python_can(
        cls,
        interface: str,
        channel: str,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> N2KDevice:
        """Create a device that communicates through a ``python-can`` interface."""
        client_kwargs = cls._prepare_client_options(client_options)
        client = PythonCanAsyncIOClient(interface, channel, **client_kwargs)
        return cls(client, **device_options)

    @classmethod
    def for_actisense(
        cls,
        host: str,
        port: int,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> N2KDevice:
        """Create a device that communicates through an Actisense BST TCP gateway."""
        client = ActisenseBstNmea2000Gateway(
            host, port, **cls._prepare_client_options(client_options)
        )
        return cls(client, **device_options)

    @classmethod
    def for_n2k_ascii(
        cls,
        host: str,
        port: int,
        *,
        client_options: dict[str, Any] | None = None,
        **device_options: Any,
    ) -> N2KDevice:
        """Convenience shortcut for ``for_text_gateway`` with N2K_ASCII_RAW format."""
        return cls.for_text_gateway(
            host,
            port,
            N2KFormat.N2K_ASCII_RAW,
            client_options=client_options,
            **device_options,
        )

    async def start(self) -> None:
        """Connect the client and begin the device startup/address-claim sequence."""
        self._started = True
        await self.client.connect()

    async def close(self) -> None:
        """Stop background tasks, mark the device not ready, and close the client."""
        self._closing = True
        self._started = False
        self._ready_event.clear()
        await self._cancel_task(self._claim_task)
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

    # ─────────────────────────── address claiming ───────────────────────────

    def _new_claimer(self) -> canboat.AddressClaimer:
        return canboat.AddressClaimer(
            self._own_name, self.preferred_address, self.arbitrary_address_capable
        )

    async def _run_claimer(self, step: Callable[[int], list[Frame]]) -> None:
        """Run one claimer step, send what it produces, and act on the outcome."""
        was_claimed = self._claimer.state == "claimed"
        for frame in step(_now_ms()):
            await self._send_frame(frame)
        claimed = self._claimer.state == "claimed"
        if self._claimer.is_timing:
            self._claimer_wake.set()
        if not self.ready:
            self._ready_event.clear()
        if claimed and not was_claimed:
            await self._on_claimed()

    async def _on_claimed(self) -> None:
        self._ready_event.set()
        self._persist(lastAddress=self.address)
        await self._announce_startup_messages()
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _claim_loop(self) -> None:
        """Start the claim, then advance it until the device stops."""
        self._claimer = self._new_claimer()
        await self._run_claimer(self._claimer.start)
        while self._started and not self._closing:
            self._claimer_wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._claimer_wake.wait(),
                    0.02 if self._claimer.is_timing else 0.25,
                )
            await self._run_claimer(self._claimer.tick)

    async def _announce_startup_messages(self) -> None:
        await self._send_frame(self._product_information_frame())
        if self._has_configuration_information():
            await self.client.send(self._build_configuration_information_message())

    async def _heartbeat_loop(self) -> None:
        while self._started and not self._closing:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._started or self._closing:
                return
            if self.ready:
                self.heartbeat_counter = (self.heartbeat_counter + 1) % 253
                await self._send_frame(
                    canboat.heartbeat_frame(
                        self.address,
                        self.heartbeat_counter,
                        round(self.heartbeat_interval * 1000),
                    )
                )

    # ─────────────────────────── receiving ───────────────────────────

    async def _handle_client_status(self, state: State) -> None:
        if state != State.CONNECTED:
            self._ready_event.clear()
            await self._cancel_task(self._claim_task)
            await self._cancel_task(self._heartbeat_task)
            self._claimer = self._new_claimer()

        if state == State.CONNECTED and self._started and not self._closing:
            await self._cancel_task(self._claim_task)
            await self._cancel_task(self._heartbeat_task)
            self._claim_task = asyncio.create_task(self._claim_loop())

        if self._status_callback is not None:
            try:
                await self._status_callback(state)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error in device status callback")

    async def _handle_client_message(self, message: NMEA2000Message) -> None:
        self._remember_device(message)

        if self._raw_receive_callback is not None:
            try:
                await self._raw_receive_callback(message)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error in raw receive callback")

        if message.PGN in MANAGEMENT_PGNS:
            await self._handle_management_message(message)
            return

        if self._receive_callback is not None:
            try:
                await self._receive_callback(message)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error in receive callback")

    async def _handle_management_message(self, message: NMEA2000Message) -> None:
        if message.PGN == 60928:
            self._get_or_create_discovered_device(
                message.source
            ).address_claim = message
            their_name = IsoName.pack_name_from_message(message)
            await self._run_claimer(
                lambda now: self._claimer.on_address_claim(
                    now, message.source, their_name
                )
            )
            return

        if message.PGN == 126996:
            self._get_or_create_discovered_device(
                message.source
            ).product_information = message
            return

        if message.PGN == 126998:
            self._get_or_create_discovered_device(
                message.source
            ).configuration_information = message
            return

        if not self._should_process_management_message(message):
            return

        if message.PGN == 59904:
            await self._handle_iso_request(message)
            return

        if message.PGN == 126208 and self.ready:
            await self._handle_group_function(message)

    async def _handle_iso_request(self, message: NMEA2000Message) -> None:
        requested_pgn = message.get_field_int_value_by_id("pgn")
        if requested_pgn == 60928:
            claim = self._claimer.respond_to_claim_request()
            if claim is not None:
                await self._send_frame(claim)
            return
        if not self.ready:
            return
        if requested_pgn == 126996:
            await self._send_frame(self._product_information_frame())
            return
        if requested_pgn == 126998 and self._has_configuration_information():
            await self.client.send(self._build_configuration_information_message())
            return
        if requested_pgn == 126464:
            for frame in canboat.pgn_list_frames(
                self.address, message.source, self.transmit_pgns, []
            ):
                await self._send_frame(frame)
            return
        if not self.disable_naks and requested_pgn is not None:
            await self._send_frame(
                canboat.iso_ack_frame(self.address, message.source, 1, requested_pgn)
            )

    async def _handle_group_function(self, message: NMEA2000Message) -> None:
        if self.disable_naks:
            return
        if message.id not in {"nmeaRequestGroupFunction", "nmeaCommandGroupFunction"}:
            return
        requested_pgn = message.get_field_int_value_by_id("pgn")
        await self.client.send(
            self._build_group_function_ack_message(message.source, requested_pgn)
        )

    def _should_process_management_message(self, message: NMEA2000Message) -> bool:
        return message.destination == 255 or (
            self.ready and message.destination == self.address
        )

    def _remember_device(self, message: NMEA2000Message) -> None:
        discovered = self._get_or_create_discovered_device(message.source)
        discovered.last_seen = message.timestamp

    def _get_or_create_discovered_device(self, source: int) -> DiscoveredDevice:
        discovered = self.devices.get(source)
        if discovered is None:
            discovered = DiscoveredDevice(source=source)
            self.devices[source] = discovered
        return discovered

    # ─────────────────────────── sending ───────────────────────────

    async def _send_frame(self, frame: Frame) -> None:
        """Send a frame canboat built, as a message through the client."""
        priority, pgn, source, destination, data = frame
        message = backend.decode(pgn, data, source, destination, priority)
        if message is None:
            logger.error("canboat built a PGN %s frame that does not decode", pgn)
            return
        message.source = source
        message.destination = destination
        message.priority = priority
        await self.client.send(message)

    def _product_information_frame(self) -> Frame:
        return canboat.product_information_frame(
            self.address,
            nmea2000_version=self.nmea2000_version,
            product_code=self.product_code,
            model_id=self.model_id,
            software_version=self.software_version_code,
            model_version=self.model_version,
            model_serial=self.model_serial_code,
            certification_level=self.certification_level,
            load_equivalency=self.load_equivalency,
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
                NMEA2000Field(
                    "installationDescription1",
                    value=self.installation_description1,
                    raw_value=self.installation_description1,
                ),
                NMEA2000Field(
                    "installationDescription2",
                    value=self.installation_description2,
                    raw_value=self.installation_description2,
                ),
                NMEA2000Field(
                    "manufacturerInformation",
                    value=self.manufacturer_information,
                    raw_value=self.manufacturer_information,
                ),
            ],
        )

    def _build_group_function_ack_message(
        self, destination: int, requested_pgn: int | None
    ) -> NMEA2000Message:
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
                NMEA2000Field(
                    "transmissionIntervalPriorityErrorCode", value=0, raw_value=0
                ),
                NMEA2000Field("numberOfParameters", value=0, raw_value=0),
                NMEA2000Field("parameter", value=0, raw_value=0),
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

    # ─────────────────────────── persistence ───────────────────────────

    def _resolve_persistence_path(
        self, persistence_path: str | Path | None, persistence_key: str
    ) -> Path:
        if persistence_path is not None:
            return Path(persistence_path)
        return Path.home() / ".nmea2000" / f"{persistence_key}.json"

    def _load_persistence_data(self) -> dict[str, Any]:
        if not self.persistence_path.exists():
            return {}
        try:
            return json.loads(self.persistence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to read persistence file %s: %s", self.persistence_path, exc
            )
            return {}

    def _persist(self, **values: Any) -> None:
        current = self._load_persistence_data()
        current.update(values)
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        self.persistence_path.write_text(
            json.dumps(current, indent=2, sort_keys=True), encoding="utf-8"
        )

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
    def _prepare_client_options(
        client_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
