
# NMEA 2000 Python Library

A Python library for encoding and decoding NMEA 2000 frames. This library provides a decoder class for parsing NMEA 2000 frames, with support for various Parameter Group Numbers (PGNs) and frame types.

## Features

- **Decode NMEA 2000 frames**: Parse and interpret raw NMEA 2000 data.
- **Encode NMEA 2000 frames**: Convert structured data back into the NMEA 2000 frame format.
- **PGN-specific parsing**: Handle various PGNs with specific parsing rules.
- **Stateful decoder**: The decoder stores state across multiple decode calls.
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
python -m nmea2000.cli decode --frame "09FF7 0FF00 3F9FDCFFFFFFFFFF"
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

### Encode NMEA 2000 Frame (CLI)
TBD
<!-- You can also encode data into NMEA 2000 frames using the `encode` command:

```bash
python -m nmea2000.cli encode --data "your_data_to_encode"
``` -->

### Example Code
TBD
<!-- ```python
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
git clone https://github.com/yourusername/nmea2000.git
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
- Special thanks to Rob from [Smart Boat Innovations](https://github.com/SmartBoatInnovations/). His code was the initial inspiration for this project.
