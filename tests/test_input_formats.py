import copy
from pathlib import Path

import can.message
import pytest

from nmea2000.encoder import NMEA2000Encoder
from nmea2000.input_formats import N2KFormat, detect_format
from nmea2000.message import NMEA2000Message

from .test_decoder import _get_decoder


N2K_ASCII_FRAME = "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF"
N2K_ASCII_RAW_PACKET = "09FF7 0FF00 3F9FDCFFFFFFFFFF"
BASIC_STRING_FRAME = (
    "2016-04-09T16:41:09.078Z,3,127257,17,255,8,00,ff,7f,52,00,21,fe,ff"
)
CAN_FRAME_ASCII_FRAME = "00:01:54.330 R 15FD0A10 00 00 00 68 65 0F 00 FF"
CAN_FRAME_ASCII_RAW_PACKET = "01F010B3 FF FF 0C 4F 70 BE 3E 33"
PCDIN_FRAME = "$PCDIN,01F119,00000000,0F,2AAF00D1067414FF*59"
MXPGN_FRAME = "$MXPGN,01F801,2801,C1308AC40C5DE343*19"
PDGY_FRAME = "!PDGY,127257,3,17,255,0.563,AP9/UgAh/v8="
CANDUMP1_FRAME = "<0x18EEFF01> [8] 05 A0 BE 1C 00 A0 A0 C0"
CANDUMP2_FRAME = "can0  18EEFF01   [8]  05 A0 BE 1C 00 A0 A0 C0"
CANDUMP3_FRAME = "(1502979132.106111) slcan0 18EEFF01#05A0BE1C00A0A0C0"
PDGY_DEBUG_FRAME = "$PDGY,000000,4,,5,482,1,0"
TCP_PACKET = bytes.fromhex("881cff00093f9fdcffffffffff")
USB_PACKET = bytes.fromhex("aa550102010900ff1c083f9fdcffffffffff00e5")
BST_D0_PACKET = bytes.fromhex("d01500ff0900ff1c00000000003f9fdcffffffffff43")

_FAST_PACKET_FIXTURE = Path(__file__).with_name("recombine-frames-1.in")
_GNSS_PRECISION_TOLERANCES = {
    "latitude": 1e-15,
    "longitude": 1e-15,
}


def _assert_semantic_roundtrip(
    original: NMEA2000Message,
    decoded: NMEA2000Message,
) -> None:
    assert decoded.PGN == original.PGN
    assert decoded.priority == original.priority
    assert decoded.source == original.source
    assert decoded.destination == original.destination

    for field in original.fields:
        other = decoded.get_field_by_id(field.id)
        abs_tol = _GNSS_PRECISION_TOLERANCES.get(field.id)
        if (
            abs_tol is not None
            and field.value is not None
            and other.value is not None
            and field.raw_value is not None
            and other.raw_value is not None
        ):
            assert other.value == pytest.approx(field.value, abs=abs_tol)
            assert other.raw_value == pytest.approx(field.raw_value, abs=abs_tol)
        else:
            assert other.value == field.value
            assert other.raw_value == field.raw_value


def _load_fast_packet_message() -> NMEA2000Message:
    decoder = _get_decoder()
    with _FAST_PACKET_FIXTURE.open("r", encoding="utf-8") as fixture:
        for line in fixture:
            input_data = line.strip()
            if input_data.startswith("#") or len(input_data) <= 1:
                continue
            msg = decoder.decode(input_data)
            if isinstance(msg, NMEA2000Message) and msg.PGN == 129029:
                return msg
    raise AssertionError("Failed to decode fast-packet fixture message")


def _prepare_roundtrip_message(
    original: NMEA2000Message,
    output_format: N2KFormat,
) -> NMEA2000Message:
    prepared = copy.deepcopy(original)
    if output_format == N2KFormat.PCDIN:
        prepared.priority = 0
    return prepared


@pytest.mark.parametrize(
    ("input_data", "expected_format"),
    [
        (N2K_ASCII_FRAME, N2KFormat.N2K_ASCII_RAW),
        (N2K_ASCII_RAW_PACKET, N2KFormat.N2K_ASCII_RAW),
        (BASIC_STRING_FRAME, N2KFormat.BASIC_STRING),
        (CAN_FRAME_ASCII_FRAME, N2KFormat.CAN_FRAME_ASCII),
        (CAN_FRAME_ASCII_RAW_PACKET, N2KFormat.CAN_FRAME_ASCII),
        (PCDIN_FRAME, N2KFormat.PCDIN),
        (MXPGN_FRAME, N2KFormat.MXPGN),
        (PDGY_FRAME, N2KFormat.PDGY),
        (PDGY_DEBUG_FRAME, N2KFormat.PDGY_DEBUG),
        (CANDUMP1_FRAME, N2KFormat.CANDUMP1),
        (CANDUMP2_FRAME, N2KFormat.CANDUMP2),
        (CANDUMP3_FRAME, N2KFormat.CANDUMP3),
        (TCP_PACKET, N2KFormat.EBYTE),
        (USB_PACKET, N2KFormat.WAVESHARE),
        (BST_D0_PACKET, N2KFormat.BST_D0),
    ],
)
def test_detect_format_supported_inputs(input_data, expected_format: N2KFormat):
    assert detect_format(input_data) == expected_format


def test_detect_format_supports_python_can_messages():
    decoder = _get_decoder()
    msg = decoder.decode(N2K_ASCII_FRAME)
    assert isinstance(msg, NMEA2000Message)

    can_encoder = NMEA2000Encoder(output_format=N2KFormat.PYTHON_CAN)
    can_msg = can_encoder.encode(msg)[0]
    assert isinstance(can_msg, can.message.Message)
    assert detect_format(can_msg) == N2KFormat.PYTHON_CAN


def test_detect_format_supports_lists_and_multiline_strings():
    assert detect_format([CANDUMP2_FRAME]) == N2KFormat.CANDUMP2
    assert detect_format(f"{CANDUMP2_FRAME}\n{CANDUMP2_FRAME}") == N2KFormat.CANDUMP2


def test_detect_format_rejects_unknown_input():
    with pytest.raises(ValueError, match="Parser not found"):
        detect_format("foo bar baz")


@pytest.mark.parametrize(
    ("input_data", "expected_pgn"),
    [
        (N2K_ASCII_FRAME, 65280),
        (N2K_ASCII_RAW_PACKET, 65280),
        (BASIC_STRING_FRAME, 127257),
        (CAN_FRAME_ASCII_FRAME, 130314),
        (CAN_FRAME_ASCII_RAW_PACKET, 126992),
        (PCDIN_FRAME, 127257),
        (MXPGN_FRAME, 129025),
        (PDGY_FRAME, 127257),
        (CANDUMP1_FRAME, 60928),
        (CANDUMP2_FRAME, 60928),
        (CANDUMP3_FRAME, 60928),
        (TCP_PACKET, 65280),
        (USB_PACKET, 65280),
        (BST_D0_PACKET, 65280),
    ],
)
def test_decoder_decode_autosenses_supported_inputs(input_data, expected_pgn: int):
    decoder = _get_decoder()
    msg = decoder.decode(input_data)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == expected_pgn


def test_decoder_decode_autosenses_python_can_messages():
    decoder = _get_decoder()
    msg = decoder.decode(N2K_ASCII_FRAME)
    assert isinstance(msg, NMEA2000Message)

    encoder = NMEA2000Encoder(output_format=N2KFormat.PYTHON_CAN)
    can_msg = encoder.encode(msg)[0]

    redecoded = _get_decoder().decode(can_msg)
    assert isinstance(redecoded, NMEA2000Message)
    assert redecoded.PGN == msg.PGN


def test_decoder_decode_rejects_pdgy_debug():
    with pytest.raises(ValueError, match="PDGY debug lines are not supported"):
        _get_decoder().decode(PDGY_DEBUG_FRAME)


def test_encoder_encode_defaults_to_n2k_ascii_raw_output():
    decoder = _get_decoder()
    msg = decoder.decode(N2K_ASCII_FRAME)
    assert isinstance(msg, NMEA2000Message)

    encoded = NMEA2000Encoder().encode(msg)
    assert encoded == N2K_ASCII_RAW_PACKET


def test_encoder_can_roundtrip_can_frame_ascii_packets_via_generic_api():
    original = _get_decoder().decode(CAN_FRAME_ASCII_FRAME)
    assert isinstance(original, NMEA2000Message)

    encoder = NMEA2000Encoder(output_format=N2KFormat.CAN_FRAME_ASCII)
    encoded = encoder.encode(original)
    assert isinstance(encoded, list)
    encoded_packet = encoded[0].decode().strip()
    assert detect_format(encoded_packet) == N2KFormat.CAN_FRAME_ASCII

    redecoded = _get_decoder().decode(encoded_packet)
    assert isinstance(redecoded, NMEA2000Message)
    assert redecoded.PGN == original.PGN
    assert redecoded.source == original.source


@pytest.mark.parametrize(
    "output_format",
    [
        N2KFormat.N2K_ASCII,
        N2KFormat.CAN_FRAME_ASCII_RAW,
        N2KFormat.CAN_FRAME_ASCII_RAW_OUT,
        N2KFormat.PCDIN,
        N2KFormat.MXPGN,
        N2KFormat.PDGY,
        N2KFormat.CANDUMP1,
        N2KFormat.CANDUMP2,
        N2KFormat.CANDUMP3,
    ],
)
def test_encoder_roundtrips_additional_single_frame_output_formats(
    output_format: N2KFormat,
):
    original = _get_decoder().decode(BASIC_STRING_FRAME)
    assert isinstance(original, NMEA2000Message)
    prepared = _prepare_roundtrip_message(original, output_format)

    encoded = NMEA2000Encoder(output_format=output_format).encode(prepared)
    redecoded = _get_decoder().decode(encoded)
    assert isinstance(redecoded, NMEA2000Message)
    _assert_semantic_roundtrip(prepared, redecoded)


def test_encoder_rejects_pdgy_debug_output():
    original = _get_decoder().decode(BASIC_STRING_FRAME)
    assert isinstance(original, NMEA2000Message)

    encoder = NMEA2000Encoder(output_format=N2KFormat.PDGY_DEBUG)
    with pytest.raises(ValueError, match="PDGY debug lines are not supported"):
        encoder.encode(original)


@pytest.mark.parametrize(
    "output_format",
    [
        N2KFormat.CAN_FRAME_ASCII_RAW,
        N2KFormat.CAN_FRAME_ASCII_RAW_OUT,
        N2KFormat.CANDUMP1,
        N2KFormat.CANDUMP2,
        N2KFormat.CANDUMP3,
    ],
)
def test_encoder_roundtrips_fast_packet_text_output_lists(output_format: N2KFormat):
    original = _load_fast_packet_message()

    encoded = NMEA2000Encoder(output_format=output_format).encode(original)
    assert isinstance(encoded, list)

    redecoded = _get_decoder().decode(encoded)
    assert isinstance(redecoded, NMEA2000Message)
    _assert_semantic_roundtrip(original, redecoded)


@pytest.mark.parametrize(
    "output_format",
    [
        N2KFormat.N2K_ASCII,
        N2KFormat.PCDIN,
        N2KFormat.MXPGN,
        N2KFormat.PDGY,
    ],
)
def test_encoder_roundtrips_fast_packet_combined_output_formats(
    output_format: N2KFormat,
):
    original = _load_fast_packet_message()
    prepared = _prepare_roundtrip_message(original, output_format)

    encoded = NMEA2000Encoder(output_format=output_format).encode(prepared)
    assert isinstance(encoded, str)

    redecoded = _get_decoder().decode(encoded)
    assert isinstance(redecoded, NMEA2000Message)
    _assert_semantic_roundtrip(prepared, redecoded)
