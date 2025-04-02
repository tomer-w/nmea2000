from datetime import date, time
from nmea2000.decoder import NMEA2000Message
from .test_decoder import _get_decoder

def _validate_129029_message(msg: NMEA2000Message):
    assert isinstance(msg, NMEA2000Message)
    assert msg.PGN == 129029
    assert msg.priority == 3
    assert msg.source == 0
    assert msg.destination == 255
    assert msg.description == "GNSS Position Data"
    assert msg.fields[0].value == 231
    assert msg.fields[1].value == date(2013, 3, 1)
    assert msg.fields[2].value == time(19,29,52)
    assert msg.fields[3].value == 42.496768422109845            
    assert msg.fields[4].value == -71.58366365704198
    assert msg.fields[5].value == 90.98460299999999
    assert msg.fields[6].value == 'GPS+SBAS/WAAS'
    assert msg.fields[7].value == 'GNSS fix'
    assert msg.fields[8].value == 'No integrity checking'
    assert msg.fields[9].value == 63
    assert msg.fields[10].value == 8
    assert msg.fields[11].value == 1.11
    assert msg.fields[12].value == 1.9000000000000001
    assert msg.fields[13].value == -33.63
    assert msg.fields[14].value == 0
    assert msg.fields[15].value is None
    assert msg.fields[15].raw_value == 15
    assert msg.fields[16].value is None
    assert msg.fields[17].value is None


def test_decode_strings_from_file_1():
    with open("tests/recombine-frames-1.in", "r") as f:
        lines = f.read().splitlines()

    decoder = _get_decoder()
    counter = 0
    for line in lines:
        input_data = line.strip()
        if input_data.startswith('#') or len(input_data) <= 1:
            continue
        counter += 1
        msg = decoder.decode_basic_string(input_data)
        if counter == 5:
            assert isinstance(msg, NMEA2000Message)
            assert msg.PGN == 130311
            assert msg.priority == 5
            assert msg.source == 35
            assert msg.destination == 255
            assert msg.description == "Environmental Parameters"
            assert msg.fields[0].value == 197
            assert msg.fields[3].value == 281.88
        elif counter == 8:
            _validate_129029_message(msg)
        else:
            assert msg is None
    assert counter == 8

def test_decode_strings_from_file_2():
    with open("tests/recombine-frames-2.in", "r") as f:
        lines = f.read().splitlines()

    decoder = _get_decoder()
    counter = 0
    for line in lines:
        input_data = line.strip()
        if input_data.startswith('#') or len(input_data) <= 1:
            continue
        counter += 1
        msg = decoder.decode_basic_string(input_data)
        if counter == 11:
            _validate_129029_message(msg)
        elif counter == 16:
            assert isinstance(msg, NMEA2000Message)
            assert msg.PGN == 126720
            assert msg.priority == 7
            assert msg.source == 0
            assert msg.destination == 255
            assert msg.description == "0x1EF00-0x1EFFF: Manufacturer Proprietary fast-packet addressed"
            assert msg.fields[0].value == "Garmin"
            assert msg.fields[1].value == 3
            assert msg.fields[2].value == "Marine"
        else:
            assert msg is None
    assert counter == 16
    
def test_decode_strings_from_file_3():
    with open("tests/recombine-frames-3.in", "r") as f:
        lines = f.read().splitlines()

    decoder = _get_decoder()
    counter = 0
    for line in lines:
        input_data = line.strip()
        if input_data.startswith('#') or len(input_data) <= 1:
            continue
        counter += 1
        msg = decoder.decode_basic_string(input_data)
        if counter == 7:
            _validate_129029_message(msg)
        else:
            assert msg is None
    assert counter == 7
    
def test_decode_strings_from_file_4():
    with open("tests/recombine-frames-4.in", "r") as f:
        lines = f.read().splitlines()

    decoder = _get_decoder()
    counter = 0
    for line in lines:
        input_data = line.strip()
        if input_data.startswith('#') or len(input_data) <= 1:
            continue
        counter += 1
        msg = decoder.decode_basic_string(input_data)
        if counter == 13:
            _validate_129029_message(msg)
        else:
            assert msg is None
    assert counter == 13
    
def test_decode_strings_from_file_5():
    with open("tests/recombine-frames-5.in", "r") as f:
        lines = f.read().splitlines()

    decoder = _get_decoder()
    counter = 0
    for line in lines:
        input_data = line.strip()
        if input_data.startswith('#') or len(input_data) <= 1:
            continue
        counter += 1
        msg = decoder.decode_basic_string(input_data)
        if counter == 32:
            assert isinstance(msg, NMEA2000Message)
            assert msg.PGN == 130823
            assert msg.priority == 3
            assert msg.source == 27
            assert msg.destination == 255
            assert msg.description == "Maretron: Proprietary Temperature High Range"
            assert msg.fields[0].id == "manufacturer_code"
            assert msg.fields[0].part_of_primary_key
            assert msg.fields[6].value == 0.1
            assert msg.fields[7].value == 0.4
        else:
            assert msg is None
    assert counter == 32
    
