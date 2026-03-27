"""NMEA2000 Decoder module to decode NMEA2000 messages from various input formats."""
from __future__ import annotations

from abc import ABC, abstractmethod
from importlib import import_module
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import can.message

from .consts import PhysicalQuantities
from .input_formats import N2KFormat, detect_format
from .message import IsoName, NMEA2000Message
from . import pgns as pgns_module

logger = logging.getLogger(__name__)


class FastPgnMetadata:
    """Class to store metadata for fast packet PGNs."""

    def __init__(self) -> None:
        self.frames: dict[int, bytes] = {}
        self.payload_length = 0
        self.bytes_stored = 0
        self.sequence_counter = -1

    def __repr__(self):
        return (
            "<FastPgnMetadata "
            f"frames={len(self.frames)} payload_length={self.payload_length} "
            f"bytes_stored={self.bytes_stored} sequence_counter={self.sequence_counter}>"
        )


ISO_CLAIM_PGN = 60928
ISO_CLAIM_PGN_ID = "isoAddressClaim"


class DecoderInterface(ABC):
    """Public decoder contract shared by the dispatcher and concrete handlers."""

    @abstractmethod
    def decode(
        self,
        input_data: str | list[str] | bytes | bytearray | memoryview | can.message.Message,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        """Decode input data into an NMEA2000Message."""


class DecoderBase:
    """Shared decoder mechanics used by concrete format handlers."""

    def __init__(
        self,
        *,
        exclude_pgns: Optional[List[int | str]] = None,
        include_pgns: Optional[List[int | str]] = None,
        exclude_manufacturer_code: Optional[List[str]] = None,
        include_manufacturer_code: Optional[List[str]] = None,
        preferred_units: Optional[Dict[PhysicalQuantities, str]] = None,
        dump_to_file: str | None = None,
        dump_pgns: Optional[List[int | str]] = None,
        build_network_map: bool = False,
        bound_format: N2KFormat | None = None,
        started_at: datetime | None = None,
    ) -> None:
        if exclude_pgns is None:
            exclude_pgns = []
        if include_pgns is None:
            include_pgns = []
        if exclude_manufacturer_code is None:
            exclude_manufacturer_code = []
        if include_manufacturer_code is None:
            include_manufacturer_code = []
        if preferred_units is None:
            preferred_units = {}
        if dump_pgns is None:
            dump_pgns = []

        self.bound_format = bound_format
        self.data: dict[str, FastPgnMetadata] = {}
        self.dump_file = None
        self.build_network_map = build_network_map
        self.started_at = started_at or datetime.now()

        if dump_to_file:
            dir_name = os.path.dirname(dump_to_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            self.dump_file = open(dump_to_file, "a", encoding="utf-8")

        if not isinstance(exclude_pgns, list):
            raise ValueError("exclude_pgns must be a list")
        if not isinstance(include_pgns, list):
            raise ValueError("include_pgns must be a list")
        if len(exclude_pgns) > 0 and len(include_pgns) > 0:
            raise ValueError("Only one of exclude_pgns or include_pgns can be used")

        self.exclude_pgns, self.exclude_pgns_ids = self.split_pgn_list(exclude_pgns)
        self.include_pgns, self.include_pgns_ids = self.split_pgn_list(include_pgns)
        self.exclude_manufacturer_code = {k.lower() for k in exclude_manufacturer_code}
        self.include_manufacturer_code = {k.lower() for k in include_manufacturer_code}
        self.dump_include_pgns, self.dump_include_pgns_ids = self.split_pgn_list(dump_pgns)
        self.preferred_units = {k: v.lower() for k, v in preferred_units.items()}
        self.source_to_iso_name: dict[int, IsoName] = {}
        self.logged_unsupported_pgns: set[int] = set()

        self.iso_claim_filter = (
            (ISO_CLAIM_PGN in self.exclude_pgns)
            or (ISO_CLAIM_PGN_ID in self.exclude_pgns_ids)
            or (len(self.include_pgns) and ISO_CLAIM_PGN not in self.include_pgns)
            or (len(self.include_pgns_ids) and ISO_CLAIM_PGN_ID not in self.include_pgns_ids)
        )
        if self.iso_claim_filter:
            while ISO_CLAIM_PGN in self.exclude_pgns:
                self.exclude_pgns.remove(ISO_CLAIM_PGN)
            while ISO_CLAIM_PGN_ID in self.exclude_pgns_ids:
                self.exclude_pgns_ids.remove(ISO_CLAIM_PGN_ID)
            logger.info("iso address claim will be removed later")

        logger.info("PGN filter exclude: %s, %s", self.exclude_pgns, self.exclude_pgns_ids)
        logger.info("PGN filter include: %s, %s", self.include_pgns, self.include_pgns_ids)
        logger.info("Preffered units: %s", self.preferred_units)
        logger.info("Dump location: %s, PGNs: %s", dump_to_file, dump_pgns)

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

    def _decode_text_lines(
        self,
        input_data: str | list[str],
        line_decoder: Callable[[str], NMEA2000Message | None],
    ) -> NMEA2000Message | None:
        decoded_message = None
        for line in self._normalize_text_lines(input_data):
            result = line_decoder(line)
            if result is not None:
                if decoded_message is not None:
                    raise ValueError("Input produced multiple decoded PGNs")
                decoded_message = result
        return decoded_message

    @staticmethod
    def split_pgn_list(pgn_list: list[int | str]) -> Tuple[list[int], list[str]]:
        """Split a list of PGNs into two lists: one for integers and one for strings."""
        int_list = []
        str_list = []
        if pgn_list is None:
            return int_list, str_list
        for pgn in pgn_list:
            if isinstance(pgn, int):
                int_list.append(pgn)
            elif isinstance(pgn, str):
                str_list.append(pgn.lower())
            else:
                raise ValueError(f"Invalid PGN type: {type(pgn)}. Must be int or str.")
        return int_list, str_list

    def _decode_fast_message(
        self,
        pgn,
        priority,
        src,
        dest,
        timestamp,
        can_data: bytes,
        source_iso_name: IsoName | None,
        raw_can_data: bytes | str,
    ) -> NMEA2000Message | None:
        """Parse a fast packet message and store the data until all frames are received."""
        fast_packet_key = f"{pgn}_{src}_{dest}"
        if self.data.get(fast_packet_key) is None:
            self.data[fast_packet_key] = FastPgnMetadata()

        fast_pgn = self.data[fast_packet_key]
        last_byte = can_data[-1]
        sequence_counter = (last_byte >> 5) & 0b111
        frame_counter = last_byte & 0b11111
        total_bytes = None

        if frame_counter != 0 and fast_pgn.payload_length == 0:
            logger.debug(
                "Ignoring frame %s for PGN %s as first frame has not been received.",
                frame_counter,
                pgn,
            )
            return None

        if frame_counter == 0 and sequence_counter != fast_pgn.sequence_counter:
            total_bytes = can_data[-2]
            fast_pgn.payload_length = total_bytes
            fast_pgn.sequence_counter = sequence_counter
            fast_pgn.bytes_stored = 0
            fast_pgn.frames.clear()
            data_payload = can_data[:-2]
        else:
            if sequence_counter != fast_pgn.sequence_counter:
                logger.debug(
                    "Ignoring frame %s for PGN %s as it does not match current sequence.",
                    sequence_counter,
                    pgn,
                )
                return None
            if frame_counter in fast_pgn.frames:
                logger.debug("Frame %s for PGN %s is already stored.", frame_counter, pgn)
                return None
            data_payload = can_data[:-1]

        byte_length = len(data_payload)
        fast_pgn.frames[frame_counter] = data_payload
        fast_pgn.bytes_stored += byte_length

        logger.debug("Sequence Counter: %s, Frame Counter: %s", sequence_counter, frame_counter)
        if total_bytes is not None:
            logger.debug("Total Payload Bytes: %s", total_bytes)
        logger.debug("Orig Payload (hex): %s, Data Payload (hex): %s", can_data, data_payload)
        logger.debug("PGN Data: %s", fast_pgn)

        if fast_pgn.bytes_stored >= fast_pgn.payload_length:
            logger.debug("All Fast packet frames collected for PGN: %d", pgn)
            combined_payload = bytes(
                [b for idx in sorted(fast_pgn.frames) for b in fast_pgn.frames[idx][::-1]]
            )[::-1]
            nmea = None
            if combined_payload is not None:
                logger.debug("Combined Payload (hex): %s)", combined_payload)
                nmea = self._call_decode_function(
                    pgn,
                    priority,
                    src,
                    dest,
                    timestamp,
                    combined_payload,
                    source_iso_name,
                    raw_can_data,
                )
            del self.data[fast_packet_key]
            return nmea

        logger.debug("Waiting for %s more bytes.", fast_pgn.payload_length - fast_pgn.bytes_stored)
        return None

    @staticmethod
    def extract_header(frame_id_int: int) -> Tuple[int, int, int, int]:
        """
        Extracts PGN, source ID, destination, and priority from a 29-bit CAN frame ID.
        Returns a tuple of (pgn_id, source_id, dest, priority).
        based on the 29 bits (ID0 - ID28) in https://canboat.github.io/canboat/canboat.html
        """
        source_id = frame_id_int & 0xFF
        pgn_id_raw = (frame_id_int >> 8) & 0x3FFFF
        priority = (frame_id_int >> 26) & 0x07

        dp = (pgn_id_raw >> 16) & 0x3
        pf = (pgn_id_raw >> 8) & 0xFF
        ps = pgn_id_raw & 0xFF

        if pf < 0xF0:
            dest = ps
            pgn_id = (dp << 16) | (pf << 8)
        else:
            dest = 255
            pgn_id = (dp << 16) | (pf << 8) | ps

        return pgn_id, source_id, dest, priority

    @staticmethod
    def is_fast_pgn(pgn_id: int) -> bool | None:
        """Check if a PGN is a fast packet PGN by looking for the is_fast_pgn_{pgn_id} function."""
        is_fast_func_name = f"is_fast_pgn_{pgn_id}"
        is_fast_func: Callable[[], bool] | None = getattr(pgns_module, is_fast_func_name, None)

        if is_fast_func and callable(is_fast_func):
            is_fast: bool = is_fast_func()
            logger.debug("Is fast PGN: %s", is_fast)
            return is_fast
        return None

    def _log_unsupported_pgn_once(self, pgn_id: int) -> None:
        """Log unsupported PGN message only once per PGN."""
        if pgn_id not in self.logged_unsupported_pgns:
            logger.warning("Not supporrted PGN: %d", pgn_id)
            self.logged_unsupported_pgns.add(pgn_id)

    def _decode(
        self,
        pgn: int,
        priority: int,
        source_id: int,
        destination_id: int,
        timestamp: datetime,
        can_data: bytes,
        raw_can_data: bytes | str,
        already_combined: bool = False,
    ) -> NMEA2000Message | None:
        """Decode a single PGN message."""
        source_iso_name = None
        if pgn != ISO_CLAIM_PGN:
            if pgn in self.exclude_pgns:
                logger.debug("Excluding PGN: %s", pgn)
                return None
            if len(self.include_pgns) > 0 and len(self.include_pgns_ids) == 0 and pgn not in self.include_pgns:
                logger.debug("Excluding (by include) PGN: %s", pgn)
                return None

            source_iso_name = self.source_to_iso_name.get(source_id, None)
            if source_iso_name is None and self.build_network_map:
                if self.started_at > datetime.now() - timedelta(minutes=10):
                    logger.debug(
                        "No ISO name found for source %s in PGN id %s. Skipping the message for now.",
                        source_id,
                        pgn,
                    )
                    return None
                logger.warning(
                    "No ISO name found for source %s in PGN id %s for too long. Will process it anyhow.",
                    source_id,
                    pgn,
                )

            if source_iso_name is not None and source_iso_name.manufacturer_code is not None:
                manufacturer_code = source_iso_name.manufacturer_code.lower()
                if manufacturer_code in self.exclude_manufacturer_code:
                    logger.debug(
                        "Excluding PGN: %s based on manufacturer code %s",
                        pgn,
                        source_iso_name.manufacturer_code,
                    )
                    return None
                if len(self.include_manufacturer_code) > 0 and manufacturer_code not in self.include_manufacturer_code:
                    logger.debug(
                        "Excluding (by include) PGN: %s based on manufacturer code %s",
                        pgn,
                        source_iso_name.manufacturer_code,
                    )
                    return None

        is_fast = False
        if not already_combined:
            is_fast = DecoderBase.is_fast_pgn(pgn)
        if is_fast is None:
            self._log_unsupported_pgn_once(pgn)
            return None

        if is_fast:
            return self._decode_fast_message(
                pgn,
                priority,
                source_id,
                destination_id,
                timestamp,
                can_data,
                source_iso_name,
                raw_can_data,
            )
        return self._call_decode_function(
            pgn,
            priority,
            source_id,
            destination_id,
            timestamp,
            can_data,
            source_iso_name,
            raw_can_data,
        )

    def _call_decode_function(
        self,
        pgn: int,
        priority: int,
        src: int,
        dest: int,
        timestamp: datetime,
        data: bytes,
        source_iso_name: IsoName | None,
        raw_can_data: bytes | str,
    ) -> NMEA2000Message | None:
        decode_func_name = f"decode_pgn_{pgn}"
        decode_func: Callable[[int, int | None], NMEA2000Message] | None = getattr(
            pgns_module, decode_func_name, None
        )

        if not decode_func or not callable(decode_func):
            logger.error(
                "No decoding function found for PGN: %s. It should be there as we found the is_fast func",
                pgn,
            )
            return None

        data_int = int.from_bytes(data, "big")
        nmea2000_message: NMEA2000Message | None = decode_func(data_int, len(data) * 8)
        if nmea2000_message is None:
            logger.debug("No sub-decoding function found for PGN: %s", pgn)
            return None

        if nmea2000_message.PGN == ISO_CLAIM_PGN:
            old_source = self.source_to_iso_name.get(src, None)
            if old_source is not None and old_source.name == data_int:
                logger.debug("Using existing ISO_CLAIM_PGN for source %s", src)
                source_iso_name = old_source
            else:
                new_source = IsoName(nmea2000_message, data_int)
                logger.info("Using new ISO_CLAIM_PGN for source %s: %s", src, new_source)
                source_iso_name = self.source_to_iso_name[src] = new_source
            if self.iso_claim_filter:
                logger.debug("Excluding ISO_CLAIM_PGN")
                return None

        msg_id = nmea2000_message.id.lower()
        if msg_id in self.exclude_pgns_ids:
            logger.debug("Excluding PGN by id: %s", nmea2000_message.id)
            return None
        if (
            len(self.include_pgns) > 0
            and msg_id not in self.include_pgns
            and len(self.include_pgns_ids) > 0
            and msg_id not in self.include_pgns_ids
        ):
            logger.debug("Excluding (by include) PGN %d by id: %s", pgn, nmea2000_message.id)
            return None

        nmea2000_message.add_data(
            src,
            dest,
            priority,
            timestamp,
            source_iso_name,
            self.build_network_map,
            raw_can_data,
        )
        nmea2000_message.apply_preferred_units(self.preferred_units)

        if (
            self.dump_file is not None
            and (
                len(self.dump_include_pgns) + len(self.dump_include_pgns_ids) == 0
                or nmea2000_message.PGN in self.dump_include_pgns
                or nmea2000_message.id in self.dump_include_pgns_ids
            )
        ):
            json_str = nmea2000_message.to_json() + "\n"
            self.dump_file.write(json_str)

        return nmea2000_message

    def close(self):
        """Close the dump_file file if it is open."""
        if self.dump_file:
            self.dump_file.close()
            self.dump_file = None
            logger.info("dump_file file has been closed.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class NMEA2000Decoder(DecoderInterface):
    """Thin public dispatcher that binds to one concrete format decoder."""

    HANDLERS: dict[N2KFormat, type[DecoderInterface]] = {}

    # Grab a few static methods from the base class for convenience and backwards compatibility
    extract_header = staticmethod(DecoderBase.extract_header)
    is_fast_pgn = staticmethod(DecoderBase.is_fast_pgn)

    def __init__(
        self,
        exclude_pgns: Optional[List[int | str]] = None,
        include_pgns: Optional[List[int | str]] = None,
        exclude_manufacturer_code: Optional[List[str]] = None,
        include_manufacturer_code: Optional[List[str]] = None,
        preferred_units: Optional[Dict[PhysicalQuantities, str]] = None,
        dump_to_file: str | None = None,
        dump_pgns: Optional[List[int | str]] = None,
        build_network_map: bool = False,
    ) -> None:
        self._started_at = datetime.now()
        self._handler_init_kwargs = {
            "exclude_pgns": list(exclude_pgns) if exclude_pgns is not None else None,
            "include_pgns": list(include_pgns) if include_pgns is not None else None,
            "exclude_manufacturer_code": list(exclude_manufacturer_code)
            if exclude_manufacturer_code is not None
            else None,
            "include_manufacturer_code": list(include_manufacturer_code)
            if include_manufacturer_code is not None
            else None,
            "preferred_units": dict(preferred_units) if preferred_units is not None else None,
            "dump_to_file": dump_to_file,
            "dump_pgns": list(dump_pgns) if dump_pgns is not None else None,
            "build_network_map": build_network_map,
            "started_at": self._started_at,
        }
        self._delegate: DecoderInterface | None = None
        self._bound_format: N2KFormat | None = None

    @classmethod
    def add_handler(cls, input_format: N2KFormat, handler_cls: type[DecoderInterface]) -> None:
        cls.HANDLERS[input_format] = handler_cls

    @classmethod
    def get_handler(cls, input_format: N2KFormat) -> type[DecoderInterface]:
        handler_cls = cls.HANDLERS.get(input_format)
        if handler_cls is None:
            raise ValueError(f"Unsupported input format: {input_format}")
        return handler_cls

    def _bind_delegate(self, input_format: N2KFormat) -> DecoderInterface:
        if self._delegate is None:
            handler_cls = self.get_handler(input_format)
            self._delegate = handler_cls(bound_format=input_format, **self._handler_init_kwargs)
            self._bound_format = input_format
            return self._delegate

        if self._bound_format != input_format:
            raise ValueError(
                "This NMEA2000Decoder instance is already bound to "
                f"{self._bound_format.value}; create a new decoder for {input_format.value}."
            )
        return self._delegate

    def decode(
        self,
        input_data: str | list[str] | bytes | bytearray | memoryview | can.message.Message,
        single_line: bool = False,
    ) -> NMEA2000Message | None:
        input_format = detect_format(input_data)
        return self._bind_delegate(input_format).decode(input_data, single_line)

    # Convenience methods for backwards compatibility
    def decode_basic_string(
        self,
        basic_string: str,
        already_combined: bool = False,
    ) -> NMEA2000Message | None:
        delegate = self._bind_delegate(N2KFormat.BASIC_STRING)
        return delegate.decode_basic_string(basic_string, already_combined)  # type: ignore[attr-defined]

    def decode_actisense_string(self, actisense_string: str) -> NMEA2000Message | None:
        delegate = self._bind_delegate(N2KFormat.ACTISENSE_N2K_ASCII)
        return delegate.decode_actisense_string(actisense_string)  # type: ignore[attr-defined]

    def decode_yacht_devices_string(self, yd_string: str) -> NMEA2000Message | None:
        delegate = self._bind_delegate(N2KFormat.YDRAW)
        return delegate.decode_yacht_devices_string(yd_string)  # type: ignore[attr-defined]

    def decode_tcp(self, packet: bytes) -> NMEA2000Message | None:
        delegate = self._bind_delegate(N2KFormat.EBYTE)
        return delegate.decode_tcp(packet)  # type: ignore[attr-defined]

    def decode_usb(self, packet: bytes) -> NMEA2000Message | None:
        delegate = self._bind_delegate(N2KFormat.USB)
        return delegate.decode_usb(packet)  # type: ignore[attr-defined]

    def decode_python_can(self, msg: can.message.Message) -> NMEA2000Message | None:
        delegate = self._bind_delegate(N2KFormat.PYTHON_CAN)
        return delegate.decode_python_can(msg)  # type: ignore[attr-defined]

    def close(self):
        if self._delegate is not None and hasattr(self._delegate, "close"):
            self._delegate.close()  # type: ignore[attr-defined]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


# Running this import registers all the format handler classes
_decoder_formats = import_module(".decoder_formats", __package__)

InvalidFrameError = _decoder_formats.InvalidFrameError

__all__ = [
    "DecoderBase",
    "DecoderInterface",
    "InvalidFrameError",
    "NMEA2000Decoder",
    "NMEA2000Message",
]
