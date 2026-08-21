from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import cast

import can
import can.message
import pytest

from nmea2000.device import N2KDevice
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.input_formats import N2KFormat
from nmea2000.ioclient import AsyncIOClient, PythonCanAsyncIOClient, State
from nmea2000.message import NMEA2000Message


def _build_message() -> NMEA2000Message:
    return NMEA2000Message(
        PGN=127250,
        id="vesselHeading",
        source=10,
        destination=255,
        priority=2,
        timestamp=datetime.now(),
        fields=[],
    )


class FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.drain_calls = 0
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        self.drain_calls += 1

    def close(self) -> None:
        self.closed = True


class RecordingClient(AsyncIOClient):
    def __init__(self, encoded_messages: list[bytes]) -> None:
        super().__init__(
            exclude_pgns=[],
            include_pgns=[],
            exclude_manufacturer_code=[],
            include_manufacturer_code=[],
            preferred_units={},
            dump_to_file=None,
            dump_pgns=[],
            build_network_map=False,
            seed_network_map=False,
        )
        self.encoded_messages = encoded_messages

    async def _connect_impl(self) -> None:
        return

    async def _receive_impl(self) -> None:
        return

    def _encode_impl(self, nmea2000Message: NMEA2000Message) -> list[bytes]:
        return self.encoded_messages


class PythonCanSendClient(PythonCanAsyncIOClient):
    def __init__(self, encoded_message: can.message.Message, **kwargs) -> None:
        super().__init__("virtual", "test-python-can-send", **kwargs)
        self.encoded_message = encoded_message

    def _encode_impl(
        self, nmea2000Message: NMEA2000Message
    ) -> list[can.message.Message]:
        return [self.encoded_message]


class FakeBus:
    def __init__(self) -> None:
        self.sent_messages: list[can.message.Message] = []
        self.timeouts: list[float | None] = []
        self.shutdown_called = False

    def send(self, message: can.message.Message, timeout: float | None = None) -> None:
        self.timeouts.append(timeout)
        self.sent_messages.append(message)

    def shutdown(self) -> None:
        self.shutdown_called = True


class FlakyBus(FakeBus):
    def __init__(
        self, failures_before_success: int, error: can.CanOperationError
    ) -> None:
        super().__init__()
        self.failures_before_success = failures_before_success
        self.error = error

    def send(self, message: can.message.Message, timeout: float | None = None) -> None:
        self.timeouts.append(timeout)
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise self.error
        self.sent_messages.append(message)


@pytest.mark.asyncio
async def test_seed_network_map_parses_timestamp_for_python_can(monkeypatch) -> None:
    client = RecordingClient([])
    seeded_pgns: list[int | float | str | bytes | None] = []
    seeded_timestamps: list[datetime] = []
    encoded_messages: list[can.message.Message] = []
    encoder = NMEA2000Encoder(N2KFormat.PYTHON_CAN)

    async def no_sleep(_delay: float) -> None:
        return

    async def record_message(message: NMEA2000Message) -> None:
        seeded_pgns.append(message.fields[0].value)
        seeded_timestamps.append(message.timestamp)
        encoded_messages.extend(encoder.encode(message))

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setattr(client, "send", record_message)

    try:
        await client._seed_network_map()
    finally:
        await client.close()

    assert seeded_pgns == [60928, 126996, 126998]
    assert all(isinstance(timestamp, datetime) for timestamp in seeded_timestamps)
    assert all(isinstance(message.timestamp, float) for message in encoded_messages)
    assert all(str(message) for message in encoded_messages)


@pytest.mark.asyncio
async def test_asyncio_client_send_uses_default_stream_send_impl() -> None:
    client = RecordingClient([b"\x01\x02", b"\x03\x04"])
    writer = FakeWriter()
    client.writer = cast(asyncio.StreamWriter, writer)

    try:
        await client.send(_build_message())
    finally:
        await client.close()

    assert writer.writes == [b"\x01\x02", b"\x03\x04"]
    assert writer.drain_calls == 2
    assert writer.closed is True


@pytest.mark.asyncio
async def test_python_can_client_send_uses_bus_instead_of_writer() -> None:
    encoded_message = can.message.Message(
        arbitration_id=0x19F1120A,
        is_extended_id=True,
        data=b"\x01\x02\x03\x04",
    )
    client = PythonCanSendClient(encoded_message)
    bus = FakeBus()
    client.bus = bus

    try:
        await client.send(_build_message())
    finally:
        await client.close()

    assert bus.sent_messages == [encoded_message]
    assert bus.shutdown_called is True
    assert bus.timeouts == [0.1]


@pytest.mark.asyncio
async def test_python_can_client_retries_transient_buffer_pressure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    encoded_message = can.message.Message(
        arbitration_id=0x19F1120A,
        is_extended_id=True,
        data=b"\x01\x02\x03\x04",
    )
    client = PythonCanSendClient(
        encoded_message,
        send_timeout=0.2,
        send_retry_count=2,
        send_retry_delay=0,
    )
    bus = FlakyBus(
        failures_before_success=2,
        error=can.CanOperationError(
            "Failed to transmit: No buffer space available", 105
        ),
    )
    client.bus = bus
    caplog.set_level(logging.DEBUG, logger=client.logger.name)

    try:
        await client.send(_build_message())
    finally:
        await client.close()

    assert bus.sent_messages == [encoded_message]
    assert bus.timeouts == [0.2, 0.2, 0.2]
    retry_records = [
        record
        for record in caplog.records
        if "python-can transmit queue full" in record.getMessage()
    ]
    assert [record.levelno for record in retry_records] == [logging.DEBUG] * 2
    assert all(record.exc_info is None for record in retry_records)


@pytest.mark.asyncio
async def test_python_can_client_raises_persistent_buffer_pressure_without_reconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    encoded_message = can.message.Message(
        arbitration_id=0x19F1120A,
        is_extended_id=True,
        data=b"\x01\x02\x03\x04",
    )
    client = PythonCanSendClient(
        encoded_message,
        send_timeout=0.05,
        send_retry_count=1,
        send_retry_delay=0,
    )
    bus = FlakyBus(
        failures_before_success=10,
        error=can.CanOperationError("Transmit buffer full"),
    )
    client.bus = bus
    client._state = State.CONNECTED
    caplog.set_level(logging.DEBUG, logger=client.logger.name)

    try:
        with pytest.raises(can.CanOperationError):
            await client.send(_build_message())
        assert client.state == State.CONNECTED
    finally:
        await client.close()

    assert client.state == State.CLOSED
    assert bus.timeouts == [0.05, 0.05]
    failure_records = [
        record
        for record in caplog.records
        if "Send failed without reconnecting" in record.getMessage()
    ]
    assert [record.levelno for record in failure_records] == [logging.WARNING]
    assert failure_records[0].exc_info is not None


@pytest.mark.asyncio
async def test_python_can_device_becomes_ready_on_virtual_bus(tmp_path) -> None:
    device = N2KDevice.for_python_can(
        "virtual",
        "test-python-can-ready",
        persistence_path=tmp_path / "python-can-device.json",
        address_claim_startup_delay=0,
        address_claim_detection_time=0.01,
        heartbeat_interval=3600,
    )

    try:
        await device.start()
        await device.wait_ready(timeout=1)
        assert device.ready is True
    finally:
        await device.close()

    assert device.ready is False
