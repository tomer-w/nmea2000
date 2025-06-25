from datetime import timedelta
import json
import uuid
from nmea2000.decoder import NMEA2000Decoder, NMEA2000Message
from nmea2000.encoder import NMEA2000Encoder
from nmea2000.consts import PhysicalQuantities, FieldTypes
import os

from nmea2000.message import IsoName


dump_to_file = None
#dump_to_file = './dumps/pgn_dump.jsonl'

def _get_decoder(exclude_pgns = [], include_pgns = [], preferred_units = {}, build_network_map = False, exclude_manufacturer_code = {}):
    return NMEA2000Decoder(exclude_pgns = exclude_pgns, include_pgns = include_pgns, exclude_manufacturer_code = exclude_manufacturer_code, preferred_units = preferred_units, dump_to_file=dump_to_file, build_network_map = build_network_map)
def _validate_65280_message(msg: NMEA2000Message | None):
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 65280
    assert msg.priority == 7
    assert msg.source == 9
    assert msg.destination == 255
    assert msg.description == "Furuno: Heave"
    assert len(msg.fields) == 5
    assert msg.fields[0].id == "manufacturerCode"
    assert msg.fields[0].name == "Manufacturer Code"
    assert msg.fields[0].part_of_primary_key
    assert msg.fields[0].description == "Furuno"
    assert msg.fields[0].value == "Furuno"
    assert msg.fields[0].type == FieldTypes.LOOKUP
    assert msg.fields[2].id == "industryCode"
    assert msg.fields[2].name == "Industry Code"
    assert msg.fields[2].description == "Marine Industry"
    assert msg.fields[2].value == "Marine"
    assert msg.fields[3].value == -0.036000000000000004
    assert msg.fields[3].type == FieldTypes.NUMBER
    assert msg.fields[3].physical_quantities == PhysicalQuantities.DISTANCE
    assert not msg.fields[3].part_of_primary_key
    assert msg.get_field_str_value_by_id("industryCode") == "Marine"

def test_single_parse():
    decoder = _get_decoder()
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    _validate_65280_message(msg)

def test_single_parse_with_json():
    filename = f"./dumps/pgn_dump_{uuid.uuid4().hex[:8]}.jsonl"
    with NMEA2000Decoder(dump_to_file=filename, dump_pgns=[65280]) as decoder:
        msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    _validate_65280_message(msg)
    assert os.path.exists(filename)
    with open(filename, "r") as f:
        lines = f.read().splitlines()
        assert len(lines) == 1
    os.remove(filename)

def test_yacht_devices_decode():
    decoder = _get_decoder()
    msg = decoder.decode_yacht_devices_string("00:01:54.330 R 15FD0A10 00 00 00 68 65 0F 00 FF")
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 130314
    assert msg.id == "actualPressure"
    assert msg.priority == 5
    assert msg.source == 16
    assert msg.destination == 255
    assert msg.description == "Actual Pressure"
    assert msg.ttl == timedelta(milliseconds=2000)
    assert msg.fields[0].name == "SID"
    assert msg.fields[0].value == 0
    assert msg.fields[1].name == "Instance"
    assert msg.fields[1].value == 0
    assert msg.fields[2].name == "Source"
    assert msg.fields[2].value == "Atmospheric"
    assert msg.fields[3].name == "Pressure"
    assert msg.fields[3].value == 100900
    assert msg.fields[3].unit_of_measurement == "Pa"
    assert msg.fields[3].physical_quantities == PhysicalQuantities.PRESSURE
    assert msg.fields[4].name == "Reserved"
    assert msg.fields[4].value == 255

def test_bitlookup_parse():
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.TEMPERATURE:"C"})
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
    assert msg.fields[6].value == 4210
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
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.TEMPERATURE:"C", PhysicalQuantities.PRESSURE:"Bar"})
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
    assert msg.fields[6].value == 4210
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
    decoder = _get_decoder()
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
    assert msg.fields[9].value == 'Yes'

def test_STRING_FIX_parse():
    decoder = _get_decoder()
    msg = decoder.decode_basic_string("2011-04-25-06:25:02.017,6,126996,60,255,134,ba,04,96,26,4d,61,73,74,65,72,42,75,73,20,4e,4d,45,41,20,49,6e,74,65,72,66,61,63,65,00,00,00,00,00,00,00,00,31,2e,30,30,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,31,2e,30,30,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,58,44,31,38,41,30,30,31,39,00,00,00,00,00,00,00,00,4e,4d,45,41,32,30,30,30,00,00,00,00,00,00,00,03,00", True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 126996
    assert msg.priority == 6
    assert msg.source == 60
    assert msg.destination == 255
    assert msg.description == "Product Information"
    assert len(msg.fields) == 8
    assert msg.fields[0].name == "NMEA 2000 Version"
    assert msg.fields[0].value == 1.21
    assert msg.fields[1].name == "Product Code"
    assert msg.fields[1].value == 9878
    assert msg.fields[2].name == "Model ID"
    assert msg.fields[2].value == 'MasterBus NMEA Interface'
    assert msg.fields[3].name == "Software Version Code"
    assert msg.fields[3].value == '1.00'
    assert msg.fields[4].name == "Model Version"
    assert msg.fields[4].value == '1.00'
    assert msg.fields[5].name == "Model Serial Code"
    assert msg.fields[5].value == 'XD18A0019'
    assert msg.fields[6].name == "Certification Level"
    assert msg.fields[6].raw_value == 3
    assert msg.fields[7].name == "Load Equivalency"
    assert msg.fields[7].value == 0

def test_STRING_LZ_parse():
    decoder = _get_decoder()
    msg = decoder.decode_basic_string("2020-08-22T13:52:52.054Z,7,130820,49,255,20,a3,99,0b,80,01,02,00,c6,3e,05,c7,08,41,56,52,4f,54,52,4f,53", True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 130820
    assert msg.priority == 7
    assert msg.source == 49
    assert msg.destination == 255
    assert msg.description == 'Fusion: Tuner'
    assert len(msg.fields) == 9
    assert msg.fields[0].name == 'Manufacturer Code'
    assert msg.fields[0].value == 'Fusion Electronics'
    assert msg.fields[3].name == 'Message ID'
    assert msg.fields[3].value == 'Tuner'
    assert msg.fields[4].name == 'Source ID'
    assert msg.fields[4].value == 'FM'
    assert msg.fields[6].name == 'Frequency'
    assert msg.fields[6].value == 88000000
    assert msg.fields[6].unit_of_measurement == 'Hz'
    assert msg.fields[6].physical_quantities == PhysicalQuantities.FREQUENCY
    assert msg.fields[8].name == 'Track'
    assert msg.fields[8].value == 'AVROTROS'

def test_STRING_LAU_parse():
    decoder = _get_decoder()
    msg = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,1,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 126998
    assert msg.priority == 6
    assert msg.source == 1
    assert msg.destination == 255
    assert msg.description == 'Configuration Information'
    assert len(msg.fields) == 3
    assert msg.fields[0].name == 'Installation Description #1'
    assert msg.fields[0].value == 'hello'
    assert msg.fields[1].name == 'Installation Description #2'
    assert msg.fields[1].value == 'wórld'
    assert msg.fields[2].name == 'Manufacturer Information'
    assert msg.fields[2].value is None

def test_json():
    decoder = _get_decoder()
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

def _validate_130842_message(msg: NMEA2000Message | None):
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


def test_iso_address_parse():
    decoder = _get_decoder(build_network_map = True)
    msg_60928 = decoder.decode_basic_string("2022-09-10T12:10:16.614Z,6,60928,5,255,8,fb,9b,70,22,00,9b,50,c0", True)
    assert isinstance(msg_60928, NMEA2000Message)
    assert msg_60928.source_iso_name is not None
    msg_126998 = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,5,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert isinstance(msg_126998, NMEA2000Message)
    assert msg_126998.PGN == 126998
    assert msg_126998.source_iso_name is not None
    assert msg_126998.source_iso_name == msg_60928.source_iso_name
    assert msg_126998.hash == "027d58d31145159c43becc14347a9c7d"
    msg_126998_2 = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,4,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert msg_126998_2 is None

def test_iso_address_parse_zero():
    decoder = _get_decoder()
    msg_60928 = decoder.decode_basic_string("2000-09-10T12:10:16.614Z,6,60928,5,255,8,f5,01,c0,2c,ef,aa,46,c0", True)
    assert isinstance(msg_60928, NMEA2000Message)
    assert msg_60928.source_iso_name is not None

def test_iso_address_parse_exclude():
    decoder = _get_decoder(exclude_pgns=[60928])
    msg_60928 = decoder.decode_basic_string("2022-09-10T12:10:16.614Z,6,60928,5,255,8,fb,9b,70,22,00,9b,50,c0", True)
    assert msg_60928 is None
    msg_126998 = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,5,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert isinstance(msg_126998, NMEA2000Message)
    assert msg_126998.PGN == 126998
    assert isinstance(msg_126998.source_iso_name, IsoName)
    assert msg_126998.source_iso_name.name == 13857746478299126779

def test_iso_address_parse_exclude_2():
    decoder = _get_decoder(exclude_pgns=["isoAddressClaim"])
    msg_60928 = decoder.decode_basic_string("2022-09-10T12:10:16.614Z,6,60928,5,255,8,fb,9b,70,22,00,9b,50,c0", True)
    assert msg_60928 is None
    msg_126998 = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,5,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert isinstance(msg_126998, NMEA2000Message)
    assert msg_126998.PGN == 126998
    assert isinstance(msg_126998.source_iso_name, IsoName)
    assert msg_126998.source_iso_name.name == 13857746478299126779

def test_exclude_manufacturer_code():
    decoder = _get_decoder(exclude_pgns=[60928], exclude_manufacturer_code=["Navico"], build_network_map=True)
    msg_60928 = decoder.decode_basic_string("2022-09-10T12:10:16.614Z,6,60928,5,255,8,fb,9b,70,22,00,9b,50,c0", True)
    assert msg_60928 is None
    msg_126998 = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,5,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert msg_126998 is None

def test_fast_parse():
    decoder = _get_decoder()
    msg = decoder.decode_actisense_string("A000057.063 09FF7 1FF1A 3F9F24000000FFFFFFFFEFFFFFFF009AFFFFFFADFFFFFF050000000000")
    _validate_130842_message(msg)

def test_encode():
    decoder = _get_decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert isinstance(msg, NMEA2000Message)
    nmea_str = encoder.encode_actisense(msg)
    assert  nmea_str == "09FF7 0FF00 3F9FDCFFFFFFFFFF"

def test_exclude():
    decoder = _get_decoder(exclude_pgns=[65280])
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert msg is None

def test_include():
    decoder = _get_decoder(include_pgns=[65280])
    msg = decoder.decode_actisense_string("A000057.055 09FF7 0FF00 3F9FDCFFFFFFFFFF")
    _validate_65280_message(msg)

def test_include_with_network_map():
    decoder = _get_decoder(include_pgns=[126998], build_network_map=True)
    msg_60928 = decoder.decode_basic_string("2022-09-10T12:10:16.614Z,6,60928,5,255,8,fb,9b,70,22,00,9b,50,c0", True)
    assert msg_60928 is None
    msg_126998 = decoder.decode_basic_string("2021-01-30-20:43:21.684,6,126998,5,255,19,07,01,68,65,6C,6C,6F,0c,00,77,00,F3,00,72,00,6C,00,64,00", True)
    assert isinstance(msg_126998, NMEA2000Message)

def test_tcp_bytes():
    decoder = _get_decoder()
    msg = decoder.decode_tcp(bytes.fromhex("881cff00093f9fdcffffffffff"))
    _validate_65280_message(msg)

def test_usb_bytes():
    decoder = _get_decoder()
    msg = decoder.decode_usb(bytes.fromhex("aae80900ff1c3f9fdcffffffffff55"))
    _validate_65280_message(msg)

def test_iso_request_decode():
    decoder = _get_decoder()
    msg = decoder.decode_basic_string("2012-06-17-15:02:11.000,6,59904,0,255,3,14,f0,01")
    assert isinstance(msg, NMEA2000Message)
    encoder = NMEA2000Encoder()
    msg_bytes = encoder.encode_usb(msg)[0]
    assert isinstance(msg_bytes, bytes)
    msg2 = decoder.decode_usb(msg_bytes)
    assert isinstance(msg2, NMEA2000Message)
    assert msg2.PGN == 59904
    assert msg2.fields[0].raw_value == msg.fields[0].raw_value
    str_json = msg.to_json()
    msg3 = NMEA2000Message.from_json(str_json)
    assert isinstance(msg3, NMEA2000Message)
    assert msg3.PGN == 59904
    assert msg3.fields[0].raw_value == msg.fields[0].raw_value

def test_decode_yacht_devices_receive():
    decoder = _get_decoder()
    msg = decoder.decode_yacht_devices_string("21:31:42.671 T 01F010B3 FF FF 0C 4F 70 BE 3E 33")
    assert isinstance(msg, NMEA2000Message)

def test_decode_yacht_devices_receive_2():
    decoder = _get_decoder()
    msg = decoder.decode_yacht_devices_string("21:31:42.520 T 01F119B3 57 00 00 8D 0B FA FE FF")
    assert isinstance(msg, NMEA2000Message)

def test_decode_speed():
    decoder = _get_decoder(preferred_units = {PhysicalQuantities.SPEED:"kts"})
    msg = decoder.decode_actisense_string("A000057.067 22FF2 1FD02 075101744CFAFFFF")
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 130306
    assert msg.priority == 2
    assert msg.source == 34
    assert msg.destination == 255
    assert msg.description == 'Wind Data'
    assert len(msg.fields) == 5
    assert msg.fields[1].name == 'Wind Speed'
    assert msg.fields[1].unit_of_measurement == 'kts'
    assert msg.fields[1].raw_value == 3.37 #m/s
    assert msg.fields[1].value == 6.6
