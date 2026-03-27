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


class EncoderTextSupportMixin:
    """Helpers shared by text encoders."""

    @staticmethod
    def _match_output_shape(encoded_lines: list[str]) -> str | list[str]:
        return encoded_lines[0] if len(encoded_lines) == 1 else encoded_lines

    @staticmethod
    def _compute_0183_checksum(sentence: str) -> str:
        payload = sentence[1:] if sentence and sentence[0] in "$!" else sentence
        checksum = 0
        for char in payload:
            checksum ^= ord(char)
        return f"*{checksum:02X}"

    @staticmethod
    def _default_basic_timestamp(timestamp: datetime) -> str:
        return timestamp.isoformat(timespec="milliseconds") + "Z"

    @staticmethod
    def _default_time_of_day(timestamp: datetime) -> str:
        return timestamp.strftime("%H:%M:%S.%f")[:-3]

    @staticmethod
    def _default_candump3_timestamp(timestamp: datetime) -> str:
        return f"({timestamp.timestamp():.6f})"

    @staticmethod
    def _hex_bytes(data: bytes, separator: str, uppercase: bool = True) -> str:
        formatter = "{:02X}" if uppercase else "{:02x}"
        return separator.join(formatter.format(byte) for byte in data)


class ActisenseEncoderSupportMixin:
    """Helpers shared by Actisense-style outputs."""

    def encode_actisense(self, nmea200_message: NMEA2000Message) -> str:
        priority = nmea200_message.priority & 0xF
        dest = nmea200_message.destination & 0xFF
        src = nmea200_message.source & 0xFF
        pgn = nmea200_message.PGN & 0xFFFFFF
        first_part = f"{((src << 12) | (dest << 4) | priority):05X}"
        pgn_part = f"{pgn:05X}"
        can_data_part = self._call_encode_function(nmea200_message).hex().upper()
        actisense_string = f"{first_part} {pgn_part} {can_data_part}"
        logger.debug("Encoded Actisense string: %s", actisense_string)
        return actisense_string


class YachtDevicesEncoderSupportMixin:
    """Helpers shared by Yacht Devices transport outputs."""

    def encode_yacht_devices(self, nmea200_message: NMEA2000Message) -> list[bytes]:
        encoded_messages = self._encode(nmea200_message)
        frame_id_int = type(self)._build_header(
            nmea200_message.PGN,
            nmea200_message.source,
            nmea200_message.destination,
            nmea200_message.priority,
        )
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder="big")
        result = []
        for message in encoded_messages:
            text_msg = frame_id_bytes.hex().upper() + " " + self._hex_bytes(message, " ") + "\r\n"
            result.append(text_msg.encode())
        return result


class PythonCanEncoderSupportMixin:
    """Helpers shared by python-can based outputs."""

    def encode_python_can(self, nmea200_message: NMEA2000Message) -> list[can.message.Message]:
        encoded_messages = self._encode(nmea200_message)
        arbitration_id = type(self)._build_header(
            nmea200_message.PGN,
            nmea200_message.source,
            nmea200_message.destination,
            nmea200_message.priority,
        )
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


class BasicStringEncoder(EncoderInterface, EncoderBase, EncoderTextSupportMixin):
    """Concrete encoder for the basic CSV string format."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        payload = self._call_encode_function(nmea200_message)
        return ",".join(
            [
                self._default_basic_timestamp(nmea200_message.timestamp),
                str(nmea200_message.priority),
                str(nmea200_message.PGN),
                str(nmea200_message.source),
                str(nmea200_message.destination),
                str(len(payload)),
                *[f"{byte:02x}" for byte in payload],
            ]
        )


class ActisenseEncoder(EncoderInterface, EncoderBase, ActisenseEncoderSupportMixin):
    """Concrete encoder for Actisense text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        return self.encode_actisense(nmea200_message)


class YdrawOutEncoder(
    EncoderInterface,
    EncoderBase,
    EncoderTextSupportMixin,
    YachtDevicesEncoderSupportMixin,
):
    """Concrete encoder for YDRAW output text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        lines = [
            frame.decode("utf-8").rstrip("\r\n")
            for frame in self.encode_yacht_devices(nmea200_message)
        ]
        return self._match_output_shape(lines)


class YdrawEncoder(
    EncoderInterface,
    EncoderBase,
    EncoderTextSupportMixin,
    YachtDevicesEncoderSupportMixin,
):
    """Concrete encoder for Yacht Devices text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        time_token = self._default_time_of_day(nmea200_message.timestamp)
        lines = []
        for frame in self.encode_yacht_devices(nmea200_message):
            payload = frame.decode("utf-8").rstrip("\r\n")
            lines.append(f"{time_token} R {payload}")
        return self._match_output_shape(lines)


class Candump1Encoder(
    EncoderInterface,
    EncoderBase,
    EncoderTextSupportMixin,
    PythonCanEncoderSupportMixin,
):
    """Concrete encoder for candump1 text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        lines = [
            f"<0x{frame.arbitration_id:08X}> [{len(frame.data)}] {self._hex_bytes(bytes(frame.data), ' ')}"
            for frame in self.encode_python_can(nmea200_message)
        ]
        return self._match_output_shape(lines)


class Candump2Encoder(
    EncoderInterface,
    EncoderBase,
    EncoderTextSupportMixin,
    PythonCanEncoderSupportMixin,
):
    """Concrete encoder for candump2 text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        lines = [
            f"can0  {frame.arbitration_id:08X}   [{len(frame.data)}]  {self._hex_bytes(bytes(frame.data), ' ')}"
            for frame in self.encode_python_can(nmea200_message)
        ]
        return self._match_output_shape(lines)


class Candump3Encoder(
    EncoderInterface,
    EncoderBase,
    EncoderTextSupportMixin,
    PythonCanEncoderSupportMixin,
):
    """Concrete encoder for candump3 text."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        self._assert_output_format(output_format)
        timestamp_token = self._default_candump3_timestamp(nmea200_message.timestamp)
        lines = [
            f"{timestamp_token} slcan0 {frame.arbitration_id:08X}#{bytes(frame.data).hex().upper()}"
            for frame in self.encode_python_can(nmea200_message)
        ]
        return self._match_output_shape(lines)


class PcdinEncoder(EncoderInterface, EncoderBase, EncoderTextSupportMixin):
    """Concrete encoder for PCDIN sentences."""

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
        return sentence + self._compute_0183_checksum(sentence)


class MxpgnEncoder(EncoderInterface, EncoderBase, EncoderTextSupportMixin):
    """Concrete encoder for MXPGN sentences."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        send_bit = 0 if nmea200_message.destination == 255 else 1
        address = nmea200_message.source if send_bit == 0 else nmea200_message.destination
        payload = self._call_encode_function(nmea200_message)
        attr_word = (
            f"{((send_bit << 7) | ((nmea200_message.priority & 0x7) << 4) | (len(payload) & 0xF)):02X}"
            f"{address:02X}"
        )
        sentence = f"$MXPGN,{nmea200_message.PGN:06X},{attr_word},{payload[::-1].hex().upper()}"
        return sentence + self._compute_0183_checksum(sentence)


class PdgyEncoder(EncoderInterface, EncoderBase):
    """Concrete encoder for PDGY sentences."""

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
    """Concrete encoder for rejected PDGY debug sentences."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        del nmea200_message
        self._assert_output_format(output_format)
        raise ValueError("PDGY debug lines are not supported")


class ActisenseN2kAsciiEncoder(
    EncoderInterface,
    EncoderBase,
    ActisenseEncoderSupportMixin,
):
    """Concrete encoder for Actisense N2K ASCII."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)
        return f"A000000.000 {self.encode_actisense(nmea200_message)}"


class EByteEncoder(EncoderInterface, EncoderBase):
    """Concrete encoder for EByte/TCP packets."""

    def encode_ebyte(self, nmea200_message: NMEA2000Message) -> list[bytes]:
        encoded_messages = self._encode(nmea200_message)
        frame_id_int = type(self)._build_header(
            nmea200_message.PGN,
            nmea200_message.source,
            nmea200_message.destination,
            nmea200_message.priority,
        )
        frame_id_bytes = frame_id_int.to_bytes(4, byteorder="big")
        result = []
        for message in encoded_messages:
            type_byte = (len(message) & 0x0F) | (1 << 7)
            result.append(bytes([type_byte]) + frame_id_bytes + message)
        return result

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[bytes]:
        self._assert_output_format(output_format)
        return self.encode_ebyte(nmea200_message)


class UsbEncoder(EncoderInterface, EncoderBase):
    """Concrete encoder for USB packets."""

    def encode_usb(self, nmea200_message: NMEA2000Message) -> list[bytes]:
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
            msg_bytes = bytes([0xAA, 0x55, 0x01, 0x02, 0x01])
            msg_bytes += frame_id_bytes
            msg_bytes += bytes([len(message)])
            msg_bytes += message
            for _ in range(8 - len(message)):
                msg_bytes += bytes([0x00])
            msg_bytes += bytes([0x00])
            checksum = calculate_canbus_checksum(msg_bytes)
            msg_bytes += bytes([checksum])
            result.append(msg_bytes)
        return result

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[bytes]:
        self._assert_output_format(output_format)
        return self.encode_usb(nmea200_message)


class PythonCanEncoder(
    EncoderInterface,
    EncoderBase,
    PythonCanEncoderSupportMixin,
):
    """Concrete encoder for python-can Message objects."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> list[can.message.Message]:
        self._assert_output_format(output_format)
        return self.encode_python_can(nmea200_message)


NMEA2000Encoder.add_handler(N2KFormat.BASIC_STRING, BasicStringEncoder)
NMEA2000Encoder.add_handler(N2KFormat.ACTISENSE, ActisenseEncoder)
NMEA2000Encoder.add_handler(N2KFormat.YDRAW_OUT, YdrawOutEncoder)
NMEA2000Encoder.add_handler(N2KFormat.YDRAW, YdrawEncoder)
NMEA2000Encoder.add_handler(N2KFormat.CANDUMP1, Candump1Encoder)
NMEA2000Encoder.add_handler(N2KFormat.CANDUMP2, Candump2Encoder)
NMEA2000Encoder.add_handler(N2KFormat.CANDUMP3, Candump3Encoder)
NMEA2000Encoder.add_handler(N2KFormat.PCDIN, PcdinEncoder)
NMEA2000Encoder.add_handler(N2KFormat.MXPGN, MxpgnEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PDGY, PdgyEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PDGY_DEBUG, PdgyDebugEncoder)
NMEA2000Encoder.add_handler(N2KFormat.ACTISENSE_N2K_ASCII, ActisenseN2kAsciiEncoder)
NMEA2000Encoder.add_handler(N2KFormat.EBYTE, EByteEncoder)
NMEA2000Encoder.add_handler(N2KFormat.USB, UsbEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PYTHON_CAN, PythonCanEncoder)
