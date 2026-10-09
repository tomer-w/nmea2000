"""NMEA2000 Decoder module to decode NMEA2000 messages from various input formats."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from importlib import import_module
from typing import ClassVar

from . import _canboat as canboat
from . import backend
from .consts import PhysicalQuantities
from .input_formats import N2KFormat, N2KInput, detect_format
from .message import IsoName, NMEA2000Message

logger = logging.getLogger(__name__)


class InvalidFrameError(Exception):
    """Raised when a USB frame has invalid structure (bad checksum, wrong length, etc.)."""


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


class DecoderStaticsMixin:
    """Shared stateless decoder helpers used by the interface and base mechanics."""

    @staticmethod
    def extract_header(frame_id_int: int) -> tuple[int, int, int, int]:
        """
        Extract PGN, source ID, destination, and priority from a 29-bit CAN frame ID.

        Returns a tuple of `(pgn_id, source_id, dest, priority)`.
        based on the 29 bits (ID0 - ID28) in https://canboat.github.io/canboat/canboat.html
        """
        priority, pgn_id, source_id, dest = canboat.can_id_decompose(
            frame_id_int & 0x1FFFFFFF
        )
        return pgn_id, source_id, dest, priority

    @staticmethod
    def is_fast_pgn(pgn_id: int) -> bool | None:
        """Return whether a PGN is a fast packet PGN, or `None` if unsupported."""
        return backend.is_fast_pgn(pgn_id)

    @staticmethod
    def split_pgn_list(pgn_list: list[int | str]) -> tuple[list[int], list[str]]:
        """Split a list of PGNs into integer and string IDs."""
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


class DecoderInterface(DecoderStaticsMixin, ABC):
    """Public decoder contract shared by the dispatcher and concrete handlers."""

    @abstractmethod
    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        """Decode the input data and return an NMEA2000Message object."""

    @abstractmethod
    def close(self):
        """Close any resources held by the decoder, such as dump files."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class DecoderBase(DecoderStaticsMixin):
    """Shared decoder mechanics used by concrete format handlers."""

    def __init__(
        self,
        *,
        exclude_pgns: list[int | str] | None = None,
        include_pgns: list[int | str] | None = None,
        exclude_manufacturer_code: list[str] | None = None,
        include_manufacturer_code: list[str] | None = None,
        preferred_units: dict[PhysicalQuantities, str] | None = None,
        dump_to_file: str | None = None,
        dump_pgns: list[int | str] | None = None,
        build_network_map: bool = False,
        bound_format: N2KFormat | None = None,
        started_at: datetime | None = None,
        already_combined: bool = False,
        units: backend.Units = "native",
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
        self.already_combined = already_combined
        if units not in backend.UNITS:
            raise ValueError(
                f"units must be one of {', '.join(backend.UNITS)}, not {units!r}"
            )
        # The unit system values are reported in (see nmea2000.backend)
        self.units: backend.Units = units
        self.data: dict[str, FastPgnMetadata] = {}
        self.reassembler = canboat.Reassembler()
        self.dump_file = None
        self.build_network_map = build_network_map
        self.started_at = started_at or datetime.now()

        if dump_to_file:
            dir_name = os.path.dirname(dump_to_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            self.dump_file = open(  # noqa: SIM115  # pylint: disable=consider-using-with
                dump_to_file, "a", encoding="utf-8"
            )

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
        self.dump_include_pgns, self.dump_include_pgns_ids = self.split_pgn_list(
            dump_pgns
        )
        self.preferred_units = {k: v.lower() for k, v in preferred_units.items()}
        self.source_to_iso_name: dict[int, IsoName] = {}
        self.logged_unsupported_pgns: set[int] = set()

        self.iso_claim_filter = (
            (ISO_CLAIM_PGN in self.exclude_pgns)
            or (ISO_CLAIM_PGN_ID in self.exclude_pgns_ids)
            or (len(self.include_pgns) and ISO_CLAIM_PGN not in self.include_pgns)
            or (
                len(self.include_pgns_ids)
                and ISO_CLAIM_PGN_ID not in self.include_pgns_ids
            )
        )
        if self.iso_claim_filter:
            while ISO_CLAIM_PGN in self.exclude_pgns:
                self.exclude_pgns.remove(ISO_CLAIM_PGN)
            while ISO_CLAIM_PGN_ID in self.exclude_pgns_ids:
                self.exclude_pgns_ids.remove(ISO_CLAIM_PGN_ID)
            logger.info("iso address claim will be removed later")

        logger.info(
            "PGN filter exclude: %s, %s", self.exclude_pgns, self.exclude_pgns_ids
        )
        logger.info(
            "PGN filter include: %s, %s", self.include_pgns, self.include_pgns_ids
        )
        logger.info("Preffered units: %s", self.preferred_units)
        logger.info("Dump location: %s, PGNs: %s", dump_to_file, dump_pgns)

    def _decode_fast_message(
        self,
        pgn: int,
        priority: int,
        src: int,
        dest: int,
        timestamp: datetime,
        can_data: bytes,
        source_iso_name: IsoName | None,
        raw_can_data: bytes | str,
    ) -> NMEA2000Message | None:
        """Collect a fast-packet frame; decode the message once it is complete."""
        # can_data is byte-reversed internally; the reassembler wants wire order
        try:
            payload = self.reassembler.push(pgn, can_data[::-1], src, dest, priority)
        except canboat.ReassemblyError as error:
            logger.debug("Dropping fast-packet frame for PGN %s: %s", pgn, error)
            return None
        if payload is None:
            return None  # waiting for more frames
        return self._call_decode_function(
            pgn,
            priority,
            src,
            dest,
            timestamp,
            payload[::-1],
            source_iso_name,
            raw_can_data,
            len(payload) * 8,
        )

    def _log_unsupported_pgn_once(self, pgn_id: int) -> None:
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
        # Check if the PGN should be excluded or included
        if (
            pgn != ISO_CLAIM_PGN
        ):  # The ISO_CLAIM_PGN should bypass this check so we can build the map later
            if pgn in self.exclude_pgns:
                logger.debug("Excluding PGN: %s", pgn)
                return None
            if (
                len(self.include_pgns) > 0
                and len(self.include_pgns_ids) == 0
                and pgn not in self.include_pgns
            ):
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

            if (
                source_iso_name is not None
                and source_iso_name.manufacturer_code is not None
            ):
                # Check if the PGN should be excluded or included based on manufacturer
                manufacturer_code = source_iso_name.manufacturer_code.lower()
                if manufacturer_code in self.exclude_manufacturer_code:
                    logger.debug(
                        "Excluding PGN: %s based on manufacturer code %s",
                        pgn,
                        source_iso_name.manufacturer_code,
                    )
                    return None
                if (
                    len(self.include_manufacturer_code) > 0
                    and manufacturer_code not in self.include_manufacturer_code
                ):
                    logger.debug(
                        "Excluding (by include) PGN: %s based on manufacturer code %s",
                        pgn,
                        source_iso_name.manufacturer_code,
                    )
                    return None

        is_fast = False
        if not already_combined:
            is_fast = type(self).is_fast_pgn(pgn)
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
        data_length_bits: int | None = None,
    ) -> NMEA2000Message | None:
        data_int = int.from_bytes(data, "big")
        payload_length_bits = (
            data_length_bits if data_length_bits is not None else len(data) * 8
        )
        # data is byte-reversed internally; canboat wants the wire-order bytes
        # without fast-packet padding
        payload = data[::-1][: payload_length_bits // 8]
        nmea2000_message = backend.decode(pgn, payload, src, dest, priority, self.units)
        if nmea2000_message is None:
            logger.debug("No decoding found for PGN: %s", pgn)
            return None

        # Handle ISO Address Claim messages and enrichment
        if nmea2000_message.PGN == ISO_CLAIM_PGN:
            # In this message the data is a 64 bit unique NAME which is stable between network restarts
            old_source = self.source_to_iso_name.get(src, None)
            if old_source is not None and old_source.name == data_int:
                logger.debug("Using existing ISO_CLAIM_PGN for source %s", src)
                source_iso_name = old_source
            else:
                new_source = IsoName(nmea2000_message, data_int)
                logger.info(
                    "Using new ISO_CLAIM_PGN for source %s: %s", src, new_source
                )
                source_iso_name = self.source_to_iso_name[src] = new_source
            if self.iso_claim_filter:
                logger.debug("Excluding ISO_CLAIM_PGN")
                return None

        # Check if the PGN should be excluded or included by ID
        msg_id = nmea2000_message.id.lower()
        if msg_id in self.exclude_pgns_ids:
            logger.debug("Excluding PGN by id: %s", nmea2000_message.id)
            return None
        if (
            len(self.include_pgns) > 0
            and nmea2000_message.PGN not in self.include_pgns
            and len(self.include_pgns_ids) > 0
            and msg_id not in self.include_pgns_ids
        ):
            logger.debug(
                "Excluding (by include) PGN %d by id: %s", pgn, nmea2000_message.id
            )
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

        # Handle dump to file
        if self.dump_file is not None and (
            len(self.dump_include_pgns) + len(self.dump_include_pgns_ids) == 0
            or nmea2000_message.PGN in self.dump_include_pgns
            or nmea2000_message.id in self.dump_include_pgns_ids
        ):
            json_str = nmea2000_message.to_json() + "\n"
            self.dump_file.write(json_str)

        return nmea2000_message

    def close(self):
        """Close the dump file if it is open."""
        if self.dump_file:
            self.dump_file.close()
            self.dump_file = None
            logger.info("dump_file file has been closed.")


class NMEA2000Decoder(DecoderInterface):
    """Thin public dispatcher that binds to one concrete format decoder."""

    HANDLERS: ClassVar[dict[N2KFormat, Callable[..., DecoderInterface]]] = {}

    def __init__(
        self,
        bound_format: N2KFormat | None = None,
        **kwargs,
    ) -> None:
        units = kwargs.get("units", "native")
        if units not in backend.UNITS:
            raise ValueError(
                f"units must be one of {', '.join(backend.UNITS)}, not {units!r}"
            )
        self._handler_init_kwargs = kwargs
        self._delegate: DecoderInterface | None = None
        self._bound_format: N2KFormat | None = None
        if bound_format is not None:
            self._bind_delegate(bound_format)

    @classmethod
    def add_handler(
        cls, input_format: N2KFormat, handler_cls: type[DecoderInterface]
    ) -> None:
        """Register the concrete decoder class for one detected input format."""
        cls.HANDLERS[input_format] = handler_cls

    @classmethod
    def get_handler(cls, input_format: N2KFormat) -> Callable[..., DecoderInterface]:
        """Return the registered decoder class for an input format."""
        handler_cls = cls.HANDLERS.get(input_format)
        if handler_cls is None:
            raise ValueError(f"Unsupported input format: {input_format}")
        return handler_cls

    def _bind_delegate(self, input_format: N2KFormat) -> DecoderInterface:
        if self._delegate is None:
            handler_cls = self.get_handler(input_format)
            self._delegate = handler_cls(
                bound_format=input_format,
                **self._handler_init_kwargs,
            )
            self._bound_format = input_format
            return self._delegate

        if self._bound_format != input_format:
            assert self._bound_format is not None
            raise ValueError(
                "This NMEA2000Decoder instance is already bound to "
                f"{self._bound_format.value}; create a new decoder for {input_format.value}."
            )
        return self._delegate

    def decode(
        self,
        data: N2KInput,
    ) -> NMEA2000Message | None:
        if self._delegate is not None:
            return self._delegate.decode(data)
        input_format = detect_format(data)
        return self._bind_delegate(input_format).decode(data)

    def close(self):
        if self._delegate:
            self._delegate.close()


import_module(".decoder_formats", __package__)

__all__ = [
    "DecoderBase",
    "DecoderInterface",
    "InvalidFrameError",
    "NMEA2000Decoder",
    "NMEA2000Message",
]
