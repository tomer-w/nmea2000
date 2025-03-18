import asyncio
import logging
import socket
import serial_asyncio

from .decoder import NMEA2000Decoder
from .encoder import NMEA2000Encoder
from .message import NMEA2000Message

class AsyncIOClient:
    """Base class for async clients (TCP or Serial)"""
    def __init__(self, reconnect_delay: int = 5):
        self.reconnect_delay = reconnect_delay
        self.connected = False
        self.reader = None
        self.writer = None
        self.receive_callback = None
        self.queue = asyncio.Queue()
        self.decoder = NMEA2000Decoder()
        self.encoder = NMEA2000Encoder()
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    async def connect(self):
        """Attempts to establish a connection (must be implemented by subclasses)."""
        raise NotImplementedError

    async def send(self, nmea2000Message: NMEA2000Message):
        """Sends data (must be implemented by subclasses)."""
        raise NotImplementedError

    def close(self):
        """Closes the connection."""
        self.connected = False
        if self.writer:
            self.writer.close()
        if self.reader:
            self.reader.close()
        self.logger.info("Connection closed.")

    def set_receive_callback(self, callback):
        """Registers a callback to be executed when data is received."""
        self.receive_callback = callback

    async def _process_queue(self):
        """Processes received packets in order."""
        while True:
            data = await self.queue.get()
            if self.receive_callback:
                await self.receive_callback(data)
            self.queue.task_done()


class TcpNmea2000Gateway(AsyncIOClient):
    """TCP implementation of AsyncIOClient"""
    def __init__(self, host: str, port: int, reconnect_delay: int = 5):
        super().__init__(reconnect_delay)
        self.host = host
        self.port = port

    async def connect(self):
        """Connects to the TCP server with automatic reconnection."""
        self.logger.info(f"Connecting to {self.host}:{self.port}")
        while not self.connected:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                # Get the underlying socket
                sock = self.writer.get_extra_info("socket")
                if sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # Enable keepalive
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)  # Idle time before keepalive probes (Linux/macOS)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # Interval between keepalive probes
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)  # Number of failed probes before dropping connection
                self.connected = True
                self.logger.info(f"Connected to {self.host}:{self.port}")

                asyncio.create_task(self._receive_loop())  # Start background receiver
                asyncio.create_task(self._process_queue())  # Start processing queue
                
            except (asyncio.TimeoutError, ConnectionRefusedError) as e:
                self.logger.warning(f"Connection failed: {e}. Retrying in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)

    async def _receive_loop(self):
        """Continuously receives 13-byte buffers and adds them to the queue."""
        self.logger.info("TCP received loop started")
        try:
            while self.connected:
                data = await self.reader.readexactly(13)
                self.logger.info(f"Received: {data.hex()}")
                message = self.decoder.decode(data)
                self.logger.info(f"Received message: {message}")
                if message is not None:
                    await self.queue.put(message)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            self.logger.error("Connection lost while reading. Reconnecting...")
            self.connected = False
            await self.connect()

    async def send(self, nmea2000Message: NMEA2000Message):
        """Sends data over TCP."""
        if not self.connected:
            await self.connect()
        try:
            data_bytes = self.encoder.encode(nmea2000Message)
            self.writer.write(data_bytes)
            await self.writer.drain()
            self.logger.info(f"Sent: {data_bytes.hex()}")
        except (BrokenPipeError, ConnectionResetError):
            self.logger.error("Connection lost while sending. Reconnecting...")
            self.connected = False
            await self.connect()


class UsbNmea2000Gateway(AsyncIOClient):
    """Serial implementation of AsyncIOClient using serial_asyncio"""
    def __init__(self, port: str, reconnect_delay: int = 5):
        super().__init__(reconnect_delay)
        self.port = port

    async def connect(self):
        """Connects to the serial device with automatic reconnection."""
        while not self.connected:
            try:
                self.reader, self.writer = await serial_asyncio.open_serial_connection(
                    url=self.port,
                    baudrate=2000000,
                    bytesize=serial_asyncio.serial.EIGHTBITS,
                    parity=serial_asyncio.serial.PARITY_NONE,
                    stopbits=serial_asyncio.serial.STOPBITS_ONE,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )

                self.connected = True
                self.logger.info(f"Connected to serial port {self.port}")

                asyncio.create_task(self._receive_loop())  # Start background receiver
                asyncio.create_task(self._process_queue())  # Start processing queue
                
            except Exception as e:
                self.logger.warning(f"Serial connection failed: {e}. Retrying in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)

    async def _receive_loop(self):
        """Continuously receives packets between 0xAA to 0x55 and adds them to the queue."""
        buffer = bytearray()
        while self.connected:
            try:
                data = await self.reader.read(100)
                self.logger.info(f"Received: {data.hex()}")
                buffer.extend(data)

                # Continue processing as long as there's data in the buffer
                while True:
                    # Find the packet start and end delimiters
                    start = buffer.find(b"\xaa")
                    end = buffer.find(b"\x55", start)

                    if start == -1 or end == -1:
                        # If start or end not found, wait for more data
                        break

                    # Extract the complete packet, including the end delimiter
                    packet = buffer[start + 1 : end]

                    # Process the packet
                    if (len(packet) > 2):  # Make sure it's not just the header and end code
                        message = self.decoder.decode(packet)
                        self.logger.info(f"Received message: {message}")
                        if message is not None:
                            await self.queue.put(message)

                    # Remove the processed packet from the buffer
                    buffer = buffer[end + 1 :]

            except asyncio.IncompleteReadError:
                self.logger.error("Connection lost while reading. Reconnecting...")
                self.connected = False
                buffer = bytearray()
                await self.connect()
                break

    async def send(self, nmea2000Message: NMEA2000Message):
        """Sends data over Serial."""
        if not self.connected:
            await self.connect()
        try:
            data_bytes = self.encoder.encode(nmea2000Message)
            self.writer.write(data_bytes)
            await self.writer.drain()
            self.logger.info(f"Sent: {data_bytes.hex()}")
        except Exception as e:
            self.logger.error(f"Error while sending: {e}. Reconnecting...")
            self.connected = False
            await self.connect()


# Example Usage
async def handle_received_data(data: bytes):
    """User-defined callback function for received data."""
    print(f"Callback: Received {data.hex()}")
