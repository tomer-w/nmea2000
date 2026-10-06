from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Self, TypeAlias, final

__all__ = [
    "AddressClaimer",
    "Database",
    "DecodeError",
    "EncodeError",
    "FieldInfo",
    "GatewayCodec",
    "MessageCodec",
    "PgnInfo",
    "Raw",
    "Reassembler",
    "ReassemblyError",
    "can_id_compose",
    "can_id_decompose",
    "fast_packet_fragment",
    "heartbeat_frame",
    "iso_ack_frame",
    "iso_name",
    "parse_line",
    "pgn_list_frames",
    "product_information_frame",
]

class DecodeError(Exception): ...
class EncodeError(Exception): ...
class ReassemblyError(Exception): ...

@final
class Raw:
    """A field's wire bits, written verbatim by ``Database.encode``."""

    value: int
    def __new__(cls, value: int) -> Self: ...

@final
class FieldInfo:
    """One field definition of a PGN."""

    @property
    def id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str | None: ...
    @property
    def field_type(self) -> str | None: ...
    @property
    def unit(self) -> str | None: ...
    @property
    def physical_quantity(self) -> str | None: ...
    @property
    def resolution(self) -> float | None: ...
    @property
    def offset(self) -> int | None: ...
    @property
    def bit_offset(self) -> int | None: ...
    @property
    def bit_length(self) -> int | None: ...
    @property
    def part_of_primary_key(self) -> bool: ...
    @property
    def lookup_bit_enumeration(self) -> str | None: ...

@final
class PgnInfo:
    """One PGN definition."""

    @property
    def pgn(self) -> int: ...
    @property
    def id(self) -> str: ...
    @property
    def packet_type(self) -> Literal["Single", "Fast", "ISO", "Mixed"]: ...
    @property
    def transmission_interval(self) -> int | None: ...
    @property
    def fields(self) -> list[FieldInfo]: ...
    @property
    def repeating_sets(self) -> list[tuple[int, int, int | None]]: ...

@final
class Database:
    """The compiled CANboat PGN database, in SI or metric units."""

    def __new__(cls, units: Literal["si", "metric"] = "si") -> Self: ...
    @property
    def version(self) -> str: ...
    def pgns(self) -> list[PgnInfo]: ...
    def pgn_variants(self, pgn: int) -> list[PgnInfo]: ...
    def pgn_info(self, id: str) -> PgnInfo: ...
    def lookup(self, name: str) -> list[tuple[int, str]]: ...
    def bit_lookup(self, name: str) -> list[tuple[int, str]]: ...
    def encode(
        self,
        pgn_id: str,
        fields: Mapping[str, Any],
        *,
        src: int = 0,
        dst: int = 255,
        prio: int | None = None,
        sets: Sequence[Sequence[Mapping[str, Any]]] | None = None,
    ) -> bytes: ...

@final
class Reassembler:
    """Joins fast-packet and ISO-TP frames into complete PGN payloads."""

    def __new__(cls) -> Self: ...
    def push(
        self, pgn: int, data: bytes, src: int = 0, dst: int = 255, prio: int = 6
    ) -> bytes | None: ...

_GatewayEvent: TypeAlias = (
    tuple[Literal["frame"], tuple[int, int, int, int, bytes]]
    | tuple[Literal["send"], bytes]
    | tuple[Literal["error"], str]
)

@final
class GatewayCodec:
    """A gateway's byte protocol (Actisense NGT-1, Digital Yacht iKonvert, Maretron IPG)."""

    def __new__(
        cls,
        kind: Literal["ngt1", "ikonvert", "maretron"],
        *,
        tx_pgns: Sequence[int] = ...,
        rx_pgns: Sequence[int] = ...,
        password: str = ...,
    ) -> Self: ...
    def open(self) -> bytes: ...
    def close(self) -> bytes: ...
    def keepalive(self) -> tuple[float, bytes] | None: ...
    def receive(
        self, data: bytes, now_ms: int | None = None
    ) -> list[_GatewayEvent]: ...
    def tick(self, now_ms: int | None = None) -> list[_GatewayEvent]: ...
    def send(
        self, pgn: int, data: bytes, src: int = 0, dst: int = 255, prio: int = 6
    ) -> bytes: ...

@final
class MessageCodec:
    """Decodes PGN payloads into nmea2000 message objects, and encodes them back."""

    def __new__(
        cls,
        template_for: Callable[[str], Any],
        field_type: type,
        message_type: type,
        units: Literal["native", "si", "metric"] = "native",
    ) -> Self: ...
    def decode(
        self, pgn: int, data: bytes, src: int = 0, dst: int = 255, prio: int = 6
    ) -> Any: ...
    def encode(self, message: Any) -> bytes: ...

def parse_line(format: str, line: str) -> tuple[int, int, int, int, bytes] | None: ...
def fast_packet_fragment(seq: int, data: bytes) -> list[bytes]: ...
def can_id_compose(prio: int, pgn: int, src: int, dst: int) -> int: ...
def can_id_decompose(can_id: int) -> tuple[int, int, int, int]: ...

# (priority, pgn, source, destination, payload): one complete PGN to send
_Frame: TypeAlias = tuple[int, int, int, int, bytes]

def iso_name(
    manufacturer_code: int,
    unique_number: int,
    *,
    device_function: int,
    device_class: int,
    device_instance: int,
    system_instance: int,
    industry_group: int,
    arbitrary_address_capable: bool,
) -> int: ...

@final
class AddressClaimer:
    """ISO 11783-5 address claiming, driven by the caller's clock (in ms)."""

    def __new__(
        cls, name: int, preferred_address: int, arbitrary_address_capable: bool
    ) -> Self: ...
    def start(self, now_ms: int) -> list[_Frame]: ...
    def tick(self, now_ms: int) -> list[_Frame]: ...
    def on_address_claim(self, now_ms: int, src: int, name: int) -> list[_Frame]: ...
    def respond_to_claim_request(self) -> _Frame | None: ...
    @property
    def state(
        self,
    ) -> Literal["scanning", "pending", "claimed", "failed", "disabled"]: ...
    @property
    def address(self) -> int | None: ...
    @property
    def send_address(self) -> int | None: ...
    @property
    def deadline(self) -> int: ...
    @property
    def is_timing(self) -> bool: ...
    @property
    def name(self) -> int: ...

def product_information_frame(
    src: int,
    *,
    nmea2000_version: int,
    product_code: int,
    model_id: str,
    software_version: str,
    model_version: str,
    model_serial: str,
    certification_level: int,
    load_equivalency: int,
) -> _Frame: ...
def heartbeat_frame(src: int, sequence: int, interval_ms: int) -> _Frame: ...
def iso_ack_frame(src: int, dst: int, control: int, pgn: int) -> _Frame: ...
def pgn_list_frames(
    src: int, dst: int, transmit: Sequence[int], receive: Sequence[int]
) -> list[_Frame]: ...
