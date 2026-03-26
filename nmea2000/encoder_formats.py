from __future__ import annotations

import base64
import logging
from datetime import datetime

import can.message

from .input_formats import N2KFormat
from .message import NMEA2000Message
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)

_TEXT_OUTPUT_FORMATS = frozenset(
    {
        N2KFormat.BASIC_STRING,
        N2KFormat.YDRAW,
        N2KFormat.YDRAW_OUT,
        N2KFormat.PCDIN,
        N2KFormat.MXPGN,
        N2KFormat.PDGY,
        N2KFormat.CANDUMP1,
        N2KFormat.CANDUMP2,
        N2KFormat.CANDUMP3,
        N2KFormat.PDGY_DEBUG,
        N2KFormat.ACTISENSE_N2K_ASCII,
    }
)


class EncoderDispatchMixin:
    """Public encoder dispatch API routed by `N2KFormat`."""

    _FORMAT_ALIASES = {
        "tcp": N2KFormat.EBYTE,
        "python-can": N2KFormat.PYTHON_CAN,
        "yacht_devices": N2KFormat.YDRAW_OUT,
    }

    def _normalize_output_format(self, output_format: N2KFormat | str) -> N2KFormat:
        if isinstance(output_format, N2KFormat):
            return output_format
        if isinstance(output_format, str):
            normalized = output_format.strip().lower()
            alias = self._FORMAT_ALIASES.get(normalized)
            if alias is not None:
                return alias
            try:
                return N2KFormat(normalized)
            except ValueError as exc:
                raise ValueError(f"Unsupported format: {output_format}") from exc
        raise ValueError(f"Unsupported format type: {type(output_format)!r}")

    def _resolve_output_format(self, output_format: N2KFormat | str | None) -> N2KFormat:
        if output_format is None:
            return self.output_format
        return self._normalize_output_format(output_format)

    def _encode_dispatch_table(self):
        return {
            N2KFormat.BASIC_STRING: self._encode_basic_string,
            N2KFormat.YDRAW: self._encode_ydraw,
            N2KFormat.YDRAW_OUT: self._encode_ydraw_out,
            N2KFormat.PCDIN: self._encode_pcdin,
            N2KFormat.MXPGN: self._encode_mxpgn,
            N2KFormat.PDGY: self._encode_pdgy,
            N2KFormat.CANDUMP1: self._encode_candump1,
            N2KFormat.CANDUMP2: self._encode_candump2,
            N2KFormat.CANDUMP3: self._encode_candump3,
            N2KFormat.PDGY_DEBUG: self._encode_pdgy_debug,
            N2KFormat.ACTISENSE_N2K_ASCII: self._encode_actisense_n2k_ascii,
            N2KFormat.ACTISENSE: self.encode_actisense,
            N2KFormat.EBYTE: self.encode_ebyte,
            N2KFormat.USB: self.encode_usb,
            N2KFormat.PYTHON_CAN: self.encode_python_can,
        }

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str] | list[bytes] | list[can.message.Message]:
        normalized_format = self._resolve_output_format(output_format)
        handler = self._encode_dispatch_table().get(normalized_format)
        if handler is None:
            raise ValueError(f"Unsupported output format: {normalized_format}")
        return handler(nmea200_message)

    def encode_text(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str | list[str]:
        normalized_format = self._resolve_output_format(output_format)
        if normalized_format not in _TEXT_OUTPUT_FORMATS:
            raise ValueError(f"Unsupported text output format: {normalized_format}")
        return self._encode_dispatch_table()[normalized_format](nmea200_message)


class EncoderTextSupportMixin:
    """Small helpers for canonical text generation."""

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


class EncoderDirectTextMixin:
    """Direct text encoders close to transport output."""

    def _encode_basic_string(self, message: NMEA2000Message) -> str:
        payload = self._call_encode_function(message)
        return ",".join(
            [
                self._default_basic_timestamp(message.timestamp),
                str(message.priority),
                str(message.PGN),
                str(message.source),
                str(message.destination),
                str(len(payload)),
                *[f"{byte:02x}" for byte in payload],
            ]
        )

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


class EncoderCanFrameTextMixin:
    """Text encoders that present CAN frames in textual wrappers."""

    def _encode_ydraw_out(self, message: NMEA2000Message) -> str | list[str]:
        lines = [frame.decode("utf-8").rstrip("\r\n") for frame in self.encode_yacht_devices(message)]
        return self._match_output_shape(lines)

    def _encode_ydraw(self, message: NMEA2000Message) -> str | list[str]:
        time_token = self._default_time_of_day(message.timestamp)
        lines = []
        for frame in self.encode_yacht_devices(message):
            payload = frame.decode("utf-8").rstrip("\r\n")
            lines.append(f"{time_token} R {payload}")
        return self._match_output_shape(lines)

    def _encode_candump1(self, message: NMEA2000Message) -> str | list[str]:
        lines = [
            f"<0x{frame.arbitration_id:08X}> [{len(frame.data)}] {self._hex_bytes(bytes(frame.data), ' ')}"
            for frame in self.encode_python_can(message)
        ]
        return self._match_output_shape(lines)

    def _encode_candump2(self, message: NMEA2000Message) -> str | list[str]:
        lines = [
            f"can0  {frame.arbitration_id:08X}   [{len(frame.data)}]  {self._hex_bytes(bytes(frame.data), ' ')}"
            for frame in self.encode_python_can(message)
        ]
        return self._match_output_shape(lines)

    def _encode_candump3(self, message: NMEA2000Message) -> str | list[str]:
        timestamp_token = self._default_candump3_timestamp(message.timestamp)
        lines = [
            f"{timestamp_token} slcan0 {frame.arbitration_id:08X}#{bytes(frame.data).hex().upper()}"
            for frame in self.encode_python_can(message)
        ]
        return self._match_output_shape(lines)


class EncoderSentenceTextMixin:
    """Sentence/coalesced text encoders."""

    def _encode_actisense_n2k_ascii(self, message: NMEA2000Message) -> str:
        return f"A000000.000 {self.encode_actisense(message)}"

    def _encode_pcdin(self, message: NMEA2000Message) -> str:
        payload = self._call_encode_function(message)
        sentence = f"$PCDIN,{message.PGN:06X},00000000,{message.source:02X},{payload.hex().upper()}"
        return sentence + self._compute_0183_checksum(sentence)

    def _encode_mxpgn(self, message: NMEA2000Message) -> str:
        send_bit = 0 if message.destination == 255 else 1
        address = message.source if send_bit == 0 else message.destination
        payload = self._call_encode_function(message)
        attr_word = (
            f"{((send_bit << 7) | ((message.priority & 0x7) << 4) | (len(payload) & 0xF)):02X}"
            f"{address:02X}"
        )
        sentence = f"$MXPGN,{message.PGN:06X},{attr_word},{payload[::-1].hex().upper()}"
        return sentence + self._compute_0183_checksum(sentence)

    def _encode_pdgy(self, message: NMEA2000Message) -> str:
        payload = self._call_encode_function(message)
        data = base64.b64encode(payload).decode("ascii")
        return ",".join(
            [
                "!PDGY",
                str(message.PGN),
                str(message.priority),
                str(message.source),
                str(message.destination),
                "0.000",
                data,
            ]
        )

    def _encode_pdgy_debug(self, _message: NMEA2000Message) -> str:
        raise ValueError("PDGY debug lines are not supported")


class EncoderBinaryMixin:
    """Binary/object transport encoders."""

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
