from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
import re

import can.message


class N2KFormat(StrEnum):
    BASIC_STRING = "basic_string"
    YDRAW = "ydraw"
    YDRAW_OUT = "ydraw_out"
    PCDIN = "pcdin"
    MXPGN = "mxpgn"
    PDGY = "pdgy"
    CANDUMP1 = "candump1"
    CANDUMP2 = "candump2"
    CANDUMP3 = "candump3"
    PDGY_DEBUG = "pdgy_debug"
    ACTISENSE_N2K_ASCII = "actisense_n2k_ascii"
    ACTISENSE = "actisense"
    EBYTE = "ebyte"
    USB = "usb"
    PYTHON_CAN = "python_can"

_BASIC_STRING_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T|-)\d{2}:\d{2}:\d{2}\.\d+(?:Z)?,"
)
_YDRAW_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}\.\d{3} [RT] [0-9A-Fa-f]{8}(?: [0-9A-Fa-f]{2})+$"
)
_YDRAW_OUT_RE = re.compile(r"^[0-9A-Fa-f]{8}(?: [0-9A-Fa-f]{2})+$")
_CANDUMP1_RE = re.compile(
    r"^<0x[0-9A-Fa-f]+> \[\d+\](?: [0-9A-Fa-f]{2})+\s*$"
)
_CANDUMP2_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*\s+[0-9A-Fa-f]{8}\s+\[\d+\](?:\s+[0-9A-Fa-f]{2})+\s*$"
)
_CANDUMP3_RE = re.compile(
    r"^\([^)]+\)\s+\S+\s+[0-9A-Fa-f]{8}#[0-9A-Fa-f]+\s*$"
)
_ACTISENSE_N2K_ASCII_RE = re.compile(
    r"^A\d+\.\d+\s+[0-9A-Fa-f]{5}\s+[0-9A-Fa-f]{5}\s+[0-9A-Fa-f]+\s*$"
)


def _get_0183_sentence(line: str) -> str:
    if line.startswith("\\"):
        parts = line.split("\\")
        if len(parts) >= 3:
            return parts[2]
    return line


def _is_basic_string(line: str) -> bool:
    return bool(_BASIC_STRING_RE.match(line))


def _is_ydraw(line: str) -> bool:
    return bool(_YDRAW_RE.match(line))


def _is_ydraw_out(line: str) -> bool:
    return bool(_YDRAW_OUT_RE.match(line))


def _is_pcdin(line: str) -> bool:
    return _get_0183_sentence(line).startswith("$PCDIN,")


def _is_mxpgn(line: str) -> bool:
    return _get_0183_sentence(line).startswith("$MXPGN,")


def _is_pdgy(line: str) -> bool:
    return line.startswith("!PDGY,")


def _is_candump1(line: str) -> bool:
    return bool(_CANDUMP1_RE.match(line))


def _is_candump2(line: str) -> bool:
    return bool(_CANDUMP2_RE.match(line))


def _is_candump3(line: str) -> bool:
    return bool(_CANDUMP3_RE.match(line))


def _is_pdgy_debug(line: str) -> bool:
    return line.startswith("$PDGY,")


def _is_actisense_n2k_ascii(line: str) -> bool:
    return bool(_ACTISENSE_N2K_ASCII_RE.match(line))


_FORMAT_DETECTORS: list[tuple[N2KFormat, Callable[[str], bool]]] = [
    (N2KFormat.BASIC_STRING, _is_basic_string),
    (N2KFormat.YDRAW, _is_ydraw),
    (N2KFormat.YDRAW_OUT, _is_ydraw_out),
    (N2KFormat.PCDIN, _is_pcdin),
    (N2KFormat.MXPGN, _is_mxpgn),
    (N2KFormat.PDGY, _is_pdgy),
    (N2KFormat.CANDUMP1, _is_candump1),
    (N2KFormat.CANDUMP2, _is_candump2),
    (N2KFormat.CANDUMP3, _is_candump3),
    (N2KFormat.PDGY_DEBUG, _is_pdgy_debug),
    (N2KFormat.ACTISENSE_N2K_ASCII, _is_actisense_n2k_ascii),
]


def _normalize_text_lines(input_data: str | list[str]) -> list[str]:
    if isinstance(input_data, str):
        return [input_data.strip()]
    if isinstance(input_data, list):
        if not all(isinstance(line, str) for line in input_data):
            raise ValueError("Input lists must contain only strings")
        return [line.strip() for line in input_data]
    raise ValueError("Input must be a string or a list of strings")


def _detect_text_format(line: str) -> N2KFormat:
    if not isinstance(line, str) or not line.strip():
        raise ValueError("Input not string or empty.")

    stripped = line.strip()
    for input_format, detector in _FORMAT_DETECTORS:
        if detector(stripped):
            return input_format

    raise ValueError(f"Parser not found for input. - {stripped}")


def _detect_text_input_format(input_data: str | list[str]) -> N2KFormat:
    lines = _normalize_text_lines(input_data)
    if not lines:
        raise ValueError("Input not string or empty.")

    input_format = _detect_text_format(lines[0])
    for line in lines[1:]:
        if _detect_text_format(line) != input_format:
            raise ValueError("Input lines must all use the same detected format")
    return input_format


def _detect_binary_format(packet: bytes | bytearray | memoryview) -> N2KFormat:
    packet_bytes = bytes(packet)
    if len(packet_bytes) >= 2 and packet_bytes[0] == 0xAA and packet_bytes[1] == 0x55:
        return N2KFormat.USB
    if len(packet_bytes) >= 6 and len(packet_bytes) == 5 + (packet_bytes[0] & 0x0F):
        return N2KFormat.EBYTE
    raise ValueError("Parser not found for binary input.")


def detect_format(
    input_data: str | list[str] | bytes | bytearray | memoryview | can.message.Message,
) -> N2KFormat:
    if isinstance(input_data, can.message.Message):
        return N2KFormat.PYTHON_CAN
    if isinstance(input_data, (bytes, bytearray, memoryview)):
        return _detect_binary_format(input_data)
    if isinstance(input_data, str) or isinstance(input_data, list):
        return _detect_text_input_format(input_data)
    raise ValueError(
        "Input must be a string, list of strings, bytes-like object, or python-can Message"
    )


__all__ = ["N2KFormat", "detect_format"]
