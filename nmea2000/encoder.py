"""NMEA 2000 Encoder Module"""
from __future__ import annotations

from abc import ABC, abstractmethod
from importlib import import_module
from typing import Callable, TypeAlias

import can.message

from .decoder import NMEA2000Decoder
from .input_formats import N2KFormat
from .message import NMEA2000Message
from . import pgns as pgns_module


N2KEncoded: TypeAlias = str | list[bytes] | list[can.message.Message]


class EncoderInterface(ABC):
    """Public encoder contract shared by the dispatcher and concrete handlers."""

    @abstractmethod
    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> N2KEncoded:
        """Encode an NMEA2000Message."""


class EncoderBase:
    """Shared encoder mechanics used by concrete format handlers."""

    def __init__(self, output_format: N2KFormat | str = N2KFormat.ACTISENSE) -> None:
        self.sequence_counter = 0
        self.output_format = self._normalize_output_format(output_format)

    @classmethod
    def _normalize_output_format(cls, output_format: N2KFormat | str) -> N2KFormat:
        if isinstance(output_format, N2KFormat):
            return output_format
        if isinstance(output_format, str):
            normalized = output_format.strip().lower()
            try:
                return N2KFormat(normalized)
            except ValueError as exc:
                raise ValueError(f"Unsupported format: {output_format}") from exc
        raise ValueError(f"Unsupported format type: {type(output_format)!r}")

    def _resolve_output_format(self, output_format: N2KFormat | str | None) -> N2KFormat:
        if output_format is None:
            return self.output_format
        return self._normalize_output_format(output_format)

    def _assert_output_format(self, output_format: N2KFormat | str | None = None) -> N2KFormat:
        requested_format = self._resolve_output_format(output_format)
        if requested_format != self.output_format:
            raise ValueError(
                "This encoder instance is already bound to "
                f"{self.output_format.value}; create a new encoder for {requested_format.value}."
            )
        return requested_format

    def _call_encode_function(self, nmea200_message: NMEA2000Message) -> bytes:
        encode_func_name = f"encode_pgn_{nmea200_message.PGN}"
        encode_func: Callable[[NMEA2000Message], bytes] | None = getattr(
            pgns_module,
            encode_func_name,
            None,
        )

        if not encode_func:
            encode_func_name = f"encode_pgn_{nmea200_message.PGN}_{nmea200_message.id}"
            encode_func = getattr(pgns_module, encode_func_name, None)

            if not encode_func:
                raise ValueError(f"No encoding function found for PGN: {nmea200_message.PGN}")

        try:
            can_data_bytes = encode_func(nmea200_message)  # pylint: disable=not-callable
        except Exception as exc:
            raise ValueError(exc) from exc
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
            chunk_size = first_frame_capacity if frame_counter == 0 else 7
            start_index = frame_offset
            end_index = min(start_index + chunk_size, payload_length)
            frame_data = payload_bytes[start_index:end_index]
            frame_offset = end_index

            frame_bytes = bytes([(self.sequence_counter << 5) | frame_counter])
            if frame_counter == 0:
                frame_bytes += bytes([payload_length])
            frame_bytes += frame_data

            packets.append(frame_bytes)

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


class NMEA2000Encoder(EncoderInterface):
    """Thin public dispatcher that binds to one concrete format encoder."""

    HANDLERS: dict[N2KFormat, type[EncoderInterface]] = {}

    def __init__(self, output_format: N2KFormat | str = N2KFormat.ACTISENSE):
        self.output_format = EncoderBase._normalize_output_format(output_format)
        self._delegate: EncoderInterface | None = None

    @classmethod
    def add_handler(cls, output_format: N2KFormat, handler_cls: type[EncoderInterface]) -> None:
        cls.HANDLERS[output_format] = handler_cls

    @classmethod
    def get_handler(cls, output_format: N2KFormat) -> type[EncoderInterface]:
        handler_cls = cls.HANDLERS.get(output_format)
        if handler_cls is None:
            raise ValueError(f"Unsupported output format: {output_format}")
        return handler_cls

    def _bind_delegate(self, output_format: N2KFormat | str | None = None) -> EncoderInterface:
        requested_format = (
            self.output_format
            if output_format is None
            else EncoderBase._normalize_output_format(output_format)
        )
        if self._delegate is None:
            handler_cls = self.get_handler(requested_format)
            self.output_format = requested_format
            self._delegate = handler_cls(output_format=requested_format)
            return self._delegate

        if requested_format != self.output_format:
            raise ValueError(
                "This NMEA2000Encoder instance is already bound to "
                f"{self.output_format.value}; create a new encoder for {requested_format.value}."
            )
        return self._delegate

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> N2KEncoded:
        delegate = self._bind_delegate(output_format)
        return delegate.encode(nmea200_message, self.output_format)


import_module(".encoder_formats", __package__)

__all__ = [
    "EncoderBase",
    "EncoderInterface",
    "NMEA2000Encoder",
]
