import logging
from .message import NMEA2000Message
from .pgns import *  # noqa: F403

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
            
    def encode_tcp(self, nmea2000Message: NMEA2000Message) -> bytes:
        """Construct a single NMEA 2000 TCP packet from PGN, source ID, priority, and CAN data."""
        if not (0 <= nmea2000Message.priority <= 7):
            raise ValueError("Priority must be between 0 and 7")
        if not (0 <= nmea2000Message.source <= 255):
            raise ValueError("Source ID must be between 0 and 255")
        if not (0 <= nmea2000Message.PGN <= 0x3FFFF):  # PGN is 18 bits
            raise ValueError("PGN ID must be between 0 and 0x3FFFF")

        can_data_int = self._call_encode_function(nmea2000Message)
        can_data_bytes = can_data_int.to_bytes(8, "big")
        if not (0 <= len(can_data_bytes) <= 8):
            raise ValueError("CAN data must be between 0 and 8 bytes long")
        
        # Construct frame ID: 29 bits (ID0 - ID28) based on https://canboat.github.io/canboat/canboat.html
        frame_id_int = nmea2000Message.source & 0xFF #lowest 8 bits are source
        frame_id_int |= (nmea2000Message.PGN & 0x3FFFF) << 8  # Shift left by 8 bits and mask to 18 bits
        frame_id_int |= (nmea2000Message.priority & 0x07) << 18   # ID26-ID28 bits represent the priority

        frame_id_bytes = frame_id_int.to_bytes(4, byteorder='big')
        
        # Construct type byte: data length in bottom 4 bits
        type_byte = (len(can_data_bytes) & 0x0F) | (1 << 7)  # Set the FF bit
        
        # Reverse CAN data to match decode behavior
        can_data_reversed = can_data_bytes[::-1]
        
        # Construct and return the full packet
        return bytes([type_byte]) + frame_id_bytes + can_data_reversed

    def encode_usb(self, nmea2000Message: NMEA2000Message) -> bytes:
        """Construct a single NMEA 2000 USB packet from PGN, source ID, priority, and CAN data."""
        if not (0 <= nmea2000Message.priority <= 7):
            raise ValueError("Priority must be between 0 and 7")
        if not (0 <= nmea2000Message.source <= 255):
            raise ValueError("Source ID must be between 0 and 255")
        if not (0 <= nmea2000Message.PGN <= 0x3FFFF):  # PGN is 18 bits
            raise ValueError("PGN ID must be between 0 and 0x3FFFF")

        can_data_int = self._call_encode_function(nmea2000Message)
        can_data_bytes = can_data_int.to_bytes(8, "big")
        if not (0 <= len(can_data_bytes) <= 8):
            raise ValueError("CAN data must be between 0 and 8 bytes long")
        
        # Construct frame ID: 29 bits (ID0 - ID28) based on https://canboat.github.io/canboat/canboat.html
        frame_id_int = nmea2000Message.source & 0xFF #lowest 8 bits are source
        frame_id_int |= (nmea2000Message.PGN & 0x3FFFF) << 8  # Shift left by 8 bits and mask to 18 bits
        frame_id_int |= (nmea2000Message.priority & 0x07) << 18   # ID26-ID28 bits represent the priority

        frame_id_bytes = frame_id_int.to_bytes(4, byteorder='little')
        
        # Construct type byte: data length in bottom 4 bits
        type_byte = 0xE << 4 # header
        type_byte |= len(can_data_bytes) & 0x0F
        
        # Reverse CAN data to match decode behavior
        can_data_reversed = can_data_bytes[::-1]
        
        # Construct and return the full packet
        return bytes([0xaa, type_byte]) + frame_id_bytes + can_data_reversed + bytes([0x55])
    
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
