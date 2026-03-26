import pytest

from nmea2000.encoder import NMEA2000Encoder
from nmea2000.input_formats import (
    N2KFormat,
    detect_format,
)
from nmea2000.message import NMEA2000Message

from .test_decoder import _get_decoder


ACTISENSE_FRAME = "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF"
BASIC_STRING_FRAME = (
    "2016-04-09T16:41:09.078Z,3,127257,17,255,8,00,ff,7f,52,00,21,fe,ff"
)
YDRAW_FRAME = "16:29:27.082 R 09F8017F 50 C3 B8 13 47 D8 2B C6"
YDRAW_OUT_FRAME = "18EEFF01 05 A0 BE 1C 00 A0 A0 C0"
PCDIN_FRAME = "$PCDIN,01F119,00000000,0F,2AAF00D1067414FF*59"
MXPGN_FRAME = "$MXPGN,01F801,2801,C1308AC40C5DE343*19"
PDGY_FRAME = "!PDGY,127257,3,17,255,0.563,AP9/UgAh/v8="
CANDUMP1_FRAME = "<0x18EEFF01> [8] 05 A0 BE 1C 00 A0 A0 C0"
CANDUMP2_FRAME = "can0  18EEFF01   [8]  05 A0 BE 1C 00 A0 A0 C0"
CANDUMP3_FRAME = "(1502979132.106111) slcan0 18EEFF01#05A0BE1C00A0A0C0"
PDGY_DEBUG_FRAME = "$PDGY,000000,4,,5,482,1,0"

_GNSS_PRECISION_TOLERANCES = {
    "latitude": 1e-15,
    "longitude": 1e-15,
}


def _assert_semantic_roundtrip(
    original: NMEA2000Message,
    decoded: NMEA2000Message,
):
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


def _decode_canonical_text_output(
    encoded_output: str | list[str],
    output_format: N2KFormat,
) -> NMEA2000Message:
    decoder = _get_decoder()
    decoded = decoder.decode(
        encoded_output,
        single_line=output_format == N2KFormat.BASIC_STRING and isinstance(encoded_output, str),
    )
    assert isinstance(decoded, NMEA2000Message)
    return decoded


@pytest.mark.parametrize(
    ("input_line", "expected_format"),
    [
        (BASIC_STRING_FRAME, N2KFormat.BASIC_STRING),
        (YDRAW_FRAME, N2KFormat.YDRAW),
        (YDRAW_OUT_FRAME, N2KFormat.YDRAW_OUT),
        (PCDIN_FRAME, N2KFormat.PCDIN),
        (MXPGN_FRAME, N2KFormat.MXPGN),
        (PDGY_FRAME, N2KFormat.PDGY),
        (CANDUMP1_FRAME, N2KFormat.CANDUMP1),
        (CANDUMP2_FRAME, N2KFormat.CANDUMP2),
        (CANDUMP3_FRAME, N2KFormat.CANDUMP3),
        (PDGY_DEBUG_FRAME, N2KFormat.PDGY_DEBUG),
        (ACTISENSE_FRAME, N2KFormat.ACTISENSE_N2K_ASCII),
    ],
)
def test_detect_format(input_line: str, expected_format: N2KFormat):
    assert detect_format(input_line) == expected_format


def test_detect_format_supports_lists():
    assert detect_format([CANDUMP2_FRAME]) == N2KFormat.CANDUMP2


def test_detect_format_supports_binary_packets():
    assert detect_format(bytes.fromhex("aa550102010113f10908fffac2ffffffffff00d0")) == N2KFormat.USB


def test_detect_format_rejects_unknown_input():
    with pytest.raises(ValueError, match="Parser not found for input"):
        detect_format("foo,bar")


@pytest.mark.parametrize(
    ("input_line", "expected_pgn"),
    [
        (ACTISENSE_FRAME, 65280),
        (BASIC_STRING_FRAME, 127257),
        (YDRAW_FRAME, 129025),
        (YDRAW_OUT_FRAME, 60928),
        (PCDIN_FRAME, 127257),
        (MXPGN_FRAME, 129025),
        (PDGY_FRAME, 127257),
        (CANDUMP1_FRAME, 60928),
        (CANDUMP2_FRAME, 60928),
        (CANDUMP3_FRAME, 60928),
    ],
)
def test_decode_text_line_supported(input_line: str, expected_pgn: int):
    decoder = _get_decoder()
    msg = decoder.decode_text_line(input_line)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == expected_pgn


def test_decoder_decode_autosenses_supported_text_input():
    decoder = _get_decoder()
    msg = decoder.decode(BASIC_STRING_FRAME)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 127257


def test_decoder_decode_supports_binary_packets():
    decoder = _get_decoder()
    msg = decoder.decode(bytes.fromhex("aa550102010113f10908fffac2ffffffffff00d0"))
    assert isinstance(msg, NMEA2000Message)


def test_decode_text_line_rejects_pdgy_debug():
    decoder = _get_decoder()
    with pytest.raises(ValueError, match="PDGY debug lines are not supported"):
        decoder.decode_text_line(PDGY_DEBUG_FRAME)


@pytest.mark.parametrize(
    "input_data",
    [
        ACTISENSE_FRAME,
        BASIC_STRING_FRAME,
        YDRAW_FRAME,
        YDRAW_OUT_FRAME,
        PCDIN_FRAME,
        MXPGN_FRAME,
        PDGY_FRAME,
        CANDUMP1_FRAME,
        CANDUMP2_FRAME,
        CANDUMP3_FRAME,
    ],
)
def test_encode_roundtrips_semantically_in_detected_format(input_data: str):
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode(input_data, True)
    assert isinstance(msg, NMEA2000Message)
    output_format = detect_format(input_data)
    encoded = encoder.encode(msg, output_format=output_format)
    assert isinstance(encoded, (str, list))
    redecoded = _decode_canonical_text_output(encoded, output_format)
    _assert_semantic_roundtrip(msg, redecoded)


def test_encoder_encode_defaults_to_basic_string():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode(BASIC_STRING_FRAME)
    assert isinstance(msg, NMEA2000Message)
    assert encoder.encode(msg) == BASIC_STRING_FRAME


def test_encoder_uses_init_output_format_default():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder(output_format=N2KFormat.ACTISENSE)
    msg = decoder.decode(ACTISENSE_FRAME)
    assert isinstance(msg, NMEA2000Message)
    assert encoder.encode(msg) == "09FF7 0FF00 3F9FDCFFFFFFFFFF"


def test_encode_n2k_message_supports_actisense_override():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode(ACTISENSE_FRAME)
    assert isinstance(msg, NMEA2000Message)
    assert encoder.encode(msg, N2KFormat.ACTISENSE) == "09FF7 0FF00 3F9FDCFFFFFFFFFF"
