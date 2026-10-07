"""The canboat decoding/encoding backend.

Every bit of NMEA 2000 knowledge (field layouts, scaling, sentinels, lookups)
comes from the ``canboat`` Rust crate (the CANboat PGN database), compiled into
``nmea2000._canboat``, which also decodes and encodes nmea2000's messages. This
module only describes, once per PGN definition, how its fields appear in
nmea2000's long-standing message model: field ids, units, the enum members, and
how each field's ``value`` and ``raw_value`` are presented.

Values are reported in one of three unit systems:

- ``"native"`` (the default): the units canboat.json uses (``%``, ``rpm``,
  ``L``, ``kWh``, ...), as nmea2000 always has;
- ``"si"``: canboat's strict SI units (``ratio``, ``Hz``, ``m3``, ``J``, ...);
- ``"metric"``: canboat's humanized units (``deg``, ``C``, ``bar``, ...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from typing import Literal

from . import _canboat as canboat
from .consts import FieldTypes, PhysicalQuantities
from .message import NMEA2000Field, NMEA2000Message
from .native_units import CANBOAT_VERSION, NATIVE_UNITS

logger = logging.getLogger(__name__)

Units = Literal["native", "si", "metric"]
UNITS: tuple[Units, ...] = ("native", "si", "metric")

# canboat.json units are mostly SI; NATIVE_UNITS lists the fields where they
# are not, which "native" rescales from the SI database.
DATABASE = canboat.Database("si")
_DATABASES = {"native": DATABASE, "si": DATABASE, "metric": canboat.Database("metric")}

if DATABASE.version != CANBOAT_VERSION:
    logger.warning(
        "canboat %s does not match the %s schema nmea2000 was generated from; "
        "units of fields added since may be reported in SI",
        DATABASE.version,
        CANBOAT_VERSION,
    )

_NUMERIC_TYPES = {
    "NUMBER",
    "MMSI",
    "PGN",
    "DURATION",
    "FIELD_INDEX",
    "DYNAMIC_FIELD_LENGTH",
}
_LOOKUP_TYPES = {"LOOKUP", "INDIRECT_LOOKUP", "DYNAMIC_FIELD_KEY"}

# How each field type's value and raw_value are reported; the codes are the
# Rust codec's `Mode` (rust/src/message.rs), which implements them:
#   0 number: the value in the chosen units, int when whole and the
#     resolution is integral; raw_value is the same value
#   1 lookup: the label (None when unknown) and the code on the wire
#   2 reserved / spare / ISO NAME: the wire integer, as value and raw_value
#   3 bit lookup: the set bits' labels joined by ", ", and the wire integer
#   4 time: a datetime.time (whole seconds), and the seconds since midnight
#   5 date: a datetime.date, and the days since 1970-01-01
#   6 fixed string: the text, and the field's bytes (padding included)
#   7 other strings: the text, as value and raw_value
#   8 decimal: the digits as an int
#   9 dynamic value: the field's bytes (whatever type its key names)
#   10 anything else: canboat's value, as value and raw_value
# A field canboat reports as not available is None (a lookup keeps its code).
_MODES = {
    **dict.fromkeys(_NUMERIC_TYPES, 0),
    **dict.fromkeys(_LOOKUP_TYPES, 1),
    **dict.fromkeys(("RESERVED", "SPARE", "ISO_NAME"), 2),
    "BITLOOKUP": 3,
    "TIME": 4,
    "DATE": 5,
    "STRING_FIX": 6,
    "STRING_LZ": 7,
    "STRING_LAU": 7,
    "DECIMAL": 8,
    "DYNAMIC_FIELD_VALUE": 9,
}


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """How one canboat field definition appears in an NMEA2000Message."""

    id: str  # nmea2000's id: RESERVED fields are named after their bit offset
    name: str
    description: str | None
    field_type: str
    unit: str | None
    physical_quantity: PhysicalQuantities | None
    type: FieldTypes
    part_of_primary_key: bool
    # canboat.json's (resolution, offset) when "native" rescales the field
    native: tuple[float, int] | None
    integral: bool  # whole values are reported as int


def _field_spec(
    pgn: canboat.PgnInfo, info: canboat.FieldInfo, units: Units
) -> FieldSpec:
    field_type = info.field_type or "NUMBER"
    native = NATIVE_UNITS.get((pgn.id, info.id)) if units == "native" else None
    if native is not None:
        unit, resolution, offset = native
        native_scale = (resolution, offset or 0) if resolution else None
    else:
        unit = info.unit
        resolution, offset = info.resolution, info.offset or 0
        native_scale = None
    try:
        physical_quantity = (
            PhysicalQuantities[info.physical_quantity]
            if info.physical_quantity
            else None
        )
    except KeyError:
        physical_quantity = None
    try:
        ftype = FieldTypes[field_type]
    except KeyError:
        ftype = FieldTypes.NUMBER
    return FieldSpec(
        # (a reserved field after a variable-length one has no fixed offset)
        id=f"reserved_{'' if info.bit_offset is None else info.bit_offset}"
        if field_type == "RESERVED"
        else info.id,
        name=info.name,
        description=info.description,
        field_type=field_type,
        unit=unit,
        physical_quantity=physical_quantity,
        type=ftype,
        part_of_primary_key=info.part_of_primary_key,
        native=native_scale,
        integral=resolution is not None
        and float(resolution).is_integer()
        and not offset,
    )


@cache
def _template(
    pgn_id: str, units: Units
) -> tuple[timedelta | None, FieldTypes, list[tuple]]:
    """How the PGN definition ``pgn_id`` appears as an NMEA2000Message."""
    info = _DATABASES[units].pgn_info(pgn_id)
    interval = info.transmission_interval
    rows = []
    for field_info in info.fields:
        f = _field_spec(info, field_info, units)
        rows.append(
            (
                f.id,
                f.name,
                f.description,
                f.unit,
                f.physical_quantity,
                f.type,
                f.part_of_primary_key,
                _MODES.get(f.field_type, 10),
                f.native[0] if f.native else None,
                float(f.native[1]) if f.native else 0.0,
                f.integral,
            )
        )
    return (
        timedelta(milliseconds=interval) if interval else None,
        FieldTypes.VARIABLE,
        rows,
    )


@cache
def _codec(units: Units) -> canboat.MessageCodec:
    if units not in UNITS:
        raise ValueError(f"units must be one of {', '.join(UNITS)}, not {units!r}")
    return canboat.MessageCodec(
        lambda pgn_id: _template(pgn_id, units), NMEA2000Field, NMEA2000Message, units
    )


@cache
def is_fast_pgn(pgn: int) -> bool | None:
    """Whether ``pgn`` is sent as a fast-packet; ``None`` for an unknown PGN."""
    variants = DATABASE.pgn_variants(pgn)
    if not variants:
        return None
    return variants[0].packet_type == "Fast"


def decode(
    pgn: int,
    payload: bytes,
    src: int = 0,
    dst: int = 255,
    prio: int = 6,
    units: Units = "native",
) -> NMEA2000Message | None:
    """Decode one complete PGN payload (wire order, fast-packets reassembled)."""
    try:
        return _codec(units).decode(pgn, payload, src, dst, prio)
    except canboat.DecodeError as error:
        logger.debug("canboat could not decode PGN %s: %s", pgn, error)
        return None


def encode(message: NMEA2000Message, units: Units = "native") -> bytes:
    """Encode ``message`` into its PGN payload (wire order, not fragmented).

    ``units`` is the unit system of the message's values, as it was decoded.
    """
    try:
        return _codec(units).encode(message)
    except (TypeError, OverflowError, canboat.EncodeError) as error:
        raise ValueError(f"Cant encode this message: {error}") from error
