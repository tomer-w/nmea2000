from __future__ import annotations

import base64
import logging
from datetime import datetime

import can.message

from .encoder import EncoderBase, EncoderInterface, NMEA2000Encoder
from .input_formats import N2KFormat
from .message import NMEA2000Message
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)


def _bytes_to_hex_string(
    data: bytes,
    separator: str = " ",
    uppercase: bool = True,
) -> str:
    formatter = "{:02X}" if uppercase else "{:02x}"
    return separator.join(formatter.format(byte) for byte in data)


def _match_text_output(lines: list[str]) -> str | list[str]:
    return lines[0] if len(lines) == 1 else lines


def _compute_0183_checksum(sentence: str) -> str:
    payload = sentence[1:] if sentence and sentence[0] in "$!" else sentence
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    return f"*{checksum:02X}"


def _format_basic_timestamp(timestamp: datetime) -> str:
    return timestamp.isoformat(timespec="milliseconds") + "Z"


def _format_time_of_day(timestamp: datetime) -> str:
    return timestamp.strftime("%H:%M:%S.%f")[:-3]


def _format_candump3_timestamp(timestamp: datetime) -> str:
    return f"({timestamp.timestamp():.6f})"


def _encode_yacht_devices_packets(
    encoder: EncoderBase,
    nmea200_message: NMEA2000Message,
) -> list[bytes]:
    encoded_messages = encoder._encode(nmea200_message)
    # Construct the frame ID
    frame_id_int = type(encoder)._build_header(
        nmea200_message.PGN,
        nmea200_message.source,
        nmea200_message.destination,
        nmea200_message.priority,
    )
    frame_id_bytes = frame_id_int.to_bytes(4, byteorder="big")
    result = []
    for message in encoded_messages:
        # Construct and return the full packet
        text_msg = (
            frame_id_bytes.hex().upper()
            + " "
            + _bytes_to_hex_string(message)
            + "\r\n"
        )
        result.append(text_msg.encode())
    return result


def _encode_python_can_messages(
    encoder: EncoderBase,
    nmea200_message: NMEA2000Message,
) -> list[can.message.Message]:
    encoded_messages = encoder._encode(nmea200_message)
    arbitration_id = type(encoder)._build_header(
        nmea200_message.PGN,
        nmea200_message.source,
        nmea200_message.destination,
        nmea200_message.priority,
    )

    # python-can expects timestamp as a float (Unix epoch seconds)
    ts = nmea200_message.timestamp
    if hasattr(ts, "timestamp"):
        ts = ts.timestamp()
    result = []
    for message in encoded_messages:
        result.append(
            can.message.Message(
                timestamp=ts,
                arbitration_id=arbitration_id,
                is_extended_id=True,
                is_remote_frame=False,
                is_error_frame=False,
                is_rx=False,
                data=message,
            )
        )
    return result


class ActisenseEncoder(EncoderInterface, EncoderBase):
    """Encoder for Actisense packet strings."""

    def _encode_packet(self, nmea200_message: NMEA2000Message) -> str:
        # Extract necessary fields
        priority = nmea200_message.priority & 0xF
        dest = nmea200_message.destination & 0xFF
        src = nmea200_message.source & 0xFF
        pgn = nmea200_message.PGN & 0xFFFFFF

        # Construct the first part (priority, dest, src)
        n = (src << 12) | (dest << 4) | priority
        first_part = f"{n:05X}"

        # Convert PGN to hex
        pgn_part = f"{pgn:05X}"

        can_data_bytes = self._call_encode_function(nmea200_message)
        can_data_part = can_data_bytes.hex().upper()

        # Construct the final Actisense string
        actisense_string = f"{first_part} {pgn_part} {can_data_part}"
        logger.debug("Encoded Actisense string: %s", actisense_string)
        return actisense_string

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        return self._encode_packet(nmea200_message)


class ActisenseN2kAsciiEncoder(ActisenseEncoder):
    """Encoder for Actisense N2K ASCII output."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        return f"A000000.000 {self._encode_packet(nmea200_message)}"


class BasicStringEncoder(EncoderInterface, EncoderBase):
    """Encoder for the basic CSV string format."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)

        can_data_bytes = self._call_encode_function(nmea200_message)
        timestamp = _format_basic_timestamp(nmea200_message.timestamp)
        data_hex = [f"{byte:02x}" for byte in can_data_bytes]
        return ",".join(
            [
                timestamp,
                str(nmea200_message.priority),
                str(nmea200_message.PGN),
                str(nmea200_message.source),
                str(nmea200_message.destination),
                str(len(can_data_bytes)),
                *data_hex,
            ]
        )


class YachtDevicesEncoder(EncoderInterface, EncoderBase):
    """Encoder for Yacht Devices packet strings."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[bytes]:
        self._assert_output_format(output_format)
        return _encode_yacht_devices_packets(self, nmea200_message)


class YdrawOutEncoder(EncoderInterface, EncoderBase):
    """Encoder for YDRAW output text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        lines = [
            frame.decode("utf-8").rstrip("\r\n")
            for frame in _encode_yacht_devices_packets(self, nmea200_message)
        ]
        return _match_text_output(lines)


class YdrawEncoder(EncoderInterface, EncoderBase):
    """Encoder for timestamped Yacht Devices text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        time_token = _format_time_of_day(nmea200_message.timestamp)
        lines = [
            f"{time_token} R {frame.decode('utf-8').rstrip('\r\n')}"
            for frame in _encode_yacht_devices_packets(self, nmea200_message)
        ]
        return _match_text_output(lines)


class Candump1Encoder(EncoderInterface, EncoderBase):
    """Encoder for candump1 text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        lines = [
            f"<0x{frame.arbitration_id:08X}> [{len(frame.data)}] "
            f"{_bytes_to_hex_string(bytes(frame.data))}"
            for frame in _encode_python_can_messages(self, nmea200_message)
        ]
        return _match_text_output(lines)


class Candump2Encoder(EncoderInterface, EncoderBase):
    """Encoder for candump2 text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        lines = [
            f"can0  {frame.arbitration_id:08X}   [{len(frame.data)}]  "
            f"{_bytes_to_hex_string(bytes(frame.data))}"
            for frame in _encode_python_can_messages(self, nmea200_message)
        ]
        return _match_text_output(lines)


class Candump3Encoder(EncoderInterface, EncoderBase):
    """Encoder for candump3 text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        timestamp_token = _format_candump3_timestamp(nmea200_message.timestamp)
        lines = [
            f"{timestamp_token} slcan0 {frame.arbitration_id:08X}"
            f"#{bytes(frame.data).hex().upper()}"
            for frame in _encode_python_can_messages(self, nmea200_message)
        ]
        return _match_text_output(lines)


class PcdinEncoder(EncoderInterface, EncoderBase):
    """Encoder for PCDIN sentences."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        payload = self._call_encode_function(nmea200_message)
        sentence = (
            f"$PCDIN,{nmea200_message.PGN:06X},00000000,"
            f"{nmea200_message.source:02X},{payload.hex().upper()}"
        )
        return sentence + _compute_0183_checksum(sentence)


class MxpgnEncoder(EncoderInterface, EncoderBase):
    """Encoder for MXPGN sentences."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        send_bit = 0 if nmea200_message.destination == 255 else 1
        address = (
            nmea200_message.source if send_bit == 0 else nmea200_message.destination
        )
        payload = self._call_encode_function(nmea200_message)
        attr_word = (
            f"{((send_bit << 7) | ((nmea200_message.priority & 0x7) << 4) | (len(payload) & 0xF)):02X}"
            f"{address:02X}"
        )
        sentence = (
            f"$MXPGN,{nmea200_message.PGN:06X},{attr_word},"
            f"{payload[::-1].hex().upper()}"
        )
        return sentence + _compute_0183_checksum(sentence)


class PdgyEncoder(EncoderInterface, EncoderBase):
    """Encoder for PDGY sentences."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        payload = self._call_encode_function(nmea200_message)
        data = base64.b64encode(payload).decode("ascii")
        return ",".join(
            [
                "!PDGY",
                str(nmea200_message.PGN),
                str(nmea200_message.priority),
                str(nmea200_message.source),
                str(nmea200_message.destination),
                "0.000",
                data,
            ]
        )


class PdgyDebugEncoder(EncoderInterface, EncoderBase):
    """Encoder for explicitly unsupported PDGY debug output."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        del nmea200_message
        self._assert_output_format(output_format)
        raise ValueError("PDGY debug lines are not supported")


class TcpEncoder(EncoderInterface, EncoderBase):
    """Encoder for TCP / EByte packets."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[bytes]:
        self._assert_output_format(output_format)

        encoded_messages = self._encode(nmea200_message)
        # Construct the frame ID
        frame_id_int = type(self)._build_header(
            nmea200_message.PGN,
            nmea200_message.source,
            nmea200_message.destination,
            nmea200_message.priority,
        )
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder="big")
        result = []
        for message in encoded_messages:
            # Construct type byte: data length in bottom 4 bits
            type_byte = (len(message) & 0x0F) | (1 << 7)  # Set the FF bit
            # Construct the full packet
            result.append(bytes([type_byte]) + frame_id_bytes + message)
        return result


class UsbEncoder(EncoderInterface, EncoderBase):
    """Encoder for USB packets."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[bytes]:
        self._assert_output_format(output_format)

        encoded_messages = self._encode(nmea200_message)
        frame_id_int = type(self)._build_header(
            nmea200_message.PGN,
            nmea200_message.source,
            nmea200_message.destination,
            nmea200_message.priority,
        )
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder="little")
        result = []
        for message in encoded_messages:
            # https://www.waveshare.com/wiki/Secondary_Development_Serial_Conversion_Definition_of_CAN_Protocol
            frame_type_byte = 0x1  # 0x0 standard frame (frame ID 2 bytes), 0x1 - extended frame (frame ID 4 bytes)
            format_type_byte = 0x02  # 0x02-Setting (for sending and receiving data with a fixed 20-byte protocol); 0x12-Setting (for sending and receiving data with a variable protocol)
            framework_format_byte = 0x01  # No idea what is it
            # Construct and return the full packet
            msg_bytes = bytes([0xAA, 0x55, frame_type_byte, format_type_byte, framework_format_byte])
            msg_bytes += frame_id_bytes
            msg_bytes += bytes([len(message)])
            msg_bytes += message
            for _ in range(8 - len(message)):
                msg_bytes += bytes([0x00])
            msg_bytes += bytes([0x00])  # byte[18] reserved
            checksum = calculate_canbus_checksum(msg_bytes)
            msg_bytes += bytes([checksum])
            result.append(msg_bytes)
        return result


class PythonCanEncoder(EncoderInterface, EncoderBase):
    """Encoder for python-can Message objects."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[can.message.Message]:
        self._assert_output_format(output_format)
        return _encode_python_can_messages(self, nmea200_message)


NMEA2000Encoder.add_handler(N2KFormat.ACTISENSE, ActisenseEncoder)
NMEA2000Encoder.add_handler(N2KFormat.ACTISENSE_N2K_ASCII, ActisenseN2kAsciiEncoder)
NMEA2000Encoder.add_handler(N2KFormat.BASIC_STRING, BasicStringEncoder)
NMEA2000Encoder.add_handler(N2KFormat.YACHT_DEVICES, YachtDevicesEncoder)
NMEA2000Encoder.add_handler(N2KFormat.YDRAW, YdrawEncoder)
NMEA2000Encoder.add_handler(N2KFormat.YDRAW_OUT, YdrawOutEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PCDIN, PcdinEncoder)
NMEA2000Encoder.add_handler(N2KFormat.MXPGN, MxpgnEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PDGY, PdgyEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PDGY_DEBUG, PdgyDebugEncoder)
NMEA2000Encoder.add_handler(N2KFormat.CANDUMP1, Candump1Encoder)
NMEA2000Encoder.add_handler(N2KFormat.CANDUMP2, Candump2Encoder)
NMEA2000Encoder.add_handler(N2KFormat.CANDUMP3, Candump3Encoder)
NMEA2000Encoder.add_handler(N2KFormat.TCP, TcpEncoder)
NMEA2000Encoder.add_handler(N2KFormat.USB, UsbEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PYTHON_CAN, PythonCanEncoder)
