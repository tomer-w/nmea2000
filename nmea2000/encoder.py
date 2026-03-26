"""NMEA 2000 Encoder Module"""
from typing import Callable

from .encoder_formats import (
    EncoderBinaryMixin,
    EncoderCanFrameTextMixin,
    EncoderDirectTextMixin,
    EncoderDispatchMixin,
    EncoderSentenceTextMixin,
    EncoderTextSupportMixin,
)
from .decoder import NMEA2000Decoder
from .input_formats import N2KFormat
from .message import NMEA2000Message
from . import pgns as pgns_module

class NMEA2000Encoder(
    EncoderDispatchMixin,
    EncoderTextSupportMixin,
    EncoderDirectTextMixin,
    EncoderCanFrameTextMixin,
    EncoderSentenceTextMixin,
    EncoderBinaryMixin,
):
    """NMEA 2000 Encoder Class"""
    def __init__(self, output_format: N2KFormat | str = N2KFormat.BASIC_STRING):
        # Sequence counter (3 bits)
        self.sequence_counter = 0
        self.output_format = self._normalize_output_format(output_format)

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
            error_message = str(e) or (
                f"{type(e).__name__} while encoding PGN {nmea200_message.PGN}"
                f"{f' ({nmea200_message.id})' if nmea200_message.id else ''}"
            )
            raise ValueError(error_message) from e
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
