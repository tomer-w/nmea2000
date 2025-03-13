import argparse
import sys
import logging
import binascii

from .decoder import NMEA2000Decoder
from .pgns import *

logger = logging.getLogger(__name__)


def parse(filename: str, decoder: NMEA2000Decoder):
    data_length = 8
    try:
        with open(filename, 'r') as file:
            while True:
                line = file.readline()
                if not line:
                    break
                if line.startswith('#') or len(line) <= 1:
                    continue
                line = line.strip()
                parts = line.split(',')
                date = parts[0]
                priority = int(parts[1])
                pgn = int(parts[2])
                src = int(parts[3])
                dest = int(parts[4])
                no_idea = parts[5]
                can_data = parts[6:6 + data_length][::-1]
                can_data_bytes = [int(byte, 16) for byte in can_data]
                can_data_hex = binascii.hexlify(bytes(can_data_bytes)).decode('ascii')
                logger.info(f'Processing: {can_data_hex}')
                decoder.decode(date, priority, pgn, src, dest, can_data_hex)
    except KeyboardInterrupt:
        sys.stdout.flush()
        pass

def main():
    logging.basicConfig(filename='parser.log', level=logging.NOTSET)
    parser = argparse.ArgumentParser(description="NMEA 2000 CLI Tool")
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

    # Parse arguments
    args = parser.parse_args()

    if args.command == "decode":
        decoder = NMEA2000Decoder()

        # Decode from a frame string if provided
        if args.frame:
            frame_str = args.frame
            print(f"Decoding frame: {frame_str}")
            decoded = decoder.decode_actisense_string(frame_str)
            print(decoded)

        # Decode from a file if provided
        elif args.file:
            parse(args.file, decoder)
        else:
            print("Error: You must provide either a frame or a file to decode.")
            exit(1)


if __name__ == "__main__":
    main()