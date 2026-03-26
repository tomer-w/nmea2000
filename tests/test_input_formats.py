import pytest

from nmea2000.input_formats import (
    N2KTextFormat,
    decode_n2k_text_line,
    detect_n2k_text_format,
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


@pytest.mark.parametrize(
    ("input_line", "expected_format"),
    [
        (BASIC_STRING_FRAME, N2KTextFormat.BASIC_STRING),
        (YDRAW_FRAME, N2KTextFormat.YDRAW),
        (YDRAW_OUT_FRAME, N2KTextFormat.YDRAW_OUT),
        (PCDIN_FRAME, N2KTextFormat.PCDIN),
        (MXPGN_FRAME, N2KTextFormat.MXPGN),
        (PDGY_FRAME, N2KTextFormat.PDGY),
        (CANDUMP1_FRAME, N2KTextFormat.CANDUMP1),
        (CANDUMP2_FRAME, N2KTextFormat.CANDUMP2),
        (CANDUMP3_FRAME, N2KTextFormat.CANDUMP3),
        (PDGY_DEBUG_FRAME, N2KTextFormat.PDGY_DEBUG),
        (ACTISENSE_FRAME, N2KTextFormat.ACTISENSE_N2K_ASCII),
    ],
)
def test_detect_n2k_text_format(input_line: str, expected_format: N2KTextFormat):
    assert detect_n2k_text_format(input_line) == expected_format


def test_detect_n2k_text_format_rejects_unknown_input():
    with pytest.raises(ValueError, match="Parser not found for input"):
        detect_n2k_text_format("foo,bar")


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
def test_decode_n2k_text_line_supported(input_line: str, expected_pgn: int):
    decoder = _get_decoder()
    msg = decode_n2k_text_line(decoder, input_line)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == expected_pgn


def test_decode_n2k_text_line_rejects_pdgy_debug():
    decoder = _get_decoder()
    with pytest.raises(ValueError, match="PDGY debug lines are not supported"):
        decode_n2k_text_line(decoder, PDGY_DEBUG_FRAME)
