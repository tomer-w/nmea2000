import argparse
import asyncio
import sys
import logging

from .message import NMEA2000Message
from .ioclient import ActisenseNmea2000Gateway, AsyncIOClient, EByteNmea2000Gateway, State, Type, WaveShareNmea2000Gateway, YachtDevicesNmea2000Gateway
from .decoder import NMEA2000Decoder
from .encoder import NMEA2000Encoder

logger = logging.getLogger(__name__)

# Define receive callback as a standalone function
async def handle_received_message(message: NMEA2000Message):
    """Callback function for received data."""
    print(f"Received: {message}")

# Define status change callback as a standalone function
async def handle_status_change(state: State):
    """Callback function for status changes."""
    print(f"Connection status: {state}")

async def interactive_client(client: AsyncIOClient):
    """Interactive client function to handle user input."""
    client.set_receive_callback(handle_received_message)
    client. set_status_callback(handle_status_change)
    await client.connect()
    
    print("Connected to NMEA2000 gateway. Enter NMEA2000 messages in JSON format.")
    print("Type 'exit' to quit.")

    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
                
            line = line.strip()
            if line.lower() == "exit":
                break
            else:
                try:
                    message = NMEA2000Message.from_json(line)
                    await client.send(message)
                except Exception as e:
                    print(f"Error: {e}")
                    print("Not valid NMEA2000Message json")
                    continue
    except KeyboardInterrupt:
        sys.stdout.flush()
        pass
    finally:
        await client.close()
        print("Connection closed.")

def parse(filename: str, decoder: NMEA2000Decoder, single_line: bool):
    try:
        with open(filename, 'r') as file:
            while True:
                line = file.readline()
                if not line:
                    break
                if line.startswith('#') or len(line) <= 1:
                    continue
                line = line.strip()
                logger.info(f'Processing: {line}')
                try:
                    decoder.decode_basic_string(line, single_line)
                except Exception as e:
                    print(f"Error: {e}")
    except KeyboardInterrupt:
        sys.stdout.flush()
        pass

async def async_main():
    logging.basicConfig(filename='parser.log', level=logging.NOTSET)
    parser = argparse.ArgumentParser(description="NMEA 2000 CLI Tool")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose mode")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Decode command
    decode_parser = subparsers.add_parser("decode", help="Decode an NMEA 2000 frame")
    
    # Either provide a frame string or a file
    decode_parser.add_argument(
        "--frame", 
        type=str, 
        help="Hex-encoded NMEA 2000 frame (optional if file is provided)"
    )
    decode_parser.add_argument(
        "--file", 
        type=str, 
        help="Path to a file containing a Hex-encoded NMEA 2000 frame"
    )
    decode_parser.add_argument(
        "--single_line", 
        action="store_true", 
        help="Fast frame is already merged to single line"
    )

    # Encode command
    encode_parser = subparsers.add_parser("encode", help="Encode an NMEA 2000 frame")
    
    # Either provide a frame string or a file
    encode_parser.add_argument(
        "--frame", 
        type=str, 
        help="json NMEA 2000 frame (optional if file is provided)"
    )
    encode_parser.add_argument(
        "--file", 
        type=str, 
        help="Path to a file containing a JSON NMEA 2000 frame"
    )

    # TCP client command
    tcp_client_parser = subparsers.add_parser("tcp_client", help="start TCP client to CANBUS gateway (for example, ECAN-E01 or ECAN-W01)")
    tcp_client_parser.add_argument(
        "--server", 
        type=str,
        required=True, 
        help="Server IP address"
    )
    tcp_client_parser.add_argument(
        "--port", 
        type=int, 
        required=True, 
        help="Server port number"
    )
    def parse_type(value):
        try:
            return Type[value.upper()]
        except KeyError:
            valid = ", ".join(t.name for t in Type)
            raise argparse.ArgumentTypeError(f"Invalid type: {value}. Valid options are: {valid}.")

    tcp_client_parser.add_argument(
        "--type",
        type=parse_type,
        required=True,
        help="Type of TCP server (EBYTE, ACTISENSE, or YACHT_DEVICES)"
    )

    # USB client command
    usb_client_parser = subparsers.add_parser("usb_client", help="start USB client to CANBUS gateway (for example, Waveshare USB-CAN-A)")
    usb_client_parser.add_argument(
        "--port", 
        type=str, 
        required=True, 
        help="Serial port"
    )

    # Parse arguments
    args = parser.parse_args()

    if args.verbose:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # Set the global log level
        root_logger.addHandler(logging.StreamHandler())

    if args.command == "decode":
        decoder = NMEA2000Decoder()

        # Decode from a frame string if provided
        if args.frame:
            decoded = decoder.decode_actisense_string(args.frame)
            if decoded is not None:
                print(decoded.to_json())

        # Decode from a file if provided
        elif args.file:
            parse(args.file, decoder, args.single_line)
        else:
            print("Error: You must provide either a frame or a file to decode.")
            exit(1)

    elif args.command == "encode":
        encoder = NMEA2000Encoder()

        # Encode from a frame json
        if args.frame:
            frame_str = args.frame
            print(f"Encoding frame: {frame_str}")
            encoded = encoder.encode_actisense(NMEA2000Message.from_json(args.frame))
            print(encoded)

        # Encode from a json file
        elif args.file:
            with open(args.file, 'r') as file:
                json_string = file.read()
            encoded = encoder.encode_actisense(NMEA2000Message.from_json(json_string))
            print(encoded)
        else:
            print("Error: You must provide either a frame or a file to encode.")
            exit(1)
            
    elif args.command == "tcp_client":
        # Create TCP client passing callbacks in constructor
        if args.type == Type.EBYTE:
            logger.info("Using EByteNmea2000Gateway with server: %s, port: %d", args.server, args.port)
            client = EByteNmea2000Gateway(args.server, args.port)
        elif args.type == Type.ACTISENSE:
            logger.info("Using ActisenseNmea2000Gateway with server: %s, port: %d", args.server, args.port)
            client = ActisenseNmea2000Gateway(args.server, args.port)            
        elif args.type == Type.YACHT_DEVICES:
            logger.info("Using YachtDevicesNmea2000Gateway with server: %s, port: %d", args.server, args.port)
            client = YachtDevicesNmea2000Gateway(args.server, args.port)            
        await interactive_client(client)
    elif args.command == "usb_client":
        # Create USB client passing callbacks in constructor
        logger.info("Using WaveShareNmea2000Gateway with port: %s", args.port)
        client = WaveShareNmea2000Gateway(args.port)
        await interactive_client(client)

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Interrupted by user")

if __name__ == "__main__":
    main()

