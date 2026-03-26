from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime, timedelta, timezone

import can.message

from .input_formats import N2KFormat, detect_format
from .message import NMEA2000Message
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)


class InvalidFrameError(Exception):
    """Raised when a USB frame has invalid structure."""


class DecoderDispatchMixin:
    """Public decoder dispatch API routed by detected `N2KFormat`."""

    @staticmethod
    def detect_format(
        input_data: str | list[str] | bytes | bytearray | memoryview | can.message.Message,
    ) -> N2KFormat:
        return detect_format(input_data)

    @staticmethod
    def _normalize_text_lines(input_data: str | list[str]) -> list[str]:
        if isinstance(input_data, str):
            return [input_data.strip()]
        if isinstance(input_data, list):
            if not all(isinstance(line, str) for line in input_data):
                raise ValueError("Input lists must contain only strings")
            return [line.strip() for line in input_data]
        raise ValueError("Input must be a string or a list of strings")

    def _text_decode_handlers(self):
        return {
            N2KFormat.YDRAW: self.decode_yacht_devices_string,
            N2KFormat.YDRAW_OUT: self._decode_ydraw_out,
            N2KFormat.PCDIN: self._decode_pcdin,
            N2KFormat.MXPGN: self._decode_mxpgn,
            N2KFormat.PDGY: self._decode_pdgy,
            N2KFormat.CANDUMP1: self._decode_candump1,
            N2KFormat.CANDUMP2: self._decode_candump2,
            N2KFormat.CANDUMP3: self._decode_candump3,
            N2KFormat.PDGY_DEBUG: self._decode_pdgy_debug,
            N2KFormat.ACTISENSE_N2K_ASCII: self.decode_actisense_string,
        }

    def _decode_text_line_by_format(
        self,
        input_format: N2KFormat,
        line: str,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        stripped = line.strip()
        if input_format == N2KFormat.BASIC_STRING:
            return self.decode_basic_string(stripped, single_line)

        handler = self._text_decode_handlers().get(input_format)
        if handler is None:
            raise ValueError(f"Unsupported input format: {input_format}")
        return handler(stripped)

    def decode(
        self,
        input_data: str | list[str] | bytes | bytearray | memoryview | can.message.Message,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        if isinstance(input_data, str) or isinstance(input_data, list):
            return self.decode_text(input_data, single_line)
        if isinstance(input_data, can.message.Message):
            return self.decode_python_can(input_data)
        if isinstance(input_data, (bytes, bytearray, memoryview)):
            packet = bytes(input_data)
            input_format = detect_format(packet)
            if input_format == N2KFormat.USB:
                return self.decode_usb(packet)
            if input_format == N2KFormat.EBYTE:
                return self.decode_tcp(packet)
            raise ValueError(f"Unsupported binary input format: {input_format}")
        raise ValueError(
            "Input must be a string, list of strings, bytes-like object, or python-can Message"
        )

    def decode_text(
        self,
        input_data: str | list[str],
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        input_lines = self._normalize_text_lines(input_data)
        input_format = detect_format(input_data)
        use_single_line = (
            single_line
            if input_format != N2KFormat.BASIC_STRING or not isinstance(input_data, list)
            else False
        )
        decoded_message = None
        for line in input_lines:
            result = self._decode_text_line_by_format(input_format, line, use_single_line)
            if result is not None:
                if decoded_message is not None:
                    raise ValueError("Input produced multiple decoded PGNs")
                decoded_message = result
        return decoded_message

    def decode_text_line(
        self,
        line: str,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        return self._decode_text_line_by_format(detect_format(line), line, single_line)


class DecoderCanFrameTextMixin:
    """Decode raw-CAN-frame text formats."""

    @staticmethod
    def _parse_hex_bytes(parts: list[str], expected_length: int | None = None) -> bytes:
        if expected_length is not None and len(parts) < expected_length:
            raise ValueError(
                f"Expected {expected_length} data bytes, got {len(parts)}"
            )
        selected_parts = parts if expected_length is None else parts[:expected_length]
        return bytes(int(part, 16) for part in selected_parts)

    @staticmethod
    def _utc_datetime_from_timestamp(timestamp: float) -> datetime:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)

    def _decode_raw_can_frame(
        self,
        can_id: int,
        payload: bytes,
        raw_input: str,
        timestamp: datetime | None = None,
    ) -> NMEA2000Message | None:
        pgn_id, source_id, dest, priority = type(self)._extract_header(can_id)
        return self._decode(
            pgn_id,
            priority,
            source_id,
            dest,
            timestamp or datetime.now(),
            payload[::-1],
            raw_input,
            False,
        )

    def _decode_ydraw_out(self, line: str) -> NMEA2000Message | None:
        parts = line.split()
        if len(parts) < 2:
            raise ValueError("Invalid YDRAW output string format")
        return self._decode_raw_can_frame(
            int(parts[0], 16),
            self._parse_hex_bytes(parts[1:]),
            line,
        )

    def _decode_candump1(self, line: str) -> NMEA2000Message | None:
        parts = line.split()
        if len(parts) < 3:
            raise ValueError("Invalid candump1 string format")
        can_id = int(parts[0][3:-1], 16)
        data_length = int(parts[1][1:-1])
        return self._decode_raw_can_frame(
            can_id,
            self._parse_hex_bytes(parts[2:], data_length),
            line,
        )

    def _decode_candump2(self, line: str) -> NMEA2000Message | None:
        parts = line.split()
        if len(parts) < 4:
            raise ValueError("Invalid candump2 string format")
        can_id = int(parts[1], 16)
        data_length = int(parts[2][1:-1])
        return self._decode_raw_can_frame(
            can_id,
            self._parse_hex_bytes(parts[3:], data_length),
            line,
        )

    def _decode_candump3(self, line: str) -> NMEA2000Message | None:
        timestamp_str, _, can_frame = line.split(maxsplit=2)
        can_id_str, data_hex = can_frame.split("#", 1)
        return self._decode_raw_can_frame(
            int(can_id_str, 16),
            bytes.fromhex(data_hex),
            line,
            self._utc_datetime_from_timestamp(float(timestamp_str[1:-1])),
        )


class DecoderSentenceTextMixin:
    """Decode sentence/coalesced text formats."""

    @staticmethod
    def _get_0183_sentence(line: str) -> str:
        if line.startswith("\\"):
            parts = line.split("\\")
            if len(parts) >= 3:
                return parts[2]
        return line

    @staticmethod
    def _strip_checksum(line: str) -> str:
        return line.split("*", 1)[0]

    def _decode_combined_payload(
        self,
        pgn_id: int,
        priority: int,
        source_id: int,
        dest: int,
        payload: bytes,
        raw_input: str,
        timestamp: datetime | None = None,
    ) -> NMEA2000Message | None:
        return self._decode(
            pgn_id,
            priority,
            source_id,
            dest,
            timestamp or datetime.now(),
            payload[::-1],
            raw_input,
            True,
        )

    def _decode_pcdin(self, line: str) -> NMEA2000Message | None:
        sentence = self._strip_checksum(self._get_0183_sentence(line))
        parts = sentence.split(",")
        if len(parts) != 5:
            raise ValueError("Invalid PCDIN string format")

        _, pgn_hex, time_hex, src_hex, data_hex = parts
        timer_seconds = (int(time_hex, 32) / 1024) + 1262304000
        return self._decode_combined_payload(
            int(pgn_hex, 16),
            0,
            int(src_hex, 16),
            255,
            bytes.fromhex(data_hex),
            line,
            DecoderCanFrameTextMixin._utc_datetime_from_timestamp(timer_seconds),
        )

    def _decode_mxpgn(self, line: str) -> NMEA2000Message | None:
        sentence = self._strip_checksum(self._get_0183_sentence(line))
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

        return self._decode_combined_payload(
            int(pgn_hex, 16),
            priority,
            source_id,
            dest,
            bytes.fromhex(data_hex)[::-1],
            line,
        )

    def _decode_pdgy(self, line: str) -> NMEA2000Message | None:
        parts = line.split(",")
        if len(parts) == 7:
            _, pgn_id, priority, source_id, dest, _, data = parts
            return self._decode_combined_payload(
                int(pgn_id),
                int(priority),
                int(source_id),
                int(dest),
                base64.b64decode(data, validate=True),
                line,
            )

        if len(parts) == 4:
            _, pgn_id, dest, data = parts
            return self._decode_combined_payload(
                int(pgn_id),
                0,
                0,
                int(dest),
                base64.b64decode(data, validate=True),
                line,
            )

        raise ValueError("Invalid PDGY string format")

    def _decode_pdgy_debug(self, _line: str) -> NMEA2000Message | None:
        raise ValueError("PDGY debug lines are not supported")


class DecoderNativeTextMixin:
    """Decode text formats with dedicated public methods."""

    def decode_actisense_string(self, actisense_string: str) -> NMEA2000Message | None:
        parts = actisense_string.split()
        if len(parts) < 3:
            raise ValueError("Invalid Actisense string format")
        if not parts[0].startswith("A"):
            raise ValueError("Invalid format: should start with 'A'")

        seconds, milliseconds = map(int, parts[0][1:].split("."))
        offset = timedelta(seconds=seconds, milliseconds=milliseconds)
        timestamp = datetime.now() + offset

        n = int(parts[1], 16)
        priority = n & 0xF
        dest = (n >> 4) & 0xFF
        src = (n >> 12) & 0xFF
        pgn = int(parts[2], 16)
        bytes_data = bytes.fromhex(parts[3])
        reversed_bytes = bytes_data[::-1]

        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            src,
            pgn,
            reversed_bytes,
        )

        return self._decode(pgn, priority, src, dest, timestamp, reversed_bytes, bytes_data, True)

    def decode_yacht_devices_string(self, yd_string: str) -> NMEA2000Message | None:
        parts = yd_string.split()
        if len(parts) < 4:
            raise ValueError("Invalid Yacht Devices string format")
        if parts[1] not in ["R", "T"]:
            raise ValueError("Invalid format: 2nd part should be 'R'")

        timestamp = datetime.strptime(parts[0], "%H:%M:%S.%f")
        msgid = int(parts[2], 16)
        pgn_id, source_id, dest, priority = type(self)._extract_header(msgid)
        can_data = parts[3:][::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]

        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            source_id,
            pgn_id,
            can_data_bytes,
        )

        return self._decode(pgn_id, priority, source_id, dest, timestamp, bytes(can_data_bytes), yd_string)

    def decode_basic_string(
        self,
        basic_string: str,
        already_combined: bool = False,
    ) -> NMEA2000Message | None:
        parts = basic_string.split(",")
        if len(parts) < 7:
            raise ValueError("Invalid string format")

        if parts[0].endswith("Z"):
            timestamp = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%S.%fZ")
        else:
            timestamp = datetime.strptime(parts[0], "%Y-%m-%d-%H:%M:%S.%f")
        priority = int(parts[1])
        pgn_id = int(parts[2])
        src = int(parts[3])
        dest = int(parts[4])
        length = int(parts[5])
        can_data = parts[6:6 + length][::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]

        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            src,
            pgn_id,
            can_data_bytes,
        )

        return self._decode(pgn_id, priority, src, dest, timestamp, bytes(can_data_bytes), basic_string, already_combined)


class DecoderBinaryMixin:
    """Decode binary/object transport formats."""

    def decode_tcp(self, packet: bytes) -> NMEA2000Message | None:
        type_byte = packet[0]
        data_length = type_byte & 0x0F
        frame_id = packet[1:5]
        frame_id_int = int.from_bytes(frame_id, byteorder="big")
        pgn_id, source_id, dest, priority = type(self)._extract_header(frame_id_int)
        can_data = packet[5:5 + data_length][::-1]

        logger.debug(
            "PGN ID: %s, Frame ID: %s, CAN Data: %s, Source ID: %s",
            pgn_id,
            binascii.hexlify(frame_id).decode("ascii"),
            can_data,
            source_id,
        )

        return self._decode(pgn_id, priority, source_id, dest, datetime.now(), bytes(can_data), packet)

    def decode_usb(self, packet: bytes) -> NMEA2000Message | None:
        if packet[0] != 0xAA or packet[1] != 0x55:
            raise InvalidFrameError("Packet does not have the right prefix and suffix")
        if len(packet) != 20:
            raise InvalidFrameError(f"Packet is not 20 bytes long: {packet.hex()}")

        frame_id = packet[5:9]
        frame_id_int = int.from_bytes(frame_id, byteorder="little")
        pgn_id, source_id, dest, priority = type(self)._extract_header(frame_id_int)

        checksum = calculate_canbus_checksum(packet)
        if checksum != packet[19]:
            raise InvalidFrameError(
                f"Invalid checksum: {checksum} (expected: {packet[19]}), "
                f"PGN ID: {pgn_id}, source: {source_id}, dest: {dest}, "
                f"priority: {priority}, packet: {packet.hex()}"
            )

        data_length = packet[9]
        can_data = packet[10:10 + data_length][::-1]

        logger.debug(
            "Got valid packet. PGN ID: %s, source: %s, dest: %s, priority: %s, CAN Data: %s",
            pgn_id,
            source_id,
            dest,
            priority,
            can_data.hex(),
        )

        return self._decode(pgn_id, priority, source_id, dest, datetime.now(), bytes(can_data), packet)

    def decode_python_can(self, msg: can.message.Message) -> NMEA2000Message | None:
        pgn_id, source_id, dest, priority = type(self)._extract_header(msg.arbitration_id)
        can_data = bytes(msg.data)[::-1]
        timestamp = datetime.fromtimestamp(msg.timestamp) if msg.timestamp else datetime.now()
        return self._decode(pgn_id, priority, source_id, dest, timestamp, can_data, msg.data)
