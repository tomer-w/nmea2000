import argparse
import asyncio
import sys
import logging

import can.cli

from .message import NMEA2000Message
from .ioclient import (
    AsyncIOClient,
    EByteNmea2000Gateway,
    State,
    WaveShareNmea2000Gateway,
    TextNmea2000Gateway,
    ActisenseBstNmea2000Gateway,
    PythonCanAsyncIOClient,
)
from .decoder import NMEA2000Decoder
from .encoder import NMEA2000Encoder
from .input_formats import N2KFormat, TEXT_FORMATS

logger = logging.getLogger(__name__)

# Stable sorted list of text formats for CLI help display
_TEXT_FORMATS_SORTED = sorted(TEXT_FORMATS, key=lambda f: f.name)


# Define receive callback as a standalone function
async def handle_received_message(message: NMEA2000Message):
    """Callback function for received data."""
    print(f"Received: {message}")

async def handle_received_message_json(message: NMEA2000Message):
    """Callback function that outputs JSON, one object per line."""
    print(message.to_json(), flush=True)

# Define status change callback as a standalone function
async def handle_status_change(state: State):
    """Callback function for status changes."""
    print(f"Connection status: {state}")

async def interactive_client(client: AsyncIOClient, json_output: bool = False):
    """Interactive client function to handle user input."""
    callback = handle_received_message_json if json_output else handle_received_message
    client.set_receive_callback(callback)
    client.set_status_callback(handle_status_change)
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
                try:
                    decoder.decode(line)
                except Exception as e:
                    print(f"Error: {e}")
    except KeyboardInterrupt:
        sys.stdout.flush()
        pass


def _add_common_client_args(sub: argparse.ArgumentParser):
    """Add arguments shared by all gateway client subcommands."""
    sub.add_argument(
        "--dump_file", type=str, help="Record frames to a given file")
    sub.add_argument(
        "--dump_pgns", type=str,
        help="Record only specific PGNs, comma separated")
    sub.add_argument(
        "--json", action="store_true",
        help="Output received messages as JSON, one per line")


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
        help="NMEA 2000 frame in any supported existing input format (optional if file is provided)"
    )
    decode_parser.add_argument(
        "--file", 
        type=str, 
        help="Path to a file containing supported NMEA 2000 frames"
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

    # --- Gateway client subcommands (one per AsyncIOClient) ---

    # EByte binary TCP gateway
    ebyte_parser = subparsers.add_parser(
        "ebyte",
        help="Connect to an EByte ECAN-E01/W01 TCP gateway")
    ebyte_parser.add_argument(
        "--server", type=str, required=True, help="Server IP address")
    ebyte_parser.add_argument(
        "--port", type=int, required=True, help="Server port number")
    _add_common_client_args(ebyte_parser)

    # Text / line-based TCP gateway (auto-sense or explicit format)
    text_parser = subparsers.add_parser(
        "text",
        help="Connect to a text/line-based TCP gateway (e.g. Actisense W2K-1, Yacht Devices YDEN-02)")

    def parse_text_format(value):
        val_upper = value.upper()
        if val_upper == "AUTO":
            return None
        try:
            fmt = N2KFormat[val_upper]
        except KeyError:
            valid = ", ".join(f.name for f in _TEXT_FORMATS)
            raise argparse.ArgumentTypeError(
                f"Invalid format: {value}. Valid options are: AUTO, {valid}.")
        if fmt not in TEXT_FORMATS:
            valid = ", ".join(f.name for f in _TEXT_FORMATS_SORTED)
            raise argparse.ArgumentTypeError(
                f"{value} is not a text format. Valid options are: AUTO, {valid}.")
        return fmt

    text_parser.add_argument(
        "--server", type=str, required=True, help="Server IP address")
    text_parser.add_argument(
        "--port", type=int, required=True, help="Server port number")
    text_parser.add_argument(
        "--format",
        type=parse_text_format,
        default=None,
        help="Parser format (default: AUTO). Options: AUTO, "
             + ", ".join(f.name for f in _TEXT_FORMATS_SORTED))
    _add_common_client_args(text_parser)

    # Actisense BST-D0 binary TCP gateway
    actisense_bst_parser = subparsers.add_parser(
        "actisense_bst",
        help="Connect to an Actisense device using BST-D0/BDTP framing over TCP")
    actisense_bst_parser.add_argument(
        "--server", type=str, required=True, help="Server IP address")
    actisense_bst_parser.add_argument(
        "--port", type=int, required=True, help="Server port number")
    _add_common_client_args(actisense_bst_parser)

    # WaveShare USB-CAN-A serial gateway
    waveshare_parser = subparsers.add_parser(
        "waveshare",
        help="Connect to a WaveShare USB-CAN-A serial gateway")
    waveshare_parser.add_argument(
        "--port", type=str, required=True, help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
    _add_common_client_args(waveshare_parser)

    # python-can generic CAN adapter
    can_parser = subparsers.add_parser(
        "can",
        help="Connect to a generic CAN adapter using the python-can library")
    _add_common_client_args(can_parser)
    can.cli.add_bus_arguments(can_parser)

    # Parse arguments
    args = parser.parse_args()

    if args.verbose:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # Set the global log level
        root_logger.addHandler(logging.StreamHandler())

    if args.command == "decode":
        decoder = NMEA2000Decoder(already_combined=args.single_line)

        # Decode from a frame string if provided
        if args.frame:
            decoded = decoder.decode(args.frame)
            if decoded is not None:
                print(decoded.to_json())

        # Decode from a file if provided
        elif args.file:
            parse(args.file, decoder)
        else:
            print("Error: You must provide either a frame or a file to decode.")
            exit(1)

    elif args.command == "encode":
        encoder = NMEA2000Encoder(output_format=N2KFormat.N2K_ASCII_RAW)

        # Encode from a frame json
        if args.frame:
            frame_str = args.frame
            print(f"Encoding frame: {frame_str}")
            encoded = encoder.encode(NMEA2000Message.from_json(args.frame))
            print(encoded)

        # Encode from a json file
        elif args.file:
            with open(args.file, 'r') as file:
                json_string = file.read()
            encoded = encoder.encode(NMEA2000Message.from_json(json_string))
            print(encoded)
        else:
            print("Error: You must provide either a frame or a file to encode.")
            exit(1)

    elif args.command == "ebyte":
        logger.info("Using EByteNmea2000Gateway with server: %s, port: %d",
                     args.server, args.port)
        client = EByteNmea2000Gateway(
            args.server, args.port,
            dump_to_file=args.dump_file, dump_pgns=args.dump_pgns)
        await interactive_client(client, json_output=args.json)

    elif args.command == "text":
        fmt_label = args.format.name if args.format else "AUTO"
        logger.info("Using TextNmea2000Gateway (%s) with server: %s, port: %d",
                     fmt_label, args.server, args.port)
        client = TextNmea2000Gateway(
            args.server, args.port, format=args.format,
            dump_to_file=args.dump_file, dump_pgns=args.dump_pgns)
        await interactive_client(client, json_output=args.json)

    elif args.command == "actisense_bst":
        logger.info("Using ActisenseBstNmea2000Gateway with server: %s, port: %d",
                     args.server, args.port)
        client = ActisenseBstNmea2000Gateway(
            args.server, args.port,
            dump_to_file=args.dump_file, dump_pgns=args.dump_pgns)
        await interactive_client(client, json_output=args.json)

    elif args.command == "waveshare":
        logger.info("Using WaveShareNmea2000Gateway with port: %s", args.port)
        client = WaveShareNmea2000Gateway(
            port=args.port,
            dump_to_file=args.dump_file, dump_pgns=args.dump_pgns)
        await interactive_client(client, json_output=args.json)

    elif args.command == "can":
        logger.info("Using PythonCanAsyncIOClient with interface: %s", args.interface)
        consumed = ["command", "dump_file", "dump_pgns", "json", "verbose"]
        kwargs = {k: v for (k, v) in args.__dict__.items() if k not in consumed}
        client = PythonCanAsyncIOClient(
            dump_to_file=args.dump_file, dump_pgns=args.dump_pgns,
            **kwargs)
        await interactive_client(client, json_output=args.json)

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Interrupted by user")

if __name__ == "__main__":
    main()
