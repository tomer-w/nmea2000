"""NMEA 2000 Encoder Module"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Literal, TypeAlias, TypeVar, overload

import can.message

from . import _canboat as canboat
from . import backend
from .decoder import NMEA2000Decoder
from .input_formats import N2KFormat
from .message import NMEA2000Message

N2KEncoded: TypeAlias = (  # pylint: disable=invalid-name
    str | list[str] | list[bytes] | list[can.message.Message]
)
EncodedT_co = TypeVar("EncodedT_co", covariant=True)


class EncoderInterface(ABC, Generic[EncodedT_co]):
    """Encoder contract for a single output format."""

    @abstractmethod
    def encode(
        self,
        nmea200_message: NMEA2000Message,
    ) -> EncodedT_co:
        """Encode an NMEA2000Message."""


class EncoderBase:
    """Shared encoder mechanics used by concrete format handlers."""

    def __init__(self, units: backend.Units = "native") -> None:
        # The unit system the messages' values are in (see nmea2000.backend)
        self.units: backend.Units = units
        # Sequence counter (3 bits)
        self.sequence_counter = 0

    def _call_encode_function(self, nmea200_message: NMEA2000Message) -> bytes:
        return backend.encode(nmea200_message, self.units)

    def _encode_fast_message(self, payload_bytes: bytes) -> list[bytes]:
        """Split a fast-packet payload into 8-byte CAN frames (the last padded with 0xff)."""
        frames = canboat.fast_packet_fragment(self.sequence_counter, payload_bytes)
        self.sequence_counter = (self.sequence_counter + 1) % 8
        return frames

    @staticmethod
    def _build_header(pgn_id: int, source: int, dest: int, priority: int) -> int:
        """Build the 29-bit CAN identifier for a PGN, source, destination and priority."""
        return canboat.can_id_compose(
            priority & 0x7, pgn_id & 0x3FFFF, source & 0xFF, dest & 0xFF
        )

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
        return [can_data_bytes]


def _normalize_output_format(output_format: N2KFormat | str) -> N2KFormat:
    if isinstance(output_format, N2KFormat):
        return output_format
    normalized = output_format.strip().lower()
    try:
        return N2KFormat(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported format: {output_format}") from exc


@overload
def create_encoder(*, units: backend.Units = ...) -> EncoderInterface[str]: ...


@overload
def create_encoder(
    output_format: Literal[
        N2KFormat.N2K_ASCII_RAW,
        N2KFormat.N2K_ASCII,
        N2KFormat.BASIC_STRING,
        N2KFormat.PCDIN,
        N2KFormat.MXPGN,
        N2KFormat.PDGY,
        N2KFormat.PDGY_DEBUG,
    ],
    *,
    units: backend.Units = ...,
) -> EncoderInterface[str]: ...


@overload
def create_encoder(
    output_format: Literal[
        N2KFormat.CAN_FRAME_ASCII_RAW,
        N2KFormat.CAN_FRAME_ASCII_RAW_OUT,
        N2KFormat.CANDUMP1,
        N2KFormat.CANDUMP2,
        N2KFormat.CANDUMP3,
    ],
    *,
    units: backend.Units = ...,
) -> EncoderInterface[str | list[str]]: ...


@overload
def create_encoder(
    output_format: Literal[
        N2KFormat.CAN_FRAME_ASCII,
        N2KFormat.EBYTE,
        N2KFormat.WAVESHARE,
        N2KFormat.BST_D0,
        N2KFormat.BST_95,
    ],
    *,
    units: backend.Units = ...,
) -> EncoderInterface[list[bytes]]: ...


@overload
def create_encoder(
    output_format: Literal[N2KFormat.PYTHON_CAN],
    *,
    units: backend.Units = ...,
) -> EncoderInterface[list[can.message.Message]]: ...


@overload
def create_encoder(
    output_format: N2KFormat | str, *, units: backend.Units = ...
) -> EncoderInterface[N2KEncoded]: ...


def create_encoder(
    output_format: N2KFormat | str = N2KFormat.N2K_ASCII_RAW,
    *,
    units: backend.Units = "native",
) -> EncoderInterface[N2KEncoded]:
    """Create an encoder bound to one output format.

    ``units`` is the unit system of the messages' values: ``"native"`` (the
    default, canboat.json's units), ``"si"`` or ``"metric"``; see
    ``NMEA2000Decoder``.
    """
    from .encoder_formats import (  # pylint: disable=import-outside-toplevel
        ENCODER_CLASSES,
    )

    normalized_format = _normalize_output_format(output_format)
    encoder_cls = ENCODER_CLASSES.get(normalized_format)
    if encoder_cls is None:
        raise ValueError(f"Unsupported output format: {normalized_format}")
    return encoder_cls(units=units)


__all__ = [
    "EncoderBase",
    "EncoderInterface",
    "create_encoder",
]
