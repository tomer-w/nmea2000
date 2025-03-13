import sys
import logging
import binascii
from .message import *
from .pgns import *

logger = logging.getLogger(__name__)

class NMEA2000Encoder:
    def _call_encode_function(self, nmea2000Message: NMEA2000Message) -> bytearray:
        encode_func_name = f'encode_pgn_{nmea2000Message.PGN}'
        encode_func = globals().get(encode_func_name)

        if encode_func:
            bytes = encode_func(nmea2000Message)
            return bytes
        else:
            logger.error(f"No function found for PGN: {nmea2000Message.PGN}\n")
            return None
            
    def encode_actisense(self, nmea2000Message: NMEA2000Message) -> str:
        """Convert an Nmea2000Message object into an Actisense packet string."""
        # Extract necessary fields
        priority = nmea2000Message.priority & 0xF
        dest = nmea2000Message.destination & 0xFF
        src = nmea2000Message.source & 0xFF
        pgn = nmea2000Message.PGN & 0xFFFFFF

        # Construct the first part (priority, dest, src)
        n = (src << 12) | (dest << 4) | priority
        first_part = f"{n:05X}"

        # Convert PGN to hex
        pgn_part = f"{pgn:05X}"

        nmea_int = self._call_encode_function(nmea2000Message)
        byte_length = (nmea_int.bit_length() + 7) // 8
        can_data_part = nmea_int.to_bytes(byte_length, byteorder="big")[::-1].hex().upper()

        # Construct the final Actisense string
        actisense_string = f"{first_part} {pgn_part} {can_data_part}"
        
        logger.debug(f"Encoded Actisense string: {actisense_string}")
        
        return actisense_string
