from __future__ import annotations

import re
from enum import StrEnum
from typing import TypeAlias

import can.message


class N2KFormat(StrEnum):
    ACTISENSE = "actisense"
    BASIC_STRING = "basic_string"
    YACHT_DEVICES = "yacht_devices"
    TCP = "tcp"
    USB = "usb"
    PYTHON_CAN = "python_can"


N2KInput: TypeAlias = str | bytes | bytearray | memoryview | can.message.Message

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


def _is_actisense(line: str) -> bool:
    return bool(_ACTISENSE_ASCII_RE.match(line) or _ACTISENSE_PACKET_RE.match(line))


def _is_basic_string(line: str) -> bool:
    return bool(_BASIC_STRING_RE.match(line))


def _is_yacht_devices(line: str) -> bool:
    return bool(_YACHT_DEVICES_RE.match(line) or _YACHT_DEVICES_PACKET_RE.match(line))


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

    if isinstance(data, str):
        line = data.strip()
        if _is_actisense(line):
            return N2KFormat.ACTISENSE
        if _is_basic_string(line):
            return N2KFormat.BASIC_STRING
        if _is_yacht_devices(line):
            return N2KFormat.YACHT_DEVICES
        raise ValueError(f"Parser not found for input: {line}")

    if isinstance(data, (bytes, bytearray, memoryview)):
        packet = bytes(data)
        if _looks_like_usb(packet):
            return N2KFormat.USB
        if _is_tcp(packet):
            return N2KFormat.TCP
        raise ValueError(f"Parser not found for binary input: {packet.hex()}")

    raise ValueError(
        "Input must be a string, bytes-like object, or python-can Message"
    )


__all__ = ["N2KFormat", "N2KInput", "detect_format"]
