from datetime import time
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
    assert not msg.fields[0].part_of_primary_key
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
    assert not msg.fields[3].part_of_primary_key

def test_single_parse():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    _validate_65280_message(msg)

def test_bitlookup_parse():
    decoder = NMEA2000Decoder(preferred_units = {PhysicalQuantities.TEMPERATURE:"C"})
    msg = decoder.decode_basic_string("2016-04-09T16:41:39.628Z,2,127489,16,255,26,00,2f,06,ff,ff,e3,73,65,05,ff,7f,72,10,00,00,ff,ff,ff,ff,ff,06,00,00,00,7f,7f", True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 127489
    assert msg.priority == 2
    assert msg.source == 16
    assert msg.destination == 255
    assert msg.description == "Engine Parameters, Dynamic"
    assert len(msg.fields) == 14
    assert msg.fields[0].name == "Instance"
    assert msg.fields[0].value == "Single Engine or Dual Engine Port"
    assert msg.fields[1].name == "Oil pressure"
    assert msg.fields[1].value == 158300
    assert msg.fields[1].unit_of_measurement == "Pa"
    assert msg.fields[1].physical_quantities == PhysicalQuantities.PRESSURE
    assert msg.fields[2].name == "Oil temperature"
    assert msg.fields[2].value is None
    assert msg.fields[2].unit_of_measurement == "C"
    assert msg.fields[2].physical_quantities == PhysicalQuantities.TEMPERATURE
    assert msg.fields[3].name == "Temperature"
    assert msg.fields[3].value == 23.52
    assert msg.fields[4].name == "Alternator Potential"
    assert msg.fields[4].value == 13.81
    assert msg.fields[5].name == "Fuel Rate"
    assert msg.fields[5].value is None
    assert msg.fields[6].name == "Total Engine hours"
    assert msg.fields[6].value == time(1,10,10)
    assert msg.fields[7].name == "Coolant Pressure"
    assert msg.fields[7].value is None
    assert msg.fields[8].name == "Fuel Pressure"
    assert msg.fields[8].value is None
    assert msg.fields[10].name == "Discrete Status 1"
    assert msg.fields[10].value == "Over Temperature, Low Oil Pressure"
    assert msg.fields[11].name == "Discrete Status 2"
    assert msg.fields[11].value == ""
    assert msg.fields[12].name == "Engine Load"
    assert msg.fields[12].value is None
    assert msg.fields[13].name == "Engine Torque"
    assert msg.fields[13].value is None

def test_bitlookup_parse2():
    decoder = NMEA2000Decoder(preferred_units = {PhysicalQuantities.TEMPERATURE:"C", PhysicalQuantities.PRESSURE:"Bar"})
    msg = decoder.decode_basic_string("1970-01-01T16:41:39.628Z,2,127489,16,255,26,00,2f,06,10,20,e3,73,65,05,65,04,72,10,00,00,10,20,30,40,ff,06,00,ff,00,30,18", True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 127489
    assert msg.priority == 2
    assert msg.source == 16
    assert msg.destination == 255
    assert msg.description == "Engine Parameters, Dynamic"
    assert len(msg.fields) == 14
    assert msg.fields[0].name == "Instance"
    assert msg.fields[0].value == "Single Engine or Dual Engine Port"
    assert msg.fields[1].name == "Oil pressure"
    assert msg.fields[1].value == 1.583
    assert msg.fields[1].unit_of_measurement == "Bar"
    assert msg.fields[1].physical_quantities == PhysicalQuantities.PRESSURE
    assert msg.fields[2].name == "Oil temperature"
    assert msg.fields[2].value == 547.65
    assert msg.fields[2].unit_of_measurement == "C"
    assert msg.fields[2].physical_quantities == PhysicalQuantities.TEMPERATURE
    assert msg.fields[3].name == "Temperature"
    assert msg.fields[3].value == 23.52
    assert msg.fields[4].name == "Alternator Potential"
    assert msg.fields[4].value == 13.81
    assert msg.fields[5].name == "Fuel Rate"
    assert msg.fields[5].value == 112.5
    assert msg.fields[6].name == "Total Engine hours"
    assert msg.fields[6].value == time(1,10,10)
    assert msg.fields[7].name == "Coolant Pressure"
    assert msg.fields[7].value == 8.208
    assert msg.fields[7].unit_of_measurement == "Bar"
    assert msg.fields[8].name == "Fuel Pressure"
    assert msg.fields[8].value == 164.32
    assert msg.fields[8].unit_of_measurement == "Bar"
    assert msg.fields[10].name == "Discrete Status 1"
    assert msg.fields[10].value == "Over Temperature, Low Oil Pressure"
    assert msg.fields[11].name == "Discrete Status 2"
    assert msg.fields[11].value == "Warning Level 1, Warning Level 2, Power Reduction, Maintenance Needed, Engine Comm Error, Sub or Secondary Throttle, Neutral Start Protect, Engine Shutting Down"
    assert msg.fields[12].name == "Engine Load"
    assert msg.fields[12].value == 48
    assert msg.fields[12].unit_of_measurement == "%"
    assert msg.fields[13].name == "Engine Torque"
    assert msg.fields[13].value == 24
    assert msg.fields[13].unit_of_measurement == "%"

def test_INDIRECT_LOOKUP_parse():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_basic_string("2022-09-10T12:10:16.614Z,6,60928,5,255,8,fb,9b,70,22,00,9b,50,c0", True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 60928
    assert msg.priority == 6
    assert msg.source == 5
    assert msg.destination == 255
    assert msg.description == "ISO Address Claim"
    assert len(msg.fields) == 10
    assert msg.fields[0].name == "Unique Number"
    assert msg.fields[0].value == 1088507
    assert msg.fields[1].name == "Manufacturer Code"
    assert msg.fields[1].value == "Navico"
    assert msg.fields[2].name == "Device Instance Lower"
    assert msg.fields[2].value == 0
    assert msg.fields[3].name == "Device Instance Upper"
    assert msg.fields[3].value == 0
    assert msg.fields[4].name == "Device Function"
    assert msg.fields[4].value == "Rudder"
    assert msg.fields[6].name == "Device Class"
    assert msg.fields[6].value == "Steering and Control surfaces"
    assert msg.fields[7].name == "System Instance"
    assert msg.fields[7].value == 0
    assert msg.fields[8].name == "Industry Group"
    assert msg.fields[8].value == "Marine"
    assert msg.fields[9].name == "Arbitrary address capable"
    assert msg.fields[9].value is None

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
    assert msg.fields[4].value == -1
    assert msg.fields[5].id == "c"
    assert msg.fields[5].value == -17
    assert msg.fields[6].id == "d"
    assert msg.fields[6].value == 0
    assert msg.fields[7].id == "e"
    assert msg.fields[7].value == -102
    assert not msg.fields[7].part_of_primary_key
    assert msg.fields[8].id == "f"
    assert msg.fields[8].value == -83
    assert msg.fields[9].id == "g"
    assert msg.fields[9].value == 5
    assert msg.fields[10].id == "h"
    assert msg.fields[10].value == 0
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
