# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring
"""Verify utility encoders and decoders for numeric, date, and time fields."""

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
    """Decodes a one-byte BCD value into its integer representation."""
    assert decode_decimal(0x12) == 12


def test_decode_decimal_multiple_bytes():
    """Decodes a multi-byte BCD value into its integer representation."""
    assert decode_decimal(0x1234) == 1234


def test_decode_decimal_leading_zero():
    """Drops leading zero digits when decoding a BCD value."""
    assert decode_decimal(0x0123) == 123


def test_decode_decimal_all_zeros():
    """Returns zero when every decoded BCD digit is zero."""
    assert decode_decimal(0x0000) == 0


def test_decode_decimal_large_number():
    """Decodes larger BCD values without truncating digits."""
    assert decode_decimal(0x12345678) == 12345678


def test_decode_decimal_zero():
    """Decodes a zero BCD byte to integer zero."""
    assert decode_decimal(0x00) == 0


def test_encode_decimal_single_byte():
    """Encodes a two-digit integer into a one-byte BCD value."""
    assert encode_decimal(12) == 0x12


def test_encode_decimal_multiple_bytes():
    """Encodes a multi-digit integer into a multi-byte BCD value."""
    assert encode_decimal(1234) == 0x1234


def test_encode_decimal_leading_zero():
    """Preserves leading zero digits required by the target BCD width."""
    assert encode_decimal(123) == 0x0123


def test_encode_decimal_all_zeros():
    """Encodes integer zero as an all-zero BCD value."""
    assert encode_decimal(0) == 0x0000


def test_encode_decimal_large_number():
    """Encodes larger integers into BCD without losing digits."""
    assert encode_decimal(12345678) == 0x12345678


def test_encode_decode_decimal():
    """Round-trips BCD encoding and decoding across a broad integer range."""
    for i in range(99999):
        encoded = encode_decimal(i)
        assert encoded is not None
        assert decode_decimal(encoded) == i


def test_decode_float_zero():
    """Decodes the IEEE 754 zero bit pattern to 0.0."""
    assert decode_float(0x00000000, 0, 32, 0, 1) == 0.0


def test_decode_float_positive():
    """Decodes the IEEE 754 bit pattern for positive one."""
    assert decode_float(0x3F800000, 0, 32, 0, 5) == 1.0


def test_decode_float_negative():
    """Decodes the IEEE 754 bit pattern for negative one."""
    assert decode_float(0xBF800000, 0, 32, -5, 5) == -1.0


def test_decode_float_small():
    """Decodes the smallest positive subnormal IEEE 754 value."""
    assert decode_float(0x00000001, 0, 32, 0, 2) == 1.401298464324817e-45


def test_encode_float_zero():
    """Encodes 0.0 to the IEEE 754 zero bit pattern."""
    assert encode_float(0.0) == 0x00000000


def test_encode_float_positive():
    """Encodes positive one to its IEEE 754 bit pattern."""
    assert encode_float(1.0) == 0x3F800000


def test_encode_float_negative():
    """Encodes negative one to its IEEE 754 bit pattern."""
    assert encode_float(-1.0) == 0xBF800000


def test_encode_float_large():
    """Encodes the largest finite single-precision float correctly."""
    assert encode_float(3.4028235e38) == 0x7F7FFFFF


def test_encode_float_small():
    """Encodes the smallest positive subnormal single-precision float."""
    assert encode_float(1.401298464324817e-45) == 0x00000001


def test_encode_decode_float():
    """Round-trips representative float values through IEEE 754 encoding."""
    test_values = [0.0, 1.0, -1.0, 3.4028235e38, 1.401298464324817e-45]
    for value in test_values:
        assert decode_float(encode_float(value), 0, 32, -100, 5.0e45) == pytest.approx(
            value
        )


def test_encode_date():
    """Encodes a date object as NMEA 2000 days since epoch."""
    assert encode_date(date(2023, 10, 5)) == 19635


def test_encode_date_from_iso_string():
    """Accepts an ISO date string when encoding a date field."""
    assert encode_date("2023-10-05") == 19635


def test_encode_date_rejects_invalid_iso_string():
    """Rejects ISO date strings that do not represent a valid calendar date."""
    with pytest.raises(ValueError):
        encode_date("2023-02-30")


def test_decode_date():
    """Decodes an NMEA 2000 day count back into a date object."""
    assert decode_date(19635) == date(2023, 10, 5)


def test_encode_decode_date():
    """Round-trips representative date values through NMEA 2000 date encoding."""
    test_dates = [date(2023, 10, 5), date(2000, 1, 1), date(1999, 12, 31)]
    for test_date in test_dates:
        assert decode_date(encode_date(test_date)) == test_date


def test_encode_time():
    """Encodes a time object at whole-second resolution."""
    assert encode_time(time(14, 30, 15), 16) == 52215


def test_encode_time_from_iso_string():
    """Accepts an ISO time string when encoding a time field."""
    assert encode_time("14:30:15", 16) == 52215


def test_encode_time_from_fractional_iso_string():
    """Preserves fractional seconds when the time resolution supports them."""
    assert encode_time("14:30:15.5", 32, 0.0001) == 522155000


def test_encode_time_rejects_invalid_iso_string():
    """Rejects ISO time strings with invalid clock values."""
    with pytest.raises(ValueError):
        encode_time("25:00:00", 16)


def test_encode_time_empty():
    """Encodes a missing time value using the not-available sentinel."""
    assert encode_time(None, 16) == 65535


def test_decode_time():
    """Decodes whole-second NMEA 2000 time values into time objects."""
    assert decode_time(52215) == time(14, 30, 15)


def test_encode_decode_time():
    """Round-trips representative clock times through NMEA 2000 time encoding."""
    test_times = [(14, 30, 15), (0, 0, 0), (23, 59, 59)]
    for hour, minute, second in test_times:
        assert decode_time(encode_time(time(hour, minute, second), 16)) == time(
            hour, minute, second
        )


def test_decode_number_8bit_not_available_sentinels():
    """Treats 8-bit not-available and error sentinel values as missing numbers."""
    # 8-bit unsigned fields reserve 0xFF and 0xFE as not available/error values.
    assert decode_number(0xFF, 0, 8, False, 1, 0, 252) is None
    assert decode_number(0xFE, 0, 8, False, 1, 0, 252) is None


def test_decode_number_16bit_not_available_sentinels_with_resolution():
    """Treats 16-bit not-available and error sentinels as missing numbers."""
    # 16-bit unsigned fields reserve 0xFFFF and 0xFFFE as not available/error values.
    assert decode_number(0xFFFF, 0, 16, False, 60, 0, 3931920) is None
    assert decode_number(0xFFFE, 0, 16, False, 60, 0, 3931920) is None
