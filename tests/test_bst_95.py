"""Tests for BST 95 format support (Actisense PRO-NDC-1E2K, CAN Actisense mode).

Test data captured from a real PRO-NDC-1E2K device (GitHub issue #46).
"""

import pytest

from nmea2000.encoder import NMEA2000Encoder
from nmea2000.encoder_formats import _compute_bst_checksum
from nmea2000.input_formats import N2KFormat, detect_format
from nmea2000.ioclient import bdtp_wrap, bdtp_unwrap
from nmea2000.message import NMEA2000Message

from .test_decoder import _get_decoder


# --- Real captured packets from PRO-NDC-1E2K ---

# PGN 127250 Vessel Heading (single frame, PDU2)
BST_95_HEADING = bytes.fromhex("950e7d062412f10958f5d000009c09fdeb")

# PGN 129025 Position Rapid Update (single frame, PDU2)
BST_95_POSITION = bytes.fromhex("950e8a060701f809dd87d5174a09d6b596")

# PGN 127257 Attitude (single frame, PDU2)
BST_95_ATTITUDE = bytes.fromhex("950eba060719f10dff95e6d501f0ffff41")

# PGN 59392 ISO Acknowledgement (single frame, PDU1 with dest=5)
BST_95_PDU1 = bytes.fromhex("950e300c2305e81801ffffffff09fd01f5")

# PGN 129029 GNSS Position Data (fast-packet, 7 frames)
BST_95_GNSS_FAST_PACKET = [
    bytes.fromhex("950ec4062305f80d002ba95950e01402f3"),
    bytes.fromhex("950ec9062305f80d01310050f0c4d79fb5"),
    bytes.fromhex("950ecb062305f80d028c0500ea78f67ff5"),
    bytes.fromhex("950ed0062305f80d037cbbeec0304600fc"),
    bytes.fromhex("950ed3062305f80d040000000023fc092b"),
    bytes.fromhex("950ed6062305f80d055a00b4004ef3ff01"),
    bytes.fromhex("950ed9062305f80d06ff00ffffffffff51"),
]

# SDK example: PGN 129026 COG & SOG Rapid Update (checksum added, not in original doc)
BST_95_SDK_EXAMPLE = bytes.fromhex("950e01203002f809fffc370a0010ffffbf")


class TestBst95FormatDetection:
    def test_detect_bst_95(self):
        assert detect_format(BST_95_HEADING) == N2KFormat.BST_95

    def test_detect_bst_95_pdu1(self):
        assert detect_format(BST_95_PDU1) == N2KFormat.BST_95

    def test_no_false_positive_on_bst_d0(self):
        """BST D0 packets must not be detected as BST 95."""
        bst_d0 = bytes.fromhex("d01500ff0900ff1c00000000003f9fdcffffffffff43")
        assert detect_format(bst_d0) == N2KFormat.BST_D0


class TestBst95Decoder:
    def test_decode_vessel_heading(self):
        decoder = _get_decoder()
        msg = decoder.decode(BST_95_HEADING)
        assert msg is not None
        assert msg.PGN == 127250
        assert msg.id == "vesselHeading"
        assert msg.source == 36
        assert msg.priority == 2
        assert msg.destination == 255

    def test_decode_position_rapid_update(self):
        decoder = _get_decoder()
        msg = decoder.decode(BST_95_POSITION)
        assert msg is not None
        assert msg.PGN == 129025
        assert msg.id == "positionRapidUpdate"
        assert msg.source == 7

    def test_decode_attitude(self):
        decoder = _get_decoder()
        msg = decoder.decode(BST_95_ATTITUDE)
        assert msg is not None
        assert msg.PGN == 127257
        assert msg.id == "attitude"
        assert msg.source == 7
        assert msg.priority == 3

    def test_decode_pdu1_iso_ack(self):
        """PDU1 message: destination is in PDUS field, not part of PGN."""
        decoder = _get_decoder()
        msg = decoder.decode(BST_95_PDU1)
        assert msg is not None
        assert msg.PGN == 59392
        assert msg.id == "isoAcknowledgement"
        assert msg.source == 35
        assert msg.destination == 5

    def test_decode_fast_packet_gnss(self):
        """Fast-packet PGN 129029 spanning 7 CAN frames."""
        decoder = _get_decoder()
        msg = None
        for frame in BST_95_GNSS_FAST_PACKET:
            msg = decoder.decode(frame)
        assert msg is not None
        assert msg.PGN == 129029
        assert msg.id == "gnssPositionData"
        assert msg.source == 35
        assert len(msg.fields) > 0

    def test_bad_checksum(self):
        bad_packet = bytearray(BST_95_HEADING)
        bad_packet[-1] ^= 0xFF
        decoder = _get_decoder()
        with pytest.raises(ValueError, match="checksum"):
            decoder.decode(bytes(bad_packet))

    def test_bad_length(self):
        bad = bytearray(BST_95_HEADING)
        bad[1] = 0x02  # wrong length
        decoder = _get_decoder()
        with pytest.raises(ValueError):
            decoder.decode(bytes(bad))

    def test_decode_sdk_example(self):
        """The example from the Actisense SDK docs should decode as COG & SOG."""
        decoder = _get_decoder()
        msg = decoder.decode(BST_95_SDK_EXAMPLE)
        assert msg is not None
        assert msg.PGN == 129026
        assert msg.id == "cogSogRapidUpdate"
        assert msg.source == 0x30
        assert msg.priority == 2


class TestBst95Encoder:
    def test_roundtrip_single_frame(self):
        """Decode a BST 95 packet, re-encode, and verify the result decodes identically."""
        decoder = _get_decoder()
        original = decoder.decode(BST_95_HEADING)
        assert original is not None

        encoder = NMEA2000Encoder(output_format=N2KFormat.BST_95)
        packets = encoder.encode(original)
        assert len(packets) == 1

        packet = packets[0]
        assert packet[0] == 0x95
        assert sum(packet) & 0xFF == 0, "Checksum must be zero-sum"

        re_decoded = decoder.decode(packet)
        assert re_decoded is not None
        assert re_decoded.PGN == original.PGN
        assert re_decoded.source == original.source
        assert re_decoded.priority == original.priority

    def test_encode_fast_packet_produces_multiple_frames(self):
        """Fast-packet PGN should produce multiple BST 95 frames."""
        decoder = _get_decoder()
        msg = None
        for frame in BST_95_GNSS_FAST_PACKET:
            msg = decoder.decode(frame)
        assert msg is not None

        encoder = NMEA2000Encoder(output_format=N2KFormat.BST_95)
        packets = encoder.encode(msg)
        assert len(packets) > 1
        for pkt in packets:
            assert pkt[0] == 0x95
            assert sum(pkt) & 0xFF == 0

    def test_checksum_helper(self):
        data = bytes([0x95, 0x0E, 0x00])
        cs = _compute_bst_checksum(data)
        assert (sum(data) + cs) % 256 == 0


class TestBst95BdtpRoundtrip:
    def test_wrap_unwrap_bst_95(self):
        """A BST 95 packet survives BDTP wrap/unwrap."""
        wrapped = bdtp_wrap(BST_95_HEADING)
        payload, consumed = bdtp_unwrap(bytearray(wrapped))
        assert payload == BST_95_HEADING

    def test_multiple_frames_in_stream(self):
        """Multiple BDTP-wrapped BST 95 frames in a stream."""
        stream = bytearray()
        for frame in BST_95_GNSS_FAST_PACKET:
            stream.extend(bdtp_wrap(frame))

        payloads = []
        buf = bytearray(stream)
        while len(buf) > 0:
            payload, consumed = bdtp_unwrap(buf)
            if payload is None:
                buf = buf[consumed:]
                break
            buf = buf[consumed:]
            if payload:
                payloads.append(payload)

        assert len(payloads) == len(BST_95_GNSS_FAST_PACKET)
        for original, recovered in zip(BST_95_GNSS_FAST_PACKET, payloads):
            assert recovered == original
