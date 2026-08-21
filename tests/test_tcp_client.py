# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring
"""TCP gateway client integration tests across supported wire formats."""

import asyncio
import logging

# pylint: disable=protected-access

import pytest

from nmea2000.consts import PhysicalQuantities
from nmea2000.input_formats import N2KFormat
from nmea2000.ioclient import EByteNmea2000Gateway, State, TextNmea2000Gateway
from nmea2000.message import NMEA2000Message
from tests.test_decoder import _validate_65280_message, _validate_130842_message

from .NMEA2000TestServer import NMEA2000TestServer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_tcp_client")


async def _wait_for_server_client(
    server: NMEA2000TestServer, timeout: float = 1.0
) -> None:
    """Wait until the test server has accepted one client connection."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not server.clients and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert server.clients, "Test server did not register a client connection"


def _create_server_client(input_format: N2KFormat):
    """Create a test server, matching client, and receive synchronization primitives."""
    # Create a queue and a signal
    receive_queue = asyncio.Queue()
    receive_signal = asyncio.Event()

    # Define receive callback
    async def handle_received_message(message: NMEA2000Message):
        """Queue the decoded message and notify waiting tests."""
        print(f"Received: {message}")
        await receive_queue.put(message)
        receive_signal.set()

    # Define status change callback as a standalone function
    async def handle_status_change(state: State):
        """Callback function for status changes."""
        print(f"Connection status: {state}")

    server = NMEA2000TestServer("127.0.0.1", 8881, input_format)
    if input_format == N2KFormat.EBYTE:
        client = EByteNmea2000Gateway("127.0.0.1", 8881)
    elif input_format == N2KFormat.N2K_ASCII_RAW:
        client = TextNmea2000Gateway(
            "127.0.0.1", 8881, output_format=input_format, seed_network_map=False
        )
    elif input_format == N2KFormat.CAN_FRAME_ASCII:
        client = TextNmea2000Gateway("127.0.0.1", 8881, output_format=input_format)
    else:
        raise ValueError(f"Unsupported test format: {input_format}")
    client.set_receive_callback(handle_received_message)
    client.set_status_callback(handle_status_change)

    return server, client, receive_signal, receive_queue


@pytest.mark.asyncio
async def test_single_message_ebyte():
    """An EBYTE client should decode one broadcast vessel-heading packet."""
    server, client, receive_signal, receive_queue = _create_server_client(
        N2KFormat.EBYTE
    )
    await server.start()
    await client.connect()
    await _wait_for_server_client(server)

    # Wait for the signal that a message was received
    try:
        await server.send_single_message()
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except TimeoutError as exc:
        raise AssertionError("Timed out waiting for receive signal") from exc
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    assert received_msg.PGN == 127250

    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_single_message_n2k_ascii_raw_1():
    """A text gateway should decode the sample Furuno heave N2K ASCII frame."""
    server, client, receive_signal, receive_queue = _create_server_client(
        N2KFormat.N2K_ASCII_RAW
    )
    await server.start()
    await client.connect()
    await _wait_for_server_client(server)

    # Wait for the signal that a message was received
    try:
        await server.send_to_clients(b"A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n")
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except TimeoutError as exc:
        raise AssertionError("Timed out waiting for receive signal") from exc
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    _validate_65280_message(received_msg)
    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_single_message_n2k_ascii_raw_2():
    """A text gateway should decode the multi-field proprietary N2K ASCII sample."""
    server, client, receive_signal, receive_queue = _create_server_client(
        N2KFormat.N2K_ASCII_RAW
    )
    await server.start()
    await client.connect()
    await _wait_for_server_client(server)

    # Wait for the signal that a message was received
    try:
        await server.send_to_clients(
            b"A000057.063 09FF7 1FF1A 3F9F24000000FFFFFFFFEFFFFFFF009AFFFFFFADFFFFFF050000000000\n"
        )
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except TimeoutError as exc:
        raise AssertionError("Timed out waiting for receive signal") from exc
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    _validate_130842_message(received_msg)
    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_single_message_can_frame_ascii():
    """A text gateway should decode one CAN frame ASCII attitude message with expected fields."""
    server, client, receive_signal, receive_queue = _create_server_client(
        N2KFormat.CAN_FRAME_ASCII
    )
    await server.start()
    await client.connect()
    await _wait_for_server_client(server)

    # Wait for the signal that a message was received
    try:
        await server.send_to_clients(
            b"00:01:54.430 R 15F11910 00 00 00 E5 0B 1D FF FF\r\n"
        )
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except TimeoutError as exc:
        raise AssertionError("Timed out waiting for receive signal") from exc
    msg = await receive_queue.get()
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 127257
    assert msg.priority == 5
    assert msg.source == 16
    assert msg.destination == 255
    assert msg.description == "Attitude"
    assert len(msg.fields) == 5
    assert msg.fields[0].id == "sid"
    assert msg.fields[0].value == 0
    assert msg.fields[1].id == "yaw"
    assert msg.fields[1].value == 0
    assert msg.fields[1].unit_of_measurement == "rad"
    assert msg.fields[1].physical_quantities == PhysicalQuantities.ANGLE
    assert msg.fields[2].id == "pitch"
    assert msg.fields[2].value == 0.3045
    assert msg.fields[2].unit_of_measurement == "rad"
    assert msg.fields[2].physical_quantities == PhysicalQuantities.ANGLE
    assert msg.fields[3].id == "roll"
    assert msg.fields[3].value == -0.0227
    assert msg.fields[3].unit_of_measurement == "rad"
    assert msg.fields[3].physical_quantities == PhysicalQuantities.ANGLE
    assert msg.fields[4].id == "reserved_56"
    assert msg.fields[4].value == 255
    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_auto_sense_decodes_n2k_ascii():
    """TextNmea2000Gateway with format=None should auto-detect N2K ASCII."""
    receive_queue = asyncio.Queue()
    receive_signal = asyncio.Event()

    async def on_message(message: NMEA2000Message):
        """Store one auto-sensed message and wake the waiting test."""
        await receive_queue.put(message)
        receive_signal.set()

    server = NMEA2000TestServer("127.0.0.1", 8881, N2KFormat.N2K_ASCII_RAW)
    client = TextNmea2000Gateway(
        "127.0.0.1", 8881, output_format=None, seed_network_map=False
    )
    client.set_receive_callback(on_message)

    await server.start()
    await client.connect()
    await _wait_for_server_client(server)

    try:
        await server.send_to_clients(b"A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n")
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except TimeoutError as exc:
        raise AssertionError("Timed out waiting for auto-sensed message") from exc

    msg = await receive_queue.get()
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 65280

    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_auto_sense_decodes_can_frame_ascii():
    """TextNmea2000Gateway with format=None should auto-detect CAN Frame ASCII."""
    receive_queue = asyncio.Queue()
    receive_signal = asyncio.Event()

    async def on_message(message: NMEA2000Message):
        """Store one auto-sensed message and wake the waiting test."""
        await receive_queue.put(message)
        receive_signal.set()

    server = NMEA2000TestServer("127.0.0.1", 8881, N2KFormat.CAN_FRAME_ASCII)
    client = TextNmea2000Gateway(
        "127.0.0.1", 8881, output_format=None, seed_network_map=False
    )
    client.set_receive_callback(on_message)

    await server.start()
    await client.connect()
    await _wait_for_server_client(server)

    try:
        await server.send_to_clients(
            b"00:01:54.430 R 15F11910 00 00 00 E5 0B 1D FF FF\r\n"
        )
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except TimeoutError as exc:
        raise AssertionError("Timed out waiting for auto-sensed message") from exc

    msg = await receive_queue.get()
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 127257

    await client.close()
    await server.stop()


@pytest.mark.asyncio
async def test_auto_sense_encode_raises():
    """Encoding must fail when format=None (auto-sense mode)."""
    client = TextNmea2000Gateway(
        "127.0.0.1", 8881, output_format=None, seed_network_map=False
    )
    dummy_msg = NMEA2000Message.from_json(
        '{"PGN":59904,"id":"isoRequest","description":"ISO Request",'
        '"fields":[{"id":"pgn","name":"PGN","value":60928,"raw_value":60928}],'
        '"source":0,"destination":255,"priority":6,'
        '"timestamp":"2012-06-17T15:02:11"}'
    )
    with pytest.raises(ValueError, match="auto-sense"):
        client._encode_impl(dummy_msg)


@pytest.mark.asyncio
async def test_text_gateway_encodes_transport_bytes():
    """Text gateway encoding should append transport line endings to the emitted frame bytes."""
    client = TextNmea2000Gateway(
        "127.0.0.1",
        8881,
        output_format=N2KFormat.N2K_ASCII_RAW,
        seed_network_map=False,
    )
    message = NMEA2000Message.from_json(
        '{"PGN":59904,"id":"isoRequest","description":"ISO Request",'
        '"fields":[{"id":"pgn","name":"PGN","value":60928,"raw_value":60928}],'
        '"source":0,"destination":255,"priority":6,'
        '"timestamp":"2012-06-17T15:02:11"}'
    )

    try:
        encoded = client._encode_impl(message)
    finally:
        await client.close()

    assert len(encoded) == 1
    assert encoded[0].endswith(b"\r\n")
