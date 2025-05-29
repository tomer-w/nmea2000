from datetime import date, time
from nmea2000.decoder import NMEA2000Message
from nmea2000.encoder import NMEA2000Encoder
from .test_decoder import _get_decoder

def _validate_129029_message(msg: NMEA2000Message | None):
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
            assert msg.description == "0x1EF00: Manufacturer Proprietary fast-packet addressed"
            assert msg.fields[0].value == "Garmin"
            assert msg.fields[1].value == 3
            assert msg.fields[2].value == "Marine"
        else:
            assert msg is None
    assert counter == 16

def test_decode_strings_from_file_2_exclude_id():
    with open("tests/recombine-frames-2.in", "r") as f:
        lines = f.read().splitlines()

    decoder = _get_decoder(exclude_pgns=["0x1ef00ManufacturerProprietaryFastPacketAddressed"])
    counter = 0
    for line in lines:
        input_data = line.strip()
        if input_data.startswith('#') or len(input_data) <= 1:
            continue
        counter += 1
        msg = decoder.decode_basic_string(input_data)
        if counter == 11:
            _validate_129029_message(msg)
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
            assert msg.fields[0].id == "manufacturerCode"
            assert msg.fields[0].part_of_primary_key
            assert msg.fields[6].value == 0.1
            assert msg.fields[7].value == 0.4
        else:
            assert msg is None
    assert counter == 32
    
def test_encode_fast():
    json = '{"PGN":129029,"id":"gnssPositionData","description":"GNSS Position Data","fields":[{"id":"sid","name":"SID","description":null,"unit_of_measurement":null,"value":231,"raw_value":231,"physical_quantities":null,"type":[1],"part_of_primary_key":false},{"id":"date","name":"Date","description":null,"unit_of_measurement":"d","value":"2013-03-01","raw_value":15765,"physical_quantities":[18],"type":[9],"part_of_primary_key":false},{"id":"time","name":"Time","description":"Seconds since midnight","unit_of_measurement":"s","value":"19:29:52","raw_value":70192.0,"physical_quantities":[19],"type":[8],"part_of_primary_key":false},{"id":"latitude","name":"Latitude","description":null,"unit_of_measurement":"deg","value":42.496768422109845,"raw_value":42.496768422109845,"physical_quantities":[20],"type":[1],"part_of_primary_key":false},{"id":"longitude","name":"Longitude","description":null,"unit_of_measurement":"deg","value":-71.58366365704198,"raw_value":-71.58366365704198,"physical_quantities":[20],"type":[1],"part_of_primary_key":false},{"id":"altitude","name":"Altitude","description":"Altitude referenced to WGS-84","unit_of_measurement":"m","value":90.98460299999999,"raw_value":90.98460299999999,"physical_quantities":[10],"type":[1],"part_of_primary_key":false},{"id":"gnssType","name":"GNSS type","description":null,"unit_of_measurement":null,"value":"GPS+SBAS/WAAS","raw_value":3,"physical_quantities":null,"type":[4],"part_of_primary_key":false},{"id":"method","name":"Method","description":null,"unit_of_measurement":null,"value":"GNSS fix","raw_value":1,"physical_quantities":null,"type":[4],"part_of_primary_key":false},{"id":"integrity","name":"Integrity","description":null,"unit_of_measurement":null,"value":"No integrity checking","raw_value":0,"physical_quantities":null,"type":[4],"part_of_primary_key":false},{"id":"reserved_258","name":"Reserved","description":null,"unit_of_measurement":null,"value":63,"raw_value":63,"physical_quantities":null,"type":[14],"part_of_primary_key":false},{"id":"numberOfSvs","name":"Number of SVs","description":"Number of satellites used in solution","unit_of_measurement":null,"value":8,"raw_value":8,"physical_quantities":null,"type":[1],"part_of_primary_key":false},{"id":"hdop","name":"HDOP","description":"Horizontal dilution of precision","unit_of_measurement":null,"value":1.11,"raw_value":1.11,"physical_quantities":null,"type":[1],"part_of_primary_key":false},{"id":"pdop","name":"PDOP","description":"Positional dilution of precision","unit_of_measurement":null,"value":1.9000000000000001,"raw_value":1.9000000000000001,"physical_quantities":null,"type":[1],"part_of_primary_key":false},{"id":"geoidalSeparation","name":"Geoidal Separation","description":"Geoidal Separation","unit_of_measurement":"m","value":-33.63,"raw_value":-33.63,"physical_quantities":[10],"type":[1],"part_of_primary_key":false},{"id":"referenceStations","name":"Reference Stations","description":"Number of reference stations","unit_of_measurement":null,"value":0,"raw_value":0,"physical_quantities":null,"type":[1],"part_of_primary_key":false},{"id":"referenceStationType","name":"Reference Station Type","description":null,"unit_of_measurement":null,"value":null,"raw_value":15,"physical_quantities":null,"type":[4],"part_of_primary_key":false},{"id":"referenceStationId","name":"Reference Station ID","description":null,"unit_of_measurement":null,"value":null,"raw_value":null,"physical_quantities":null,"type":[1],"part_of_primary_key":false},{"id":"ageOfDgnssCorrections","name":"Age of DGNSS Corrections","description":null,"unit_of_measurement":"s","value":null,"raw_value":null,"physical_quantities":[19],"type":[8],"part_of_primary_key":false}],"source":0,"destination":255,"priority":3,"timestamp":"2022-09-28T11:36:59.668000"}'
    msg1 = NMEA2000Message.from_json(json)
    encoder = NMEA2000Encoder()
    msg_packets = encoder.encode_ebyte(msg1)
    decoder = _get_decoder()
    for msg_bytes in msg_packets:
        msg2 = decoder.decode_tcp(msg_bytes)
    assert isinstance(msg2, NMEA2000Message)
    _validate_129029_message(msg2)
