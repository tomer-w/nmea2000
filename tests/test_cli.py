import asyncio
import json
import logging
import subprocess
import sys
import os

import pytest
from nmea2000.input_formats import N2KFormat
from tests.NMEA2000TestServer import NMEA2000TestServer

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_cli")

CLI_MODULE = [sys.executable, "-m", "nmea2000.cli"]


N2K_ASCII_FRAME = "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF"


class TestCliDecode:
    """Tests for the CLI decode command."""

    def test_decode_frame(self):
        result = subprocess.run(
            [*CLI_MODULE, "decode", "--frame", N2K_ASCII_FRAME],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        output = result.stdout.strip()
        data = json.loads(output)
        assert data["PGN"] == 65280
        assert data["id"] == "furunoHeave"
        assert data["source"] == 9
        assert data["destination"] == 255
        assert data["priority"] == 7

    def test_decode_frame_fields(self):
        result = subprocess.run(
            [*CLI_MODULE, "decode", "--frame", N2K_ASCII_FRAME],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout.strip())
        fields = data["fields"]
        assert len(fields) == 5
        assert fields[0]["id"] == "manufacturerCode"
        assert fields[0]["value"] == "Furuno"

    def test_decode_missing_args(self):
        result = subprocess.run(
            [*CLI_MODULE, "decode"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0 or "Error" in result.stdout

    def test_decode_file(self, tmp_path):
        frame_file = tmp_path / "frames.txt"
        frame_file.write_text(N2K_ASCII_FRAME + "\n")
        result = subprocess.run(
            [*CLI_MODULE, "decode", "--file", str(frame_file)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0


class TestCliEncode:
    """Tests for the CLI encode command."""

    SAMPLE_JSON = '{"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturerCode","name":"Manufacturer Code","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","value":3,"raw_value":3},{"id":"industryCode","name":"Industry Code","value":"Marine Industry","raw_value":4},{"id":"heave","name":"Heave","unit_of_measurement":"m","value":-0.036,"raw_value":-0.036},{"id":"reserved_48","name":"Reserved","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'

    def test_encode_frame(self):
        result = subprocess.run(
            [*CLI_MODULE, "encode", "--frame", self.SAMPLE_JSON],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "09FF7" in result.stdout

    def test_encode_file(self, tmp_path):
        json_file = tmp_path / "message.json"
        json_file.write_text(self.SAMPLE_JSON)
        result = subprocess.run(
            [*CLI_MODULE, "encode", "--file", str(json_file)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "09FF7" in result.stdout

    def test_encode_missing_args(self):
        result = subprocess.run(
            [*CLI_MODULE, "encode"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0 or "Error" in result.stdout


class TestCliTcpClientJson:
    """Tests for the CLI gateway client --json flag using a fake NMEA2000 server."""

    @pytest.fixture
    async def actisense_server(self):
        server = NMEA2000TestServer("127.0.0.1", 18881, N2KFormat.N2K_ASCII_RAW)
        await server.start()
        yield server
        await server.stop()

    @pytest.fixture
    async def ebyte_server(self):
        server = NMEA2000TestServer("127.0.0.1", 18882, N2KFormat.EBYTE)
        await server.start()
        yield server
        await server.stop()

    @pytest.fixture
    async def yacht_devices_server(self):
        server = NMEA2000TestServer("127.0.0.1", 18883, N2KFormat.CAN_FRAME_ASCII)
        await server.start()
        yield server
        await server.stop()

    @pytest.mark.asyncio
    async def test_tcp_client_json_actisense(self, actisense_server):
        """text --json should output valid JSON lines for Actisense."""
        proc = await asyncio.create_subprocess_exec(
            *CLI_MODULE, "text",
            "--server", "127.0.0.1", "--port", "18881",
            "--format", "N2K_ASCII_RAW", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        try:
            # Wait until the server sees a connected client
            for _ in range(20):
                if actisense_server.clients:
                    break
                await asyncio.sleep(0.2)
            assert actisense_server.clients, "CLI client did not connect to server"

            await actisense_server.send_to_clients(
                "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8')
            )

            lines = []
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded.startswith("{"):
                        lines.append(decoded)
                        break
            except asyncio.TimeoutError:
                pass

            assert len(lines) >= 1, "Expected at least one JSON line from --json output"
            data = json.loads(lines[0])
            assert data["PGN"] == 65280
            assert data["id"] == "furunoHeave"
            assert data["source"] == 9
            assert isinstance(data["fields"], list)
            assert len(data["fields"]) > 0
        finally:
            proc.terminate()
            await proc.wait()

    @pytest.mark.asyncio
    async def test_tcp_client_json_ebyte(self, ebyte_server):
        """ebyte --json should output valid JSON for EBYTE gateway."""
        proc = await asyncio.create_subprocess_exec(
            *CLI_MODULE, "ebyte",
            "--server", "127.0.0.1", "--port", "18882",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        try:
            for _ in range(20):
                if ebyte_server.clients:
                    break
                await asyncio.sleep(0.2)
            assert ebyte_server.clients, "CLI client did not connect to server"

            await ebyte_server.send_single_message()

            line = b""
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                    decoded = line.decode().strip()
                    if decoded.startswith("{"):
                        break
            except asyncio.TimeoutError:
                pass

            decoded = line.decode().strip()
            assert decoded.startswith("{"), f"Expected JSON, got: {decoded}"
            data = json.loads(decoded)
            assert data["PGN"] == 127250
            assert isinstance(data["fields"], list)
        finally:
            proc.terminate()
            await proc.wait()

    @pytest.mark.asyncio
    async def test_tcp_client_json_yacht_devices(self, yacht_devices_server):
        """text --json should output valid JSON for Yacht Devices gateway."""
        proc = await asyncio.create_subprocess_exec(
            *CLI_MODULE, "text",
            "--server", "127.0.0.1", "--port", "18883",
            "--format", "CAN_FRAME_ASCII", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        try:
            for _ in range(20):
                if yacht_devices_server.clients:
                    break
                await asyncio.sleep(0.2)
            assert yacht_devices_server.clients, "CLI client did not connect to server"

            await yacht_devices_server.send_to_clients(
                "00:01:54.430 R 15F11910 00 00 00 E5 0B 1D FF FF\r\n".encode('utf-8')
            )

            line = b""
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                    decoded = line.decode().strip()
                    if decoded.startswith("{"):
                        break
            except asyncio.TimeoutError:
                pass

            decoded = line.decode().strip()
            assert decoded.startswith("{"), f"Expected JSON, got: {decoded}"
            data = json.loads(decoded)
            assert data["PGN"] == 127257
            assert data["description"] == "Attitude"
            assert not data["timestamp"].startswith("1900-01-01")
            assert isinstance(data["fields"], list)
        finally:
            proc.terminate()
            await proc.wait()

    @pytest.mark.asyncio
    async def test_tcp_client_no_json_flag(self, actisense_server):
        """Without --json, output should use the default 'Received:' format."""
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = await asyncio.create_subprocess_exec(
            *CLI_MODULE, "text",
            "--server", "127.0.0.1", "--port", "18881",
            "--format", "N2K_ASCII_RAW",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            for _ in range(20):
                if actisense_server.clients:
                    break
                await asyncio.sleep(0.2)
            assert actisense_server.clients, "CLI client did not connect to server"

            await actisense_server.send_to_clients(
                "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8')
            )

            lines = []
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded.startswith("Received:"):
                        lines.append(decoded)
                        break
            except asyncio.TimeoutError:
                pass

            assert len(lines) >= 1, "Expected at least one 'Received:' line"
            assert lines[0].startswith("Received:")
            # Should NOT be valid JSON
            with pytest.raises(json.JSONDecodeError):
                json.loads(lines[0])
        finally:
            proc.terminate()
            await proc.wait()

    @pytest.mark.asyncio
    async def test_tcp_client_json_multiple_messages(self, actisense_server):
        """Multiple messages should each produce a separate JSON line."""
        proc = await asyncio.create_subprocess_exec(
            *CLI_MODULE, "text",
            "--server", "127.0.0.1", "--port", "18881",
            "--format", "N2K_ASCII_RAW", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        try:
            for _ in range(20):
                if actisense_server.clients:
                    break
                await asyncio.sleep(0.2)
            assert actisense_server.clients, "CLI client did not connect to server"

            # Send two messages
            await actisense_server.send_to_clients(
                "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8')
            )
            await asyncio.sleep(0.2)
            await actisense_server.send_to_clients(
                "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8')
            )

            json_lines = []
            try:
                while len(json_lines) < 2:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded.startswith("{"):
                        json_lines.append(decoded)
            except asyncio.TimeoutError:
                pass

            assert len(json_lines) == 2, f"Expected 2 JSON lines, got {len(json_lines)}"
            for jl in json_lines:
                data = json.loads(jl)
                assert data["PGN"] == 65280
        finally:
            proc.terminate()
            await proc.wait()

    @pytest.mark.asyncio
    async def test_tcp_client_json_roundtrip(self, actisense_server):
        """JSON output should be parseable back into NMEA2000Message via from_json."""
        from nmea2000.message import NMEA2000Message

        proc = await asyncio.create_subprocess_exec(
            *CLI_MODULE, "text",
            "--server", "127.0.0.1", "--port", "18881",
            "--format", "N2K_ASCII_RAW", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        try:
            for _ in range(20):
                if actisense_server.clients:
                    break
                await asyncio.sleep(0.2)
            assert actisense_server.clients, "CLI client did not connect to server"

            await actisense_server.send_to_clients(
                "A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF\n".encode('utf-8')
            )

            json_line = None
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded.startswith("{"):
                        json_line = decoded
                        break
            except asyncio.TimeoutError:
                pass

            assert json_line is not None, "Expected JSON output"
            msg = NMEA2000Message.from_json(json_line)
            assert isinstance(msg, NMEA2000Message)
            assert msg.PGN == 65280
            assert len(msg.fields) == 5
        finally:
            proc.terminate()
            await proc.wait()
