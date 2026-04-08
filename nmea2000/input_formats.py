from __future__ import annotations

import re
import sys
from typing import List, Union

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum

from typing_extensions import TypeAlias

import can.message


class N2KFormat(StrEnum):
    ACTISENSE = "actisense"
    ACTISENSE_N2K_ASCII = "actisense_n2k_ascii"
    BASIC_STRING = "basic_string"
    YACHT_DEVICES = "yacht_devices"
    YDRAW = "ydraw"
    YDRAW_OUT = "ydraw_out"
    PCDIN = "pcdin"
    MXPGN = "mxpgn"
    PDGY = "pdgy"
    PDGY_DEBUG = "pdgy_debug"
    CANDUMP1 = "candump1"
    CANDUMP2 = "candump2"
    CANDUMP3 = "candump3"
    TCP = "tcp"
    USB = "usb"
    PYTHON_CAN = "python_can"


N2KInput: TypeAlias = Union[
    str,
    List[str],
    List[bytes],
    bytes,
    bytearray,
    memoryview,
    can.message.Message,
]

_ACTISENSE_ASCII_RE = re.compile(
    r"^A\d+\.\d+\s+[0-9A-Fa-f]{5}\s+[0-9A-Fa-f]{5,6}\s+[0-9A-Fa-f]+$"
)
_ACTISENSE_PACKET_RE = re.compile(
    r"^[0-9A-Fa-f]{5}\s+[0-9A-Fa-f]{5,6}\s+[0-9A-Fa-f]+$"
)
_BASIC_STRING_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}\.\d+Z?|\-\d{2}:\d{2}:\d{2}\.\d+)"
    r"(?:,\d+){5}(?:,[0-9A-Fa-f]{2})+$"
)
_YACHT_DEVICES_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}\.\d+\s+[RT]\s+[0-9A-Fa-f]{8}(?:\s+[0-9A-Fa-f]{2})+$"
)
_YACHT_DEVICES_PACKET_RE = re.compile(
    r"^[0-9A-Fa-f]{8}(?:\s+[0-9A-Fa-f]{2})+$"
)
_CANDUMP1_RE = re.compile(
    r"^<0x[0-9A-Fa-f]+>\s+\[\d+\](?:\s+[0-9A-Fa-f]{2})+\s*$"
)
_CANDUMP2_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*\s+[0-9A-Fa-f]{8}\s+\[\d+\](?:\s+[0-9A-Fa-f]{2})+\s*$"
)
_CANDUMP3_RE = re.compile(
    r"^\([^)]+\)\s+\S+\s+[0-9A-Fa-f]{8}#[0-9A-Fa-f]+\s*$"
)


def _get_0183_sentence(line: str) -> str:
    if line.startswith("\\"):
        parts = line.split("\\")
        if len(parts) >= 3:
            return parts[2]
    return line


def _first_text_line(data: str | list[str] | list[bytes]) -> str:
    if isinstance(data, str):
        candidates = data.splitlines() if "\n" in data else [data]
    else:
        candidates = data

    for candidate in candidates:
        if isinstance(candidate, (bytes, bytearray, memoryview)):
            candidate = bytes(candidate).decode("utf-8")
        elif not isinstance(candidate, str):
            raise ValueError("Input list must contain only strings or bytes")
        stripped = candidate.strip()
        if stripped:
            return stripped

    raise ValueError("Input must contain at least one non-empty string")


def _is_actisense(line: str) -> bool:
    return bool(_ACTISENSE_ASCII_RE.match(line) or _ACTISENSE_PACKET_RE.match(line))


def _is_basic_string(line: str) -> bool:
    return bool(_BASIC_STRING_RE.match(line))


def _is_yacht_devices(line: str) -> bool:
    return bool(_YACHT_DEVICES_RE.match(line) or _YACHT_DEVICES_PACKET_RE.match(line))


def _is_pcdin(line: str) -> bool:
    return _get_0183_sentence(line).startswith("$PCDIN,")


def _is_mxpgn(line: str) -> bool:
    return _get_0183_sentence(line).startswith("$MXPGN,")


def _is_pdgy(line: str) -> bool:
    return line.startswith("!PDGY,")


def _is_pdgy_debug(line: str) -> bool:
    return line.startswith("$PDGY,")


def _is_candump1(line: str) -> bool:
    return bool(_CANDUMP1_RE.match(line))


def _is_candump2(line: str) -> bool:
    return bool(_CANDUMP2_RE.match(line))


def _is_candump3(line: str) -> bool:
    return bool(_CANDUMP3_RE.match(line))


def _is_usb(packet: bytes) -> bool:
    return len(packet) == 20 and packet[:2] == b"\xaa\x55"


def _looks_like_usb(packet: bytes) -> bool:
    return packet.startswith(b"\xaa\x55") or (
        len(packet) >= 5 and packet[1:5] == b"\x55\x01\x02\x01"
    )


def _is_tcp(packet: bytes) -> bool:
    if _is_usb(packet) or len(packet) < 6:
        return False

    data_length = packet[0] & 0x0F
    if data_length <= 0 or data_length > 8:
        return False

    return len(packet) == 5 + data_length


def detect_format(data: N2KInput) -> N2KFormat:
    if isinstance(data, can.message.Message):
        return N2KFormat.PYTHON_CAN

    if isinstance(data, (str, list)):
        line = _first_text_line(data)
        if _is_actisense(line):
            return N2KFormat.ACTISENSE
        if _is_basic_string(line):
            return N2KFormat.BASIC_STRING
        if _is_yacht_devices(line):
            return N2KFormat.YACHT_DEVICES
        if _is_pcdin(line):
            return N2KFormat.PCDIN
        if _is_mxpgn(line):
            return N2KFormat.MXPGN
        if _is_pdgy(line):
            return N2KFormat.PDGY
        if _is_pdgy_debug(line):
            return N2KFormat.PDGY_DEBUG
        if _is_candump1(line):
            return N2KFormat.CANDUMP1
        if _is_candump2(line):
            return N2KFormat.CANDUMP2
        if _is_candump3(line):
            return N2KFormat.CANDUMP3
        raise ValueError(f"Parser not found for input: {line}")

    if isinstance(data, (bytes, bytearray, memoryview)):
        packet = bytes(data)
        if _looks_like_usb(packet):
            return N2KFormat.USB
        if _is_tcp(packet):
            return N2KFormat.TCP
        raise ValueError(f"Parser not found for binary input: {packet.hex()}")

    raise ValueError(
        "Input must be a string, list of strings or bytes, bytes-like object, or python-can Message"
    )


__all__ = ["N2KFormat", "N2KInput", "detect_format"]
