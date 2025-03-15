import pytest
from nmea2000.decoder import NMEA2000Decoder, NMEA2000Message

def test_decode_strings_from_file():
    with open("tests\\recombine-frames-1.in", "r") as f:
        lines = f.read().splitlines()

    decoder = NMEA2000Decoder()
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
        elif counter == 8:
            assert isinstance(msg, NMEA2000Message)
            assert msg.PGN == 65280
            assert msg.priority == 7
            assert msg.source == 9
            assert msg.destination == 255
            assert msg.description == "Furuno: Heave"
        else:
            assert msg == None