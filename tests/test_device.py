# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring
"""Device behavior tests for address claiming, startup announcements, and replies."""

import asyncio
import warnings
from datetime import datetime
from typing import Any

import can
import pytest

from nmea2000 import backend
from nmea2000 import device as device_module
from nmea2000.decoder import NMEA2000Decoder
from nmea2000.device import N2KDevice
from nmea2000.encoder import create_encoder
from nmea2000.ioclient import PythonCanAsyncIOClient, State
from nmea2000.message import IsoName, NMEA2000Field, NMEA2000Message

pytestmark = pytest.mark.usefixtures("fast_claim_clock")


class FakeClient:
    """Minimal async client double that records sent messages and callbacks."""

    def __init__(self):
        """Initialize disconnected client state and message capture storage."""
        self.state = State.DISCONNECTED
        self.receive_callback = None
        self.status_callback = None
        self.sent_messages: list[NMEA2000Message] = []
        self.encoder = create_encoder()

    def set_receive_callback(self, callback):
        """Register the coroutine used to deliver received messages."""
        self.receive_callback = callback

    def set_status_callback(self, callback):
        """Register the coroutine used to observe state changes."""
        self.status_callback = callback

    async def connect(self):
        """Mark the client connected and notify the status callback once."""
        self.state = State.CONNECTED
        if self.status_callback is not None:
            await self.status_callback(self.state)

    async def close(self):
        """Mark the client closed and notify the status callback once."""
        self.state = State.CLOSED
        if self.status_callback is not None:
            await self.status_callback(self.state)

    async def send(self, message: NMEA2000Message):
        """Record every message the device asks the client to send."""
        self.sent_messages.append(message)

    async def emit(self, message: NMEA2000Message):
        """Deliver an inbound message to the registered receive callback."""
        if self.receive_callback is not None:
            await self.receive_callback(message)


class EncodingFakeClient(FakeClient):
    """Fake client variant that also verifies messages encode successfully."""

    async def send(self, message: NMEA2000Message):
        """Encode the message before recording it to mimic transport validation."""
        self.encoder.encode(message)
        await super().send(message)


def _build_iso_request(
    requested_pgn: int, *, source: int = 10, destination: int = 255
) -> NMEA2000Message:
    """Build an ISO Request asking a device to transmit one PGN."""
    return NMEA2000Message(
        PGN=59904,
        id="isoRequest",
        description="ISO Request",
        source=source,
        destination=destination,
        priority=6,
        timestamp=datetime.now(),
        fields=[NMEA2000Field("pgn", value=requested_pgn, raw_value=requested_pgn)],
    )


def _build_address_claim(source: int, unique_number: int) -> NMEA2000Message:
    """Build an address claim message for collision-resolution tests."""
    return NMEA2000Message(
        PGN=60928,
        id="isoAddressClaim",
        description="ISO Address Claim",
        source=source,
        destination=255,
        priority=6,
        timestamp=datetime.now(),
        fields=[
            NMEA2000Field("uniqueNumber", value=unique_number, raw_value=unique_number),
            NMEA2000Field("manufacturerCode", value=999, raw_value=999),
            NMEA2000Field("deviceInstanceLower", value=0, raw_value=0),
            NMEA2000Field("deviceInstanceUpper", value=0, raw_value=0),
            NMEA2000Field("deviceFunction", value=130, raw_value=130),
            NMEA2000Field("spare", value=1, raw_value=1),
            NMEA2000Field("deviceClass", value=25, raw_value=25),
            NMEA2000Field("systemInstance", value=0, raw_value=0),
            NMEA2000Field("industryGroup", value=4, raw_value=4),
            NMEA2000Field("arbitraryAddressCapable", value=1, raw_value=1),
        ],
    )


def _build_group_function_request(
    source: int, requested_pgn: int, destination: int
) -> NMEA2000Message:
    """Build a group-function request directed at one device address."""
    return NMEA2000Message(
        PGN=126208,
        id="nmeaRequestGroupFunction",
        description="NMEA - Request group function",
        source=source,
        destination=destination,
        priority=3,
        timestamp=datetime.now(),
        fields=[
            NMEA2000Field("pgn", value=requested_pgn, raw_value=requested_pgn),
            NMEA2000Field("numberOfParameters", value=0, raw_value=0),
            NMEA2000Field("parameter", value=0, raw_value=0),
        ],
    )


def _pgns_from_message(message: NMEA2000Message) -> list[int]:
    """Extract the PGNs a PGN list message advertises."""
    entries = message.get_field_by_id("##list##").value
    assert isinstance(entries, list)
    pgns = [entry["pgn"].value for entry in entries]
    assert all(isinstance(pgn, int) for pgn in pgns)
    return [pgn for pgn in pgns if isinstance(pgn, int)]


@pytest.mark.asyncio
async def test_device_start_claims_address_and_filters_management_messages(tmp_path):
    """Startup should claim an address, answer ISO requests, and suppress management PGNs from data callbacks."""
    client = FakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
    )

    data_messages = asyncio.Queue()
    raw_messages = asyncio.Queue()

    async def handle_data(message: NMEA2000Message):
        """Capture forwarded non-management messages."""
        await data_messages.put(message)

    async def handle_raw(message: NMEA2000Message):
        """Capture raw inbound management messages before filtering."""
        await raw_messages.put(message)

    device.set_receive_callback(handle_data)
    device.set_raw_receive_callback(handle_raw)

    await device.start()
    await device.wait_ready(timeout=1)

    assert [message.PGN for message in client.sent_messages[:2]] == [59904, 60928]
    assert device.ready is True

    await client.emit(_build_iso_request(126996, source=31, destination=255))
    response = client.sent_messages[-1]
    assert response.PGN == 126996
    assert data_messages.empty()
    raw_message = await raw_messages.get()
    assert raw_message.PGN == 59904

    data_message = NMEA2000Message(
        PGN=127250, id="vesselHeading", source=44, destination=255, priority=2
    )
    await client.emit(data_message)
    forwarded = await asyncio.wait_for(data_messages.get(), timeout=1)
    assert forwarded.PGN == 127250


@pytest.mark.asyncio
async def test_device_announces_product_information_on_startup(tmp_path):
    """Startup should transmit product information immediately after address claim messages."""
    client = EncodingFakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
    )

    try:
        await device.start()
        await device.wait_ready(timeout=1)
    finally:
        await device.close()

    assert [message.PGN for message in client.sent_messages[:3]] == [
        59904,
        60928,
        126996,
    ]


@pytest.mark.asyncio
async def test_device_announces_configuration_information_on_startup_when_present(
    tmp_path,
):
    """Startup should advertise configuration information when descriptive fields are configured."""
    client = EncodingFakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
        installation_description1="Autopilot demo",
        manufacturer_information="nmea2000 autopilot heading simulator",
    )

    try:
        await device.start()
        await device.wait_ready(timeout=1)
    finally:
        await device.close()

    assert [message.PGN for message in client.sent_messages[:4]] == [
        59904,
        60928,
        126996,
        126998,
    ]


@pytest.mark.asyncio
async def test_device_conflict_increments_address_when_it_loses(tmp_path):
    """A losing address claim should move the device to the next address and re-announce."""
    client = FakeClient()
    device = N2KDevice(
        client,
        unique_number=10,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
    )

    await device.start()
    await device.wait_ready(timeout=1)
    assert device.address == 100

    await client.emit(_build_address_claim(100, unique_number=1))
    await asyncio.sleep(0.05)

    assert device.address == 101
    resent_messages = [
        message for message in client.sent_messages if message.source == 101
    ]
    assert [message.PGN for message in resent_messages[-2:]] == [60928, 126996]


@pytest.mark.asyncio
async def test_device_conflict_keeps_address_when_it_wins(tmp_path):
    """A winning address claim should keep the current address and avoid moving to a new one."""
    client = FakeClient()
    device = N2KDevice(
        client,
        unique_number=1,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
    )

    await device.start()
    await device.wait_ready(timeout=1)
    assert device.address == 100

    await client.emit(_build_address_claim(100, unique_number=10))
    await asyncio.sleep(0.05)

    assert device.address == 100
    resent_messages = [
        message for message in client.sent_messages if message.source == 100
    ]
    assert [message.PGN for message in resent_messages[-2:]] == [60928, 126996]
    assert not any(
        message.PGN == 60928 and message.source == 101
        for message in client.sent_messages
    )


@pytest.mark.asyncio
async def test_device_responds_with_iso_nak_and_group_function_ack(tmp_path):
    """Unsupported requests should produce ISO NAK and group-function acknowledge responses."""
    client = FakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
    )

    await device.start()
    await device.wait_ready(timeout=1)

    await client.emit(_build_iso_request(130000, source=22, destination=255))
    iso_nak = client.sent_messages[-1]
    assert iso_nak.PGN == 59392
    assert iso_nak.destination == 22

    await client.emit(_build_group_function_request(25, 130000, device.address))
    group_ack = client.sent_messages[-1]
    assert group_ack.PGN == 126208
    assert group_ack.id == "nmeaAcknowledgeGroupFunction"
    assert group_ack.destination == 25


@pytest.mark.asyncio
async def test_device_heartbeat_messages_encode(tmp_path):
    """Heartbeats should encode, advertising their interval and healthy controllers."""
    client = EncodingFakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=0.01,
    )

    try:
        await device.start()
        await device.wait_ready(timeout=1)
        await asyncio.sleep(0.05)
    finally:
        await device.close()

    heartbeats = [message for message in client.sent_messages if message.PGN == 126993]
    assert heartbeats

    heartbeat = heartbeats[0]
    assert heartbeat.get_field_by_id("dataTransmitOffset").value == pytest.approx(0.01)
    assert heartbeat.priority == 7
    assert heartbeat.get_field_by_id("controller1State").value == "Error Active"
    assert heartbeat.get_field_by_id("controller1State").raw_value == 0
    # there is no second controller
    assert heartbeat.get_field_by_id("controller2State").value is None
    assert heartbeat.get_field_by_id("controller2State").raw_value == 3
    assert heartbeat.get_field_by_id("equipmentStatus").value == "Operational"
    assert heartbeat.get_field_by_id("equipmentStatus").raw_value == 0
    assert heartbeat.get_field_by_id("reserved_30").value == (1 << 34) - 1
    assert heartbeat.get_field_by_id("reserved_30").raw_value == (1 << 34) - 1


@pytest.mark.asyncio
async def test_device_product_information_encodes_scaled_nmea_version(tmp_path):
    """Product information replies should carry the NMEA version in raw thousandths."""
    client = EncodingFakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
    )

    try:
        await device.start()
        await device.wait_ready(timeout=1)
        await client.emit(_build_iso_request(126996, source=31, destination=255))
    finally:
        await device.close()

    product_information = client.sent_messages[-1]
    version_field = product_information.get_field_by_id("nmea2000Version")
    assert product_information.PGN == 126996
    assert version_field.value == pytest.approx(1.3)
    assert version_field.raw_value == pytest.approx(1.3)
    payload = backend.encode(product_information)
    assert int.from_bytes(payload[:2], "little") == 1300


@pytest.mark.asyncio
async def test_device_pgn_list_always_includes_management_pgns(tmp_path):
    """Reported transmit PGN lists should always include required management PGNs."""
    client = FakeClient()
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        transmit_pgns=[127250],
        heartbeat_interval=60,
    )

    try:
        await device.start()
        await device.wait_ready(timeout=1)
        await client.emit(_build_iso_request(126464, source=31, destination=255))
    finally:
        await device.close()

    transmit_list = client.sent_messages[-2]
    receive_list = client.sent_messages[-1]
    assert (transmit_list.PGN, receive_list.PGN) == (126464, 126464)
    assert transmit_list.get_field_by_id("functionCode").value == "Transmit PGN list"
    assert receive_list.get_field_by_id("functionCode").value == "Receive PGN list"
    advertised_pgns = set(_pgns_from_message(transmit_list))

    assert 127250 in advertised_pgns
    assert {59392, 59904, 60928, 126208, 126464, 126993, 126996, 126998}.issubset(
        advertised_pgns
    )


@pytest.mark.parametrize(
    "option", ["address_claim_startup_delay", "address_claim_detection_time"]
)
def test_device_warns_that_claim_timing_options_are_ignored(tmp_path, option):
    """The old claim timing options still construct, but warn that they are ignored."""
    options: dict[str, Any] = {option: 0.1}
    with pytest.warns(
        FutureWarning, match=f"{option} is deprecated and no longer respected"
    ):
        N2KDevice(FakeClient(), persistence_path=tmp_path / "device.json", **options)


def test_device_does_not_warn_by_default(tmp_path):
    """A device built without the old options raises no warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        N2KDevice(FakeClient(), persistence_path=tmp_path / "device.json")


@pytest.mark.asyncio
async def test_device_claims_with_the_standard_timings(tmp_path, monkeypatch):
    """A 1 s scan, then the claim, then 250 ms before the address is used."""
    now = 0
    monkeypatch.setattr(device_module, "_now_ms", lambda: now)

    async def at(ms: int) -> None:
        nonlocal now
        now = ms
        await asyncio.sleep(0.1)  # several of the claim loop's 20 ms polls

    client = FakeClient()
    device = N2KDevice(
        client, persistence_path=tmp_path / "device.json", heartbeat_interval=60
    )
    try:
        await device.start()
        await at(0)  # the claim loop starts, and the scan with it
        await at(999)
        assert [m.PGN for m in client.sent_messages] == [59904]  # still scanning
        await at(1000)
        assert [m.PGN for m in client.sent_messages] == [59904, 60928]  # claimed
        await at(1249)
        assert not device.ready
        await at(1250)
        assert device.ready
    finally:
        await device.close()


@pytest.mark.parametrize("interval", [0, -1, 65.533, 3600])
def test_device_refuses_a_heartbeat_interval_it_cannot_advertise(tmp_path, interval):
    """PGN 126993 can advertise at most 65.532 s, so a longer interval is refused."""
    with pytest.raises(ValueError, match="heartbeat_interval"):
        N2KDevice(
            FakeClient(),
            persistence_path=tmp_path / "device.json",
            heartbeat_interval=interval,
        )


def test_device_accepts_the_longest_heartbeat_interval(tmp_path):
    """65.532 s is the longest interval a heartbeat can advertise."""
    N2KDevice(
        FakeClient(),
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=65.532,
    )


async def _ready_device(client, tmp_path, **options) -> N2KDevice:
    device = N2KDevice(
        client,
        persistence_path=tmp_path / "device.json",
        heartbeat_interval=60,
        **options,
    )
    await device.start()
    await device.wait_ready(timeout=1)
    return device


# 127237 command with two parameters: steering mode (field 5) = Heading Control,
# and heading to steer (field 11, 2 bytes) = 1.5 rad
MULTI_PARAMETER_COMMAND = bytes(
    [0x01, 0x05, 0xF1, 0x01, 0xF8, 0x02, 0x05, 0x04, 0x0B, 0x98, 0x3A]
)


def _command_parameters(
    message: NMEA2000Message,
) -> list[tuple[object, object, object]]:
    entries = message.get_field_by_id("##list##").value
    assert isinstance(entries, list)
    return [
        (e["parameter"].value, e["value"].value, e["value"].raw_value) for e in entries
    ]


def _fast_packet_frames(arbitration_id: int, payload: bytes, sequence: int = 3) -> list:
    chunks = [payload[:6]] + [payload[i : i + 7] for i in range(6, len(payload), 7)]
    frames = []
    for index, chunk in enumerate(chunks):
        header = bytes([(sequence << 5) | index]) + (
            bytes([len(payload)]) if index == 0 else b""
        )
        data = (header + chunk).ljust(8, b"\xff")
        frames.append(
            can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
        )
    return frames


def _can_id(priority: int, pgn: int, source: int, destination: int = 255) -> int:
    if (pgn >> 8) & 0xFF < 240:
        pgn = (pgn & 0x3FF00) | destination
    return (priority << 26) | (pgn << 8) | source


def _decode_frames(decoder, frames) -> list[NMEA2000Message]:
    return [
        message
        for message in (decoder.decode(frame) for frame in frames)
        if message is not None
    ]


@pytest.mark.asyncio
async def test_group_function_handler_true_suppresses_nak(tmp_path):
    client = FakeClient()
    device = await _ready_device(client, tmp_path)
    calls = []

    async def handler(message):
        calls.append(message)
        return True

    device.set_group_function_handler(handler)
    sent_before = len(client.sent_messages)
    request = _build_group_function_request(25, 127237, device.address)
    await client.emit(request)

    assert calls == [request]
    assert len(client.sent_messages) == sent_before


@pytest.mark.asyncio
async def test_group_function_handler_false_keeps_nak(tmp_path):
    client = FakeClient()
    device = await _ready_device(client, tmp_path)
    calls = []

    async def handler(message):
        calls.append(message)
        return False

    device.set_group_function_handler(handler)
    await client.emit(_build_group_function_request(25, 127237, device.address))

    assert len(calls) == 1
    ack = client.sent_messages[-1]
    assert ack.id == "nmeaAcknowledgeGroupFunction"
    assert ack.destination == 25
    assert ack.get_field_int_value_by_id("pgnErrorCode") == 1


@pytest.mark.asyncio
async def test_group_function_handler_ignores_messages_for_other_devices(tmp_path):
    client = FakeClient()
    device = await _ready_device(client, tmp_path)
    calls = []

    async def handler(message):
        calls.append(message)
        return True

    device.set_group_function_handler(handler)
    await client.emit(
        _build_group_function_request(25, 127237, (device.address + 1) % 253)
    )
    await client.emit(_build_group_function_request(25, 127237, 255))

    assert [message.destination for message in calls] == [255]


@pytest.mark.asyncio
async def test_group_function_handler_gets_decoded_command(tmp_path):
    client = FakeClient()
    device = await _ready_device(client, tmp_path)
    commands = []

    async def handler(message):
        commands.append(message)
        return True

    device.set_group_function_handler(handler)
    decoder = NMEA2000Decoder()
    frames = _fast_packet_frames(
        _can_id(3, 126208, 25, device.address), MULTI_PARAMETER_COMMAND
    )
    assert len(frames) == 2
    messages = _decode_frames(decoder, frames)
    assert len(messages) == 1
    await client.emit(messages[0])

    assert len(commands) == 1
    assert commands[0].get_field_by_id("pgn").value == 127237
    assert _command_parameters(commands[0]) == [
        (5, "Heading Control", 4),
        (11, 1.5, 1.5),
    ]


@pytest.mark.asyncio
async def test_iso_request_handler_called_only_for_unanswered_pgns(tmp_path):
    client = FakeClient()
    device = await _ready_device(client, tmp_path, installation_description1="test")
    requested = []

    async def handler(_message, pgn):
        requested.append(pgn)
        return pgn == 127237

    device.set_iso_request_handler(handler)
    for pgn in (60928, 126996, 126998, 126464):
        await client.emit(_build_iso_request(pgn, source=22))
        assert client.sent_messages[-1].PGN == pgn
    assert not requested

    sent_before = len(client.sent_messages)
    await client.emit(_build_iso_request(127237, source=22))
    assert requested == [127237]
    assert len(client.sent_messages) == sent_before

    await client.emit(_build_iso_request(130000, source=22))
    assert requested == [127237, 130000]
    nak = client.sent_messages[-1]
    assert nak.PGN == 59392
    assert nak.destination == 22
    assert nak.get_field_int_value_by_id("pgn") == 130000


@pytest.mark.asyncio
async def test_own_name_matches_claimed_name(tmp_path):
    client = FakeClient()
    device = await _ready_device(
        client, tmp_path, unique_number=1234, manufacturer_code=1851
    )
    claim = next(message for message in client.sent_messages if message.PGN == 60928)

    assert device.own_name == IsoName.pack_name_from_message(claim)
    assert device.own_name & 0x1FFFFF == 1234
    with pytest.raises(AttributeError):
        device.own_name = 0  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("include_pgns", [[127250], [127250, "vesselHeading"]])
@pytest.mark.asyncio
async def test_management_pgns_bypass_restrictive_include_filter(
    tmp_path, monkeypatch, include_pgns
):
    device = N2KDevice.for_python_can(
        "virtual",
        "test",
        client_options={"include_pgns": include_pgns},
        persistence_path=tmp_path / "device.json",
    )
    sent = []

    async def send(message):
        sent.append(message)

    device.client.send = send
    # as if the address were claimed
    monkeypatch.setattr(N2KDevice, "ready", property(lambda self: True))
    group_functions = []
    iso_requests = []

    async def group_function_handler(message):
        group_functions.append(_command_parameters(message))
        return True

    async def iso_request_handler(_message, pgn):
        iso_requests.append(pgn)
        return True

    device.set_group_function_handler(group_function_handler)
    device.set_iso_request_handler(iso_request_handler)
    assert isinstance(device.client, PythonCanAsyncIOClient)
    decoder = device.client.decoder
    source = 25

    # the forced network map drops messages from sources that have not claimed an address
    claim = (1 << 63 | 4 << 60 | 1851 << 21 | 77).to_bytes(8, "little")
    claim_frame = can.Message(
        arbitration_id=_can_id(6, 60928, source), data=claim, is_extended_id=True
    )
    request_frame = can.Message(
        arbitration_id=_can_id(6, 59904, source, device.address),
        data=(127237).to_bytes(3, "little"),
        is_extended_id=True,
    )
    frames = [claim_frame, request_frame]
    frames += _fast_packet_frames(
        _can_id(3, 126208, source, device.address), MULTI_PARAMETER_COMMAND
    )
    for message in _decode_frames(decoder, frames):
        await device._handle_client_message(message)  # pylint: disable=protected-access

    assert iso_requests == [127237]
    assert group_functions == [[(5, "Heading Control", 4), (11, 1.5, 1.5)]]
