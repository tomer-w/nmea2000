from nmea2000.message import NMEA2000Message, NMEA2000Field
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.consts import PhysicalQuantities, FieldTypes
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
                name="Sequence ID",
                description="Sequence ID",
                unit_of_measurement="",
                value=0,
                raw_value=0,
                physical_quantities=None,
                type=FieldTypes.NUMBER
            ),
            NMEA2000Field(
                id="heading",
                name="Heading",
                description="Vessel Heading",
                unit_of_measurement="rad",
                value=1,
                raw_value=1,
                physical_quantities=PhysicalQuantities.ANGLE,
                type=FieldTypes.FLOAT
            ),
            NMEA2000Field(
                id="deviation",
                name="Deviation",
                description="Magnetic Deviation",
                unit_of_measurement="rad",
                value=0,
                raw_value=0,
                physical_quantities=PhysicalQuantities.ANGLE,
                type=FieldTypes.FLOAT
            ),
            NMEA2000Field(
                id="variation",
                name="Variation",
                description="Magnetic Variation",
                unit_of_measurement="rad",
                value=0,
                raw_value=0,
                physical_quantities=PhysicalQuantities.ANGLE,
                type=FieldTypes.FLOAT
            ),
            NMEA2000Field(
                id="reference",
                name="Reference",
                description="Heading Reference",
                unit_of_measurement="",
                value=0,
                raw_value=0,
                physical_quantities=None,
                type=FieldTypes.LOOKUP
            ),
            NMEA2000Field(
                id="reserved_58",
                name="Reserved",
                value=0,
                raw_value=0,
                type=FieldTypes.RESERVED
            )
        ]
    )
    return message

def test_tcp_encode():
    encoder = NMEA2000Encoder()
    msg_bytes = encoder.encode_tcp(_generate_test_message())
    decoder = _get_decoder()
    msg = decoder.decode_tcp(msg_bytes)
    assert isinstance(msg, NMEA2000Message)

