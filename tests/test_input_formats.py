import can.message
import pytest

from nmea2000.encoder import NMEA2000Encoder
from nmea2000.input_formats import N2KFormat, detect_format
from nmea2000.message import NMEA2000Message

from .test_decoder import _get_decoder


ACTISENSE_FRAME = "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF"
ACTISENSE_PACKET = "09FF7 0FF00 3F9FDCFFFFFFFFFF"
BASIC_STRING_FRAME = "2012-06-17-15:02:11.000,6,59904,0,255,3,14,f0,01"
YACHT_DEVICES_FRAME = "00:01:54.330 R 15FD0A10 00 00 00 68 65 0F 00 FF"
YACHT_DEVICES_PACKET = "01F010B3 FF FF 0C 4F 70 BE 3E 33"
TCP_PACKET = bytes.fromhex("881cff00093f9fdcffffffffff")
USB_PACKET = bytes.fromhex("aa550102010900ff1c083f9fdcffffffffff00e5")


@pytest.mark.parametrize(
    ("input_data", "expected_format"),
    [
        (ACTISENSE_FRAME, N2KFormat.ACTISENSE),
        (ACTISENSE_PACKET, N2KFormat.ACTISENSE),
        (BASIC_STRING_FRAME, N2KFormat.BASIC_STRING),
        (YACHT_DEVICES_FRAME, N2KFormat.YACHT_DEVICES),
        (YACHT_DEVICES_PACKET, N2KFormat.YACHT_DEVICES),
        (TCP_PACKET, N2KFormat.TCP),
        (USB_PACKET, N2KFormat.USB),
    ],
)
def test_detect_format_supported_inputs(input_data, expected_format: N2KFormat):
    assert detect_format(input_data) == expected_format


def test_detect_format_supports_python_can_messages():
    decoder = _get_decoder()
    msg = decoder.decode(ACTISENSE_FRAME)
    assert isinstance(msg, NMEA2000Message)

    can_encoder = NMEA2000Encoder(output_format=N2KFormat.PYTHON_CAN)
    can_msg = can_encoder.encode(msg)[0]
    assert isinstance(can_msg, can.message.Message)
    assert detect_format(can_msg) == N2KFormat.PYTHON_CAN


def test_detect_format_rejects_unknown_input():
    with pytest.raises(ValueError, match="Parser not found"):
        detect_format("foo bar baz")


@pytest.mark.parametrize(
    ("input_data", "expected_pgn"),
    [
        (ACTISENSE_FRAME, 65280),
        (ACTISENSE_PACKET, 65280),
        (BASIC_STRING_FRAME, 59904),
        (YACHT_DEVICES_FRAME, 130314),
        (YACHT_DEVICES_PACKET, 126992),
        (TCP_PACKET, 65280),
        (USB_PACKET, 65280),
    ],
)
def test_decoder_decode_autosenses_supported_inputs(input_data, expected_pgn: int):
    decoder = _get_decoder()
    msg = decoder.decode(input_data)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == expected_pgn


def test_decoder_decode_autosenses_python_can_messages():
    decoder = _get_decoder()
    msg = decoder.decode(ACTISENSE_FRAME)
    assert isinstance(msg, NMEA2000Message)

    encoder = NMEA2000Encoder(output_format=N2KFormat.PYTHON_CAN)
    can_msg = encoder.encode(msg)[0]

    redecoded = _get_decoder().decode(can_msg)
    assert isinstance(redecoded, NMEA2000Message)
    assert redecoded.PGN == msg.PGN


def test_encoder_encode_defaults_to_actisense_packet_output():
    decoder = _get_decoder()
    msg = decoder.decode(ACTISENSE_FRAME)
    assert isinstance(msg, NMEA2000Message)

    encoded = NMEA2000Encoder().encode(msg)
    assert encoded == ACTISENSE_PACKET


def test_encoder_can_roundtrip_yacht_devices_packets_via_generic_api():
    original = _get_decoder().decode(YACHT_DEVICES_FRAME)
    assert isinstance(original, NMEA2000Message)

    encoder = NMEA2000Encoder(output_format=N2KFormat.YACHT_DEVICES)
    encoded = encoder.encode(original)
    assert isinstance(encoded, list)
    encoded_packet = encoded[0].decode().strip()
    assert detect_format(encoded_packet) == N2KFormat.YACHT_DEVICES

    redecoded = _get_decoder().decode(encoded_packet)
    assert isinstance(redecoded, NMEA2000Message)
    assert redecoded.PGN == original.PGN
    assert redecoded.source == original.source
