import asyncio
import logging
from typing import List

import pytest

from nmea2000.ioclient import WaveShareNmea2000Gateway
from nmea2000.message import NMEA2000Message

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class MockSerialReader:
    """Mock serial reader that yields pre-loaded data chunks."""

    def __init__(self, chunks: List[bytes]):
        self._chunks = list(chunks)

    async def read(self, n: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        # Block forever once data is exhausted (simulates waiting for more data)
        await asyncio.Future()


def _create_gateway() -> WaveShareNmea2000Gateway:
    """Create a WaveShareNmea2000Gateway with internal state ready for testing."""
    gw = WaveShareNmea2000Gateway.__new__(WaveShareNmea2000Gateway)
    # Initialize only what _receive_impl needs
    from nmea2000.decoder import NMEA2000Decoder
    gw.decoder = NMEA2000Decoder(
        exclude_pgns=[], include_pgns=[],
        exclude_manufacturer_code=[], include_manufacturer_code=[],
        preferred_units={}, dump_to_file=None, dump_pgns=[],
        build_network_map=False,
    )
    gw.queue = asyncio.Queue()
    gw._buffer = bytearray()
    gw.logger = logging.getLogger("test_waveshare")
    return gw


# Known valid packet: PGN 65280 (Furuno Heave), source=9, priority=7
VALID_PACKET_HEX = "aa550102010900ff1c083f9fdcffffffffff00e5"
VALID_PACKET = bytes.fromhex(VALID_PACKET_HEX)


@pytest.mark.asyncio
async def test_single_valid_packet():
    """A single valid 20-byte packet should be decoded and queued."""
    gw = _create_gateway()
    gw.reader = MockSerialReader([VALID_PACKET])

    await gw._receive_impl()

    assert gw.queue.qsize() == 1
    msg = await gw.queue.get()
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 65280


@pytest.mark.asyncio
async def test_multiple_valid_packets():
    """Multiple concatenated valid packets should all be decoded."""
    gw = _create_gateway()
    gw.reader = MockSerialReader([VALID_PACKET * 3])

    await gw._receive_impl()

    assert gw.queue.qsize() == 3


@pytest.mark.asyncio
async def test_garbage_before_valid_packet():
    """Garbage bytes before a valid packet should be skipped."""
    gw = _create_gateway()
    garbage = bytes([0x00, 0x11, 0x22, 0x33, 0x44])
    gw.reader = MockSerialReader([garbage + VALID_PACKET])

    await gw._receive_impl()

    assert gw.queue.qsize() == 1
    msg = await gw.queue.get()
    assert msg.PGN == 65280


@pytest.mark.asyncio
async def test_resync_after_checksum_failure():
    """When a false aa55 causes a checksum failure, the gateway should
    resync and find the real packet that follows."""
    gw = _create_gateway()
    # Simulate: 8 bytes ending in aa55 (false start) + valid 20-byte packet.
    # The first aa55 at offset 0 grabs 20 bytes that span both chunks → checksum fails.
    # After resync (advance 2), the real aa55 at offset 8 is found.
    false_start = bytes.fromhex("aa550102ffff003e")  # 8 bytes with aa55 header
    gw.reader = MockSerialReader([false_start + VALID_PACKET])

    await gw._receive_impl()

    assert gw.queue.qsize() == 1
    msg = await gw.queue.get()
    assert msg.PGN == 65280


@pytest.mark.asyncio
async def test_resync_with_issue_13_packet():
    """Reproduce the exact scenario from issue #13: a misaligned 'packet'
    that contains aa55 at offset 0 AND offset 8 (two partial real packets
    spliced together). After resync the valid packet that follows should
    be decoded."""
    gw = _create_gateway()
    # This is one of the corrupted packets from issue #13
    corrupted = bytes.fromhex("aa550102ffff003eaa550102012412f2190861ff")
    gw.reader = MockSerialReader([corrupted + VALID_PACKET])

    await gw._receive_impl()

    # The corrupted packet fails checksum; after resyncing past embedded
    # aa55 markers the gateway should eventually reach the valid packet.
    assert gw.queue.qsize() == 1
    msg = await gw.queue.get()
    assert msg.PGN == 65280


@pytest.mark.asyncio
async def test_resync_does_not_lose_following_valid_packets():
    """After a corrupted packet, multiple subsequent valid packets should
    all be decoded (no cascading misalignment)."""
    gw = _create_gateway()
    corrupted = bytes.fromhex("aa550102ffff003eaa550102012412f2190861ff")
    gw.reader = MockSerialReader([corrupted + VALID_PACKET * 3])

    await gw._receive_impl()

    assert gw.queue.qsize() == 3


@pytest.mark.asyncio
async def test_buffer_accumulation_across_reads():
    """A valid packet split across two reads should still be decoded."""
    gw = _create_gateway()
    first_half = VALID_PACKET[:10]
    second_half = VALID_PACKET[10:]
    gw.reader = MockSerialReader([first_half, second_half])

    # First read: not enough data for a full packet
    await gw._receive_impl()
    assert gw.queue.qsize() == 0

    # Second read: completes the packet
    await gw._receive_impl()
    assert gw.queue.qsize() == 1


@pytest.mark.asyncio
async def test_only_corrupted_packets():
    """When only corrupted data is received, nothing should be queued
    and the buffer should not grow unbounded."""
    gw = _create_gateway()
    # Two corrupted packets with no valid data following
    corrupted = bytes.fromhex("aa550102ffff003eaa550102012412f2190861ff")
    gw.reader = MockSerialReader([corrupted * 2])

    await gw._receive_impl()

    assert gw.queue.qsize() == 0
    # Buffer should only contain leftover bytes that couldn't form a packet
    assert len(gw._buffer) < 20
