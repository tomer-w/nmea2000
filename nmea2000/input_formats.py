from __future__ import annotations

import re
from enum import StrEnum
from typing import TypeAlias

import can.message


class N2KFormat(StrEnum):
    """Supported NMEA 2000 wire formats.

    Naming convention
    -----------------
    Names describe *what the data looks like on the wire*, not which vendor
    originated the format.  The two main axes are:

    1. **CAN_FRAME vs N2K** — whether the format carries raw 8-byte CAN frames
       (requiring fast-packet reassembly by the receiver) or fully reassembled
       NMEA 2000 messages (no reassembly needed).
    2. **ASCII vs binary** — self-explanatory.

    The ``_RAW`` suffix means the format omits the timestamp / direction
    wrapper that the full variant includes.

    Formats named after an NMEA 0183 sentence identifier (``PCDIN``, ``MXPGN``,
    ``PDGY``) or a well-known tool (``CANDUMP*``) keep those established names,
    since they already refer to the wire format rather than to a single vendor.
    """

    # -- Reassembled N2K messages, ASCII ---------------------------------
    N2K_ASCII_RAW = "n2k_ascii_raw"    # ``09FF7 0FF00 3F9FDCFF…``
    N2K_ASCII = "n2k_ascii"            # ``A173321.107 23FF7 1F513 012F…``

    # -- CSV / basic string ----------------------------------------------
    BASIC_STRING = "basic_string"      # ``2016-04-09T16:41:09.078Z,3,127257,…``

    # -- Raw CAN frames, ASCII -------------------------------------------
    CAN_FRAME_ASCII = "can_frame_ascii"              # ``17:33:21.107 R 19F51323 01 2F…``
    CAN_FRAME_ASCII_RAW = "can_frame_ascii_raw"      # ``19F51323 01 2F 30 70…`` (no timestamp)
    CAN_FRAME_ASCII_RAW_OUT = "can_frame_ascii_raw_out"  # output-only variant

    # -- NMEA 0183 sentence formats --------------------------------------
    PCDIN = "pcdin"            # ``$PCDIN,…``  (SeaSmart)
    MXPGN = "mxpgn"            # ``$MXPGN,…``  (Shipmodul)
    PDGY = "pdgy"              # ``!PDGY,…``   (Digital Yacht)
    PDGY_DEBUG = "pdgy_debug"  # ``$PDGY,…``   (debug, decode-only)

    # -- Linux can-utils log formats -------------------------------------
    CANDUMP1 = "candump1"      # ``<0x18EEFF01> [8] 05 A0…``
    CANDUMP2 = "candump2"      # ``can0  18EEFF01   [8]  05 A0…``
    CANDUMP3 = "candump3"      # ``(1502979132.106111) slcan0 18EEFF01#05A0…``

    # -- Binary formats --------------------------------------------------
    BST_D0 = "bst_d0"          # Actisense BST D0 (reassembled N2K, binary, BDTP-framed)
    BST_95 = "bst_95"          # Actisense BST 95 (raw CAN frames, binary, BDTP-framed)
    EBYTE = "ebyte"            # https://www.cdebyte.com/products/ECAN-E01
    WAVESHARE = "waveshare"    # https://www.waveshare.com/wiki/USB-CAN-A

    # -- Library-level ---------------------------------------------------
    PYTHON_CAN = "python_can"  # python-can ``can.message.Message`` objects


TEXT_FORMATS: frozenset[N2KFormat] = frozenset({
    N2KFormat.N2K_ASCII_RAW,
    N2KFormat.N2K_ASCII,
    N2KFormat.BASIC_STRING,
    N2KFormat.CAN_FRAME_ASCII,
    N2KFormat.CAN_FRAME_ASCII_RAW,
    N2KFormat.PCDIN,
    N2KFormat.MXPGN,
    N2KFormat.PDGY,
    N2KFormat.PDGY_DEBUG,
    N2KFormat.CANDUMP1,
    N2KFormat.CANDUMP2,
    N2KFormat.CANDUMP3,
})

N2KInput: TypeAlias = (
    str
    | bytes
    | bytearray
    | memoryview
    | can.message.Message
)

_N2K_ASCII_RE = re.compile(
    r"^A\d+\.\d+\s+[0-9A-Fa-f]{5}\s+[0-9A-Fa-f]{5,6}\s+[0-9A-Fa-f]+$"
)
_N2K_ASCII_RAW_RE = re.compile(
    r"^[0-9A-Fa-f]{5}\s+[0-9A-Fa-f]{5,6}\s+[0-9A-Fa-f]+$"
)
_BASIC_STRING_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}\.\d+Z?|\-\d{2}:\d{2}:\d{2}\.\d+)"
    r"(?:,\d+){5}(?:,[0-9A-Fa-f]{2})+$"
)
_CAN_FRAME_ASCII_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}\.\d+\s+[RT]\s+[0-9A-Fa-f]{8}(?:\s+[0-9A-Fa-f]{2})+$"
)
_CAN_FRAME_ASCII_RAW_RE = re.compile(
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


def _is_n2k_ascii(line: str) -> bool:
    return bool(_N2K_ASCII_RE.match(line) or _N2K_ASCII_RAW_RE.match(line))


def _is_basic_string(line: str) -> bool:
    return bool(_BASIC_STRING_RE.match(line))


def _is_can_frame_ascii(line: str) -> bool:
    return bool(_CAN_FRAME_ASCII_RE.match(line) or _CAN_FRAME_ASCII_RAW_RE.match(line))


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


def _is_bst_d0(packet: bytes) -> bool:
    if len(packet) < 14 or packet[0] != 0xD0:
        return False
    length = int.from_bytes(packet[1:3], byteorder="little")
    # Length field = 13 + data_length; total with checksum = length + 1
    return length >= 13 and len(packet) == length + 1


def _is_bst_95(packet: bytes) -> bool:
    if len(packet) < 8 or packet[0] != 0x95:
        return False
    length = packet[1]
    # Total packet = 2 (header) + length + 1 (checksum)
    return length >= 6 and len(packet) == length + 3


def detect_format(data: N2KInput) -> N2KFormat:
    if isinstance(data, can.message.Message):
        return N2KFormat.PYTHON_CAN

    if isinstance(data, str):
        line = data.strip()
        if not line:
            raise ValueError("Input must contain a non-empty string")
        if _is_n2k_ascii(line):
            return N2KFormat.N2K_ASCII_RAW
        if _is_basic_string(line):
            return N2KFormat.BASIC_STRING
        if _is_can_frame_ascii(line):
            return N2KFormat.CAN_FRAME_ASCII
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
            return N2KFormat.WAVESHARE
        if _is_bst_d0(packet):
            return N2KFormat.BST_D0
        if _is_bst_95(packet):
            return N2KFormat.BST_95
        if _is_tcp(packet):
            return N2KFormat.EBYTE
        raise ValueError(f"Parser not found for binary input: {packet.hex()}")

    raise ValueError(
        "Input must be a string, list of strings or bytes, bytes-like object, or python-can Message"
    )


__all__ = ["N2KFormat", "N2KInput", "TEXT_FORMATS", "detect_format"]
