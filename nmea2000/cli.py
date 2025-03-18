import argparse
import asyncio
import sys
import logging

from .message import NMEA2000Message
from .ioclient import TcpNmea2000Gateway, UsbNmea2000Gateway
from .decoder import NMEA2000Decoder
from .encoder import NMEA2000Encoder

logger = logging.getLogger(__name__)

async def tcp_client(client):
    client.set_receive_callback(handle_received_data)  # Register callback
    await client.connect()

    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if line:
            try:
                message = NMEA2000Message.from_json(line)
            except Exception:
                print ("Not valid NMEA2000Message json")
                continue
            await client.send(message)
    await client.close()

async def handle_received_data(message: NMEA2000Message):
    """User-defined callback function for received data."""
    print(f"Callback: Received {message}")


def parse(filename: str, decoder: NMEA2000Decoder):
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
                decoder.decode_basic_string(line)
    except KeyboardInterrupt:
        sys.stdout.flush()
        pass

def main():
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

    # USB client command
    usb_client_parser = subparsers.add_parser("usb_client", help="start USB client to CANBUS gateway (for example, ECAN-E01 or ECAN-W01)")
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
            print(decoded.to_json())

        # Decode from a file if provided
        elif args.file:
            parse(args.file, decoder)
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
        if args.file:
            with open(args.file, 'r') as file:
                json_string = file.read()
            frame_str = args.frame
            encoded = encoder.encode_actisense(NMEA2000Message.from_json(json_string))
            print(encoded)
            
    elif args.command == "tcp_client":
        asyncio.run(tcp_client(TcpNmea2000Gateway(args.server, args.port)))
    elif args.command == "usb_client":
        asyncio.run(tcp_client(UsbNmea2000Gateway(args.port)))

if __name__ == "__main__":
    main()