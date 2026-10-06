# pylint: disable=missing-function-docstring,redefined-outer-name
"""Gateway clients built on canboat's codecs, against simulated devices."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from typing import Self

import pytest

from nmea2000 import (
    IkonvertNmea2000Gateway,
    MaretronIpgNmea2000Gateway,
    Ngt1Nmea2000Gateway,
    NMEA2000Message,
)
from nmea2000 import ioclient as ioclient_module

WIND = bytes.fromhex("ff0b02983afaffff")  # 5.23 m/s, 1.5 rad, apparent
TIMEOUT = 5


class Device:
    """A simulated gateway: a local TCP server the client talks to."""

    def __init__(self, script):
        self.script = script
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.done = asyncio.Event()
        self.error: BaseException | None = None

    async def __aenter__(self) -> Self:
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    async def _serve(self, reader, writer):
        try:
            await self.script(reader, writer)
        except BaseException as error:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self.error = error
        finally:
            self.done.set()
            with contextlib.suppress(Exception):
                await reader.read()  # until the client goes away
            writer.close()


@pytest.fixture
def serial_to_tcp(monkeypatch):
    """Point the serial gateways at a TCP port instead of a serial port."""

    def use(port: int) -> None:
        async def open_serial_connection(url, baudrate):
            del url, baudrate
            return await asyncio.open_connection("127.0.0.1", port)

        monkeypatch.setattr(
            ioclient_module.serial_asyncio,
            "open_serial_connection",
            open_serial_connection,
        )

    return use


async def run_client(client, device: Device) -> NMEA2000Message:
    received: asyncio.Queue[NMEA2000Message] = asyncio.Queue()

    async def on_message(message: NMEA2000Message) -> None:
        await received.put(message)

    client.set_receive_callback(on_message)
    await client.connect()
    try:
        message = await asyncio.wait_for(received.get(), TIMEOUT)
        await asyncio.wait_for(device.done.wait(), TIMEOUT)
    finally:
        await client.close()
    if device.error is not None:
        raise device.error
    return message


def assert_wind(message: NMEA2000Message, src: int) -> None:
    assert message.PGN == 130306
    assert message.source == src
    assert message.get_field_by_id("windSpeed").value == 5.23
    assert message.get_field_by_id("reference").value == "Apparent"


# ─────────────────────────────── NGT-1 ───────────────────────────────


def ngt_message(command: int, payload: bytes) -> bytes:
    body = bytes([command, len(payload)]) + payload
    body += bytes([-sum(body) & 0xFF])
    return b"\x10\x02" + body.replace(b"\x10", b"\x10\x10") + b"\x10\x03"


def ngt_received(prio: int, pgn: int, src: int, dst: int, data: bytes) -> bytes:
    header = (
        bytes([prio])
        + pgn.to_bytes(3, "little")
        + bytes([dst, src])
        + bytes(4)
        + bytes([len(data)])
    )
    return ngt_message(0x93, header + data)


@pytest.mark.asyncio
async def test_ngt1(serial_to_tcp):
    async def ngt1(reader, writer):
        startup = await reader.readexactly(len(ngt_message(0xA1, b"\x11\x02\x00")))
        assert startup == ngt_message(0xA1, b"\x11\x02\x00")
        writer.write(ngt_received(2, 130306, 35, 255, WIND))
        await writer.drain()

    async with Device(ngt1) as device:
        serial_to_tcp(device.port)
        message = await run_client(Ngt1Nmea2000Gateway("/dev/ttyUSB0"), device)
    assert_wind(message, src=35)


@pytest.mark.asyncio
async def test_ngt1_sends_n2k_msg_send(serial_to_tcp):
    sent: asyncio.Queue[bytes] = asyncio.Queue()

    async def ngt1(reader, writer):
        await reader.readexactly(len(ngt_message(0xA1, b"\x11\x02\x00")))
        writer.write(ngt_received(2, 130306, 35, 255, WIND))
        await writer.drain()
        await sent.put(await reader.readuntil(b"\x10\x03"))

    async with Device(ngt1) as device:
        serial_to_tcp(device.port)
        client = Ngt1Nmea2000Gateway("/dev/ttyUSB0")
        message = await run_client_and_send(client, device)
        frame = await asyncio.wait_for(sent.get(), TIMEOUT)
    assert_wind(message, src=35)
    assert frame.startswith(b"\x10\x02\x94")  # N2K_MSG_SEND
    assert WIND in frame.replace(b"\x10\x10", b"\x10")


async def run_client_and_send(client, device: Device) -> NMEA2000Message:
    """Receive one message, then send it back to the device."""
    received: asyncio.Queue[NMEA2000Message] = asyncio.Queue()

    async def on_message(message: NMEA2000Message) -> None:
        await received.put(message)

    client.set_receive_callback(on_message)
    await client.connect()
    try:
        message = await asyncio.wait_for(received.get(), TIMEOUT)
        await client.send(message)
        await asyncio.wait_for(device.done.wait(), TIMEOUT)
    finally:
        await client.close()
    if device.error is not None:
        raise device.error
    return message


# ─────────────────────────────── iKonvert ───────────────────────────────


@pytest.mark.asyncio
async def test_ikonvert_handshake_then_frames(serial_to_tcp):
    async def ikonvert(reader, writer):
        async def expect(line: bytes) -> None:
            assert await reader.readline() == line

        await expect(b"$PDGY,N2NET_OFFLINE\r\n")
        writer.write(
            b"$PDGY,TEXT,Digital_Yacht_iKonvert_v2\r\n"
        )  # its "ACK" to going offline
        await expect(b"$PDGY,N2NET_RESET\r\n")
        writer.write(b"$PDGY,ACK,N2NET_RESET\r\n")
        await expect(b"$PDGY,N2NET_INIT,ALL\r\n")
        writer.write(b"$PDGY,ACK,N2NET_INIT\r\n")
        writer.write(b"!PDGY,130306,2,17,255,0.563," + base64.b64encode(WIND) + b"\r\n")
        await writer.drain()

    async with Device(ikonvert) as device:
        serial_to_tcp(device.port)
        message = await run_client(IkonvertNmea2000Gateway("/dev/ttyUSB0"), device)
    assert_wind(message, src=17)


# ─────────────────────────────── Maretron IPG ───────────────────────────────


@pytest.mark.asyncio
async def test_maretron_login_then_binary_frames():
    async def ipg(reader, writer):
        assert await reader.readuntil(b"\0") == b'CONNECT\t"secret"\t\tMOBILE\0'
        writer.write(b"CONNECTED\t1234567\0")
        await writer.drain()
        assert await reader.readuntil(b"\0") == b"SET_MODE\tBINARY\0"
        pgn, prio, src = 130306, 2, 23
        flags = 0x80 | (prio << 4) | (1 << 1) | ((pgn >> 16) & 1)  # single frame
        writer.write(
            bytes([0xA5, flags, (pgn >> 8) & 0xFF, pgn & 0xFF, src, len(WIND)]) + WIND
        )
        await writer.drain()

    async with Device(ipg) as device:
        client = MaretronIpgNmea2000Gateway("127.0.0.1", device.port, password="secret")
        message = await run_client(client, device)
    assert_wind(message, src=23)
