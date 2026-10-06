# pylint: disable=missing-function-docstring,redefined-outer-name
"""Tests of nmea2000._canboat, the compiled canboat core, below the message model."""

from types import SimpleNamespace

import pytest

from nmea2000 import _canboat as canboat


@pytest.fixture(scope="module")
def db():
    return canboat.Database()


def test_encode(db):
    payload = db.encode(
        "windData", {"windSpeed": 5.23, "windAngle": 1.5, "reference": "Apparent"}
    )
    assert payload.hex() == "ff0b02983afaffff"
    # Raw writes the wire bits verbatim: 523 * 0.01 m/s.
    assert (
        db.encode(
            "windData",
            {"windSpeed": canboat.Raw(523), "windAngle": 1.5, "reference": 2},
        )
        == payload
    )


def test_encode_errors(db):
    with pytest.raises(canboat.EncodeError):
        db.encode("noSuchPgn", {})
    with pytest.raises(canboat.EncodeError):
        db.encode("windData", {"noSuchField": 1})
    with pytest.raises(canboat.EncodeError):
        db.encode("windData", {"windSpeed": 1000})  # beyond its range
    with pytest.raises(canboat.EncodeError):
        db.encode("windData", {"reference": "Sideways"})


def test_encode_repeating_set(db):
    payload = db.encode(
        "gnssSatsInView", {}, sets=[[{"prn": 1, "snr": 40.0}, {"prn": 2, "snr": 35.5}]]
    )
    assert payload[2] == 2  # the count field follows the instances


def test_schema(db):
    assert db.version
    info = db.pgn_info("windData")
    assert (info.pgn, info.packet_type, info.transmission_interval) == (
        130306,
        "Single",
        100,
    )
    speed = info.fields[1]
    assert (speed.id, speed.name, speed.field_type) == (
        "windSpeed",
        "Wind Speed",
        "NUMBER",
    )
    assert (speed.unit, speed.physical_quantity, speed.resolution) == (
        "m/s",
        "SPEED",
        0.01,
    )
    assert (speed.bit_offset, speed.bit_length) == (8, 16)
    assert info.fields[3].part_of_primary_key
    assert [v.id for v in db.pgn_variants(130306)] == ["windData"]
    assert db.pgn_variants(1) == []
    start, size, count = db.pgn_info("gnssSatsInView").repeating_sets[0]
    assert (size, count) == (7, start - 1)
    assert any(p.id == "windData" for p in db.pgns())
    with pytest.raises(KeyError):
        db.pgn_info("noSuchPgn")


def test_bit_lookup(db):
    name = next(
        f.lookup_bit_enumeration
        for p in db.pgns()
        for f in p.fields
        if f.lookup_bit_enumeration
    )
    assert db.bit_lookup(name)
    with pytest.raises(KeyError):
        db.bit_lookup("NO_SUCH_LOOKUP")


def test_reassembly(db):
    payload = db.encode("gnssPositionData", {"latitude": 52.1, "longitude": 4.3})
    frames = [bytes([0x20, len(payload)]) + payload[:6]]
    for i, start in enumerate(range(6, len(payload), 7), start=1):
        frames.append(
            (bytes([0x20 | i]) + payload[start : start + 7]).ljust(8, b"\xff")
        )
    reassembler = canboat.Reassembler()
    results = [reassembler.push(129029, f, src=12) for f in frames]
    assert results[:-1] == [None] * (len(frames) - 1)
    assert results[-1] == payload
    # A single-frame PGN passes straight through.
    assert reassembler.push(130306, b"\xff" * 8) == b"\xff" * 8


def test_message_codec_reports_unknown_pgns():
    codec = canboat.MessageCodec(lambda _id: None, object, object)
    with pytest.raises(canboat.DecodeError):
        codec.decode(1, b"\x00")


def test_can_framing():
    payload = bytes(range(19))  # 6 + 7 + 6 bytes: the last frame needs padding
    frames = canboat.fast_packet_fragment(5, payload)
    assert [len(f) for f in frames] == [8, 8, 8]
    assert frames[0][:2] == bytes([5 << 5, 19])
    assert frames[-1].endswith(b"\xff")  # the last frame is padded
    reassembler = canboat.Reassembler()
    assert [reassembler.push(129029, f) for f in frames][-1] == payload
    can_id = canboat.can_id_compose(2, 130306, 7, 255)
    assert can_id == 0x09FD0207
    assert canboat.can_id_decompose(can_id) == (2, 130306, 7, 255)
    # PDU1: the destination rides in the identifier
    assert canboat.can_id_decompose(canboat.can_id_compose(6, 59904, 7, 42)) == (
        6,
        59904,
        7,
        42,
    )
    with pytest.raises(canboat.EncodeError):
        canboat.fast_packet_fragment(0, bytes(224))


def test_message_codec_refuses_unknown_definitions():
    codec = canboat.MessageCodec(lambda _id: None, object, object)

    message = SimpleNamespace(
        PGN=1, id="noSuchPgn", fields=[], source=0, destination=0, priority=0
    )
    with pytest.raises(ValueError, match="No encoding function found"):
        codec.encode(message)
    with pytest.raises(ValueError, match="units"):
        canboat.MessageCodec(lambda _id: None, object, object, "imperial")  # pyright: ignore[reportArgumentType]
