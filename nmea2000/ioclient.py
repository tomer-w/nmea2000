import asyncio
import logging
import socket
from enum import Enum
from typing import Callable, Awaitable, Optional, Sequence
import serial_asyncio
import can.cli
import can.interface
import can.message
from tenacity import stop_never, wait_exponential, retry_if_exception_type
from tenacity.asyncio import AsyncRetrying
from abc import ABC, abstractmethod

from .consts import PhysicalQuantities
from .utils import calculate_canbus_checksum
from .decoder import NMEA2000Decoder, InvalidFrameError
from .encoder import NMEA2000Encoder
from .input_formats import N2KFormat, TEXT_FORMATS
from .message import NMEA2000Message

EncodedMessage = bytes | can.message.Message


def _configure_tcp_keepalive(sock: socket.socket) -> None:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # Enable keepalive

    idle_opt = getattr(socket, "TCP_KEEPIDLE", None)
    if idle_opt is None:
        idle_opt = getattr(socket, "TCP_KEEPALIVE", None)
    if idle_opt is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, idle_opt, 30)  # Idle time before keepalive probes (Linux/macOS)
        except OSError:
            pass

    interval_opt = getattr(socket, "TCP_KEEPINTVL", None)
    if interval_opt is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, interval_opt, 10)  # Interval between keepalive probes
        except OSError:
            pass

    count_opt = getattr(socket, "TCP_KEEPCNT", None)
    if count_opt is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, count_opt, 5)  # Number of failed probes before dropping connection
        except OSError:
            pass


class State(Enum):
    """Connection states for NMEA2000 clients.
    
    Attributes:
        DISCONNECTED: Client is initialized but not connected or has lost connection.
        CONNECTED: Client has an active connection to the device/server.
        CLOSED: Client has been deliberately closed and cannot be reconnected.
    """
    DISCONNECTED = 0
    CONNECTED = 1
    CLOSED = 2

class AsyncIOClient(ABC):
    """Base class for asynchronous NMEA2000 clients.
    
    This abstract class implements common functionality for TCP and Serial clients,
    including connection management, automatic reconnection, message handling,
    and state management. Subclasses must implement _connect_impl, _receive_impl,
    and _send_impl methods.
    """

    @abstractmethod
    async def _connect_impl(self):
        """Subclasses must implement."""
        pass

    @abstractmethod
    async def _receive_impl(self):
        """Subclasses must implement."""
        pass

    @abstractmethod
    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> Sequence[EncodedMessage]:
        """Subclasses must implement."""
        pass

    async def _send_impl(self, encoded_message: EncodedMessage):
        """Send an already encoded message using the transport's native writer."""
        if not isinstance(encoded_message, bytes):
            raise TypeError("Stream transports must encode messages as bytes.")

        writer = self.writer
        if writer is None:
            raise RuntimeError("Client is not connected to a writable stream.")

        writer.write(encoded_message)
        await writer.drain()

    def _should_reconnect_on_send_error(self, error: Exception) -> bool:
        """Whether a send failure should trigger reconnect handling."""
        return True

    def __init__(self, 
                 exclude_pgns:list[int | str], 
                 include_pgns:list[int | str],
                 exclude_manufacturer_code:list[str],
                 include_manufacturer_code:list[str],
                 preferred_units:dict[PhysicalQuantities, str],
                 dump_to_file: str | None,
                 dump_pgns:list[int | str],
                 build_network_map: bool,
                 seed_network_map: bool,
                 bound_format: N2KFormat | None = None,
                 ):
        """Initialize the AsyncIOClient.
        
        Args:
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        self._state = State.DISCONNECTED
        self.seed_network_map = seed_network_map
        if not build_network_map:
            self.seed_network_map = False
        self.reader = None
        self.writer: asyncio.StreamWriter | None = None
        self.receive_callback = None
        self.status_callback = None
        self.queue = asyncio.Queue()
        self.decoder = NMEA2000Decoder(
            bound_format=bound_format,
            exclude_pgns=exclude_pgns,
            include_pgns=include_pgns,
            exclude_manufacturer_code = exclude_manufacturer_code,
            include_manufacturer_code = include_manufacturer_code,
            preferred_units = preferred_units,
            dump_to_file=dump_to_file,
            dump_pgns = dump_pgns,
            build_network_map = build_network_map)
        self.encoder = NMEA2000Encoder()
        self.lock = asyncio.Lock()
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        self._process_queue_task = asyncio.create_task(self._process_queue())  # Track the process queue task
        self._receive_task = None  # Track the receive loop task


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
            if self._state == State.CONNECTED:
                return
                
            # Use AsyncRetrying for proper async behavior
            async for attempt in AsyncRetrying(
                stop=stop_never,  # Retry forever
                wait=wait_exponential(multiplier=0.5, max=10),  # Exponential backoff
                retry=retry_if_exception_type(Exception),  # Only retry on exceptions
                before_sleep=self.log_before_retry  # Log each failure before sleeping
            ):
                with attempt:
                    if self._state == State.CLOSED:
                        self.logger.info("Object terminated. stop connect retry.")
                        return
                    
                    await self._connect_impl()            
                    await self._update_state(State.CONNECTED)
                    self.logger.info("Connected to the gateway.")
    
                    # Cancel any existing receive loop task
                    if self._receive_task and not self._receive_task.done():
                        self.logger.info("Going to cancel existing receive task")
                        self._receive_task.cancel()
                        try:
                            await asyncio.sleep(0.01)  # Allow cancellation to propagate
                        except asyncio.CancelledError:
                            raise AssertionError("Super strange. not expected at all")
    
                    self.logger.info("Starting receive loop task")
                    # Start a new receive loop task
                    self._receive_task = asyncio.create_task(self._receive_loop())
                    if self.seed_network_map:
                        asyncio.create_task(self._seed_network_map())

    async def _seed_network_map(self):
        # To seed the network map we will send request for 3 PGNS: 60928, 126996, 126998 
        await asyncio.sleep(2)
        json_str = '{"PGN":59904,"id":"isoRequest","description":"ISO Request","fields":[{"id":"pgn","name":"PGN","description":null,"unit_of_measurement":null,"value":60928,"raw_value":60928,"physical_quantities":null,"type":[13],"part_of_primary_key":false}],"source":0,"destination":255,"priority":6,"timestamp":"2012-06-17T15:02:11","source_iso_name":null,"hash":null}'
        msg = NMEA2000Message.from_json(json_str)
        await self.send(msg)
        await asyncio.sleep(2)
        msg.fields[0].value = 126996
        await self.send(msg)
        await asyncio.sleep(2)
        msg.fields[0].value = 126998
        await self.send(msg)

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
                self.logger.error(f"Connection lost while reading. Error: {ex}. Reconnecting...", exc_info=True)
                await self._update_state(State.DISCONNECTED)
                asyncio.create_task(self.connect())
        self.logger.info("Received loop terminated")
        
    async def send(self, nmea2000Message: NMEA2000Message):
        """Send a NMEA2000 message to the gateway.
        
        If an exception occurs during sending (e.g., connection lost),
        it will trigger a reconnection attempt.
        
        Args:
            nmea2000Message: The NMEA2000Message object to send.
        """
        try:
            msgs = tuple(self._encode_impl(nmea2000Message))
        except ValueError as ve:
            self.logger.warning("Failed to encode message. Error %s", ve)
            return

        try:
            for msg in msgs:
                await self._send_impl(msg)
                if isinstance(msg, bytes):
                    self.logger.debug("Sent: %s", msg.hex())
                else:
                    self.logger.debug("Sent: %s", msg)
        except Exception as ex:
            if self._state != State.CLOSED:
                if self._should_reconnect_on_send_error(ex):
                    self.logger.error("Connection lost while sending. Error %s. Reconnecting...", ex, exc_info=True)
                    await self._update_state(State.DISCONNECTED)
                    asyncio.create_task(self.connect())
                else:
                    self.logger.warning("Send failed without reconnecting. Error %s", ex, exc_info=True)
            raise

    async def close(self):
        """Close the connection and terminate the client.
        
        This method closes the connection and sets the state to CLOSED.
        After calling this method, the client cannot be reconnected.
        """
        await self._update_state(State.CLOSED)
        if self.writer:
            self.writer.close()
        # Cancel the receive loop task if it exists
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            await asyncio.sleep(0.01)  # Allow cancellation to propagate
        # Cancel the process queue task if it exists
        if self._process_queue_task and not self._process_queue_task.done():
            self._process_queue_task.cancel()
            await asyncio.sleep(0.01)  # Allow cancellation to propagate
        self.logger.info("Connection closed.")

    async def _process_queue(self):
        """Process received messages in order.
        
        This background task processes messages from the queue and calls
        the receive_callback for each message. It runs until the client is closed.
        """
        self.logger.info("process queue loop started")
        while self._state != State.CLOSED:
            try:
                data = await self.queue.get()
            except asyncio.CancelledError:
                self.logger.info("Process queue task cancelled")
                raise

            receive_callback = self.receive_callback
            if receive_callback:
                try:
                    await receive_callback(data)
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

    async def __aenter__(self):
        """Enter the async runtime context related to this object."""
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Exit the async runtime context and clean up resources."""
        await self.close()
        

class EByteNmea2000Gateway(AsyncIOClient):
    """TCP implementation of AsyncIOClient for NMEA2000 gateways.
    
    This class implements a TCP client for connecting to NMEA2000 networks
    through TCP-based gateways like ECAN-E01 or ECAN-W01.
    https://www.cdebyte.com/products/ECAN-E01
    """
    def __init__(self,
                 host: str,
                 port: int, 
                 exclude_pgns:list[int | str]=[], 
                 include_pgns:list[int | str]=[],
                 exclude_manufacturer_code:list[str]=[],
                 include_manufacturer_code:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={},
                 dump_to_file: str | None = None,
                 dump_pgns:list[int | str]=[],
                 build_network_map: bool = False):
        """Initialize a TCP NMEA2000 gateway client.
        
        Args:
            host: Server hostname or IP address.
            port: Server port number.
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        super().__init__(
            exclude_pgns = exclude_pgns,
            include_pgns = include_pgns,
            exclude_manufacturer_code = exclude_manufacturer_code,
            include_manufacturer_code = include_manufacturer_code,
            preferred_units = preferred_units,
            dump_to_file = dump_to_file,
            dump_pgns = dump_pgns,
            build_network_map = build_network_map,
            seed_network_map = True,
            bound_format = N2KFormat.EBYTE)
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
            _configure_tcp_keepalive(sock)
        self.logger.info(f"Connected to {self.host}:{self.port}")

    async def _receive_impl(self):
        """Receive data from the TCP connection.
        
        This method reads exactly 13 bytes from the TCP connection (the size of
        a standard NMEA2000 message) and processes it. It's called repeatedly
        by the _receive_loop() method.
        """
        data = await self.reader.readexactly(13)
        self.logger.debug(f"Received: {data.hex()}")
        if data == b'Sorry,Limited':  # cant handle more TCP connections
            self.logger.error("Sorry, Limited. sleeping for 30 seconds")
            self.connected = False
            await asyncio.sleep(30)
            raise Exception("Gateway busy. reconnecting.")
        try:
            message = self.decoder.decode(data)
        except Exception as e:
            self.logger.warning(f"decoding failed. text: {data}, bytes: {data.hex()}. Error: {e}", exc_info=True)
            return

        self.logger.debug(f"Received message: {message}")
        if message is not None:
            await self.queue.put(message)

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        """Encode a NMEA2000 message over the TCP connection.
        
        Args:
            nmea2000Message: The NMEA2000Message object to encode.
        """
        return self.encoder.encode(nmea2000Message, output_format=N2KFormat.EBYTE)
    
class TextNmea2000Gateway(AsyncIOClient):
    """TCP client for text/line-based NMEA 2000 gateways.

    Connects to any gateway that sends line-delimited ASCII frames over TCP
    (e.g. Actisense W2K-1, Yacht Devices YDEN-02, Actisense PRO-NDC-1E2K in
    CAN ASCII mode).  The ``format`` parameter selects how lines are parsed
    and how outgoing messages are encoded.  When ``format`` is ``None`` the
    gateway auto-detects the format from the first received message; encoding
    is not available in that mode.
    """
    def __init__(self,
                 host: str,
                 port: int, 
                 format: N2KFormat | None = None,
                 exclude_pgns:list[int | str]=[],
                 include_pgns:list[int | str]=[],
                 exclude_manufacturer_code:list[str]=[],
                 include_manufacturer_code:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={},
                 dump_to_file: str | None = None,
                 dump_pgns:list[int | str]=[],
                 build_network_map: bool = False,
                 seed_network_map: bool = True):
        """Initialize a TCP NMEA2000 gateway client.
        
        Args:
            host: Server hostname or IP address.
            port: Server port number.
            format: The N2KFormat used by this gateway for parsing and encoding.
                When ``None``, the format is auto-detected from the first
                received message (encoding is disabled in this mode).
                Must be a text/line-based format from ``TEXT_FORMATS``.
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
            seed_network_map: Whether to seed the network map on connect.

        Raises:
            ValueError: If *format* is not ``None`` and not in ``TEXT_FORMATS``.
        """
        if format is not None and format not in TEXT_FORMATS:
            valid = ", ".join(sorted(f.name for f in TEXT_FORMATS))
            raise ValueError(
                f"TextNmea2000Gateway does not support format {format.name!r}. "
                f"Valid text formats are: {valid}."
            )
        super().__init__(
            exclude_pgns = exclude_pgns,
            include_pgns = include_pgns,
            exclude_manufacturer_code = exclude_manufacturer_code,
            include_manufacturer_code = include_manufacturer_code,
            preferred_units = preferred_units,
            dump_to_file = dump_to_file,
            dump_pgns = dump_pgns,
            build_network_map = build_network_map,
            seed_network_map = seed_network_map,
            bound_format = format)
        self.host = host
        self.port = port
        self.format = format
        self.lock = asyncio.Lock()

    async def _connect_impl(self):
        """Connect to the TCP server."""
        self.logger.info(f"Connecting to {self.host}:{self.port}")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        sock = self.writer.get_extra_info("socket")
        if sock:
            _configure_tcp_keepalive(sock)
        self.logger.info(f"Connected to {self.host}:{self.port}")

    async def _receive_impl(self):
        """Receive a single text line from the TCP connection and decode it."""
        data = await self.reader.readline()
        self.logger.debug(f"Received: {data.hex()}")
        line = data.decode('utf-8', errors='ignore').strip()
        try:
            message = self.decoder.decode(line)
        except Exception as e:
            self.logger.warning(f"decoding failed. text: {line}, bytes: {data.hex()}. Error: {e}", exc_info=True)
            return

        self.logger.debug(f"Received message: {message}")
        if message is not None:
            await self.queue.put(message)

    def _encode_impl(self, nmea2000Message: NMEA2000Message):
        """Encode a NMEA2000 message using the bound format."""
        if self.format is None:
            raise ValueError(
                "Cannot encode: this gateway was created with format=None "
                "(auto-sense mode). Specify an explicit format to enable encoding."
            )
        return self.encoder.encode(nmea2000Message, output_format=self.format)

class WaveShareNmea2000Gateway(AsyncIOClient):
    """Serial implementation of AsyncIOClient for NMEA2000 gateways.
    
    This class implements a USB/Serial client for connecting to NMEA2000 networks
    through serial-based gateways like Waveshare USB-CAN-A
    https://www.waveshare.com/wiki/USB-CAN-A
    """
    def __init__(self,
                 port: str,
                 exclude_pgns:list[int | str]=[], 
                 include_pgns:list[int | str]=[],
                 exclude_manufacturer_code:list[str]=[],
                 include_manufacturer_code:list[str]=[],
                 preferred_units:dict[PhysicalQuantities, str]={},
                 dump_to_file: str | None = None,
                 dump_pgns:list[int | str]=[],
                 build_network_map: bool = False):
        """Initialize a USB/Serial NMEA2000 gateway client.
        
        Args:
            port: Serial port name (e.g., "/dev/ttyUSB0" on Linux or "COM3" on Windows).
            exclude_pgns: List of PGNs to exclude from processing.
            include_pgns: List of PGNs to include for processing.
        """
        super().__init__(
            exclude_pgns = exclude_pgns,
            include_pgns = include_pgns,
            exclude_manufacturer_code = exclude_manufacturer_code,
            include_manufacturer_code = include_manufacturer_code,
            preferred_units = preferred_units,
            dump_to_file = dump_to_file,
            dump_pgns = dump_pgns,
            build_network_map = build_network_map,
            seed_network_map = True,
            bound_format = N2KFormat.WAVESHARE)
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

        config_packet = [
            0xaa,     #  0  Packet header
            0x55,     #  1  Packet header
            0x02,     #  3 Type: use fixed 20 bytes protocol to send and receive data ##  0x02- Setting (using fixed 20 byte protocol to send and receive data),   0x12- Setting (using variable protocol to send and receive data)##
            0x05,     #  3 CAN Baud Rate:  500kbps  ##  0x01(1Mbps),  0x02(800kbps),  0x03(500kbps),  0x04(400kbps),  0x05(250kbps),  0x06(200kbps),  0x07(125kbps),  0x08(100kbps),  0x09(50kbps),  0x0a(20kbps),  0x0b(10kbps),   0x0c(5kbps)##
            0x02,     #  4  Frame Type: Extended Frame  ##   0x01 standard frame,   0x02 extended frame ##
            0x00,     #  5  Filter ID1
            0x00,     #  6  Filter ID2
            0x00,     #  7  Filter ID3
            0x00,     #  8  Filter ID4
            0x00,     #  9  Mask ID1
            0x00,     #  10 Mask ID2
            0x00,     #  11 Mask ID3
            0x00,     #  12 Mask ID4
            0x00,     #  13 CAN mode:  normal mode  ##   0x00 normal mode,   0x01 silent mode,   0x02 loopback mode,   0x03 loopback silent mode ##
            0x00,     #  14 automatic resend:  automatic retransmission
            0x00,     #  15 Spare
            0x00,     #  16 Spare
            0x00,     #  17 Spare
            0x00,     #  18 Spare
        ]

        checksum = calculate_canbus_checksum(config_packet)
        config_packet.append(checksum)
        config_packet_bytes = bytes(config_packet)
        self.writer.write(config_packet_bytes)
        await self.writer.drain()
        self.logger.info(f"Sent config packet: {config_packet_bytes.hex()}")

    async def _receive_impl(self):
        """Receive data from the USB/Serial connection.
        Based on: https://www.waveshare.com/wiki/Secondary_Development_Serial_Conversion_Definition_of_CAN_Protocol
        This method reads up to 100 bytes from the serial connection and
        processes complete 20 bytes packets found after the 0xAA 0x55 header.
        We are using the _buffer as I saw from time to time bytes getting lost and we cant count on
        the fact that the header will always be after 20 bytes.
        It's called repeatedly by the _receive_loop() method.
        """
        data = await self.reader.read(100)
        self.logger.debug(f"Received: {data.hex()}")
        assert self._buffer is not None
        self._buffer.extend(data)

        # Continue processing as long as there's data in the buffer
        while True:
            # Find the packet start and end delimiters
            start = self._buffer.find(b"\xaa\x55")

            if start == -1:
                # If start marker not found, wait for more data
                break
            if start + 20 > len(self._buffer):
                # Not enough data for a full packet yet
                break

            # Extract the complete packet, including the end delimiter
            packet = self._buffer[start : start + 20]
            self.logger.debug(f"single packet: {packet.hex()}")

            # Process the packet
            message = None
            try:
                message = self.decoder.decode(packet)
            except InvalidFrameError as e:
                self.logger.debug("Invalid frame, resyncing: %s", e)
                # Skip past this false aa55 marker to find the next valid packet start
                self._buffer = self._buffer[start + 2:]
                continue
            except Exception as e:
                self.logger.warning(f"decoding failed. bytes: {packet.hex()}. Error: {e}", exc_info=True)

            self.logger.debug(f"Received message: {message}")
            if message is not None:
                await self.queue.put(message)

            # Remove the processed packet from the buffer
            self._buffer = self._buffer[start + 20:]

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        """Encode a NMEA2000 message for USB/Serial device.
        
        Args:
            nmea2000Message: The NMEA2000Message object to encode.
        """
        return self.encoder.encode(nmea2000Message, output_format=N2KFormat.WAVESHARE)

class PythonCanAsyncIOClient(AsyncIOClient):
    """AsyncIOClient implementation for python-can supported devices.

    Connects to NMEA2000 networks through any CAN interface supported by the
    python-can library (e.g. slcan, seeedstudio, socketcan).
    """
    def __init__(self,
                 interface: str,
                 channel: str,
                 exclude_pgns: list[int | str] = [],
                 include_pgns: list[int | str] = [],
                 exclude_manufacturer_code: list[str] = [],
                 include_manufacturer_code: list[str] = [],
                 preferred_units: dict[PhysicalQuantities, str] = {},
                 dump_to_file: str | None = None,
                 dump_pgns: list[int | str] = [],
                 build_network_map: bool = False,
                 send_timeout: float = 0.1,
                 send_retry_count: int = 3,
                 send_retry_delay: float = 0.05,
                 **kwargs):
        """Initialize a python-can NMEA2000 client.

        Args:
            interface: python-can interface name (e.g. 'slcan', 'socketcan').
            channel: CAN channel (e.g. '/dev/ttyUSB0', 'can0').
            **kwargs: Additional arguments passed to python-can Bus constructor.
        """
        super().__init__(
            exclude_pgns=exclude_pgns,
            include_pgns=include_pgns,
            exclude_manufacturer_code=exclude_manufacturer_code,
            include_manufacturer_code=include_manufacturer_code,
            preferred_units=preferred_units,
            dump_to_file=dump_to_file,
            dump_pgns=dump_pgns,
            build_network_map=build_network_map,
            seed_network_map=True,
            bound_format=N2KFormat.PYTHON_CAN)
        self.interface = interface
        self.channel = channel
        self.send_timeout = send_timeout
        self.send_retry_count = send_retry_count
        self.send_retry_delay = send_retry_delay
        self.can_options = kwargs
        self.bus: can.interface.Bus | None = None

    async def _connect_impl(self):
        """Connect to the CAN device via python-can."""
        self.logger.info("Connecting to %s on %s", self.interface, self.channel)
        self.bus = can.interface.Bus(
            interface=self.interface, channel=self.channel, **self.can_options)
        self.logger.info("Connected to %s on %s", self.interface, self.channel)

    async def _receive_impl(self):
        """Receive data from the CAN device using non-blocking poll."""
        msg = self.bus.recv(timeout=0)
        if msg is None:
            await asyncio.sleep(0.01)
            return

        self.logger.debug("Received: %s", msg)
        try:
            decoded_frame = self.decoder.decode(msg)
        except Exception as e:
            self.logger.warning("decoding failed. message: %s. Error: %s", msg, e, exc_info=True)
            return

        self.logger.debug("Received message: %s", decoded_frame)
        if decoded_frame is not None:
            await self.queue.put(decoded_frame)

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list:
        """Encode a NMEA2000 message for python-can device."""
        return self.encoder.encode(nmea2000Message, output_format=N2KFormat.PYTHON_CAN)

    @staticmethod
    def _is_transient_send_error(error: Exception) -> bool:
        if not isinstance(error, can.CanOperationError):
            return False

        error_text = str(error).lower()
        return (
            error.error_code == 105
            or "no buffer space available" in error_text
            or "transmit buffer full" in error_text
            or "buffer full" in error_text
        )

    def _should_reconnect_on_send_error(self, error: Exception) -> bool:
        return not self._is_transient_send_error(error)

    async def _send_impl(self, encoded_message: EncodedMessage):
        """Send an encoded python-can message over the CAN bus."""
        if not isinstance(encoded_message, can.message.Message):
            raise TypeError("python-can transport requires can.Message objects.")

        if self.bus is None:
            raise RuntimeError("Client is not connected to a CAN bus.")

        attempts = self.send_retry_count + 1
        for attempt in range(1, attempts + 1):
            try:
                self.bus.send(encoded_message, timeout=self.send_timeout)
                return
            except can.CanOperationError as error:
                if not self._is_transient_send_error(error) or attempt == attempts:
                    raise

                self.logger.warning(
                    "python-can transmit queue full, retrying send (%s/%s) in %.2fs",
                    attempt,
                    attempts,
                    self.send_retry_delay,
                    exc_info=error
                )
                await asyncio.sleep(self.send_retry_delay)

    async def close(self):
        try:
            await super().close()
        finally:
            if self.bus is not None:
                self.bus.shutdown()


# BDTP (Binary Data Transfer Protocol) framing constants
_DLE = 0x10
_STX = 0x02
_ETX = 0x03


def bdtp_unwrap(buffer: bytearray) -> tuple[bytes | None, int]:
    """Extract one BDTP frame from a byte buffer.

    Returns ``(payload, consumed)`` where *payload* is the un-escaped data
    block (or ``None`` if no complete frame is available yet) and *consumed*
    is the number of bytes to discard from the front of *buffer*.
    """
    # Find DLE STX
    start = -1
    for i in range(len(buffer) - 1):
        if buffer[i] == _DLE and buffer[i + 1] == _STX:
            start = i
            break
    if start == -1:
        # No frame start found; discard everything except possibly a trailing DLE
        return None, max(0, len(buffer) - 1)

    # Scan for DLE ETX while un-escaping DLE DLE
    result = bytearray()
    i = start + 2  # skip past DLE STX
    while i < len(buffer):
        if buffer[i] == _DLE:
            if i + 1 >= len(buffer):
                # Need more data to decide
                return None, start
            if buffer[i + 1] == _ETX:
                # End of frame
                return bytes(result), i + 2
            if buffer[i + 1] == _DLE:
                # Escaped DLE
                result.append(_DLE)
                i += 2
                continue
            if buffer[i + 1] == _STX:
                # Unexpected new frame start — discard current and restart
                return None, i
            # Unknown DLE escape — discard frame
            return None, i + 2
        else:
            result.append(buffer[i])
            i += 1

    # Incomplete frame — need more data
    return None, start


def bdtp_wrap(data: bytes) -> bytes:
    """Wrap a data block in BDTP framing (DLE/STX ... DLE/ETX)."""
    escaped = bytearray()
    for byte in data:
        if byte == _DLE:
            escaped.append(_DLE)
        escaped.append(byte)
    return bytes([_DLE, _STX]) + bytes(escaped) + bytes([_DLE, _ETX])


class ActisenseBstNmea2000Gateway(AsyncIOClient):
    """TCP client for Actisense devices using BST protocol over BDTP framing.

    Supports both BST D0 (pre-assembled N2K messages) and BST 95 (raw CAN
    frames).  The device mode determines which format is received; both are
    decoded transparently.

    Suitable for devices like the PRO-NDC-1E2K.
    """

    _SUPPORTED_BST_CMDS = {0xD0, 0x95}

    def __init__(self,
                 host: str,
                 port: int,
                 exclude_pgns: list[int | str] = [],
                 include_pgns: list[int | str] = [],
                 exclude_manufacturer_code: list[str] = [],
                 include_manufacturer_code: list[str] = [],
                 preferred_units: dict[PhysicalQuantities, str] = {},
                 dump_to_file: str | None = None,
                 dump_pgns: list[int | str] = [],
                 build_network_map: bool = False):
        super().__init__(
            exclude_pgns=exclude_pgns,
            include_pgns=include_pgns,
            exclude_manufacturer_code=exclude_manufacturer_code,
            include_manufacturer_code=include_manufacturer_code,
            preferred_units=preferred_units,
            dump_to_file=dump_to_file,
            dump_pgns=dump_pgns,
            build_network_map=build_network_map,
            seed_network_map=True,
            bound_format=None)
        self.host = host
        self.port = port
        self._buffer: bytearray | None = None

    async def _connect_impl(self):
        self.logger.info("Connecting to %s:%s (BST/BDTP)", self.host, self.port)
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        sock = self.writer.get_extra_info("socket")
        if sock:
            _configure_tcp_keepalive(sock)
        self._buffer = bytearray()
        self.logger.info("Connected to %s:%s", self.host, self.port)

    async def _receive_impl(self):
        data = await self.reader.read(4096)
        if not data:
            raise ConnectionError("Connection closed by remote host")
        self.logger.debug("Received %d bytes: %s", len(data), data.hex())
        assert self._buffer is not None
        self._buffer.extend(data)

        while True:
            payload, consumed = bdtp_unwrap(self._buffer)
            if payload is None:
                self._buffer = self._buffer[consumed:]
                break
            self._buffer = self._buffer[consumed:]

            if not payload or payload[0] not in self._SUPPORTED_BST_CMDS:
                self.logger.debug("Skipping unsupported BST message: %s",
                                  payload.hex() if payload else "(empty)")
                continue

            try:
                message = self.decoder.decode(payload)
            except Exception as e:
                self.logger.warning("BST decode failed: %s. Data: %s",
                                    e, payload.hex(), exc_info=True)
                continue

            if message is not None:
                await self.queue.put(message)

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        bst_packets = self.encoder.encode(nmea2000Message, output_format=N2KFormat.BST_95)
        return [bdtp_wrap(pkt) for pkt in bst_packets]
