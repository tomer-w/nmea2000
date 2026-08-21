from datetime import date, time

import pytest

from nmea2000.utils import (
    decode_date,
    decode_decimal,
    decode_float,
    decode_number,
    decode_time,
    encode_date,
    encode_decimal,
    encode_float,
    encode_time,
)


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
    for i in range(99999):
        encoded = encode_decimal(i)
        assert encoded is not None
        assert decode_decimal(encoded) == i


def test_decode_float_zero():
    assert decode_float(0x00000000, 0, 32, 0, 1) == 0.0


def test_decode_float_positive():
    assert decode_float(0x3F800000, 0, 32, 0, 5) == 1.0


def test_decode_float_negative():
    assert decode_float(0xBF800000, 0, 32, -5, 5) == -1.0


def test_decode_float_small():
    assert decode_float(0x00000001, 0, 32, 0, 2) == 1.401298464324817e-45


def test_encode_float_zero():
    assert encode_float(0.0) == 0x00000000


def test_encode_float_positive():
    assert encode_float(1.0) == 0x3F800000


def test_encode_float_negative():
    assert encode_float(-1.0) == 0xBF800000


def test_encode_float_large():
    assert encode_float(3.4028235e38) == 0x7F7FFFFF


def test_encode_float_small():
    assert encode_float(1.401298464324817e-45) == 0x00000001


def test_encode_decode_float():
    test_values = [0.0, 1.0, -1.0, 3.4028235e38, 1.401298464324817e-45]
    for value in test_values:
        assert decode_float(encode_float(value), 0, 32, -100, 5.0e45) == pytest.approx(
            value
        )


def test_encode_date():
    assert encode_date(date(2023, 10, 5)) == 19635


def test_encode_date_from_iso_string():
    assert encode_date("2023-10-05") == 19635


def test_encode_date_rejects_invalid_iso_string():
    with pytest.raises(ValueError):
        encode_date("2023-02-30")


def test_decode_date():
    assert decode_date(19635) == date(2023, 10, 5)


def test_encode_decode_date():
    test_dates = [date(2023, 10, 5), date(2000, 1, 1), date(1999, 12, 31)]
    for test_date in test_dates:
        assert decode_date(encode_date(test_date)) == test_date


def test_encode_time():
    assert encode_time(time(14, 30, 15), 16) == 52215


def test_encode_time_from_iso_string():
    assert encode_time("14:30:15", 16) == 52215


def test_encode_time_from_fractional_iso_string():
    assert encode_time("14:30:15.5", 32, 0.0001) == 522155000


def test_encode_time_rejects_invalid_iso_string():
    with pytest.raises(ValueError):
        encode_time("25:00:00", 16)


def test_encode_time_empty():
    assert encode_time(None, 16) == 65535


def test_decode_time():
    assert decode_time(52215) == time(14, 30, 15)


def test_encode_decode_time():
    test_times = [(14, 30, 15), (0, 0, 0), (23, 59, 59)]
    for hour, minute, second in test_times:
        assert decode_time(encode_time(time(hour, minute, second), 16)) == time(
            hour, minute, second
        )


def test_decode_number_8bit_not_available_sentinels():
    # 8-bit unsigned fields reserve 0xFF and 0xFE as not available/error values.
    assert decode_number(0xFF, 0, 8, False, 1, 0, 252) is None
    assert decode_number(0xFE, 0, 8, False, 1, 0, 252) is None


def test_decode_number_16bit_not_available_sentinels_with_resolution():
    # 16-bit unsigned fields reserve 0xFFFF and 0xFFFE as not available/error values.
    assert decode_number(0xFFFF, 0, 16, False, 60, 0, 3931920) is None
    assert decode_number(0xFFFE, 0, 16, False, 60, 0, 3931920) is None
