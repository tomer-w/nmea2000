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
    msg_bytes = encoder.encode_tcp(_generate_test_message())[0]
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.ANGLE:"deg"})
    msg = decoder.decode_tcp(msg_bytes)
    assert isinstance(msg, NMEA2000Message)
    assert msg.fields[1].value == 57

