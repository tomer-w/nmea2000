
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
- **PGN-specific parsing**: Handle various PGNs with specific parsing rules based on [canboat](https://canboat.github.io/canboat/canboat.html).
- **Stateful decoder**: The decoder supports NMEA 2000 fast messages, which are split across multiple CANBUS messages.
- **CLI support**: Built-in command-line interface for encoding and decoding frames.

## Installation

You can install the library using `pip`:

```bash
pip install nmea2000
```

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
```json
Or in JSON format:
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
```
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


#### Example:
```bash
nmea2000-cli encode --data '{"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'
Encoding frame: {"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'

output:
09FF7 0FF00 3F9FDCFFFFFFFFFF
```



#### Example Code
```python
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.input_formats import N2KFormat

# Initialize encoder
encoder = NMEA2000Encoder(output_format=N2KFormat.TCP)

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
