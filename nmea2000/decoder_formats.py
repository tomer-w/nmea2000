from __future__ import annotations

import binascii
import logging
from datetime import datetime, timedelta

import can.message

from .decoder import DecoderBase, DecoderInterface, InvalidFrameError, NMEA2000Decoder
from .input_formats import N2KFormat, N2KInput
from .message import NMEA2000Message
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)


def _as_text(data: N2KInput) -> str:
    if isinstance(data, str):
        return data.strip()
    raise ValueError("Input must be a string")


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


class ActisenseDecoder(DecoderBase, DecoderInterface):
    """Decoder for Actisense ASCII output format."""

    def decode(
        self,
        data: N2KInput,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        del single_line
        actisense_string = _as_text(data)
        parts = actisense_string.split()

        if len(parts) == 4 and parts[0].startswith("A"):
            seconds, milliseconds = map(int, parts[0][1:].split("."))
            offset = timedelta(seconds=seconds, milliseconds=milliseconds)
            timestamp = datetime.now() + offset
            n = int(parts[1], 16)
            pgn = int(parts[2], 16)
            bytes_data = bytes.fromhex(parts[3])
        elif len(parts) == 3:
            timestamp = datetime.now()
            n = int(parts[0], 16)
            pgn = int(parts[1], 16)
            bytes_data = bytes.fromhex(parts[2])
        else:
            raise ValueError("Invalid Actisense string format")

        priority = n & 0xF
        dest = (n >> 4) & 0xFF
        src = (n >> 12) & 0xFF
        reversed_bytes = bytes_data[::-1]

        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            src,
            pgn,
            reversed_bytes,
        )

        return self._decode(pgn, priority, src, dest, timestamp, bytes(reversed_bytes), bytes_data, True)


class BasicStringDecoder(DecoderBase, DecoderInterface):
    """Decoder for the basic CSV string format."""

    def decode(
        self,
        data: N2KInput,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        basic_string = _as_text(data)
        parts = basic_string.split(",")

        if len(parts) < 7:
            raise ValueError("Invalid string format")

        timestamp = _parse_basic_timestamp(parts[0])
        priority = int(parts[1])
        pgn_id = int(parts[2])
        src = int(parts[3])
        dest = int(parts[4])
        length = int(parts[5])
        can_data = parts[6 : 6 + length][::-1]
        can_data_bytes = [int(byte, 16) for byte in can_data]

        logger.debug(
            "Priority: %s, Destination: %s, Source: %s, PGN: %s, CAN Data: %s",
            priority,
            dest,
            src,
            pgn_id,
            can_data_bytes,
        )

        return self._decode(
            pgn_id,
            priority,
            src,
            dest,
            timestamp,
            bytes(can_data_bytes),
            basic_string,
            single_line,
        )


class YachtDevicesDecoder(DecoderBase, DecoderInterface):
    """Decoder for Yacht Devices text format."""

    def decode(
        self,
        data: N2KInput,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        del single_line
        yd_string = _as_text(data)
        parts = yd_string.split()

        if len(parts) >= 4 and parts[1] in ["R", "T"]:
            timestamp = datetime.strptime(parts[0], "%H:%M:%S.%f")
            msgid = int(parts[2], 16)
            can_data_parts = parts[3:]
        elif len(parts) >= 2:
            timestamp = datetime.now()
            msgid = int(parts[0], 16)
            can_data_parts = parts[1:]
        else:
            raise ValueError("Invalid Yacht Devices string format")

        pgn_id, source_id, dest, priority = type(self).extract_header(msgid)
        can_data = can_data_parts[::-1]
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


class TcpDecoder(DecoderBase, DecoderInterface):
    """Decoder for TCP / EByte packets."""

    def decode(
        self,
        data: N2KInput,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        del single_line
        packet = _as_bytes(data)
        if len(packet) < 6:
            raise ValueError("Packet is too short")

        type_byte = packet[0]
        data_length = type_byte & 0x0F
        if len(packet) != 5 + data_length:
            raise ValueError(f"Invalid TCP packet length: {packet.hex()}")

        frame_id = packet[1:5]
        frame_id_int = int.from_bytes(frame_id, byteorder="big")
        pgn_id, source_id, dest, priority = type(self).extract_header(frame_id_int)
        can_data = packet[5 : 5 + data_length][::-1]

        logger.debug(
            "PGN ID: %s, Frame ID: %s, CAN Data: %s, Source ID: %s",
            pgn_id,
            binascii.hexlify(frame_id).decode("ascii"),
            can_data,
            source_id,
        )

        return self._decode(pgn_id, priority, source_id, dest, datetime.now(), bytes(can_data), packet)


class UsbDecoder(DecoderBase, DecoderInterface):
    """Decoder for USB packets."""

    def decode(
        self,
        data: N2KInput,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        del single_line
        packet = _as_bytes(data)

        if packet[0] != 0xAA or packet[1] != 0x55:
            raise InvalidFrameError("Packet does not have the right prefix and suffix")
        if len(packet) != 20:
            raise InvalidFrameError(f"Packet is not 20 bytes long: {packet.hex()}")

        frame_id = packet[5:9]
        frame_id_int = int.from_bytes(frame_id, byteorder="little")
        pgn_id, source_id, dest, priority = type(self).extract_header(frame_id_int)

        checksum = calculate_canbus_checksum(packet)
        if checksum != packet[19]:
            raise InvalidFrameError(
                f"Invalid checksum: {checksum} (expected: {packet[19]}), "
                f"PGN ID: {pgn_id}, source: {source_id}, dest: {dest}, "
                f"priority: {priority}, packet: {packet.hex()}"
            )

        data_length = packet[9]
        can_data = packet[10 : 10 + data_length][::-1]

        logger.debug(
            "Got valid packet. PGN ID: %s, source: %s, dest: %s, priority: %s, CAN Data: %s",
            pgn_id,
            source_id,
            dest,
            priority,
            can_data.hex(),
        )

        return self._decode(pgn_id, priority, source_id, dest, datetime.now(), bytes(can_data), packet)


class PythonCanDecoder(DecoderBase, DecoderInterface):
    """Decoder for python-can Message objects."""

    def decode(
        self,
        data: N2KInput,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        del single_line
        if not isinstance(data, can.message.Message):
            raise ValueError("Input must be a python-can Message")

        pgn_id, source_id, dest, priority = type(self).extract_header(data.arbitration_id)
        can_data = bytes(data.data)[::-1]
        timestamp = datetime.fromtimestamp(data.timestamp) if data.timestamp else datetime.now()
        return self._decode(pgn_id, priority, source_id, dest, timestamp, can_data, data.data)


NMEA2000Decoder.add_handler(N2KFormat.ACTISENSE, ActisenseDecoder)
NMEA2000Decoder.add_handler(N2KFormat.BASIC_STRING, BasicStringDecoder)
NMEA2000Decoder.add_handler(N2KFormat.YACHT_DEVICES, YachtDevicesDecoder)
NMEA2000Decoder.add_handler(N2KFormat.TCP, TcpDecoder)
NMEA2000Decoder.add_handler(N2KFormat.USB, UsbDecoder)
NMEA2000Decoder.add_handler(N2KFormat.PYTHON_CAN, PythonCanDecoder)
