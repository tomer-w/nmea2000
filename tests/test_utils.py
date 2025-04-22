from datetime import date, time
import pytest
from nmea2000.utils import decode_decimal, encode_decimal, decode_float, encode_float, decode_date, encode_date, decode_time, encode_time

def test_decode_decimal_single_byte():
    assert decode_decimal(0x12) == 12

def test_decode_decimal_multiple_bytes():
    assert decode_decimal(0x1234) == 1234

def test_decode_decimal_leading_zero():
    assert decode_decimal(0x0123) == 123

def test_decode_decimal_all_zeros():
    assert decode_decimal(0x0000) == 0

def test_decode_decimal_large_number():
    assert decode_decimal(0x12345678) == 12345678

def test_decode_decimal_zero():
    assert decode_decimal(0x00) == 0

def test_encode_decimal_single_byte():
    assert encode_decimal(12) == 0x12

def test_encode_decimal_multiple_bytes():
    assert encode_decimal(1234) == 0x1234

def test_encode_decimal_leading_zero():
    assert encode_decimal(123) == 0x0123

def test_encode_decimal_all_zeros():
    assert encode_decimal(0) == 0x0000

def test_encode_decimal_large_number():
    assert encode_decimal(12345678) == 0x12345678

def test_encode_decode_decimal():
    for i in range (0,99999):
         assert decode_decimal(encode_decimal(i)) == i

def test_decode_float_zero():
    assert decode_float(0x00000000, 0, 32) == 0.0

def test_decode_float_positive():
    assert decode_float(0x3f800000, 0, 32) == 1.0

def test_decode_float_negative():
    assert decode_float(0xbf800000, 0, 32) == -1.0

def test_decode_float_small():
    assert decode_float(0x00000001, 0, 32) == 1.401298464324817e-45

def test_encode_float_zero():
    assert encode_float(0.0) == 0x00000000

def test_encode_float_positive():
    assert encode_float(1.0) == 0x3f800000

def test_encode_float_negative():
    assert encode_float(-1.0) == 0xbf800000

def test_encode_float_large():
    assert encode_float(3.4028235e+38) == 0x7f7fffff

def test_encode_float_small():
    assert encode_float(1.401298464324817e-45) == 0x00000001

def test_encode_decode_float():
    test_values = [0.0, 1.0, -1.0, 3.4028235e+38, 1.401298464324817e-45]
    for value in test_values:
        assert decode_float(encode_float(value), 0, 32) == pytest.approx(value)

def test_encode_date():
    assert encode_date(date(2023, 10, 5)) == 19635

def test_decode_date():
    assert decode_date(19635) == date(2023, 10, 5)

def test_encode_decode_date():
    test_dates = [date(2023, 10, 5), date(2000, 1, 1), date(1999, 12, 31)]
    for test_date in test_dates:
        assert decode_date(encode_date(test_date)) == test_date

def test_encode_time():
    assert encode_time(time(14, 30, 15), 16) == 52215

def test_encode_time_empty():
    assert encode_time(None, 16) == 65535

def test_decode_time():
    assert decode_time(52215) == time(14, 30, 15)

def test_encode_decode_time():
    test_times = [(14, 30, 15), (0, 0, 0), (23, 59, 59)]
    for hour, minute, second in test_times:
        assert decode_time(encode_time(time(hour, minute, second), 16)) == time(hour, minute, second)