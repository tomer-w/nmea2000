# pylint: disable=missing-function-docstring
"""The enumerations built from the canboat crate keep nmea2000's numbering."""

from nmea2000 import FieldTypes, ManufacturerCodes, PhysicalQuantities
from nmea2000 import _canboat as canboat


def test_numbering_is_the_one_nmea2000_has_always_used():
    # to_json writes these values, so they must never move
    assert FieldTypes.NUMBER.value == (1,)
    assert FieldTypes.ADDRESS.value == (24,)
    assert PhysicalQuantities.ELECTRICAL_CURRENT.value == (1,)
    assert PhysicalQuantities.SPEED.value == (11,)
    assert PhysicalQuantities.SIGNAL_TO_NOISE_RATIO.value == (30,)


def test_every_crate_field_type_and_quantity_is_a_member():
    for pgn in canboat.Database().pgns():
        for field in pgn.fields:
            if field.field_type:
                assert field.field_type in FieldTypes.__members__
            if field.physical_quantity:
                assert field.physical_quantity in PhysicalQuantities.__members__


def test_manufacturer_codes_come_from_the_crate():
    lookup = canboat.Database().lookup("MANUFACTURER_CODE")
    assert ManufacturerCodes == [name for _code, name in lookup]
    assert "Garmin" in ManufacturerCodes
    assert dict(lookup)[229] == "Garmin"
