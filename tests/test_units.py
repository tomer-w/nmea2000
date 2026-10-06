# pylint: disable=missing-function-docstring
"""The units option: canboat.json's own units, canboat's SI, or canboat's metric."""

import pytest

from nmea2000 import NMEA2000Decoder, create_encoder
from nmea2000.input_formats import N2KFormat
from nmea2000.message import NMEA2000Field, NMEA2000Message

# Engine Parameters, Rapid Update: 600 rpm, 1 bar boost, 50 % trim
LINE = "2026-10-06T10:00:00.000Z,2,127488,1,255,8,00,60,09,e8,03,32,ff,ff"

EXPECTED = {
    "native": {
        "speed": (600.0, "rpm"),
        "boostPressure": (100000, "Pa"),
        "tiltTrim": (50, "%"),
    },
    "si": {
        "speed": (10.0, "Hz"),
        "boostPressure": (100000, "Pa"),
        "tiltTrim": (0.5, "ratio"),
    },
    "metric": {
        "speed": (600.0, "rpm"),
        "boostPressure": (1.0, "bar"),
        "tiltTrim": (50, "%"),
    },
}


@pytest.mark.parametrize("units", EXPECTED)
def test_decode_and_reencode_in_each_unit_system(units):
    msg = NMEA2000Decoder(units=units).decode(LINE)
    assert isinstance(msg, NMEA2000Message)
    for field_id, (value, unit) in EXPECTED[units].items():
        field = msg.get_field_by_id(field_id)
        assert (field.value, field.unit_of_measurement) == (value, unit)
    assert create_encoder(N2KFormat.BASIC_STRING, units=units).encode(msg) == LINE


def test_default_is_native():
    assert NMEA2000Decoder().decode(LINE) == NMEA2000Decoder(units="native").decode(
        LINE
    )


@pytest.mark.parametrize("units", EXPECTED)
def test_encode_values_in_each_unit_system(units):
    fields = [NMEA2000Field("instance", value=0)] + [
        NMEA2000Field(field_id, value=value)
        for field_id, (value, _unit) in EXPECTED[units].items()
    ]
    msg = NMEA2000Message(
        PGN=127488,
        id="engineParametersRapidUpdate",
        fields=fields,
        priority=2,
        source=1,
        destination=255,
    )
    encoded = create_encoder(N2KFormat.BASIC_STRING, units=units).encode(msg)
    assert encoded.endswith(",2,127488,1,255,8,00,60,09,e8,03,32,ff,ff")


def test_unknown_units_are_refused():
    with pytest.raises(ValueError, match="units"):
        NMEA2000Decoder(units="imperial")  # pyright: ignore[reportArgumentType]
