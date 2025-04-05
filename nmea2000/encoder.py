import logging
from .message import NMEA2000Message
from .pgns import *  # noqa: F403

logger = logging.getLogger(__name__)

class NMEA2000Encoder:
    def _call_encode_function(self, nmea2000Message: NMEA2000Message) -> bytearray:
        encode_func_name = f'encode_pgn_{nmea2000Message.PGN}'
        encode_func = globals().get(encode_func_name)

        #if we have multiple functions we need to use the ID as well
        if not encode_func:
            encode_func_name = f'encode_pgn_{nmea2000Message.PGN}_{nmea2000Message.id}'
            encode_func = globals().get(encode_func_name)
            if not encode_func:
                raise ValueError(f"No encoding function found for PGN: {nmea2000Message.PGN}")
        
        try:
            bytes = encode_func(nmea2000Message)
        except Exception as e:
            raise ValueError(e)
        return bytes

    def _build_header(pgn_id: int, source: int, dest: int, priority: int) -> int:
        """
        Builds a 29-bit CAN frame ID (ID0 - ID28) from PGN, source ID, destination, and priority.
        Based on https://canboat.github.io/canboat/canboat.html
        """
        dp = (pgn_id >> 16) & 0x03      # Extract DP (and reserved)
        pf = (pgn_id >> 8) & 0xFF       # Extract PF
        ps = 0

        if pf < 0xF0:
            # PDU1 format: destination-specific, use `dest` in PS
            ps = dest
        else:
            # PDU2 format: broadcast, PGN includes PS
            ps = pgn_id & 0xFF

        pgn_field = (dp << 16) | (pf << 8) | ps  # 18 bits
        frame_id = (priority & 0x7) << 26        # 3 bits: Priority
        frame_id |= (pgn_field & 0x3FFFF) << 8   # 18 bits: PGN
        frame_id |= source & 0xFF                # 8 bits: Source

        return frame_id

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
        
        frame_id_int = NMEA2000Encoder._build_header(nmea2000Message.PGN, nmea2000Message.source, nmea2000Message.destination, nmea2000Message.priority)
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
        
        frame_id_int = NMEA2000Encoder._build_header(nmea2000Message.PGN, nmea2000Message.source, nmea2000Message.destination, nmea2000Message.priority)
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
