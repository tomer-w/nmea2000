import json
from nmea2000.decoder import NMEA2000Decoder, NMEA2000Message
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.consts import PhysicalQuantities, FieldTypes

def _validate_65280_message(msg: NMEA2000Message):
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 65280
    assert msg.priority == 7
    assert msg.source == 9
    assert msg.destination == 255
    assert msg.description == "Furuno: Heave"
    assert len(msg.fields) == 5
    assert msg.fields[0].id == "manufacturer_code"
    assert msg.fields[0].name == "Manufacturer Code"
    assert msg.fields[0].description == "Furuno"
    assert msg.fields[0].value == "Furuno"
    assert msg.fields[0].type == FieldTypes.LOOKUP
    assert msg.fields[2].id == "industry_code"
    assert msg.fields[2].name == "Industry Code"
    assert msg.fields[2].description == "Marine Industry"
    assert msg.fields[2].value == "Marine"
    assert msg.fields[3].value == -0.036000000000000004
    assert msg.fields[3].type == FieldTypes.NUMBER
    assert msg.fields[3].physical_quantities == PhysicalQuantities.DISTANCE

def test_single_parse():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    _validate_65280_message(msg)

def test_json():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert isinstance(msg, NMEA2000Message)
    json_msg=msg.to_json()
    data = json.loads(json_msg)
    assert data["PGN"] == msg.PGN
    assert data["priority"] == msg.priority
    assert data["source"] == msg.source
    assert data["destination"] == msg.destination
    assert data["description"] == msg.description
    assert len(data["fields"]) == len(msg.fields)
    for field in msg.fields:
        field_data = data["fields"].pop(0)
        assert field_data["id"] == field.id
        assert field_data["name"] == field.name
        assert field_data["description"] == field.description
        assert field_data["unit_of_measurement"] == field.unit_of_measurement
        assert field_data["value"] == field.value
        assert field_data["raw_value"] == field.raw_value
    msg2 = NMEA2000Message.from_json(json_msg)
    assert msg2.PGN == msg.PGN
    assert msg2.priority == msg.priority
    assert msg2.source == msg.source
    assert msg2.destination == msg.destination
    assert msg2.description == msg.description
    assert len(msg2.fields) == len(msg.fields)
    for field in msg.fields:
        field2 = msg2.fields.pop(0)
        assert field2.id == field.id
        assert field2.name == field.name
        assert field2.description == field.description
        assert field2.unit_of_measurement == field.unit_of_measurement
        assert field2.value == field.value
        assert field2.raw_value == field.raw_value

def test_fast_parse():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_actisense_string("A000057.063 09FF7 1FF1A 3F9F24000000FFFFFFFFEFFFFFFF009AFFFFFFADFFFFFF050000000000")
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 130842
    assert msg.priority == 7
    assert msg.source == 9
    assert msg.destination == 255
    assert msg.description == "Furuno: Six Degrees Of Freedom Movement"
    assert len(msg.fields) == 12  
    assert msg.fields[3].id == "a"
    assert msg.fields[3].value == 36
    assert msg.fields[4].id == "b"
    assert msg.fields[4].value is None
    assert msg.fields[5].id == "c"
    assert msg.fields[5].value == -17
    assert msg.fields[11].id == "i"
    assert msg.fields[11].value == 0

def test_encode():
    decoder = NMEA2000Decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert isinstance(msg, NMEA2000Message)
    nmea_str = encoder.encode_actisense(msg)
    assert  nmea_str == "09FF7 0FF00 3F9FDCFFFFFFFFFF"

def test_exclude():
    decoder = NMEA2000Decoder(exclude_pgns=[65280])
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert msg is None

def test_include():
    decoder = NMEA2000Decoder(include_pgns=[65280])
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    _validate_65280_message(msg)

def test_tcp_bytes():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_tcp(bytes.fromhex("8800ff00093f9fdcffffffffff"))
    _validate_65280_message(msg)

def test_usb_bytes():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_usb(bytes.fromhex("aae80900ff003f9fdcffffffffff55"))
    _validate_65280_message(msg)

def test_tcp_encode():
    decoder = NMEA2000Decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_tcp(bytes.fromhex("8800ff00093f9fdcffffffffff"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode_tcp(msg)
    assert  msg_bytes == bytes.fromhex("8800ff00093f9fdcffffffffff")

def test_usb_encode():
    decoder = NMEA2000Decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_usb(bytes.fromhex("aae80900ff003f9fdcffffffffff55"))
    assert isinstance(msg, NMEA2000Message)
    msg_bytes = encoder.encode_usb(msg)
    assert  msg_bytes == bytes.fromhex("aae80900ff003f9fdcffffffffff55")
