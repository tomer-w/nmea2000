
# NMEA 2000 Python Library

A Python library for encoding and decoding NMEA 2000 frames. The encoding and decoding is based on the extensive [canboat](https://canboat.github.io/canboat/canboat.html) database. It also supports inexpensive CANBUS USB and TCP devices as gateways between your NMEA 2000 boat network and any Python code that wants to receive or send these messages.
This package is the backend for the Home Assistant [NMEA 2000 Integration](https://github.com/tomer-w/ha-nmea2000).

## Features

- **Decode NMEA 2000 frames**: Parse and interpret raw NMEA 2000 data.
- **Encode NMEA 2000 frames**: Convert structured data back into the NMEA 2000 frame format.
- **Gateway clients**: Send and receive NMEA 2000 data through various hardware gateways:
     - **EByte** — binary TCP gateways like [ECAN-E01](https://www.cdebyte.com/products/ECAN-E01) and [ECAN-W01S](https://www.cdebyte.com/products/ECAN-W01S)
     - **Text** — any line-based ASCII TCP gateway with auto-sensing or explicit format selection (e.g. [Actisense W2K-1](https://actisense.com/products/w2k-1-nmea-2000-wifi-gateway/), [Yacht Devices YDEN-02](https://yachtdevicesus.com/products/nmea-2000-ethernet-gateway-yden-02), [Actisense PRO-NDC-1E2K](https://actisense.com/products/pro-ndc-1e2k/) in CAN ASCII mode)
     - **Actisense BST** — Actisense devices using the [BST binary protocol](https://github.com/Actisense/SDK/blob/main/docs/DataFormats/Binary/BST.md) over TCP, supporting both [BST-95](https://github.com/Actisense/SDK/blob/main/docs/DataFormats/Binary/bst-detail/BST-95-can-frame.md) (raw CAN frames) and [BST-D0](https://github.com/Actisense/SDK/blob/main/docs/DataFormats/Binary/bst-detail/BST-D0.md) (pre-assembled N2K). Compatible with the [PRO-NDC-1E2K](https://actisense.com/products/pro-ndc-1e2k/) and [W2K-1](https://actisense.com/products/w2k-1-nmea-2000-wifi-gateway/) in CAN Actisense mode
     - **WaveShare** — USB serial devices like [Waveshare USB-CAN-A](https://www.waveshare.com/wiki/USB-CAN-A)
     - **python-can** — any generic USB or SocketCAN device [supported by the python-can library](https://python-can.readthedocs.io/en/stable/interfaces.html)
     - **Actisense NGT-1** (`Ngt1Nmea2000Gateway`), **Digital Yacht iKonvert** (`IkonvertNmea2000Gateway`) and **Maretron IPG100/200** (`MaretronIpgNmea2000Gateway`) — using canboat's own protocol implementations, including the NGT-1 and iKonvert transmit lists (pass every PGN you will send as `tx_pgns`; others are refused once any is named)
- **PGN-specific parsing**: Every PGN in the [canboat](https://canboat.github.io/canboat/canboat.html) database is decoded and encoded by canboat's own Rust decoder, compiled into this package.
- **Stateful decoder**: The decoder supports NMEA 2000 fast messages, which are split across multiple CANBUS messages.
- **CLI support**: Built-in command-line interface for encoding and decoding frames.

## Installation

You can install the library using `pip`:

```bash
pip install nmea2000
```

Prebuilt wheels cover Python 3.11 and later on Windows (x64), macOS (Apple
silicon and Intel) and Linux (x86_64 and ARM64, glibc and musl), and the
Raspberry Pi on 64-bit Raspberry Pi OS (Pi 3, 4, 5, Zero 2 W) and 32-bit
Raspberry Pi OS (Pi 2 to 5, Zero 2 W). Elsewhere, including the original Pi
Zero, Zero W and Pi 1, installing builds from source and needs a
[Rust toolchain](https://rustup.rs).

Alternatively, you can clone the repository and install it locally:

```bash
git clone https://github.com/tomer-w/nmea2000.git
cd nmea2000
pip install .
```

## Usage

### Decode NMEA 2000 Frame (CLI)

To decode a frame, use the `decode` command followed by the frame in Actisense hex format:

```bash
nmea2000-cli decode --frame "09FF7 0FF00 3F9FDCFFFFFFFFFF"

65280 Furuno: Heave: Manufacturer Code = Furuno (bytes = "3F 07"), Reserved = 3 (bytes = "03"), Industry Code = Marine (bytes = "04"), Heave = -0.036000000000000004 (bytes = "DC"), Reserved = 65535 (bytes = "FF FF 00")
```

Or in JSON format:

```json
{"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}
```

### Example Code

```python
from nmea2000.decoder import NMEA2000Decoder

# Initialize decoder
decoder = NMEA2000Decoder()

# Decode a frame
frame_str = "09FF7 0FF00 3F9FDCFFFFFFFFFF"
decoded_frame = decoder.decode(frame_str)

# Print decoded frame
print(decoded_frame)
```

### Repeating Fields

Some PGNs (e.g. AC Input/Output Status) contain repeating field sets — for example, one set of measurements per AC line. These are exposed as a `list` field whose value is a list of dicts, where each dict maps field IDs to `NMEA2000Field` objects:

```python
from nmea2000.decoder import NMEA2000Decoder
from nmea2000.consts import FieldTypes

decoder = NMEA2000Decoder(already_combined=True)
msg = decoder.decode(
    "2021-07-29-09:00:42.386,6,127503,1,255,20,"
    "00,01,f0,00,05,2c,01,88,13,e8,03,80,15,00,00,80,15,00,00,64"
)

for field in msg.fields:
    if field.type == FieldTypes.VARIABLE and isinstance(field.value, list):
        for idx, entry in enumerate(field.value):
            print(f"AC Line {idx}:")
            for field_id, sub_field in entry.items():
                print(f"  {sub_field.name}: {sub_field.value} {sub_field.unit_of_measurement or ''}")
```

Output:

```text
AC Line 0:
  Line: Line 1
  Acceptability: Bad level
  Reserved: 15
  Voltage: 12.8 V
  Current: 30.0 A
  Frequency: 50.0 Hz
  Breaker Size: 100.0 A
  Real Power: 5504 W
  Reactive Power: 5504 VAR
  Power factor: 1.0 Cos Phi
```

### Example reading packets using python-can

```python
import can
from nmea2000.decoder import NMEA2000Decoder

# Initialize decoder
decoder = NMEA2000Decoder()

# Connect to CAN bus (e.g. slcan device on /dev/ttyUSB0)
bus = can.interface.Bus(interface='slcan', channel="/dev/ttyUSB0", bitrate=250000)

# Decode frames
for msg in bus:
    decoded_frame = decoder.decode(msg)

    # Print decoded frame when ready (fast data intermediate frames return None)
    if decoded_frame is not None:
        print(decoded_frame)
```

### Simple `N2KDevice` example

If you want to behave like a small NMEA 2000 device instead of just reading frames, `N2KDevice` wraps the transport client, handles address claiming, and lets you send/receive `NMEA2000Message` objects directly:

```python
import asyncio

from nmea2000.device import N2KDevice
from nmea2000.message import NMEA2000Field, NMEA2000Message


async def handle_received(message: NMEA2000Message) -> None:
    print(f"received PGN {message.PGN} from source {message.source}")


async def main() -> None:
    device = N2KDevice.for_python_can(
        interface="socketcan",
        channel="can0",
        preferred_address=25,
        model_id="Python demo device",
        manufacturer_information="nmea2000 README example",
    )
    device.set_receive_callback(handle_received)

    try:
        await device.start()
        await device.wait_ready(timeout=5)

        await device.send(
            NMEA2000Message(
                PGN=127250,
                id="vesselHeading",
                priority=2,
                source=0,  # 0 means "use the address claimed by this device"
                destination=255,
                fields=[
                    NMEA2000Field(id="sid", raw_value=0),
                    NMEA2000Field(id="heading", value=1.0),
                    NMEA2000Field(id="deviation", raw_value=0),
                    NMEA2000Field(id="variation", raw_value=0),
                    NMEA2000Field(id="reference", raw_value=0),
                    NMEA2000Field(id="reserved_58", raw_value=0),
                ],
            )
        )

        await asyncio.sleep(10)
    finally:
        await device.close()


asyncio.run(main())
```

Use `N2KDevice.for_ebyte(...)`, `N2KDevice.for_yacht_devices(...)`, `N2KDevice.for_waveshare(...)`, or `N2KDevice.for_actisense(...)` if you are connecting through one of those gateways instead of `python-can`.

### Gateway Client CLI

Each gateway type has its own subcommand:

```bash
# EByte binary TCP gateway
nmea2000-cli ebyte --server 192.168.0.46 --port 8881

# Text/line-based TCP gateway with auto-sensing (W2K-1, YDEN-02, PRO-NDC-1E2K in CAN ASCII mode)
nmea2000-cli text --server 192.168.0.46 --port 8881

# Text gateway with explicit format
nmea2000-cli text --server 192.168.0.46 --port 8881 --format N2K_ASCII_RAW

# Actisense BST over TCP (PRO-NDC-1E2K / W2K-1 in CAN Actisense mode)
nmea2000-cli actisense_bst --server 192.168.0.46 --port 8881

# WaveShare USB-CAN-A serial
nmea2000-cli waveshare --port /dev/ttyUSB0

# Generic python-can adapter
nmea2000-cli can --interface slcan --channel /dev/ttyUSB0 --bitrate 250000
```

Use `--json` to output received messages as JSON (one object per line), useful for piping into other tools:

```bash
nmea2000-cli text --server 192.168.0.46 --port 8881 --json
```

The `--json` flag is available on all gateway subcommands. Use `--dump_file` to record raw frames to a file.

### Gateway Client code

```python
async def handle_received_data(message: NMEA2000Message):
    """User-defined callback function for received data."""
    print(f"Callback: Received {message}")

client = EByteNmea2000Gateway(ip, port)
client.set_receive_callback(handle_received_data)  # Register callback
```

### Encode NMEA 2000 Frame (CLI)

You can also encode data into NMEA 2000 frames using the `encode` command:

```bash
nmea2000-cli encode --data "your_data_to_encode"
```

#### CLI Example

```bash
nmea2000-cli encode --data '{"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'
Encoding frame: {"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'

output:
09FF7 0FF00 3F9FDCFFFFFFFFFF
```

#### Encoder Example

```python
from nmea2000.encoder import create_encoder
from nmea2000.input_formats import N2KFormat

# Initialize encoder
encoder = create_encoder(N2KFormat.EBYTE)

# Data to encode: vessel heading message (PGN 127250)
   message = NMEA2000Message(
        PGN=127250,
        priority=2,
        source=1,
        destination=255,
        fields=[
            NMEA2000Field(
                id="sid",
                raw_value=0,
            ),
            NMEA2000Field(
                id="heading",
                value=1, # 1 radian is 57 degrees
            ),
            NMEA2000Field(
                id="deviation",
                raw_value=0,
            ),
            NMEA2000Field(
                id="variation",
                raw_value=0,
            ),
            NMEA2000Field(
                id="reference",
                raw_value=0,
            ),
            NMEA2000Field(
                id="reserved_58",
                raw_value=0,
            )
        ]
    )

msg_bytes = encoder.encode(_generate_test_message())
print(msg_bytes)
```

## Node-RED Integration

You can stream decoded NMEA 2000 data into [Node-RED](https://nodered.org/) using the CLI with the `--json` flag and a Node-RED **exec** node.

### Setup

1. **Exec node** — add an `exec` node and configure:
   - **Command**: `nmea2000-cli ebyte --server 192.168.1.100 --port 8881 --json`
   - **Output**: select **"when stdout has data"** so it emits a message for each line (not on process exit)
   - **Use spawn mode**: enable `Use spawn() instead of exec()`
   - **Timeout**: leave blank (this is a long-running process)
   - **Append msg.payload**: uncheck

2. **JSON node** — connect the exec node's first output (stdout) to a `json` node to parse each line into a JavaScript object.

3. **Process the data** — use a `switch` or `function` node to route by PGN:

   ```js
   // Example function node: add topic by PGN
   msg.topic = "nmea2000/pgn/" + msg.payload.PGN;
   return msg;
   ```

### Importable Flow

Copy and import this JSON into Node-RED (Menu → Import → Clipboard):

```json
[
    {
        "id": "nmea2000_exec",
        "type": "exec",
        "name": "NMEA2000 Stream",
        "command": "nmea2000-cli ebyte --server 192.168.1.100 --port 8881 --json",
        "addpay": "",
        "append": "",
        "useSpawn": "true",
        "oldrc": false,
        "timer": "",
        "wires": [["nmea2000_json"], [], []]
    },
    {
        "id": "nmea2000_json",
        "type": "json",
        "name": "Parse JSON",
        "property": "payload",
        "wires": [["nmea2000_debug"]]
    },
    {
        "id": "nmea2000_debug",
        "type": "debug",
        "name": "NMEA2000 Data",
        "active": true,
        "tosidebar": true,
        "wires": []
    }
]
```

Each received NMEA 2000 message arrives as a parsed JSON object:

```json
{
    "PGN": 127250,
    "id": "vesselHeading",
    "description": "Vessel Heading",
    "source": 3,
    "destination": 255,
    "priority": 2,
    "fields": [
        {
            "id": "heading",
            "name": "Heading",
            "value": 182.5,
            "unit_of_measurement": "deg"
        }
    ]
}
```

> **Tip:** Replace `ebyte` with `text`, `actisense_bst`, `waveshare`, or `can` depending on your gateway hardware. All gateway subcommands support the `--json` flag.

## Development

Contributions, feedback, and suggestions to improve this project are welcome. If you have ideas for new features, bug fixes, or improvements, feel free to open an issue or create a pull request. I’m always happy to collaborate and learn from the community!

Please don't hesitate to reach out with any questions, comments, or suggestions.

### Setup for Development

To contribute to this library, clone the repository and install the required dependencies:

```bash
git clone https://github.com/tomer-w/nmea2000.git
cd nmea2000
pip install -e .[dev]
```

### Running Tests

To run the tests, use:

```bash
pytest
```

### How decoding works

Decoding, encoding, fast-packet reassembly and fragmentation, and CAN
identifiers are all handled by the canboat project's Rust crate and PGN
database, compiled into this package as `nmea2000._canboat` (the crate is in
`rust/`). Messages are built straight into this library's own model
(`NMEA2000Message`, `NMEA2000Field`, the `##list##` repeating-set entries).

### Units

By default values are in the units canboat.json uses (`%`, `rpm`, `L`, `kWh`,
...), as they always have been. canboat's own unit systems are available too:

```python
NMEA2000Decoder(units="si")  # ratio, Hz, m3, J, rad, K, Pa, ...
NMEA2000Decoder(units="metric")  # deg, C, bar, %, rpm, L, ...
create_encoder("basic_string", units="si")  # values given in SI
```

An encoder must use the unit system its messages' values are in. The few
fields where canboat.json's units differ from canboat's SI units are listed in
the generated `nmea2000/native_units.py`.

Building from source needs a [Rust toolchain](https://rustup.rs);
`pip install -e .[dev]` compiles the core with [maturin](https://www.maturin.rs).

nmea2000 follows canboat's releases: the "Sync canboat release" workflow runs
weekly and opens a pull request that moves the `canboat` crate in
`rust/Cargo.toml` and `canboat.json` to the latest release together, and
regenerates `nmea2000/native_units.py`. To do the same by hand, set the
crate's version, download that release's `canboat.json` asset here, run
`cargo update --package canboat` in `rust/` and then `python canboat2python.py`.
The `FieldTypes`,
`PhysicalQuantities` and `ManufacturerCodes` enumerations in
`nmea2000/consts.py` are built from the crate when nmea2000 is imported; their
values keep the numbering nmea2000 has always used.

Compared with the generated decoder used before, the canboat backend:

- reports fields beyond the end of a short payload, and canboat's "not
  available" and "out of range" sentinels, as `None` rather than as values read
  from missing bits;
- applies canboat's field offsets (e.g. AC power fields that are offset by
  2,000,000,000);
- returns `BINARY` and dynamic field values in wire byte order, at their full
  field width;
- decodes a group function's `VARIABLE` parameter values with the type of the
  field they refer to (`'Furuno'` rather than raw bytes);
- reports an empty string field as `None`;
- emits only the repeating-set entries actually present in the payload, even
  when the count field claims more.

and its encoder:

- pads the last frame of a fast-packet to 8 bytes with `0xff`, as the
  standard requires;
- writes fixed-length PGNs at their full length, filling unset fields with
  their "not available" values;
- refuses values it cannot represent (a lookup label that does not exist, a
  number too large for its field), raising `ValueError`, instead of writing
  truncated bits; values outside a field's nominal range that still fit are
  written as they are.

`N2KDevice` claims its address with canboat's ISO 11783-5 address claimer and
builds its product information, heartbeat, ISO acknowledgement and PGN list
messages with canboat's device module. Its persisted address is unchanged.
What changes:

- address claiming follows the standard's timings (ISO 11783-5 / SAE
  J1939-81): the device listens for other devices' claims for 1 s, then uses
  its address once its claim has stood unchallenged for 250 ms. The
  `address_claim_startup_delay` and `address_claim_detection_time` options
  are deprecated and ignored, and passing either raises a `FutureWarning`. The
  old defaults waited 1 s and then 5 s, so a device is now ready about 5 s
  sooner;
- heartbeats are sent at priority 7 and report the CAN controller as
  "Error Active" (working normally) instead of not available;
- an ISO Request for PGN 126464 is answered with both the Transmit and the
  Receive PGN lists, decoded as `##list##` entries of `pgn` fields;
- messages the device sends are decoded like received ones: lookups carry
  their labels, reserved fields their wire values, and the NMEA 2000 version's
  `raw_value` is the scaled value (`1.3`), like every other number.

The per-PGN `nmea2000.pgns.decode_pgn_<pgn>` / `encode_pgn_<pgn>` functions
remain available for existing code.

### Not yet exposed from canboat

The canboat crate has more than this package exposes so far. Each item below
would be a binding plus a new option or entry point, with no change to
existing behaviour:

- **Analyzer JSON**: read and write canboat's `analyzer -json` records
  (crate feature `json-input`, `engine/output/json.rs`), for interchange with
  canboat, canboatjs and Signal K tooling.
- **NMEA 0183 and AIS output**: convert decoded messages into 0183 sentences
  and AIVDM (crate features `nmea0183` and `ais`).
- **Capture readers**: replay SocketCAN `.pcap` / `.pcap.gz`, Navico `.nif`
  and EBL captures (`io/container.rs`, part of the `io` feature).
- **SAE J1939 and Quick**: decode J1939 engine and genset PGNs and Quick's
  11-bit PCS bus, via a protocol option (`engine/bus_protocol.rs`).
- **Quirks**: opt-in decode-time corrections for misbehaving devices, such as
  GPS week-rollover dates (`engine/quirk.rs`).

### Running the CLI Locally

To test the CLI locally, you can use the following command:

```bash
python -m nmea2000.cli decode --frame "your_hex_encoded_frame"
```

## License

This project is licensed under the Apache 2.0 license - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- This library leverages the [canboat](https://github.com/canboat/canboat) as the source for all PGN data.
- Special thanks to Rob from [Smart Boat Innovations](https://github.com/SmartBoatInnovations/). His code was the initial inspiration for this project. Some of the code here may still be based on his latest open-source version.
