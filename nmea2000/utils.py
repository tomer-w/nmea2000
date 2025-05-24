# Standard Library Imports

from datetime import date, timedelta
import struct
import math
from datetime import time
from typing import Optional, Tuple

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
    celsius = round(kelvin - 273.15,2)

    return celsius

def pascal_to_bar(pascal):
    if pascal is None:
        return None

    # Convert pascal to bar
    bar = pascal / 100000

    return bar

def pascal_to_PSI(pascal):
    if pascal is None:
        return None

    # Convert pascal to PSI
    PSI = pascal / 6894.76

    return PSI

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

def decode_int(data_raw: int, bit_offset: int, bit_length: int):
    data_raw = data_raw >> bit_offset
    # Create a mask with the desired number of bits set to 1
    mask = (1 << bit_length) - 1
    # Perform bitwise AND with the mask
    result = data_raw & mask
    return result

def decode_date(days_since_epoch: int | float | None) -> date | None:
    """
    Decodes an integer representing the number of days since 1970-01-01 (UNIX epoch)
    """
    if days_since_epoch is None:
        return None
    
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


def decode_time(seconds_since_midnight: int | float | None) -> time | None:
    """
    Decodes an integer representing seconds since midnight into a time object.
    Returns:
        time: The decoded time.
    """
    if seconds_since_midnight is None:
        return None

    # Ensure the input is treated as an integer
    seconds_since_midnight = int(seconds_since_midnight)

    # Validate input
    if not (0 <= seconds_since_midnight < 86400):  # There are 86400 seconds in a day
        return time(hour=0, minute=0, second=0)

    hours = seconds_since_midnight // 3600  # 3600 seconds in an hour
    minutes = (seconds_since_midnight % 3600) // 60
    seconds = seconds_since_midnight % 60

    return time(hour=hours, minute=minutes, second=seconds)

def encode_time(time: time, bit_length: int) -> int:
    """
    Encodes a time object into an integer representing the number of seconds since midnight.
    Returns:
        int: The number of seconds since midnight.
    """
    if time is None:
        # Set to "not available" value
        return (1 << bit_length) - 1

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

def decode_float(data_raw: int, bit_offset: int, bit_length: int):
    """
    Decodes a 32-bit integer representing an IEEE-754 floating-point number in little endian format into a Python float.
    """
    number_int = decode_int(data_raw, bit_offset, bit_length)
    # Ensure the input integer fits in 32 bits
    if not (0 <= number_int <= 0xFFFFFFFF):
        return 0

    # Convert the integer to bytes. The '<I' format specifies little-endian unsigned 32-bit integer.
    bytes_data = struct.pack('<I', number_int)

    # Unpack the bytes to a float using the '<f' format which specifies little-endian 32-bit floating point.
    decoded_float, = struct.unpack('<f', bytes_data)
    
    return decoded_float

def encode_float(float_number) -> int:
    """
    Encodes a Python float into a 32-bit integer representing an IEEE-754 floating-point number in little endian format.
    """
    if float_number is None:
        raise ValueError("Cannot encode None as a float")

    # Pack the float into bytes using the '<f' format which specifies little-endian 32-bit floating point.
    bytes_data = struct.pack('<f', float_number)

    # Unpack the bytes to an integer using the '<I' format which specifies little-endian unsigned 32-bit integer.
    encoded_int, = struct.unpack('<I', bytes_data)

    return encoded_int


def decode_number(data_raw: int, bit_offset: int, bit_length: int, signed: bool, resolution: float) -> Optional[float]:
    """
    The function follows specific decoding rules based on the bit length of the number:
    - For numbers using 2 or 3 bits, the maximum value indicates the field is not present (None is returned).
    - For numbers using 4 bits or more, the maximum positive value indicates the field is not present (None is returned).
    """
    number_int = decode_int(data_raw, bit_offset, bit_length)

    #make it signed using sign extension operation
    if signed:
        signed_mask = 1 << (bit_length -1)
        if number_int & signed_mask != 0:
            number_int -= (1 << bit_length)

    if bit_length <= 3:
        if number_int == (1 << bit_length) - 1:
            return None
    elif bit_length >= 4:
        max_positive_value = (1 << bit_length) - 1 if not signed else (1 << (bit_length - 1)) - 1
        if number_int == max_positive_value:
            return None

    # adjust resolution
    number_int *= resolution

    return number_int

def encode_number(
    value: Optional[float],
    bit_length: int,
    signed: bool,
    resolution: float
) -> int:
    """
    Encodes a number into a bitfield within an integer.

    - If value is None, the field is set to the "not available" value per bit length.
    - Applies resolution scaling and sign encoding.
    - Modifies the bits in `data_raw` at the specified offset and returns the new value.
    """
    if value is None:
        # Set to "not available" value
        if bit_length <= 3:
            return (1 << bit_length) - 1
        elif signed:
            return (1 << (bit_length - 1)) - 1
        else:
            return (1 << bit_length) - 1

    # Scale using resolution
    number_int = int(round(value / resolution))

    # Check bounds
    if signed:
        min_val = -(1 << (bit_length - 1))
        max_val = (1 << (bit_length - 1)) - 2  # reserve max for "not available"
    else:
        min_val = 0
        max_val = (1 << bit_length) - 2  # reserve max for "not available"

    if not (min_val <= number_int <= max_val):
        raise ValueError(f"Value {value} out of range after scaling")

    # Handle sign bit if negative
    if signed and number_int < 0:
        number_int = (1 << bit_length) + number_int

    return number_int

def decode_bit_lookup(data_raw: int, bit_lookup_dict) -> str:
    bit = 0
    flags = []
    while data_raw !=0:
        if data_raw & 1 == 1:
            str = bit_lookup_dict.get(bit, None)
            if str is not None:
                flags.append(str)
        bit +=1
        data_raw >>= 1
    return ', '.join(flags)

def decode_string_fix(data_raw: int, bit_offset: int, bit_length: int) -> str:
    number_int = decode_int(data_raw, bit_offset, bit_length)
    num_bytes = (bit_length + 7) // 8
    byte_arr = number_int.to_bytes(num_bytes, 'little')
    decoded_str = byte_arr.decode('utf-8', errors='ignore')
    decoded_str = decoded_str.split('\x00', 1)[0]
    decoded_str = decoded_str.split('\xff', 1)[0]
    decoded_str = decoded_str.split('@', 1)[0]
    decoded_str = decoded_str.strip()
    return decoded_str
    
def decode_string_lz(data_raw: int, bit_offset: int) -> str:
    data_raw = data_raw >> bit_offset
    byte_arr = data_raw.to_bytes((data_raw.bit_length() + 7) // 8, byteorder="little")
    str_len = byte_arr[0]
    byte_arr_str = byte_arr[1 : 1 + str_len]
    decoded_str = byte_arr_str.decode('utf-8', errors='ignore')
    return decoded_str
    
def decode_string_lau(data_raw: int, bit_offset: int) -> Tuple[str | None, int]:
    data_raw = data_raw >> bit_offset
    byte_arr = data_raw.to_bytes(((data_raw.bit_length() + 7) // 8)+1, byteorder='little')
    if len(byte_arr) < 2:
        return None, len(byte_arr)
    str_len = byte_arr[0]
    is_asci = byte_arr[1]
    byte_arr_str = byte_arr[2 : str_len]
    if is_asci:
        decoded_str = byte_arr_str.decode('utf-8', errors='ignore')
    else:
        decoded_str = byte_arr_str.decode('utf-16', errors='ignore')
    return decoded_str, str_len*8
    
