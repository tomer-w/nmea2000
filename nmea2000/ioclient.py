import asyncio
import logging
import socket
import enum
from typing import Callable, Awaitable, Optional
import serial_asyncio
from tenacity import retry, stop_never, wait_exponential, retry_if_exception_type

from nmea2000.consts import PhysicalQuantities, Type

from .decoder import NMEA2000Decoder
from .encoder import NMEA2000Encoder
from .message import NMEA2000Message

class State(enum.Enum):
    """Connection states for NMEA2000 clients.
    
    Attributes:
        DISCONNECTED: Client is initialized but not connected or has lost connection.
        CONNECTED: Client has an active connection to the device/server.
        CLOSED: Client has been deliberately closed and cannot be reconnected.
    """
    DISCONNECTED = 0
    CONNECTED = 1
    CLOSED = 2

class AsyncIOClient:
    """Base class for asynchronous NMEA2000 clients.
    
    This abstract class implements common functionality for TCP and Serial clients,
    including connection management, automatic reconnection, message handling,
    and state management. Subclasses must implement _connect_impl, _receive_impl,
    and _send_impl methods.
    """
    def __init__(self, 
                 exclude_pgns:list[str]=[], 
                 include_pgns:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={}):
        """Initialize the AsyncIOClient.
        
        Args:
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        self._state = State.DISCONNECTED
        self.reader = None
        self.writer = None
        self.receive_callback = None
        self.status_callback = None
        self.queue = asyncio.Queue()
        self.decoder = NMEA2000Decoder(exclude_pgns=exclude_pgns, include_pgns=include_pgns, preferred_units = preferred_units)
        self.encoder = NMEA2000Encoder()
        self.lock = asyncio.Lock()
        
        # Setup logging
        self.logger = logging.getLogger(__name__)

    def set_status_callback(self, callback: Optional[Callable[[State], Awaitable[None]]]):
        """Registers a callback to be executed when the connection status changes.
        
        Args:
            callback: Async function with signature: async def callback(status: State) -> None
        """
        self.status_callback = callback

    def set_receive_callback(self, callback: Optional[Callable[[NMEA2000Message], Awaitable[None]]]):
        """Registers a callback to be executed when data is received.
        
        Args:
            callback: Async function with signature: async def callback(message: NMEA2000Message) -> None
        """
        self.receive_callback = callback

    @property
    def state(self) -> State:
        """Get the current connection state.
        
        Returns:
            The current connection state as a State enum value.
        """
        return self._state

    async def _update_state(self, new_state):
        """Update connection state and trigger callback if status changes.
        
        This method changes the internal state and triggers the status callback
        if registered. It's used internally whenever the connection state changes.
        
        Args:
            new_state: New State enum value to set.
        """
        self.logger.info("State changed. old: %s, new: %s", self._state, new_state)
        if self._state == new_state:
            return  # State hasn't changed, no need to do anything
            
        self._state = new_state
        
        # Call status callback if registered
        if self.status_callback:
            try:
                await self.status_callback(self.state)
            except Exception as e:
                self.logger.error(f"Error in status callback: {e}", exc_info=True)

    async def connect(self):
        """Establish connection to the NMEA2000 gateway.
        
        This method attempts to connect to the gateway device with automatic 
        reconnection on failure. It uses exponential backoff for retry attempts.
        The method is thread-safe and can be called multiple times.
        
        If the client has been closed (state is CLOSED), this method will return
        without attempting to connect.
        """
        if self._state == State.CLOSED:
            self.logger.info("Object terminated. Cannot connect.")
            return
        
        if self.lock.locked():
            self.logger.info("connect is already running")
            return

        async with self.lock:
            @retry(
                stop=stop_never,  # Retry forever 
                wait=wait_exponential(multiplier=0.5, max=10),  # Exponential backoff (0.5s, 1s, 2s, ...)
                retry=retry_if_exception_type(Exception),  # Only retry on exceptions
                before_sleep=self.log_before_retry  # Log each failure before sleeping
            )
            async def retrying_task():
                if self._state == State.CLOSED:
                    self.logger.info("Object terminated. stop connect retry.")
                    return
                
                await self._connect_impl()            
                await self._update_state(State.CONNECTED)

                asyncio.create_task(self._receive_loop())  # Start background receiver
                asyncio.create_task(self._process_queue())  # Start processing queue

            if self._state == State.CONNECTED:
                return
            await retrying_task()

    async def _receive_loop(self):
        """Background task that continuously receives messages from the gateway.
        
        This loop runs until the client is closed. If an exception occurs during
        reading (e.g., connection lost), it will trigger a reconnection attempt.
        """
        self.logger.info("Received loop started")
        try:
            while self._state != State.CLOSED:
                await self._receive_impl()
        except Exception as ex:
            if self._state != State.CLOSED:
                self.logger.error(f"Connection lost while reading. Error: {ex}. Reconnecting...")
                await self._update_state(State.DISCONNECTED)
                await self.connect()
        self.logger.info("Received loop terminated")
        
    async def send(self, nmea2000Message: NMEA2000Message):
        """Send a NMEA2000 message to the gateway.
        
        If an exception occurs during sending (e.g., connection lost),
        it will trigger a reconnection attempt.
        
        Args:
            nmea2000Message: The NMEA2000Message object to send.
        """
        try:
            msgs =  self._encode_impl(nmea2000Message)
            assert self.writer is not None
            for msg in msgs:
                self.writer.write(msg)
                await self.writer.drain()
                self.logger.info(f"Sent: {msg.hex()}")

        except ValueError as ve:
                self.logger.error(f"Failed to encode message. Error {ve}")
        except Exception as ex:
            if self._state != State.CLOSED:
                self.logger.error(f"Connection lost while sending. Error {ex}. Reconnecting...")
                await self._update_state(State.DISCONNECTED)
                await self.connect()

    async def close(self):
        """Close the connection and terminate the client.
        
        This method closes the connection and sets the state to CLOSED.
        After calling this method, the client cannot be reconnected.
        """
        await self._update_state(State.CLOSED)
        if self.writer:
            self.writer.close()
        self.logger.info("Connection closed.")

    async def _process_queue(self):
        """Process received messages in order.
        
        This background task processes messages from the queue and calls
        the receive_callback for each message. It runs until the client is closed.
        """
        self.logger.info("process queue loop started")
        while self._state != State.CLOSED:
            data = await self.queue.get()
            if self.receive_callback:
                try:
                    await self.receive_callback(data)
                except Exception as e:
                    self.logger.error(f"Error in receive callback: {e}", exc_info=True)
            self.queue.task_done()
        self.logger.info("process queue loop terminated")

    def log_before_retry(self, retry_state):
        """Custom retry logging callback for the tenacity retry decorator.
        
        Args:
            retry_state: The current retry state from tenacity.
        """
        self.logger.warning(
            "Retrying due to error: %s. Next attempt in %.2f seconds.",
            retry_state.outcome.exception(),
            retry_state.next_action.sleep if retry_state.next_action else 0
        )


class EByteNmea2000Gateway(AsyncIOClient):
    """TCP implementation of AsyncIOClient for NMEA2000 gateways.
    
    This class implements a TCP client for connecting to NMEA2000 networks
    through TCP-based gateways like ECAN-E01 or ECAN-W01.
    """
    def __init__(self,
                 host: str,
                 port: int, 
                 exclude_pgns:list[str]=[], 
                 include_pgns:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={}):
        """Initialize a TCP NMEA2000 gateway client.
        
        Args:
            host: Server hostname or IP address.
            port: Server port number.
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        super().__init__(exclude_pgns, include_pgns, preferred_units)
        self.host = host
        self.port = port
        self.lock = asyncio.Lock()

    async def _connect_impl(self):
        """Connect to the TCP server.
        
        This method establishes a TCP connection to the server and configures
        TCP keepalive to detect dropped connections. It's called by the
        connect() method.
        """
        self.logger.info(f"Connecting to {self.host}:{self.port}")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        # Get the underlying socket
        sock = self.writer.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # Enable keepalive
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)  # Idle time before keepalive probes (Linux/macOS)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # Interval between keepalive probes
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)  # Number of failed probes before dropping connection
        self.logger.info(f"Connected to {self.host}:{self.port}")

    async def _receive_impl(self):
        """Receive data from the TCP connection.
        
        This method reads exactly 13 bytes from the TCP connection (the size of
        a standard NMEA2000 message) and processes it. It's called repeatedly
        by the _receive_loop() method.
        """
        data = await self.reader.readexactly(13)
        self.logger.info(f"Received: {data.hex()}")
        if data == b'Sorry,Limited':  # cant handle more TCP connections
            self.logger.error("Sorry, Limited. sleeping for 30 seconds")
            self.connected = False
            await asyncio.sleep(30)
            await self.connect()
            return
        try:
            message = self.decoder.decode_tcp(data)
        except Exception as e:
            self.logger.warning(f"decoding failed. text: {data}, bytes: {data.hex()}. Error: {e}")
            return

        self.logger.info(f"Received message: {message}")
        if message is not None:
            await self.queue.put(message)

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        """Encode a NMEA2000 message over the TCP connection.
        
        Args:
            nmea2000Message: The NMEA2000Message object to encode.
        """
        return self.encoder.encode_tcp(nmea2000Message)
    
class TextNmea2000Gateway(AsyncIOClient):
    """TCP implementation of AsyncIOClient for NMEA2000 Actisense gateways.
    
    This class implements a TCP client for connecting to NMEA2000 networks
    through TCP-based gateways like Actisense W2K-1 or Yacht Devices YDEN-02.
    """
    def __init__(self,
                 host: str,
                 port: int, 
                 type: Type,
                 exclude_pgns:list[str]=[], 
                 include_pgns:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={}):
        """Initialize a TCP NMEA2000 gateway client.
        
        Args:
            host: Server hostname or IP address.
            port: Server port number.
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        if type != Type.ACTISENSE and type != Type.YACHT_DEVICES:
            raise ValueError(f"Invalid type: {type}. Must be either ACTISENSE or YACHT_DEVICES.")
        
        super().__init__(exclude_pgns, include_pgns, preferred_units)
        self.host = host
        self.port = port
        self.type = type    
        self.lock = asyncio.Lock()

    async def _connect_impl(self):
        """Connect to the TCP server.
        
        This method establishes a TCP connection to the server and configures
        TCP keepalive to detect dropped connections. It's called by the
        connect() method.
        """
        self.logger.info(f"Connecting to {self.host}:{self.port}")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        # Get the underlying socket
        sock = self.writer.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # Enable keepalive
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)  # Idle time before keepalive probes (Linux/macOS)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # Interval between keepalive probes
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)  # Number of failed probes before dropping connection
        self.logger.info(f"Connected to {self.host}:{self.port}")

    async def _receive_impl(self):
        """Receive data from the TCP connection.
        
        This method reads exactly 13 bytes from the TCP connection (the size of
        a standard NMEA2000 message) and processes it. It's called repeatedly
        by the _receive_loop() method.
        """
        data = await self.reader.readline()
        self.logger.info(f"Received: {data.hex()}")
        line = data.decode('utf-8', errors='ignore').strip()
        try:
            if self.type == Type.ACTISENSE:
                message = self.decoder.decode_actisense_string(line)
            elif self.type == Type.YACHT_DEVICES:
                message = self.decoder.decode_yacht_devices_string(line)
        except Exception as e:
            self.logger.warning(f"decoding failed. text: {line}, bytes: {data.hex()}. Error: {e}")
            return

        self.logger.info(f"Received message: {message}")
        if message is not None:
            await self.queue.put(message)

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        """Encode a NMEA2000 message over the TCP connection.
        
        Args:
            nmea2000Message: The NMEA2000Message object to encode.
        """
        return self.encoder.encode_tcp(nmea2000Message)
    

class WaveShareNmea2000Gateway(AsyncIOClient):
    """Serial implementation of AsyncIOClient for NMEA2000 gateways.
    
    This class implements a USB/Serial client for connecting to NMEA2000 networks
    through serial-based gateways like ECAN-E01 or ECAN-W01.
    """
    def __init__(self,
                 port: str,
                 exclude_pgns:list[str]=[], 
                 include_pgns:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={}
                 ):
        """Initialize a USB/Serial NMEA2000 gateway client.
        
        Args:
            port: Serial port name (e.g., "/dev/ttyUSB0" on Linux or "COM3" on Windows).
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        super().__init__(exclude_pgns, include_pgns, preferred_units)
        self.port = port
        self._buffer = None

    async def _connect_impl(self):
        """Connect to the USB/Serial device.
        
        This method establishes a serial connection to the device with the
        appropriate parameters for NMEA2000 communication. It's called by the
        connect() method.
        """
        self.logger.info(f"Connecting to {self.port}")
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
        self.logger.info(f"Connected to serial port {self.port}")
        self._buffer = bytearray()
                
    async def _receive_impl(self):
        """Receive data from the USB/Serial connection.
        
        This method reads up to 100 bytes from the serial connection and
        processes complete packets found between 0xAA (start) and 0x55 (end)
        delimiters. It's called repeatedly by the _receive_loop() method.
        """
        data = await self.reader.read(100)
        self.logger.info(f"Received: {data.hex()}")
        assert self._buffer is not None
        self._buffer.extend(data)

        # Continue processing as long as there's data in the buffer
        while True:
            # Find the packet start and end delimiters
            start = self._buffer.find(b"\xaa")
            end = self._buffer.find(b"\x55", start)

            if start == -1 or end == -1:
                # If start or end not found, wait for more data
                break

            # Extract the complete packet, including the end delimiter
            packet = self._buffer[start : end + 1]
            self.logger.info(f"Received: {packet.hex()}")

            # Process the packet
            message = None
            try:
                message = self.decoder.decode_usb(packet)
            except Exception as e:
                self.logger.warning(f"decoding failed. bytes: {packet.hex()}. Error: {e}")

            self.logger.info(f"Received message: {message}")
            if message is not None:
                await self.queue.put(message)

            # Remove the processed packet from the buffer
            self._buffer = self._buffer[end + 1 :]

    async def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        """Encode a NMEA2000 message for USB/Serial device.
        
        Args:
            nmea2000Message: The NMEA2000Message object to encode.
        """
        return self.encoder.encode_usb(nmea2000Message)
