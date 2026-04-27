from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import can.message

from .decoder import DecoderBase, DecoderInterface, InvalidFrameError, NMEA2000Decoder
from .input_formats import N2KFormat, N2KInput
from .message import NMEA2000Message
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)


def _decode_text_input(
    data: N2KInput,
    decode_line: Callable[[str], NMEA2000Message | None],
) -> NMEA2000Message | None:
    """Decode a single text line."""
    if not isinstance(data, str):
        raise ValueError(f"Unsupported input type: {type(data)}")
    return decode_line(data.strip())


def _as_bytes(data: N2KInput) -> bytes:
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise ValueError("Input must be bytes-like")


def _parse_basic_timestamp(timestamp: str) -> datetime:
    if timestamp.endswith("Z"):
        return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    if "T" in timestamp:
        return datetime.fromisoformat(timestamp)
    return datetime.strptime(timestamp, "%Y-%m-%d-%H:%M:%S.%f")


def _utc_datetime_from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)


def _get_0183_sentence(line: str) -> str:
    if line.startswith("\\"):
        parts = line.split("\\")
        if len(parts) >= 3:
            return parts[2]
    return line


def _strip_checksum(line: str) -> str:
    return line.split("*", 1)[0]


def _parse_hex_bytes(parts: list[str], expected_length: int | None = None) -> bytes:
    if expected_length is not None and len(parts) < expected_length:
        raise ValueError(f"Expected {expected_length} data bytes, got {len(parts)}")

    selected_parts = parts if expected_length is None else parts[:expected_length]
    return bytes(int(part, 16) for part in selected_parts)


def _decode_raw_can_frame(
    decoder: DecoderBase,
    can_id: int,
    payload: bytes,
    raw_input: str,
    timestamp: datetime | None = None,
) -> NMEA2000Message | None:
    pgn_id, source_id, dest, priority = type(decoder).extract_header(can_id)
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
    decoder: DecoderBase,
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


class N2kAsciiDecoder(DecoderBase, DecoderInterface):
    """Decoder for N2K ASCII output format.

    Examples:
        ``A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF``
        ``09FF7 0FF00 3F9FDCFFFFFFFFFF``
    """

    def _decode_text(self, n2k_ascii_string: str) -> NMEA2000Message | None:
        # Split the N2K ASCII string by spaces
        parts = n2k_ascii_string.split()

        if len(parts) == 4 and parts[0].startswith("A"):
            # Extract the timestamp from the first part
            seconds, milliseconds = map(int, parts[0][1:].split("."))
            offset = timedelta(seconds=seconds, milliseconds=milliseconds)
            timestamp = datetime.now() + offset
            # Extract the priority, destination, and source from the second part
            n = int(parts[1], 16)
            # Extract the PGN from the third part
            pgn = int(parts[2], 16)
            # Extract the CAN data from the remaining parts
            bytes_data = bytes.fromhex(parts[3])
        elif len(parts) == 3:
            timestamp = datetime.now()
            n = int(parts[0], 16)
            pgn = int(parts[1], 16)
            bytes_data = bytes.fromhex(parts[2])
        else:
            raise ValueError("Invalid N2K ASCII string format")

        priority = n & 0xF
        dest = (n >> 4) & 0xFF
        src = (n >> 12) & 0xFF
        # Convert to bytes
        # Reverse the byte order
        reversed_bytes = bytes_data[::-1]

        # Log the extracted information
        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            src,
            pgn,
            reversed_bytes,
        )

        return self._decode(
            pgn,
            priority,
            src,
            dest,
            timestamp,
            bytes(reversed_bytes),
            bytes_data,
            True,
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class BasicStringDecoder(DecoderBase, DecoderInterface):
    """Decoder for the basic CSV string format.

    Example:
        ``2016-04-09T16:41:09.078Z,3,127257,17,255,8,00,ff,7f,52,00,21,fe,ff``
    """

    def _decode_text(
        self,
        basic_string: str,
        already_combined: bool = False,
    ) -> NMEA2000Message | None:
        # Split the basic string by commas
        parts = basic_string.split(",")

        if len(parts) < 7:  # should have at least one data bytes probably
            raise ValueError("Invalid string format")

        # Extract the fields
        timestamp = _parse_basic_timestamp(parts[0])
        priority = int(parts[1])
        pgn_id = int(parts[2])
        src = int(parts[3])
        dest = int(parts[4])
        length = int(parts[5])
        # Extract the CAN data from the remaining parts
        can_data = parts[6 : 6 + length][::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]

        # Log the extracted information
        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            src,
            pgn_id,
            can_data_bytes,
        )

        # not calling _decode as in this format the fast frames are already combined
        return self._decode(
            pgn_id,
            priority,
            src,
            dest,
            timestamp,
            bytes(can_data_bytes),
            basic_string,
            already_combined,
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        if self.already_combined and isinstance(data, str):
            return self._decode_text(data.strip(), True)
        return _decode_text_input(data, self._decode_text)


class CanFrameAsciiDecoder(DecoderBase, DecoderInterface):
    """Decoder for CAN Frame ASCII text format.

    Examples:
        ``00:01:54.330 R 15FD0A10 00 00 00 68 65 0F 00 FF``
        ``01F010B3 FF FF 0C 4F 70 BE 3E 33``
    """

    def _decode_text(self, can_frame_line: str) -> NMEA2000Message | None:
        # Split the CAN Frame ASCII string by spaces
        parts = can_frame_line.split()

        if len(parts) >= 4 and parts[1] in ["R", "T"]:
            # Extract the timestamp from the first part
            parsed_time = datetime.strptime(parts[0], "%H:%M:%S.%f").time()
            timestamp = datetime.combine(datetime.now().date(), parsed_time)
            # Extract the PGN, priority, destination, and source from the second part
            msgid = int(parts[2], 16)
            can_data_parts = parts[3:]
        elif len(parts) >= 2:
            timestamp = datetime.now()
            msgid = int(parts[0], 16)
            can_data_parts = parts[1:]
        else:
            raise ValueError("Invalid CAN Frame ASCII string format")

        pgn_id, source_id, dest, priority = type(self).extract_header(msgid)
        # Extract the CAN data from the remaining parts
        can_data = can_data_parts[::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]

        # Log the extracted information
        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            source_id,
            pgn_id,
            can_data_bytes,
        )

        return self._decode(
            pgn_id,
            priority,
            source_id,
            dest,
            timestamp,
            bytes(can_data_bytes),
            can_frame_line,
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class Candump1Decoder(DecoderBase, DecoderInterface):
    """Decoder for candump1 text.

    Example:
        ``<0x18EEFF01> [8] 05 A0 BE 1C 00 A0 A0 C0``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
        parts = line.split()
        if len(parts) < 3:
            raise ValueError("Invalid candump1 string format")

        can_id = int(parts[0][3:-1], 16)
        data_length = int(parts[1][1:-1])
        return _decode_raw_can_frame(
            self,
            can_id,
            _parse_hex_bytes(parts[2:], data_length),
            line,
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class Candump2Decoder(DecoderBase, DecoderInterface):
    """Decoder for candump2 text.

    Example:
        ``can0  18EEFF01   [8]  05 A0 BE 1C 00 A0 A0 C0``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
        parts = line.split()
        if len(parts) < 4:
            raise ValueError("Invalid candump2 string format")

        can_id = int(parts[1], 16)
        data_length = int(parts[2][1:-1])
        return _decode_raw_can_frame(
            self,
            can_id,
            _parse_hex_bytes(parts[3:], data_length),
            line,
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class Candump3Decoder(DecoderBase, DecoderInterface):
    """Decoder for candump3 text.

    Example:
        ``(1502979132.106111) slcan0 18EEFF01#05A0BE1C00A0A0C0``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
        timestamp_str, _, can_frame = line.split(maxsplit=2)
        can_id_str, data_hex = can_frame.split("#", 1)
        return _decode_raw_can_frame(
            self,
            int(can_id_str, 16),
            bytes.fromhex(data_hex),
            line,
            _utc_datetime_from_timestamp(float(timestamp_str[1:-1])),
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class PcdinDecoder(DecoderBase, DecoderInterface):
    """Decoder for PCDIN sentences.

    Example:
        ``$PCDIN,01F119,00000000,0F,2AAF00D1067414FF*59``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
        sentence = _strip_checksum(_get_0183_sentence(line))
        parts = sentence.split(",")
        if len(parts) != 5:
            raise ValueError("Invalid PCDIN string format")

        _, pgn_hex, time_hex, src_hex, data_hex = parts
        timer_seconds = (int(time_hex, 32) / 1024) + 1262304000
        return _decode_combined_payload(
            self,
            int(pgn_hex, 16),
            0,
            int(src_hex, 16),
            255,
            bytes.fromhex(data_hex),
            line,
            _utc_datetime_from_timestamp(timer_seconds),
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class MxpgnDecoder(DecoderBase, DecoderInterface):
    """Decoder for MXPGN sentences.

    Example:
        ``$MXPGN,01F801,2801,C1308AC40C5DE343*19``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
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
            self,
            int(pgn_hex, 16),
            priority,
            source_id,
            dest,
            bytes.fromhex(data_hex)[::-1],
            line,
        )

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class PdgyDecoder(DecoderBase, DecoderInterface):
    """Decoder for PDGY sentences.

    Example:
        ``!PDGY,127257,3,17,255,0.563,AP9/UgAh/v8=``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
        parts = line.split(",")
        if len(parts) == 7:
            _, pgn_id, priority, source_id, dest, _, encoded = parts
            return _decode_combined_payload(
                self,
                int(pgn_id),
                int(priority),
                int(source_id),
                int(dest),
                base64.b64decode(encoded, validate=True),
                line,
            )

        if len(parts) == 4:
            _, pgn_id, dest, encoded = parts
            return _decode_combined_payload(
                self,
                int(pgn_id),
                0,
                0,
                int(dest),
                base64.b64decode(encoded, validate=True),
                line,
            )

        raise ValueError("Invalid PDGY string format")

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class PdgyDebugDecoder(DecoderBase, DecoderInterface):
    """Decoder for explicitly unsupported PDGY debug lines.

    Example:
        ``$PDGY,000000,4,,5,482,1,0``
    """

    def _decode_text(self, line: str) -> NMEA2000Message | None:
        del line
        raise ValueError("PDGY debug lines are not supported")

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        return _decode_text_input(data, self._decode_text)


class TcpDecoder(DecoderBase, DecoderInterface):
    """Decoder for TCP / EByte packets."""

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        packet = _as_bytes(data)
        if len(packet) < 6:
            raise ValueError("Packet is too short")

        # First byte has the data length in the lowest 4 bits
        type_byte = packet[0]
        data_length = type_byte & 0x0F  # last 4 bits represent the data length
        if len(packet) != 5 + data_length:
            raise ValueError(f"Invalid TCP packet length: {packet.hex()}")

        # Extract the frame ID
        frame_id = packet[1:5]
        # Convert frame_id bytes to an integer
        frame_id_int = int.from_bytes(frame_id, byteorder="big")
        # Parse it
        pgn_id, source_id, dest, priority = type(self).extract_header(frame_id_int)
        # Extract and reverse the CAN data
        can_data = packet[5 : 5 + data_length][::-1]

        # Log the extracted information including the combined string
        logger.debug(
            "PGN ID: %s, Frame ID: %s, CAN Data: %s, Source ID: %s",
            pgn_id,
            binascii.hexlify(frame_id).decode("ascii"),
            can_data,
            source_id,
        )

        return self._decode(
            pgn_id,
            priority,
            source_id,
            dest,
            datetime.now(),
            bytes(can_data),
            packet,
        )


class UsbDecoder(DecoderBase, DecoderInterface):
    """Decoder for USB packets."""

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        packet = _as_bytes(data)

        if packet[0] != 0xAA or packet[1] != 0x55:
            raise InvalidFrameError("Packet does not have the right prefix and suffix")
        if len(packet) != 20:
            raise InvalidFrameError(f"Packet is not 20 bytes long: {packet.hex()}")

        # Extract the frame ID
        frame_id = packet[5:9]
        # Convert frame_id bytes to an integer
        frame_id_int = int.from_bytes(frame_id, byteorder="little")
        # Parse it
        pgn_id, source_id, dest, priority = type(self).extract_header(frame_id_int)

        checksum = calculate_canbus_checksum(packet)
        if checksum != packet[19]:
            raise InvalidFrameError(
                f"Invalid checksum: {checksum} (expected: {packet[19]}), "
                f"PGN ID: {pgn_id}, source: {source_id}, dest: {dest}, "
                f"priority: {priority}, packet: {packet.hex()}"
            )

        data_length = packet[9]
        # Extract and reverse the CAN data
        can_data = packet[10 : 10 + data_length][::-1]

        # Log the extracted information including the combined string
        logger.debug(
            "Got valid packet. PGN ID: %s, source: %s, dest: %s, priority: %s, "
            "CAN Data: %s",
            pgn_id,
            source_id,
            dest,
            priority,
            can_data.hex(),
        )

        return self._decode(
            pgn_id,
            priority,
            source_id,
            dest,
            datetime.now(),
            bytes(can_data),
            packet,
        )


class PythonCanDecoder(DecoderBase, DecoderInterface):
    """Decoder for python-can Message objects."""

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        if not isinstance(data, can.message.Message):
            raise ValueError("Input must be a python-can Message")

        pgn_id, source_id, dest, priority = type(self).extract_header(
            data.arbitration_id
        )
        # python-can data is already in network byte order; reverse to match internal convention
        can_data = bytes(data.data)[::-1]
        timestamp = (
            datetime.fromtimestamp(data.timestamp) if data.timestamp else datetime.now()
        )
        return self._decode(
            pgn_id,
            priority,
            source_id,
            dest,
            timestamp,
            can_data,
            data.data,
        )


class BstD0Decoder(DecoderBase, DecoderInterface):
    """Decoder for Actisense BST D0 binary format.

    This is the newer binary format used in devices like the PRO-NDC-1E2K.
    Messages are pre-assembled (fast packets and transport protocol messages
    are already decoded by the device).

    See https://github.com/Actisense/SDK/blob/main/docs/DataFormats/Binary/bst-detail/BST-D0.md
    """

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        packet = _as_bytes(data)
        if len(packet) < 14:
            raise ValueError("BST D0 packet too short")
        if packet[0] != 0xD0:
            raise ValueError(f"Not a BST D0 message: ID byte 0x{packet[0]:02X}")

        length = int.from_bytes(packet[1:3], byteorder="little")
        if len(packet) != length + 1:
            raise ValueError(
                f"BST D0 length mismatch: header says {length}, "
                f"packet is {len(packet)} bytes (expected {length + 1})"
            )

        if sum(packet) & 0xFF != 0:
            raise ValueError("BST D0 checksum failed")

        dest = packet[3]
        source = packet[4]
        pdus = packet[5]
        pduf = packet[6]
        dpp = packet[7]

        data_page = dpp & 0x03
        priority = (dpp >> 2) & 0x07

        if pduf >= 240:
            pgn = (data_page << 16) | (pduf << 8) | pdus
        else:
            pgn = (data_page << 16) | (pduf << 8)

        timestamp = datetime.now()  # BST D0 timestamp is relative; use wall clock
        payload = packet[13:-1]  # exclude checksum

        logger.debug(
            "BST D0: PGN=%d, src=%d, dst=%d, pri=%d, payload=%s",
            pgn, source, dest, priority, payload.hex(),
        )

        return _decode_combined_payload(
            self,
            pgn,
            priority,
            source,
            dest,
            payload,
            packet,
            timestamp,
        )


class Bst95Decoder(DecoderBase, DecoderInterface):
    """Decoder for Actisense BST 95 binary CAN frame format.

    BST 95 carries raw CAN frames (up to 8 data bytes) wrapped in BDTP
    framing.  Fast-packet and transport-protocol PGNs require reassembly,
    which is handled by the inherited :class:`DecoderBase` logic.

    See https://github.com/Actisense/SDK/blob/main/docs/DataFormats/Binary/bst-detail/BST-95-can-frame.md
    """

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        packet = _as_bytes(data)
        if len(packet) < 8:
            raise ValueError("BST 95 packet too short")
        if packet[0] != 0x95:
            raise ValueError(f"Not a BST 95 message: ID byte 0x{packet[0]:02X}")

        length = packet[1]
        expected_len = length + 3  # BSTID(1) + L(1) + payload(L) + checksum(1)
        if len(packet) != expected_len:
            raise ValueError(
                f"BST 95 length mismatch: header says {length}, "
                f"packet is {len(packet)} bytes (expected {expected_len})"
            )

        if sum(packet) & 0xFF != 0:
            raise ValueError("BST 95 checksum failed")

        source = packet[4]
        pdus = packet[5]
        pduf = packet[6]
        dppc = packet[7]

        data_page = dppc & 0x03
        priority = (dppc >> 2) & 0x07

        if pduf >= 240:
            pgn = (data_page << 16) | (pduf << 8) | pdus
        else:
            pgn = (data_page << 16) | (pduf << 8)

        if pduf < 240:
            dest = pdus
        else:
            dest = 255

        can_data = packet[8:-1]  # between DPPC and checksum

        logger.debug(
            "BST 95: PGN=%d, src=%d, dst=%d, pri=%d, payload=%s",
            pgn, source, dest, priority, can_data.hex(),
        )

        return self._decode(
            pgn,
            priority,
            source,
            dest,
            datetime.now(),
            can_data[::-1],
            packet,
        )


NMEA2000Decoder.add_handler(N2KFormat.N2K_ASCII_RAW, N2kAsciiDecoder)
NMEA2000Decoder.add_handler(N2KFormat.N2K_ASCII, N2kAsciiDecoder)
NMEA2000Decoder.add_handler(N2KFormat.BASIC_STRING, BasicStringDecoder)
NMEA2000Decoder.add_handler(N2KFormat.CAN_FRAME_ASCII, CanFrameAsciiDecoder)
NMEA2000Decoder.add_handler(N2KFormat.CAN_FRAME_ASCII_RAW, CanFrameAsciiDecoder)
NMEA2000Decoder.add_handler(N2KFormat.CAN_FRAME_ASCII_RAW_OUT, CanFrameAsciiDecoder)
NMEA2000Decoder.add_handler(N2KFormat.PCDIN, PcdinDecoder)
NMEA2000Decoder.add_handler(N2KFormat.MXPGN, MxpgnDecoder)
NMEA2000Decoder.add_handler(N2KFormat.PDGY, PdgyDecoder)
NMEA2000Decoder.add_handler(N2KFormat.PDGY_DEBUG, PdgyDebugDecoder)
NMEA2000Decoder.add_handler(N2KFormat.CANDUMP1, Candump1Decoder)
NMEA2000Decoder.add_handler(N2KFormat.CANDUMP2, Candump2Decoder)
NMEA2000Decoder.add_handler(N2KFormat.CANDUMP3, Candump3Decoder)
NMEA2000Decoder.add_handler(N2KFormat.EBYTE, TcpDecoder)
NMEA2000Decoder.add_handler(N2KFormat.WAVESHARE, UsbDecoder)
NMEA2000Decoder.add_handler(N2KFormat.PYTHON_CAN, PythonCanDecoder)
NMEA2000Decoder.add_handler(N2KFormat.BST_D0, BstD0Decoder)
NMEA2000Decoder.add_handler(N2KFormat.BST_95, Bst95Decoder)
