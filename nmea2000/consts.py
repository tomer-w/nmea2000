"""Enumerations of canboat's field types, physical quantities and manufacturers.

The members come from the canboat crate's PGN database. Their values are the
numbers nmea2000 has always given them (their position in canboat.json, as a
1-tuple), which ``NMEA2000Message.to_json`` writes, so the legacy tables below
fix that numbering; anything newer canboat adds is numbered after them.
"""

from __future__ import annotations

from enum import Enum

from . import _canboat as canboat

_DATABASE = canboat.Database()

# canboat.json's order, which numbers the members
_LEGACY_PHYSICAL_QUANTITIES = (
    "ELECTRICAL_CURRENT",
    "ELECTRICAL_CHARGE",
    "ELECTRICAL_ENERGY",
    "ELECTRICAL_POWER",
    "ELECTRICAL_APPARENT_POWER",
    "ELECTRICAL_REACTIVE_POWER",
    "POTENTIAL_DIFFERENCE",
    "POWER_FACTOR",
    "LENGTH",
    "DISTANCE",
    "SPEED",
    "ANGLE",
    "ANGULAR_VELOCITY",
    "VOLUME",
    "VOLUMETRIC_FLOW",
    "MAGNETIC_FIELD",
    "FREQUENCY",
    "DATE",
    "TIME",
    "DURATION",
    "GEOGRAPHICAL_LATITUDE",
    "GEOGRAPHICAL_LONGITUDE",
    "TEMPERATURE",
    "PRESSURE",
    "PRESSURE_RATE",
    "CONCENTRATION",
    "DIMENSIONLESS_RATIO",
    "SQUARE_ROOT_LENGTH",
    "SIGNAL_STRENGTH",
    "SIGNAL_TO_NOISE_RATIO",
)
_LEGACY_FIELD_TYPES = (
    "NUMBER",
    "FLOAT",
    "DECIMAL",
    "LOOKUP",
    "INDIRECT_LOOKUP",
    "BITLOOKUP",
    "DYNAMIC_FIELD_KEY",
    "DYNAMIC_FIELD_LENGTH",
    "DYNAMIC_FIELD_VALUE",
    "TIME",
    "DURATION",
    "DATE",
    "PGN",
    "ISO_NAME",
    "STRING_FIX",
    "STRING_LZ",
    "STRING_LAU",
    "BINARY",
    "RESERVED",
    "SPARE",
    "MMSI",
    "VARIABLE",
    "FIELD_INDEX",
    "ADDRESS",
)


def _members(legacy: tuple[str, ...], names: set[str]) -> list[tuple[str, tuple[int]]]:
    ordered = [*legacy, *sorted(names.difference(legacy))]
    return [(name, (number,)) for number, name in enumerate(ordered, start=1)]


_FIELDS = [field for pgn in _DATABASE.pgns() for field in pgn.fields]

PhysicalQuantities = Enum(  # members typed in consts.pyi
    "PhysicalQuantities",
    _members(
        _LEGACY_PHYSICAL_QUANTITIES,
        {f.physical_quantity for f in _FIELDS if f.physical_quantity},
    ),
    module=__name__,
)
FieldTypes = Enum(
    "FieldTypes",
    _members(_LEGACY_FIELD_TYPES, {f.field_type for f in _FIELDS if f.field_type}),
    module=__name__,
)

# Indexed by nothing in particular: the manufacturer names, in canboat's order
ManufacturerCodes: list[str] = [
    name for _code, name in _DATABASE.lookup("MANUFACTURER_CODE")
]
