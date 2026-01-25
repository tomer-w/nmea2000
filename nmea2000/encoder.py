"""NMEA 2000 Encoder Module"""
import logging
from typing import Callable

from .decoder import NMEA2000Decoder
from .message import NMEA2000Message
from . import pgns as pgns_module
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)

class NMEA2000Encoder:
    """NMEA 2000 Encoder Class"""
    def __init__(self):
        # Sequence counter (3 bits)
        self.sequence_counter = 0

    def _call_encode_function(self, nmea200_message: NMEA2000Message) -> bytes:
        encode_func_name = f'encode_pgn_{nmea200_message.PGN}'
        encode_func: Callable[[NMEA2000Message], bytes] | None = getattr(pgns_module, encode_func_name, None)

        #if we have multiple functions we need to use the ID as well
        if not encode_func:
            encode_func_name = f'encode_pgn_{nmea200_message.PGN}_{nmea200_message.id}'
            encode_func: Callable[[NMEA2000Message], bytes] | None = getattr(pgns_module, encode_func_name, None)

            if not encode_func:
                raise ValueError(f"No encoding function found for PGN: {nmea200_message.PGN}")

        try:
            can_data_bytes = encode_func(nmea200_message) # pylint: disable=not-callable
        except Exception as e:
            raise ValueError(e) from e
        return can_data_bytes

    def _encode_fast_message(self, payload_bytes: bytes) -> list[bytes]:
        payload_length = len(payload_bytes)

        first_frame_capacity = 6
        if payload_length <= first_frame_capacity:
            total_frames = 1
        else:
            leftover = payload_length - first_frame_capacity
            total_frames = 1 + (leftover + 7 - 1) // 7

        packets = []
        frame_offset = 0
        for frame_counter in range(total_frames):
            if frame_counter == 0:
                chunk_size = first_frame_capacity
            else:
                chunk_size = 7
            start_index = frame_offset
            end_index = min(start_index + chunk_size, payload_length)
            frame_data = payload_bytes[start_index:end_index]
            frame_offset = end_index

            frame_bytes = bytes([(self.sequence_counter << 5) | frame_counter])
            if frame_counter == 0:
                frame_bytes += bytes([payload_length])
            frame_bytes += frame_data

            packets.append(frame_bytes)
            frame_counter += 1

        self.sequence_counter = (self.sequence_counter + 1) % 8
        return packets

    @staticmethod
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

    def _encode(self, nmea200_message: NMEA2000Message) -> list[bytes]:
        """Construct a single NMEA 2000 TCP packet from PGN, source ID, priority, and CAN data."""
        if not 0 <= nmea200_message.priority <= 7:
            raise ValueError("Priority must be between 0 and 7")
        if not 0 <= nmea200_message.source <= 255:
            raise ValueError("Source ID must be between 0 and 255")
        if not 0 <= nmea200_message.PGN <= 0x3FFFF:  # PGN is 18 bits
            raise ValueError("PGN ID must be between 0 and 0x3FFFF")

        can_data_bytes = self._call_encode_function(nmea200_message)
        is_fast = NMEA2000Decoder.is_fast_pgn(nmea200_message.PGN)
        if is_fast:
            bytes_list = self._encode_fast_message(can_data_bytes)
            return bytes_list
        else:
            return [can_data_bytes]

    def encode_ebyte(self, nmea200_message: NMEA2000Message) -> list[bytes]:
        """Construct a single NMEA 2000 eByte packet from PGN, source ID, priority, and CAN data."""
        encoded_messages = self._encode(nmea200_message)
        # Construct the frame ID
        frame_id_int = NMEA2000Encoder._build_header(nmea200_message.PGN, nmea200_message.source, nmea200_message.destination, nmea200_message.priority)
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder='big')
        result = []
        for message in encoded_messages:
            # Construct type byte: data length in bottom 4 bits
            type_byte = (len(message) & 0x0F) | (1 << 7)  # Set the FF bit
            # Construct the full packet
            result.append(bytes([type_byte]) + frame_id_bytes + message)
        return result

    def encode_usb(self, nmea200_message: NMEA2000Message) -> list[bytes]:
        """Construct a single NMEA 2000 USB packet from PGN, source ID, priority, and CAN data."""
        encoded_messages = self._encode(nmea200_message)
        frame_id_int = NMEA2000Encoder._build_header(nmea200_message.PGN, nmea200_message.source, nmea200_message.destination, nmea200_message.priority)
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder='little')
        result = []
        for message in encoded_messages:
            # https://www.waveshare.com/wiki/Secondary_Development_Serial_Conversion_Definition_of_CAN_Protocol
            frame_type_byte = 0x1 # 0x0 standard frame (frame ID 2 bytes), 0x1 - extended frame (frame ID 4 bytes)
            format_type_byte = 0x02 # 0x02-Setting (for sending and receiving data with a fixed 20-byte protocol); 0x12-Setting (for sending and receiving data with a variable protocol)
            framework_format_byte = 0x01 # No idea what is it
            # Construct and return the full packet
            msg_bytes = bytes([0xaa, 0x55, frame_type_byte, format_type_byte, framework_format_byte])
            msg_bytes += frame_id_bytes
            msg_bytes += bytes([len(message)])
            msg_bytes += message
            for _ in range(8-len(message)):
                msg_bytes += bytes([0x00])
            msg_bytes += bytes([0x00]) # byte[18] reserved
            checksum = calculate_canbus_checksum(msg_bytes)
            msg_bytes += bytes([checksum])
            result.append(msg_bytes)
        return result

    def encode_actisense(self, nmea200_message: NMEA2000Message) -> str:
        """Convert an Nmea2000Message object into an Actisense packet string."""
        # Extract necessary fields
        priority = nmea200_message.priority & 0xF
        dest = nmea200_message.destination & 0xFF
        src = nmea200_message.source & 0xFF
        pgn = nmea200_message.PGN & 0xFFFFFF

        # Construct the first part (priority, dest, src)
        n = (src << 12) | (dest << 4) | priority
        first_part = f"{n:05X}"

        # Convert PGN to hex
        pgn_part = f"{pgn:05X}"

        can_data_bytes = self._call_encode_function(nmea200_message)
        can_data_part = can_data_bytes.hex().upper()

        # Construct the final Actisense string
        actisense_string = f"{first_part} {pgn_part} {can_data_part}"

        logger.debug("Encoded Actisense string: %s", actisense_string)

        return actisense_string

    @staticmethod
    def _bytes_to_hex_string(data: bytes) -> str:
        return ' '.join(f'{byte:02X}' for byte in data)

    def encode_yacht_devices(self, nmea200_message: NMEA2000Message) -> list[bytes]:
        """Construct a single NMEA 2000 Yacht Devices packet from PGN, source ID, priority, and CAN data."""
        encoded_messages = self._encode(nmea200_message)
        # Construct the frame ID
        frame_id_int = NMEA2000Encoder._build_header(nmea200_message.PGN, nmea200_message.source, nmea200_message.destination, nmea200_message.priority)
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder='big')
        result = []
        for message in encoded_messages:
            # Construct and return the full packet
            text_msg = frame_id_bytes.hex().upper() + " " + self._bytes_to_hex_string(message) + "\r\n"
            result.append(text_msg.encode())
        return result
