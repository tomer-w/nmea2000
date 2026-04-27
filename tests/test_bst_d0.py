"""Tests for BST D0 format support (Actisense PRO-NDC-1E2K)."""

from pathlib import Path

import pytest

from nmea2000.encoder import NMEA2000Encoder
from nmea2000.encoder_formats import _compute_bst_checksum
from nmea2000.input_formats import N2KFormat, detect_format
from nmea2000.ioclient import bdtp_wrap, bdtp_unwrap
from nmea2000.message import NMEA2000Message

from .test_decoder import _get_decoder


# PGN 65280 (Furuno Heave), PDU2: PDUF=0xFF, PDUS=0x00, priority=7, src=9, dst=255
BST_D0_PACKET = bytes.fromhex("d01500ff0900ff1c00000000003f9fdcffffffffff43")

# PGN 59904 (ISO Request), PDU1: PDUF=0xEA, PDUS=31 (dest), priority=6, src=1, dst=31
BST_D0_PDU1_PACKET = bytes.fromhex("d010001f011fea18000000000000ee00f1")

_FAST_PACKET_FIXTURE = Path(__file__).with_name("recombine-frames-1.in")


def _load_fast_packet_message() -> NMEA2000Message:
    decoder = _get_decoder()
    with _FAST_PACKET_FIXTURE.open("r", encoding="utf-8") as fixture:
        for line in fixture:
            input_data = line.strip()
            if input_data.startswith("#") or len(input_data) <= 1:
                continue
            msg = decoder.decode(input_data)
            if isinstance(msg, NMEA2000Message) and msg.PGN == 129029:
                return msg
    raise AssertionError("Failed to decode fast-packet fixture message")


# --- Format detection ---


class TestBstD0FormatDetection:
    def test_detect_bst_d0(self):
        assert detect_format(BST_D0_PACKET) == N2KFormat.BST_D0

    def test_detect_bst_d0_pdu1(self):
        assert detect_format(BST_D0_PDU1_PACKET) == N2KFormat.BST_D0

    def test_existing_formats_unaffected(self):
        """USB and TCP detection must still work."""
        tcp_packet = bytes.fromhex("881cff00093f9fdcffffffffff")
        usb_packet = bytes.fromhex("aa550102010900ff1c083f9fdcffffffffff00e5")
        assert detect_format(tcp_packet) == N2KFormat.EBYTE
        assert detect_format(usb_packet) == N2KFormat.WAVESHARE


# --- Decoder ---


class TestBstD0Decoder:
    def test_decode_pdu2_pgn_65280(self):
        decoder = _get_decoder()
        msg = decoder.decode(BST_D0_PACKET)
        assert isinstance(msg, NMEA2000Message)
        assert msg.PGN == 65280
        assert msg.source == 9
        assert msg.destination == 255
        assert msg.priority == 7

    def test_decode_pdu1_pgn_59904(self):
        decoder = _get_decoder()
        msg = decoder.decode(BST_D0_PDU1_PACKET)
        assert isinstance(msg, NMEA2000Message)
        assert msg.PGN == 59904
        assert msg.source == 1
        assert msg.destination == 31
        assert msg.priority == 6

    def test_reject_bad_checksum(self):
        bad_packet = bytearray(BST_D0_PACKET)
        bad_packet[-1] ^= 0xFF  # corrupt checksum
        with pytest.raises(ValueError, match="checksum"):
            _get_decoder().decode(bytes(bad_packet))

    def test_reject_too_short(self):
        with pytest.raises(ValueError):
            _get_decoder().decode(b"\xd0\x0d\x00")

    def test_reject_wrong_id(self):
        bad = bytearray(BST_D0_PACKET)
        bad[0] = 0xAA
        with pytest.raises(ValueError, match="Parser not found"):
            _get_decoder().decode(bytes(bad))


# --- Encoder ---


class TestBstD0Encoder:
    def test_encode_roundtrip_single_frame(self):
        """Decode a BST D0 packet, re-encode, and verify the result decodes identically."""
        decoder = _get_decoder()
        original = decoder.decode(BST_D0_PACKET)
        assert isinstance(original, NMEA2000Message)

        encoder = NMEA2000Encoder(output_format=N2KFormat.BST_D0)
        encoded = encoder.encode(original)
        assert isinstance(encoded, list) and len(encoded) == 1
        packet = encoded[0]
        assert isinstance(packet, bytes)
        assert packet[0] == 0xD0
        # Checksum must be valid
        assert sum(packet) & 0xFF == 0

        redecoded = _get_decoder().decode(packet)
        assert isinstance(redecoded, NMEA2000Message)
        assert redecoded.PGN == original.PGN
        assert redecoded.source == original.source
        assert redecoded.destination == original.destination
        assert redecoded.priority == original.priority

    def test_encode_fast_packet_combined(self):
        """BST D0 sends pre-assembled payloads, so fast packets encode as one message."""
        original = _load_fast_packet_message()
        encoder = NMEA2000Encoder(output_format=N2KFormat.BST_D0)
        encoded = encoder.encode(original)
        assert isinstance(encoded, list) and len(encoded) == 1
        packet = encoded[0]
        assert isinstance(packet, bytes)
        assert sum(packet) & 0xFF == 0

        redecoded = _get_decoder().decode(packet)
        assert isinstance(redecoded, NMEA2000Message)
        assert redecoded.PGN == original.PGN

    def test_checksum_helper(self):
        data = bytes([0xD0, 0x15, 0x00])
        cs = _compute_bst_checksum(data)
        assert (sum(data) + cs) & 0xFF == 0


# --- BDTP framing ---


class TestBdtpFraming:
    def test_wrap_simple(self):
        data = bytes([0x01, 0x02, 0x03])
        wrapped = bdtp_wrap(data)
        assert wrapped == bytes([0x10, 0x02, 0x01, 0x02, 0x03, 0x10, 0x03])

    def test_wrap_escapes_dle(self):
        data = bytes([0x10, 0xAA])
        wrapped = bdtp_wrap(data)
        assert wrapped == bytes([0x10, 0x02, 0x10, 0x10, 0xAA, 0x10, 0x03])

    def test_unwrap_simple(self):
        buf = bytearray([0x10, 0x02, 0x01, 0x02, 0x03, 0x10, 0x03])
        payload, consumed = bdtp_unwrap(buf)
        assert payload == bytes([0x01, 0x02, 0x03])
        assert consumed == 7

    def test_unwrap_with_escaped_dle(self):
        buf = bytearray([0x10, 0x02, 0x10, 0x10, 0xAA, 0x10, 0x03])
        payload, consumed = bdtp_unwrap(buf)
        assert payload == bytes([0x10, 0xAA])
        assert consumed == 7

    def test_unwrap_incomplete(self):
        buf = bytearray([0x10, 0x02, 0x01, 0x02])
        payload, consumed = bdtp_unwrap(buf)
        assert payload is None

    def test_unwrap_no_frame(self):
        buf = bytearray([0x01, 0x02, 0x03])
        payload, consumed = bdtp_unwrap(buf)
        assert payload is None

    def test_unwrap_leading_garbage(self):
        buf = bytearray([0xFF, 0xAA, 0x10, 0x02, 0x42, 0x10, 0x03])
        payload, consumed = bdtp_unwrap(buf)
        assert payload == bytes([0x42])
        assert consumed == 7

    def test_wrap_unwrap_roundtrip(self):
        original = bytes([0x10, 0x02, 0x03, 0x10, 0xFF, 0x00])
        wrapped = bdtp_wrap(original)
        buf = bytearray(wrapped)
        payload, _ = bdtp_unwrap(buf)
        assert payload == original

    def test_wrap_unwrap_bst_d0_roundtrip(self):
        """A BST D0 packet survives BDTP wrap/unwrap."""
        wrapped = bdtp_wrap(BST_D0_PACKET)
        buf = bytearray(wrapped)
        payload, _ = bdtp_unwrap(buf)
        assert payload == BST_D0_PACKET

    def test_unwrap_multiple_frames(self):
        """Multiple BDTP frames in one buffer."""
        frame1 = bdtp_wrap(b"\x01")
        frame2 = bdtp_wrap(b"\x02")
        buf = bytearray(frame1 + frame2)

        p1, c1 = bdtp_unwrap(buf)
        assert p1 == b"\x01"
        buf = buf[c1:]

        p2, c2 = bdtp_unwrap(buf)
        assert p2 == b"\x02"
