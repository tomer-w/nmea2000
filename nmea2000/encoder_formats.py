from __future__ import annotations

import logging

import can.message

from .encoder import EncoderBase, EncoderInterface, NMEA2000Encoder
from .input_formats import N2KFormat
from .message import NMEA2000Message
from .utils import calculate_canbus_checksum

logger = logging.getLogger(__name__)


def _bytes_to_hex_string(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


class ActisenseEncoder(EncoderInterface, EncoderBase):
    """Encoder for Actisense packet strings."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)

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


class BasicStringEncoder(EncoderInterface, EncoderBase):
    """Encoder for the basic CSV string format."""

    def encode(
        self,
        nmea200_message: NMEA2000Message,
        output_format: N2KFormat | str | None = None,
    ) -> str:
        self._assert_output_format(output_format)

        can_data_bytes = self._call_encode_function(nmea200_message)
        timestamp = nmea200_message.timestamp.isoformat(timespec="milliseconds") + "Z"
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
            # Construct and return the full packet
            text_msg = frame_id_bytes.hex().upper() + " " + _bytes_to_hex_string(message) + "\r\n"
            result.append(text_msg.encode())
        return result


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

        encoded_messages = self._encode(nmea200_message)
        arbitration_id = type(self)._build_header(
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


NMEA2000Encoder.add_handler(N2KFormat.ACTISENSE, ActisenseEncoder)
NMEA2000Encoder.add_handler(N2KFormat.BASIC_STRING, BasicStringEncoder)
NMEA2000Encoder.add_handler(N2KFormat.YACHT_DEVICES, YachtDevicesEncoder)
NMEA2000Encoder.add_handler(N2KFormat.TCP, TcpEncoder)
NMEA2000Encoder.add_handler(N2KFormat.USB, UsbEncoder)
NMEA2000Encoder.add_handler(N2KFormat.PYTHON_CAN, PythonCanEncoder)
