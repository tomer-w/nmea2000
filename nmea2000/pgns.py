"""Compatibility shim for the per-PGN functions nmea2000 used to generate.

Earlier releases generated ``decode_pgn_<pgn>``, ``decode_pgn_<pgn>_<id>``,
``encode_pgn_<pgn>``, ``encode_pgn_<pgn>_<id>`` and ``is_fast_pgn_<pgn>`` for
every PGN in canboat.json. They are now thin wrappers around the canboat
backend, created on first use.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from . import backend
from .message import NMEA2000Message

_NAME = re.compile(r"^(decode|encode|is_fast)_pgn_(\d+)(?:_(\w+))?$")


def _payload(data_raw: int, data_length_bits: int | None) -> bytes:
    if data_length_bits is None:
        data_length_bits = data_raw.bit_length()
    length = (data_length_bits + 7) // 8
    return (data_raw & ((1 << (length * 8)) - 1)).to_bytes(length, "little")


def _decoder(pgn: int, pgn_id: str | None) -> Callable[..., NMEA2000Message | None]:
    def decode(
        data_raw: int, data_length_bits: int | None = None
    ) -> NMEA2000Message | None:
        message = backend.decode(pgn, _payload(data_raw, data_length_bits))
        if message is not None and pgn_id is not None and message.id != pgn_id:
            return None
        return message

    return decode


def _encoder(pgn_id: str | None) -> Callable[[NMEA2000Message], bytes]:
    def encode(message: NMEA2000Message) -> bytes:
        if pgn_id is not None and not message.id:
            message.id = pgn_id
        return backend.encode(message)

    return encode


def __getattr__(name: str) -> Any:
    match = _NAME.match(name)
    if match is None or not backend.DATABASE.pgn_variants(int(match[2])):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    kind, pgn, pgn_id = match[1], int(match[2]), match[3]
    if kind == "is_fast":
        if pgn_id is not None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        return lambda: backend.is_fast_pgn(pgn)
    if pgn_id is not None and pgn_id not in {
        v.id for v in backend.DATABASE.pgn_variants(pgn)
    }:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    function = _decoder(pgn, pgn_id) if kind == "decode" else _encoder(pgn_id)
    function.__name__ = name
    globals()[name] = function
    return function
