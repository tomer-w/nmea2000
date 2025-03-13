import pytest
from nmea2000.decoder import NMEA2000Decoder, NMEA2000Message
from nmea2000.encoder import NMEA2000Encoder

def test_single_parse():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_actisense_string("09FF7 0FF00 3F9FDCFFFFFFFFFF")
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
    assert msg.fields[2].id == "industry_code"
    assert msg.fields[2].name == "Industry Code"
    assert msg.fields[2].description == "Marine Industry"
    assert msg.fields[2].value == "Marine"
    assert msg.fields[3].value == -0.036000000000000004

def test_fast_parse():
    decoder = NMEA2000Decoder()
    msg = decoder.decode_actisense_string("09FF7 1FF1A 3F9F24000000FFFFFFFFEFFFFFFF009AFFFFFFADFFFFFF050000000000")
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
    assert msg.fields[4].value == None
    assert msg.fields[5].id == "c"
    assert msg.fields[5].value == -17
    assert msg.fields[11].id == "i"
    assert msg.fields[11].value == 0


def test_encode():
    decoder = NMEA2000Decoder()
    encoder = NMEA2000Encoder()
    msg = decoder.decode_actisense_string("09FF7 0FF00 3F9FDCFFFFFFFFFF")
    assert isinstance(msg, NMEA2000Message)
    nmea_str = encoder.encode_actisense(msg)
    assert  nmea_str == "09FF7 0FF00 3F9FDCFFFFFFFFFF"
