
# NMEA 2000 Python Library

A Python library for encoding and decoding NMEA 2000 frames. The encoding and decoding is based on the extensive [canboat](https://canboat.github.io/canboat/canboat.html) database. It also support cheap CANBUS USB and TCP devices as a gateways between you NMEA 2000 boat network and any python code which want to recieve or send those messages.

## Features

- **Decode NMEA 2000 frames**: Parse and interpret raw NMEA 2000 data.
- **Encode NMEA 2000 frames**: Convert structured data back into the NMEA 2000 frame format.
- **USB client**: Send and receive NMEA 2000 data over CANBUS USB devices like [Waveshare USB-CAN-A](https://www.waveshare.com/wiki/USB-CAN-A)
- **TCP client**: Send and receive NMEA 2000 data over CANBUS TCP devices like [ECAN-W01S](https://www.cdebyte.com/products/ECAN-W01S) or [ECAN-E01](https://www.cdebyte.com/products/ECAN-E01)
- **PGN-specific parsing**: Handle various PGNs with specific parsing rules based on [canboat](https://canboat.github.io/canboat/canboat.html).
- **Stateful decoder**: The decoder support NMEA 2000 fast messages which are split between CANBUS messages.
- **CLI support**: Built-in command-line interface for encoding and decoding frames.

## Installation

You can install the library using `pip`:

```bash
pip install nmea2000
```

Or you can clone the repository and install it locally:

```bash
git clone https://github.com/tomer-w/nmea2000.git
cd nmea2000
pip install .
```

## Usage

### Decode NMEA 2000 Frame (CLI)

To decode a frame, use the `decode` command followed by the frame in actisense hex format:

```bash
nmea2000-cli decode --frame "09FF7 0FF00 3F9FDCFFFFFFFFFF"

65280 Furuno: Heave: Manufacturer Code = Furuno (bytes = "3F 07"), Reserved = 3 (bytes = "03"), Industry Code = Marine (bytes = "04"), Heave = -0.036000000000000004 (bytes = "DC"), Reserved = 65535 (bytes = "FF FF 00")
```
```json
And in JSON format:
{"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}

```

### Example Code

```python
from nmea2000.decoder import NMEA2000Decoder

# Initialize decoder
decoder = NMEA2000Decoder()

# Decode a frame
frame_str = "09FF7 0FF00 3F9FDCFFFFFFFFFF"
decoded_frame = decoder.decode_actisense_string(frame_str)

# Print decoded frame
print(decoded_frame)
```

### TCP Client CLI

```bash
nmea2000-cli tcp_client --server 192.168.0.46 --port 8881
```

### TCP Client code

```python
async def handle_received_data(message: NMEA2000Message):
    """User-defined callback function for received data."""
    print(f"Callback: Received {message}")
    
client = AsyncTCPClient(ip, port)
client.set_receive_callback(handle_received_data)  # Register callback
```

### Encode NMEA 2000 Frame (CLI)
TBD
You can also encode data into NMEA 2000 frames using the `encode` command:

```bash
nmea2000-cli encode --data "your_data_to_encode"
``` 

Example:
```bash
nmea2000-cli encode --data 'mea2000-cli encode --frame '{"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'
Encoding frame: {"PGN":65280,"id":"furunoHeave","description":"Furuno: Heave","fields":[{"id":"manufacturer_code","name":"Manufacturer Code","description":"Furuno","unit_of_measurement":"","value":"Furuno","raw_value":1855},{"id":"reserved_11","name":"Reserved","description":"","unit_of_measurement":"","value":3,"raw_value":3},{"id":"industry_code","name":"Industry Code","description":"Marine Industry","unit_of_measurement":"","value":"Marine","raw_value":4},{"id":"heave","name":"Heave","description":"","unit_of_measurement":"m","value":-0.036000000000000004,"raw_value":-36},{"id":"reserved_48","name":"Reserved","description":"","unit_of_measurement":"","value":65535,"raw_value":65535}],"source":9,"destination":255,"priority":7}'

output:
09FF7 0FF00 3F9FDCFFFFFFFFFF
``` 



### Example Code
TBD
```python
from nmea2000.encoder import NMEA2000Encoder

# Initialize encoder
encoder = NMEA2000Encoder()

# Data to encode
data = {"manufacturer_code": 1234, "pgn": 65280, "payload": "example_payload"}

# Encode to NMEA 2000 frame
encoded_frame = encoder.encode_pgn_65280(data)

# Print encoded frame
print(encoded_frame)
``` -->

## Development
I welcome contributions, feedback, and suggestions to improve this project. If you have any ideas for new features, bug fixes, or improvements, feel free to open an issue or create a pull request. I’m always happy to collaborate and learn from the community!

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
- Special thanks to Rob from [Smart Boat Innovations](https://github.com/SmartBoatInnovations/). His code was the initial inspiration for this project. Some the code here might still be based on his latest OSS version.

