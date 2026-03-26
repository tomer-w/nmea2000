from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
import re

from .decoder import NMEA2000Decoder
from .message import NMEA2000Message


class N2KTextFormat(StrEnum):
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


def _strip_checksum(line: str) -> str:
    return line.split("*", 1)[0]


def _utc_datetime_from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)


def _parse_hex_bytes(parts: list[str], expected_length: int | None = None) -> bytes:
    if expected_length is not None and len(parts) < expected_length:
        raise ValueError(
            f"Expected {expected_length} data bytes, got {len(parts)}"
        )
    selected_parts = parts if expected_length is None else parts[:expected_length]
    return bytes(int(part, 16) for part in selected_parts)


def _decode_raw_can_frame(
    decoder: NMEA2000Decoder,
    can_id: int,
    payload: bytes,
    raw_input: str,
    timestamp: datetime | None = None,
) -> NMEA2000Message | None:
    pgn_id, source_id, dest, priority = NMEA2000Decoder._extract_header(can_id)
    return decoder._decode(
        pgn_id,
        priority,
        source_id,
        dest,
        timestamp or datetime.now(),
        payload[::-1],
        raw_input,
        False,
    )


def _decode_combined_payload(
    decoder: NMEA2000Decoder,
    pgn_id: int,
    priority: int,
    source_id: int,
    dest: int,
    payload: bytes,
    raw_input: str,
    timestamp: datetime | None = None,
) -> NMEA2000Message | None:
    return decoder._decode(
        pgn_id,
        priority,
        source_id,
        dest,
        timestamp or datetime.now(),
        payload[::-1],
        raw_input,
        True,
    )


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


_FORMAT_DETECTORS: list[tuple[N2KTextFormat, Callable[[str], bool]]] = [
    (N2KTextFormat.BASIC_STRING, _is_basic_string),
    (N2KTextFormat.YDRAW, _is_ydraw),
    (N2KTextFormat.YDRAW_OUT, _is_ydraw_out),
    (N2KTextFormat.PCDIN, _is_pcdin),
    (N2KTextFormat.MXPGN, _is_mxpgn),
    (N2KTextFormat.PDGY, _is_pdgy),
    (N2KTextFormat.CANDUMP1, _is_candump1),
    (N2KTextFormat.CANDUMP2, _is_candump2),
    (N2KTextFormat.CANDUMP3, _is_candump3),
    (N2KTextFormat.PDGY_DEBUG, _is_pdgy_debug),
    (N2KTextFormat.ACTISENSE_N2K_ASCII, _is_actisense_n2k_ascii),
]


def detect_n2k_text_format(line: str) -> N2KTextFormat:
    if not isinstance(line, str) or not line.strip():
        raise ValueError("Input not string or empty.")

    stripped = line.strip()
    for input_format, detector in _FORMAT_DETECTORS:
        if detector(stripped):
            return input_format

    raise ValueError(f"Parser not found for input. - {stripped}")


def _decode_ydraw_out(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    parts = line.split()
    if len(parts) < 2:
        raise ValueError("Invalid YDRAW output string format")
    return _decode_raw_can_frame(
        decoder,
        int(parts[0], 16),
        _parse_hex_bytes(parts[1:]),
        line,
    )


def _decode_candump1(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    parts = line.split()
    if len(parts) < 3:
        raise ValueError("Invalid candump1 string format")
    can_id = int(parts[0][3:-1], 16)
    data_length = int(parts[1][1:-1])
    return _decode_raw_can_frame(
        decoder,
        can_id,
        _parse_hex_bytes(parts[2:], data_length),
        line,
    )


def _decode_candump2(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    parts = line.split()
    if len(parts) < 4:
        raise ValueError("Invalid candump2 string format")
    can_id = int(parts[1], 16)
    data_length = int(parts[2][1:-1])
    return _decode_raw_can_frame(
        decoder,
        can_id,
        _parse_hex_bytes(parts[3:], data_length),
        line,
    )


def _decode_candump3(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    timestamp_str, _, can_frame = line.split(maxsplit=2)
    can_id_str, data_hex = can_frame.split("#", 1)
    return _decode_raw_can_frame(
        decoder,
        int(can_id_str, 16),
        bytes.fromhex(data_hex),
        line,
        _utc_datetime_from_timestamp(float(timestamp_str[1:-1])),
    )


def _decode_pcdin(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    sentence = _strip_checksum(_get_0183_sentence(line))
    parts = sentence.split(",")
    if len(parts) != 5:
        raise ValueError("Invalid PCDIN string format")

    _, pgn_hex, time_hex, src_hex, data_hex = parts
    timer_seconds = (int(time_hex, 32) / 1024) + 1262304000
    return _decode_combined_payload(
        decoder,
        int(pgn_hex, 16),
        0,
        int(src_hex, 16),
        255,
        bytes.fromhex(data_hex),
        line,
        _utc_datetime_from_timestamp(timer_seconds),
    )


def _decode_mxpgn(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    sentence = _strip_checksum(_get_0183_sentence(line))
    parts = sentence.split(",")
    if len(parts) != 4:
        raise ValueError("Invalid MXPGN string format")

    _, pgn_hex, attribute_word, data_hex = parts
    send_prio_len = bin(int(attribute_word[:2], 16))[2:].zfill(8)
    address = int(attribute_word[2:4], 16)
    send = int(send_prio_len[:1], 2)
    priority = int(send_prio_len[1:4], 2)
    source_id = 0 if send else address
    dest = address if send else 255

    return _decode_combined_payload(
        decoder,
        int(pgn_hex, 16),
        priority,
        source_id,
        dest,
        bytes.fromhex(data_hex)[::-1],
        line,
    )


def _decode_pdgy(decoder: NMEA2000Decoder, line: str) -> NMEA2000Message | None:
    parts = line.split(",")
    if len(parts) == 7:
        _, pgn_id, priority, source_id, dest, _, data = parts
        return _decode_combined_payload(
            decoder,
            int(pgn_id),
            int(priority),
            int(source_id),
            int(dest),
            base64.b64decode(data, validate=True),
            line,
        )

    if len(parts) == 4:
        _, pgn_id, dest, data = parts
        return _decode_combined_payload(
            decoder,
            int(pgn_id),
            0,
            0,
            int(dest),
            base64.b64decode(data, validate=True),
            line,
        )

    raise ValueError("Invalid PDGY string format")


def decode_n2k_text_line(
    decoder: NMEA2000Decoder,
    line: str,
    single_line: bool = False,
) -> NMEA2000Message | None:
    stripped = line.strip()
    input_format = detect_n2k_text_format(stripped)

    if input_format == N2KTextFormat.BASIC_STRING:
        return decoder.decode_basic_string(stripped, single_line)
    if input_format == N2KTextFormat.YDRAW:
        return decoder.decode_yacht_devices_string(stripped)
    if input_format == N2KTextFormat.YDRAW_OUT:
        return _decode_ydraw_out(decoder, stripped)
    if input_format == N2KTextFormat.PCDIN:
        return _decode_pcdin(decoder, stripped)
    if input_format == N2KTextFormat.MXPGN:
        return _decode_mxpgn(decoder, stripped)
    if input_format == N2KTextFormat.PDGY:
        return _decode_pdgy(decoder, stripped)
    if input_format == N2KTextFormat.CANDUMP1:
        return _decode_candump1(decoder, stripped)
    if input_format == N2KTextFormat.CANDUMP2:
        return _decode_candump2(decoder, stripped)
    if input_format == N2KTextFormat.CANDUMP3:
        return _decode_candump3(decoder, stripped)
    if input_format == N2KTextFormat.PDGY_DEBUG:
        raise ValueError("PDGY debug lines are not supported")
    if input_format == N2KTextFormat.ACTISENSE_N2K_ASCII:
        return decoder.decode_actisense_string(stripped)

    raise ValueError(f"Unsupported input format: {input_format}")


__all__ = [
    "N2KTextFormat",
    "detect_n2k_text_format",
    "decode_n2k_text_line",
]
