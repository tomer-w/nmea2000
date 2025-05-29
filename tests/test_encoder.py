from nmea2000.message import NMEA2000Message, NMEA2000Field
from nmea2000.encoder import NMEA2000Encoder
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
    encoder = NMEA2000Encoder()
    msg_bytes = encoder.encode_ebyte(_generate_test_message())[0]
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.ANGLE:"deg"})
    msg = decoder.decode_tcp(msg_bytes)
    assert isinstance(msg, NMEA2000Message)
    assert msg.fields[1].value == 57

def test_tcp_encode_2():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_tcp(bytes.fromhex("8800ff00093f9fdcffffffffff"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode_ebyte(msg)[0]
    assert  msg_bytes == bytes.fromhex("8800ff00093f9fdcffffffffff")

def test_usb_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_usb(bytes.fromhex("aae80900ff003f9fdcffffffffff55"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode_usb(msg)[0]
    assert  msg_bytes == bytes.fromhex("aae80900ff003f9fdcffffffffff55")

def test_yacht_devices_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_yacht_devices_string("21:31:42.671 T 01F010B3 FF FF 0C 4F 70 BE 3E 33")
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode_yacht_devices(msg)[0]
    assert  msg_bytes == "01F010B3 FF FF 0C 4F 70 BE 3E 33\r\n".encode()

