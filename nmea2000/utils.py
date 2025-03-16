# Standard Library Imports

from datetime import date, timedelta
import struct
import math
from datetime import time

def kelvin_to_fahrenheit(kelvin):
    """
    Converts temperature from Kelvin to Fahrenheit.
    Returns:
        float: The temperature in Fahrenheit.
    """
    if kelvin is None:
        return None
    
    # Convert Kelvin to Fahrenheit
    fahrenheit = round((kelvin - 273.15) * (9/5) + 32,0)

    return fahrenheit


def kelvin_to_celsius(kelvin):
    """
    Converts temperature from Kelvin to Celsius.
    Returns:
        float: The temperature in Celsius.
    """
    if kelvin is None:
        return None

    # Convert Kelvin to Celsius
    celsius = round(kelvin - 273.15,1)

    return celsius

def mps_to_knots(mps):
    """
    Converts speed from meters per second (m/s) to nautical knots.
    Returns:
        float: The speed in nautical knots, rounded to one decimal place.
    """
    if mps is None:
        return None
    
    # Conversion factor from m/s to knots
    conversion_factor = 3600 / 1852
    
    # Convert m/s to knots and round to one decimal place
    knots = round(mps * conversion_factor, 1)

    return knots


def radians_to_degrees(radians):
    """
    Converts an angle from radians to degrees.
    Returns:
        float: The angle in degrees.
    """
    if radians is None:
        return None

    # Convert radians to degrees
    degrees = round(math.degrees(radians), 0)
    return degrees

def decode_date(days_since_epoch: int) -> date:
    """
    Decodes an integer representing the number of days since 1970-01-01 (UNIX epoch)
    """
    # Ensure the input is treated as an integer
    days_since_epoch = int(days_since_epoch)
    
    # Define the start date as 1970-01-01
    start_date = date(1970, 1, 1)
    
    # Calculate the decoded date by adding the days to the start date
    decoded_date = start_date + timedelta(days=days_since_epoch)

    # Format and return the date string
    return decoded_date

def encode_date(decoded_date: date) -> int:
    """
    Encodes a date into an integer representing the number of days since 1970-01-01 (UNIX epoch)
    """
    # Define the start date as 1970-01-01
    start_date = date(1970, 1, 1)
    
    # Calculate the number of days since the start date
    days_since_epoch = (decoded_date - start_date).days

    return days_since_epoch


def decode_time(seconds_since_midnight: int) -> time:
    """
    Decodes an integer representing seconds since midnight into a time object.
    Returns:
        time: The decoded time.
    """
    # Ensure the input is treated as an integer
    seconds_since_midnight = int(seconds_since_midnight)

    # Validate input
    if not (0 <= seconds_since_midnight < 86400):  # There are 86400 seconds in a day
        return "0:0:0"

    hours = seconds_since_midnight // 3600  # 3600 seconds in an hour
    minutes = (seconds_since_midnight % 3600) // 60
    seconds = seconds_since_midnight % 60

    return time(hour=hours, minute=minutes, second=seconds)

def encode_time(time: time) -> int:
    """
    Encodes a time object into an integer representing the number of seconds since midnight.
    Returns:
        int: The number of seconds since midnight.
    """
    if time is None:
        return None

    # Calculate the number of seconds since midnight
    seconds_since_midnight = time.hour * 3600 + time.minute * 60 + time.second

    return seconds_since_midnight



def decode_decimal(number_int):
    """
    Decodes a numeric value where each byte represents 2 decimal digits in BCD format.
    """
    if number_int is None:
        return None

    decimal_value = 0
    multiplier = 1

    while number_int > 0:
        byte = number_int & 0xFF
        decimal_value += ((byte >> 4) * 10 + (byte & 0x0F)) * multiplier
        number_int >>= 8
        multiplier *= 100

    return decimal_value

def encode_decimal(decimal_value):
    """
    Encodes a numeric value into BCD format where each byte represents 2 decimal digits.
    """
    if decimal_value is None:
        return None

    number_int = 0
    shift = 0

    while decimal_value > 0:
        two_digits = decimal_value % 100
        bcd_byte = ((two_digits // 10) << 4) | (two_digits % 10)
        number_int |= (bcd_byte << shift)
        decimal_value //= 100
        shift += 8

    return number_int

def decode_float(number_int):
    """
    Decodes a 32-bit integer representing an IEEE-754 floating-point number in little endian format into a Python float.
    """
    # Ensure the input integer fits in 32 bits
    if not (0 <= number_int <= 0xFFFFFFFF):
        return 0

    # Convert the integer to bytes. The '<I' format specifies little-endian unsigned 32-bit integer.
    bytes_data = struct.pack('<I', number_int)

    # Unpack the bytes to a float using the '<f' format which specifies little-endian 32-bit floating point.
    decoded_float, = struct.unpack('<f', bytes_data)

    return decoded_float

def encode_float(float_number):
    """
    Encodes a Python float into a 32-bit integer representing an IEEE-754 floating-point number in little endian format.
    """
    if float_number is None:
        return None

    # Pack the float into bytes using the '<f' format which specifies little-endian 32-bit floating point.
    bytes_data = struct.pack('<f', float_number)

    # Unpack the bytes to an integer using the '<I' format which specifies little-endian unsigned 32-bit integer.
    encoded_int, = struct.unpack('<I', bytes_data)

    return encoded_int


def decode_number(number_int, bit_length) -> int:
    """
    The function follows specific decoding rules based on the bit length of the number:
    - For numbers using 2 or 3 bits, the maximum value indicates the field is not present (0 is returned).
    - For numbers using 4 bits or more, two special conditions are checked:
        - The maximum positive value indicates the field is not present (0 is returned).
    """

    if bit_length <= 3:
        if number_int == (1 << bit_length) - 1:
            return None
    elif bit_length >= 4:
        max_positive_value = (1 << bit_length) - 1
        if number_int == max_positive_value:
            return None
        elif number_int == max_positive_value - 1:
            return None

    return number_int
