import asyncio
import logging
import argparse
import time
import math
from typing import List
from nmea2000.ioclient import Type
from nmea2000.message import NMEA2000Message, NMEA2000Field
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.consts import PhysicalQuantities, FieldTypes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NMEA2000TestServer")

class NMEA2000TestServer:
    """Test TCP server that simulates a NMEA2000 gateway."""

    def __init__(self, host, port: int, type: Type):
        """Initialize the test server.

        Args:
            host: The host address to bind to.
            port: The port to listen on.
        """
        self.host = host
        self.port = port
        self.type = type
        self.server = None
        self.clients: List[asyncio.StreamWriter] = []
        self.running = False
        self.encoder = NMEA2000Encoder()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a new client connection."""
        addr = writer.get_extra_info('peername')
        logger.info(f"New connection from {addr}")

        self.clients.append(writer)
        try:
            while self.running:
                try:
                    # Read data from the client (if any)
                    data = await asyncio.wait_for(reader.read(8), timeout=0.1)
                    if data:
                        logger.info(f"Received from {addr}: {data.hex()}")
                        # Echo back the received data
                        writer.write(data)
                        await writer.drain()
                        logger.info(f"Echoed back: {data.hex()}")
                except asyncio.TimeoutError:
                    # Timeout is expected when no data is received
                    pass
                except asyncio.IncompleteReadError:
                    # Client disconnected
                    logger.info(f"Client {addr} disconnected")
                    break
        except Exception as e:
            logger.error(f"Error handling client {addr}: {e}")
        finally:
            # Clean up
            if writer in self.clients:
                self.clients.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Connection from {addr} closed")

    async def send_single_message(self):
        # Generate a test message
        if self.type == Type.EBYTE:
            message = self._generate_test_message()

            # Encode the message using the NMEA2000Encoder
            tcp_data = self.encoder.encode_ebyte(message)[0]
            logger.info(f"Broadcasting message (PGN {message.PGN}): {tcp_data.hex()}")
        elif self.type == Type.ACTISENSE:
            tcp_data = "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8')
        elif self.type == Type.YACHT_DEVICES:
            tcp_data = "00:01:54.430 R 15F11910 00 00 00 E5 0B 1D FF FF\r\n".encode('utf-8')
        else:
            raise Exception ("Type not supported")
        # Send the encoded message to all connected clients
        await self.send_to_clients(tcp_data)

    async def broadcast_test_messages(self):
        """Broadcast test NMEA2000 messages to all connected clients."""
        while self.running:
            if not self.clients:
                await asyncio.sleep(1)
                continue

            try:
                await self.send_single_message()
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

            await asyncio.sleep(1)

    def _generate_test_message(self) -> NMEA2000Message:
        """Generate a test NMEA2000 message."""
        # Example: Generate a vessel heading message (PGN 127250)
        message = NMEA2000Message(
            PGN=127250,
            priority=2,
            source=1,
            destination=255,
            fields=[
                NMEA2000Field(
                    id="sid",
                    name="Sequence ID",
                    description="Sequence ID",
                    unit_of_measurement="",
                    value=0,
                    raw_value=0,
                    physical_quantities=None,
                    type=FieldTypes.NUMBER
                ),
                NMEA2000Field(
                    id="heading",
                    name="Heading",
                    description="Vessel Heading",
                    unit_of_measurement="rad",
                    value=self._generate_heading(),
                    raw_value=self._generate_heading_raw(),
                    physical_quantities=PhysicalQuantities.ANGLE,
                    type=FieldTypes.FLOAT
                ),
                NMEA2000Field(
                    id="deviation",
                    name="Deviation",
                    description="Magnetic Deviation",
                    unit_of_measurement="rad",
                    value=0,
                    raw_value=0,
                    physical_quantities=PhysicalQuantities.ANGLE,
                    type=FieldTypes.FLOAT
                ),
                NMEA2000Field(
                    id="variation",
                    name="Variation",
                    description="Magnetic Variation",
                    unit_of_measurement="rad",
                    value=0,
                    raw_value=0,
                    physical_quantities=PhysicalQuantities.ANGLE,
                    type=FieldTypes.FLOAT
                ),
                NMEA2000Field(
                    id="reference",
                    name="Reference",
                    description="Heading Reference",
                    unit_of_measurement="",
                    value=0,
                    raw_value=0,
                    physical_quantities=None,
                    type=FieldTypes.LOOKUP
                ),
                NMEA2000Field(
                    id="reserved_58",
                    name="Reserved",
                    value=0,
                    raw_value=0,
                    type=FieldTypes.RESERVED
                )
            ]
        )
        return message

    def _generate_heading(self) -> float:
        """Generate a simulated heading value in radians."""
        current_time = time.time()
        heading_degrees = (current_time * 10) % 360  # Simulate heading in degrees
        return math.radians(heading_degrees)

    def _generate_heading_raw(self) -> int:
        """Generate a simulated raw heading value in radians * 10000."""
        return int(self._generate_heading() * 10000)

    async def send_to_clients(self, data: bytes):
        """Send data to all connected clients."""
        disconnected_clients = []
        for writer in self.clients:
            try:
                writer.write(data)
                await writer.drain()
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
                disconnected_clients.append(writer)

        # Remove disconnected clients
        for writer in disconnected_clients:
            if writer in self.clients:
                self.clients.remove(writer)

    async def start(self):
        """Start the test server."""
        self.running = True
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )

        addr = self.server.sockets[0].getsockname()
        logger.info(f'NMEA2000 Test Server running on {addr}')

    def start_broadcast(self):
        # Start broadcasting test messages
        asyncio.create_task(self.broadcast_test_messages())

    async def wait(self):
        assert self.server is not None
        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        """Stop the test server."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Close all client connections
        for writer in self.clients:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self.clients = []
        logger.info("Server stopped")


async def main():
    """Run the test server."""
    parser = argparse.ArgumentParser(description='NMEA2000 Test TCP Server')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host address to bind to')
    parser.add_argument('--port', type=int, default=8881, help='Port to listen on')
    parser.add_argument("--type", type=lambda s: Type[s.upper()], default=Type.ACTISENSE, help="Type of TCP server (e.g. EBYTE or ACTISENSE)")
    args = parser.parse_args()

    server = NMEA2000TestServer(host=args.host, port=args.port, type=args.type)
    await server.start()
    server.start_broadcast()
    try:
        await server.wait()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())