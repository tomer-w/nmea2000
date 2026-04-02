from nmea2000.message import NMEA2000Message, NMEA2000Field
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.decoder import NMEA2000Decoder
from nmea2000.input_formats import N2KFormat
from nmea2000.consts import PhysicalQuantities
from .test_decoder import _get_decoder

def _generate_test_message() -> NMEA2000Message:
    """Generate a test NMEA2000 message."""
    # Example: Generate a vessel heading message (PGN 127250)
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
    return message

def test_tcp_encode():
    encoder = NMEA2000Encoder(output_format=N2KFormat.TCP)
    msg_bytes = encoder.encode(_generate_test_message())[0]
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.ANGLE:"deg"})
    msg = decoder.decode(msg_bytes)
    assert isinstance(msg, NMEA2000Message)
    assert msg.fields[1].value == 57

def test_tcp_encode_2():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder(output_format=N2KFormat.TCP)
    msg = decoder.decode(bytes.fromhex("8800ff00093f9fdcffffffffff"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes_hex = encoder.encode(msg)[0].hex()
    assert msg_bytes_hex == "8800ff00093f9fdcffffffffff"

def test_usb_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder(output_format=N2KFormat.USB)
    msg = decoder.decode(bytes.fromhex("aa550102010113f10908fffac2ffffffffff00d0"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes_hex = encoder.encode(msg)[0].hex()
    assert msg_bytes_hex == "aa550102010113f10908fffac2ffffffffff00d0"

def test_yacht_devices_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder(output_format=N2KFormat.YACHT_DEVICES)
    msg = decoder.decode("21:31:42.671 T 01F010B3 FF FF 0C 4F 70 BE 3E 33")
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode(msg)[0]
    assert  msg_bytes == "01F010B3 FF FF 0C 4F 70 BE 3E 33\r\n".encode()

def test_python_can_encode():
    """Test encoding a NMEA2000 message to python-can Message objects."""
    import can.message
    decoder = _get_decoder()
    encoder = NMEA2000Encoder(output_format=N2KFormat.PYTHON_CAN)
    # Decode a known message
    msg = decoder.decode("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert isinstance(msg, NMEA2000Message)
    # Encode to python-can
    can_messages = encoder.encode(msg)
    assert len(can_messages) == 1
    can_msg = can_messages[0]
    assert isinstance(can_msg, can.message.Message)
    assert can_msg.is_extended_id is True
    assert can_msg.is_rx is False
    assert len(can_msg.data) == 8
    # Verify arbitration_id encodes PGN 65280, source 9, priority 7
    pgn_id, source_id, dest, priority = NMEA2000Decoder.extract_header(can_msg.arbitration_id)
    assert pgn_id == 65280
    assert source_id == 9
    assert priority == 7

def test_python_can_roundtrip():
    """Test that encode -> decode roundtrip via python-can preserves message content."""
    decoder = _get_decoder()
    encoder = NMEA2000Encoder(output_format=N2KFormat.PYTHON_CAN)
    # Start with a USB-decoded message
    msg = decoder.decode(bytes.fromhex("aa550102010113f10908fffac2ffffffffff00d0"))
    assert isinstance(msg, NMEA2000Message)
    # Encode to python-can
    can_messages = encoder.encode(msg)
    assert len(can_messages) == 1
    # Decode back from python-can
    decoder2 = _get_decoder()
    decoded = decoder2.decode(can_messages[0])
    assert isinstance(decoded, NMEA2000Message)
    assert decoded.PGN == msg.PGN
    assert decoded.source == msg.source
    assert decoded.priority == msg.priority
