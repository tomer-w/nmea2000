import logging
from nmea2000.ioclient import State, TcpNmea2000Gateway
from nmea2000.message import NMEA2000Message
from .NMEA2000TestServer import NMEA2000TestServer
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_tcp_client")

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


async def test_single_message():
    server = NMEA2000TestServer("127.0.0.1", 8881)
    await server.start()
    client = TcpNmea2000Gateway("127.0.0.1", 8881)
    client.set_receive_callback(handle_received_message)
    client.set_status_callback(handle_status_change)
    await client.connect()
    
    # Wait for the signal that a message was received
    try:
        await asyncio.wait_for(receive_signal.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise AssertionError("Timed out waiting for receive signal")
    received_msg = await receive_queue.get()
    assert isinstance(received_msg, NMEA2000Message)
    assert received_msg.PGN == 127250

    client.close()
    server.stop()
