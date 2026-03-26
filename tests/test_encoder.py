import json
from pathlib import Path

import pytest

from nmea2000.message import NMEA2000Message, NMEA2000Field
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.decoder import NMEA2000Decoder
from nmea2000.consts import PhysicalQuantities
from .test_decoder import _get_decoder


_ROUNDTRIP_FIXTURE_PATH = Path(__file__).with_name("canboatjs_roundtrip.json")
with _ROUNDTRIP_FIXTURE_PATH.open("r", encoding="utf-8") as fixture_file:
    _CANBOATJS_ROUNDTRIP_CASES = json.load(fixture_file)["cases"]

def _roundtrip_case_id(case: dict) -> str:
    return f"{case['pgn']}-{case['caseIndex']}"


def _payload_from_basic_string(raw_message: str) -> bytes:
    return bytes(int(byte, 16) for byte in raw_message.split(",")[6:])


_GNSS_PRECISION_TOLERANCES = {
    "latitude": 1e-15,
    "longitude": 1e-15,
}


def _assert_payload_roundtrip(
    decoder: NMEA2000Decoder,
    encoder: NMEA2000Encoder,
    msg: NMEA2000Message,
    raw_message: str,
):
    expected_payload = _payload_from_basic_string(raw_message)
    actual_payload = encoder._call_encode_function(msg)
    if actual_payload == expected_payload:
        return

    if msg.PGN != 129029 or msg.id != "gnssPositionData":
        assert actual_payload == expected_payload
        return

    redecoder = _get_decoder()
    redecoded = None
    for packet in encoder.encode_ebyte(msg):
        redecoded = redecoder.decode_tcp(packet)
    assert isinstance(redecoded, NMEA2000Message)

    for field in msg.fields:
        other = redecoded.get_field_by_id(field.id)
        abs_tol = _GNSS_PRECISION_TOLERANCES.get(field.id)
        if abs_tol is not None:
            assert other.value == pytest.approx(field.value, abs=abs_tol)
            assert other.raw_value == pytest.approx(field.raw_value, abs=abs_tol)
        else:
            assert other.value == field.value
            assert other.raw_value == field.raw_value


def _generate_test_message() -> NMEA2000Message:
    """Generate a test NMEA2000 message."""
    # Example: Generate a vessel heading message (PGN 127250)
    message = NMEA2000Message(
        PGN=127250,
        priority=2,
        source=1,
        destination=255,
        fields=[
            NMEA2000Field(
                id="sid",
                raw_value=0,
            ),
            NMEA2000Field(
                id="heading",
                value=1, # 1 radian is 57 degrees
            ),
            NMEA2000Field(
                id="deviation",
                raw_value=0,
            ),
            NMEA2000Field(
                id="variation",
                raw_value=0,
            ),
            NMEA2000Field(
                id="reference",
                raw_value=0,
            ),
            NMEA2000Field(
                id="reserved_58",
                raw_value=0,
            )
        ]
    )
    return message

def test_tcp_encode():
    encoder = NMEA2000Encoder()
    msg_bytes = encoder.encode_ebyte(_generate_test_message())[0]
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.ANGLE:"deg"})
    msg = decoder.decode_tcp(msg_bytes)
    assert isinstance(msg, NMEA2000Message)
    assert msg.fields[1].value == 57

def test_tcp_encode_2():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_tcp(bytes.fromhex("8800ff00093f9fdcffffffffff"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes_hex = encoder.encode_ebyte(msg)[0].hex()
    assert msg_bytes_hex == "8800ff00093f9fdcffffffffff"

def test_usb_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_usb(bytes.fromhex("aa550102010113f10908fffac2ffffffffff00d0"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes_hex = encoder.encode_usb(msg)[0].hex()
    assert msg_bytes_hex == "aa550102010113f10908fffac2ffffffffff00d0"

def test_yacht_devices_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_yacht_devices_string("21:31:42.671 T 01F010B3 FF FF 0C 4F 70 BE 3E 33")
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode_yacht_devices(msg)[0]
    assert  msg_bytes == "01F010B3 FF FF 0C 4F 70 BE 3E 33\r\n".encode()

def test_python_can_encode():
    """Test encoding a NMEA2000 message to python-can Message objects."""
    import can.message
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    # Decode a known message
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert isinstance(msg, NMEA2000Message)
    # Encode to python-can
    can_messages = encoder.encode_python_can(msg)
    assert len(can_messages) == 1
    can_msg = can_messages[0]
    assert isinstance(can_msg, can.message.Message)
    assert can_msg.is_extended_id is True
    assert can_msg.is_rx is False
    assert len(can_msg.data) == 8
    # Verify arbitration_id encodes PGN 65280, source 9, priority 7
    pgn_id, source_id, dest, priority = NMEA2000Decoder._extract_header(can_msg.arbitration_id)
    assert pgn_id == 65280
    assert source_id == 9
    assert priority == 7

def test_python_can_roundtrip():
    """Test that encode -> decode roundtrip via python-can preserves message content."""
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    # Start with a USB-decoded message
    msg = decoder.decode_usb(bytes.fromhex("aa550102010113f10908fffac2ffffffffff00d0"))
    assert isinstance(msg, NMEA2000Message)
    # Encode to python-can
    can_messages = encoder.encode_python_can(msg)
    assert len(can_messages) == 1
    # Decode back from python-can
    decoder2 = _get_decoder()
    decoded = decoder2.decode_python_can(can_messages[0])
    assert isinstance(decoded, NMEA2000Message)
    assert decoded.PGN == msg.PGN
    assert decoded.source == msg.source
    assert decoded.priority == msg.priority


@pytest.mark.parametrize(
    "case",
    _CANBOATJS_ROUNDTRIP_CASES,
    ids=_roundtrip_case_id,
)
def test_canboatjs_basic_string_roundtrip_cases(case: dict):
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    expected = case["expected"]

    msg = decoder.decode_basic_string(case["input"], True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == expected["pgn"]
    assert msg.priority == expected["prio"]
    assert msg.source == expected["src"]
    assert msg.destination == expected["dst"]

    _assert_payload_roundtrip(decoder, encoder, msg, case["input"])

