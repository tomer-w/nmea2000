import logging

import pytest
from nmea2000.consts import PhysicalQuantities
from nmea2000.ioclient import ActisenseNmea2000Gateway, EByteNmea2000Gateway, State, Type, YachtDevicesNmea2000Gateway
from nmea2000.message import NMEA2000Message
from tests.test_decoder import _validate_130842_message, _validate_65280_message
from .NMEA2000TestServer import NMEA2000TestServer
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_tcp_client")

def _create_server_client(type: Type):
    # Create a queue and a signal
    receive_queue = asyncio.Queue()
    receive_signal = asyncio.Event()

    # Define receive callback
    async def handle_received_message(message: NMEA2000Message):
        print(f"Received: {message}")
        await receive_queue.put(message)
        receive_signal.set()

    # Define status change callback as a standalone function
    async def handle_status_change(state: State):
        """Callback function for status changes."""
        print(f"Connection status: {state}")

    server = NMEA2000TestServer("127.0.0.1", 8881, type)
    if type == Type.EBYTE:
        client = EByteNmea2000Gateway("127.0.0.1", 8881)
    elif type == Type.ACTISENSE:
        client = ActisenseNmea2000Gateway("127.0.0.1", 8881)            
    elif type == Type.YACHT_DEVICES:
        client = YachtDevicesNmea2000Gateway("127.0.0.1", 8881)            
    client.set_receive_callback(handle_received_message)
    client.set_status_callback(handle_status_change)

    return server, client, receive_signal, receive_queue

@pytest.mark.asyncio
async def test_single_message_EBYTE():
    server,client, receive_signal, receive_queue = _create_server_client(Type.EBYTE)
    await server.start()
    await client.connect()
    
    # Wait for the signal that a message was received
    try:
        await server.send_single_message()
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise AssertionError("Timed out waiting for receive signal")
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    assert received_msg.PGN == 127250

    await client.close()
    await server.stop()

@pytest.mark.asyncio
async def test_single_message_ACTISENSE_1():
    server,client, receive_signal, receive_queue = _create_server_client(Type.ACTISENSE)
    await server.start()
    await client.connect()
    
    # Wait for the signal that a message was received
    try:
        await server.send_to_clients("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8'))
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise AssertionError("Timed out waiting for receive signal")
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    _validate_65280_message(received_msg)
    await client.close()
    await server.stop()

@pytest.mark.asyncio
async def test_single_message_ACTISENSE_2():
    server,client, receive_signal, receive_queue = _create_server_client(Type.ACTISENSE)
    await server.start()
    await client.connect()
    
    # Wait for the signal that a message was received
    try:
        await server.send_to_clients("A000057.063 09FF7 1FF1A 3F9F24000000FFFFFFFFEFFFFFFF009AFFFFFFADFFFFFF050000000000\n".encode('utf-8'))
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise AssertionError("Timed out waiting for receive signal")
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    _validate_130842_message(received_msg)
    await client.close()
    await server.stop()

@pytest.mark.asyncio
async def test_single_message_YACHT_DEVICES():
    server,client, receive_signal, receive_queue = _create_server_client(Type.YACHT_DEVICES)
    await server.start()
    await client.connect()
    
    # Wait for the signal that a message was received
    try:
        await server.send_to_clients("00:01:54.430 R 15F11910 00 00 00 E5 0B 1D FF FF\r\n".encode('utf-8'))
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise AssertionError("Timed out waiting for receive signal")
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
    assert msg.fields[1].unit_of_measurement == 'rad'
    assert msg.fields[1].physical_quantities == PhysicalQuantities.ANGLE
    assert msg.fields[2].id == "pitch"
    assert msg.fields[2].value == 0.3045
    assert msg.fields[2].unit_of_measurement == 'rad'
    assert msg.fields[2].physical_quantities == PhysicalQuantities.ANGLE
    assert msg.fields[3].id == "roll"
    assert msg.fields[3].value == -0.0227
    assert msg.fields[3].unit_of_measurement == 'rad'
    assert msg.fields[3].physical_quantities == PhysicalQuantities.ANGLE
    assert msg.fields[4].id == "reserved_56"
    assert msg.fields[4].value == 255
    await client.close()
    await server.stop()

# @pytest.mark.asyncio
# async def test_server():
#     server = NMEA2000TestServer("127.0.0.1", 8881, Type.YACHT_DEVICES)
#     await server.start()
#     await server.broadcast_test_messages()