# pylint: disable=missing-function-docstring
"""PGN 126208 Read/Write Fields: the manufacturer header goes with proprietary PGNs.

The Manufacturer Code / Industry Code header after the commanded PGN is in the
message exactly when that PGN is proprietary (canboat/canboat#1006).
"""

import pytest

from nmea2000 import backend
from nmea2000.message import NMEA2000Field, NMEA2000Message

STANDARD = "14f201"  # 127508 Battery Status
PROPRIETARY = "1dff01"  # 130845, proprietary
HEADER = "3f9f"  # Furuno, reserved bits, Marine Industry

FRAMES = {
    # a captured Write Fields for 127508 (canboat/canboat#1002)
    "write fields, standard": f"05 {STANDARD} 00 01 01 01 66 01 05",
    "write fields, proprietary, empty": f"05 {PROPRIETARY} {HEADER} 00 00 00",
    # parameter 1 of 130845 is the 2-byte Manufacturer Code
    "write fields, proprietary": f"05 {PROPRIETARY} {HEADER} 00 01 01 01 6600 01 0500",
    "read fields, standard": f"03 {STANDARD} 00 01 01 01 66 01",
    "read fields, proprietary": f"03 {PROPRIETARY} {HEADER} 00 01 01 01 6600 01",
    "read fields reply, standard": f"04 {STANDARD} 00 01 01 01 66 01 05",
    "read fields reply, proprietary": (
        f"04 {PROPRIETARY} {HEADER} 00 01 01 01 6600 01 0500"
    ),
    "write fields reply, standard": f"06 {STANDARD} 00 01 01 01 66 01 05",
    "write fields reply, proprietary": (
        f"06 {PROPRIETARY} {HEADER} 00 01 01 01 6600 01 0500"
    ),
}


@pytest.mark.parametrize("name", FRAMES)
def test_read_and_write_fields_round_trip(name):
    data = bytes.fromhex(FRAMES[name].replace(" ", ""))
    message = backend.decode(126208, data)
    assert message is not None
    ids = {field.id for field in message.fields}
    if "proprietary" in name:
        assert message.get_field_by_id("manufacturerCode").value == "Furuno"
        assert message.get_field_by_id("industryCode").value == "Marine Industry"
    else:
        assert "manufacturerCode" not in ids
    assert message.get_field_by_id("uniqueId").value == 0
    assert backend.encode(message) == data


def write_fields(target_pgn: int, *, header: bool) -> NMEA2000Message:
    fields = [
        NMEA2000Field("functionCode", value="Write Fields"),
        NMEA2000Field("pgn", value=target_pgn),
    ]
    if header:
        fields += [
            NMEA2000Field("manufacturerCode", value="Furuno"),
            NMEA2000Field("industryCode", value="Marine Industry"),
        ]
    fields += [
        NMEA2000Field("uniqueId", value=0),
        NMEA2000Field("numberOfSelectionPairs", value=0),
        NMEA2000Field("numberOfParameters", value=0),
    ]
    return NMEA2000Message(
        PGN=126208,
        id="nmeaWriteFieldsGroupFunction",
        fields=fields,
        priority=3,
        source=1,
        destination=255,
    )


def test_header_is_written_for_a_proprietary_pgn():
    encoded = backend.encode(write_fields(130845, header=True))
    assert encoded.hex() == f"05{PROPRIETARY}{HEADER}000000"


def test_no_header_for_a_standard_pgn():
    encoded = backend.encode(write_fields(127508, header=False))
    assert encoded.hex() == f"05{STANDARD}000000"


def test_proprietary_pgn_without_header_is_refused():
    with pytest.raises(ValueError, match="must be set: PGN 130845 is proprietary"):
        backend.encode(write_fields(130845, header=False))


def test_standard_pgn_with_header_is_refused():
    with pytest.raises(ValueError, match="only sent for a proprietary PGN"):
        backend.encode(write_fields(127508, header=True))


def command_parameters(hex_payload: str) -> list[tuple[object, object]]:
    message = backend.decode(126208, bytes.fromhex(hex_payload.replace(" ", "")))
    assert message is not None
    entries = message.get_field_by_id("##list##").value
    assert isinstance(entries, list)
    return [(e["value"].value, e["value"].raw_value) for e in entries]


def test_command_parameters_take_their_field_type():
    # 127237: steering mode (a lookup) = Heading Control, vessel heading 1.3208 rad
    assert command_parameters("01 05f101 f8 02 05 04 12 9833") == [
        ("Heading Control", 4),
        (1.3208, 1.3208),
    ]
    # 126998: a text parameter
    assert command_parameters("01 16f001 f8 01 01 0e01 50503a61702e6d6f6465") == [
        ("PP:ap.mode", "PP:ap.mode")
    ]


def test_unusable_command_parameter_keeps_its_wire_bytes():
    # 6 is the out-of-range value of the 3-bit steering mode
    assert command_parameters("01 05f101 f8 01 05 06") == [(None, b"\x06")]
