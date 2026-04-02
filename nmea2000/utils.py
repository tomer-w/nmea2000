# Standard Library Imports

from datetime import date, timedelta
import struct
import math
from datetime import time

def kelvin_to_fahrenheit(kelvin: float | None) -> float | None:
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


def kelvin_to_celsius(kelvin: float | None) -> float | None:
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

def pascal_to_bar(pascal: float | None) -> float | None:
    if pascal is None:
        return None

    # Convert pascal to bar
    bar = pascal / 100000

    return bar

def pascal_to_PSI(pascal: float | None) -> float | None:
    if pascal is None:
        return None

    # Convert pascal to PSI
    PSI = pascal / 6894.76

    return PSI

def mps_to_knots(mps: float | None) -> float | None:
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


def radians_to_degrees(radians: float | None) -> float | None:
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

def decode_int(data_raw: int, bit_offset: int, bit_length: int) -> int:
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

def encode_date(decoded_date: date | None, bit_length: int = 16) -> int:
    """
    Encodes a date into an integer representing the number of days since 1970-01-01 (UNIX epoch)
    """
    if decoded_date is None:
        return (1 << bit_length) - 1

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

def encode_time(time: time | None, bit_length: int) -> int:
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



def decode_decimal(number_int: int | None) -> int | None:
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

def encode_decimal(decimal_value: int | float | None) -> int | None:
    """
    Encodes a numeric value into BCD format where each byte represents 2 decimal digits.
    """
    if decimal_value is None:
        return None

    number_int = 0
    shift = 0

    while decimal_value > 0:
        two_digits = int(decimal_value % 100)
        bcd_byte = ((two_digits // 10) << 4) | (two_digits % 10)
        number_int |= (bcd_byte << shift)
        decimal_value //= 100
        shift += 8

    return number_int

def decode_float(data_raw: int, bit_offset: int, bit_length: int, min_value: float, max_value: float) -> float:
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

    if decoded_float < min_value:
        raise ValueError("Value below minimum allowed")
    if decoded_float > max_value:
        raise ValueError("Value above maximum allowed")

    return decoded_float

def encode_float(float_number: float | None) -> int:
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


def decode_number(data_raw: int, bit_offset: int, bit_length: int, signed: bool, resolution: float, min_value: float, max_value: float) -> float | None:
    """
    The function follows specific decoding rules based on the bit length of the number:
    - For numbers using 2 or 3 bits, the maximum value indicates the field is not present (None is returned).
    - For numbers using 4 bits or more, the maximum positive value indicates the field is not present (None is returned).
    """
    number_int = decode_int(data_raw, bit_offset, bit_length)

    # make it signed using sign extension operation
    if signed:
        signed_mask = 1 << (bit_length - 1)
        if number_int & signed_mask != 0:
            number_int -= (1 << bit_length)

    if bit_length <= 3:
        if number_int == (1 << bit_length) - 1:
            return None
    elif bit_length >= 4:
        max_positive_value = (1 << bit_length) - 1 if not signed else (1 << (bit_length - 1)) - 1
        if number_int in (max_positive_value, max_positive_value - 1):
            return None

    # adjust resolution
    number_int *= resolution

    if number_int < min_value:
        raise ValueError("Value below minimum allowed")
    if number_int > max_value:
        raise ValueError("Value above maximum allowed")

    return number_int

def encode_number(
    value: float | None,
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


def encode_number_raw(raw_value: int | float | None, bit_length: int, signed: bool) -> int:
    if raw_value is None:
        return encode_number(None, bit_length, signed, 1)

    if isinstance(raw_value, float):
        if not raw_value.is_integer():
            raise ValueError(f"Raw value {raw_value} must be an integer")
        raw_value = int(raw_value)

    if not isinstance(raw_value, int):
        raise ValueError(f"Raw value {raw_value} must be an integer")

    if signed:
        min_val = -(1 << (bit_length - 1))
        max_val = (1 << (bit_length - 1)) - 2
    else:
        min_val = 0
        max_val = (1 << bit_length) - 2

    if not (min_val <= raw_value <= max_val):
        raise ValueError(f"Raw value {raw_value} out of range")

    if signed and raw_value < 0:
        raw_value = (1 << bit_length) + raw_value

    return raw_value


def raw_number_matches_value(raw_value: int | float | None, value: float | None, resolution: float) -> bool:
    if not isinstance(raw_value, int):
        return False
    if value is None:
        return False
    return math.isclose(
        raw_value * resolution,
        value,
        rel_tol=0.0,
        abs_tol=max(abs(resolution) * 50, 1e-3),
    )

def decode_bit_lookup(data_raw: int, bit_lookup_dict: dict) -> str:
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
    decoded_str, _ = decode_string_fix_raw(data_raw, bit_offset, bit_length)
    return decoded_str


def decode_string_fix_raw(data_raw: int, bit_offset: int, bit_length: int) -> tuple[str, bytes]:
    number_int = decode_int(data_raw, bit_offset, bit_length)
    num_bytes = (bit_length + 7) // 8
    byte_arr = number_int.to_bytes(num_bytes, 'little')
    decoded_str = byte_arr.decode('utf-8', errors='ignore')
    decoded_str = decoded_str.split('\x00', 1)[0]
    decoded_str = decoded_str.split('\xff', 1)[0]
    decoded_str = decoded_str.split('@', 1)[0]
    decoded_str = decoded_str.strip()
    return decoded_str, byte_arr
    
def decode_string_lz(data_raw: int, bit_offset: int) -> str:
    data_raw = data_raw >> bit_offset
    byte_arr = data_raw.to_bytes((data_raw.bit_length() + 7) // 8, byteorder="little")
    str_len = byte_arr[0]
    byte_arr_str = byte_arr[1 : 1 + str_len]
    decoded_str = byte_arr_str.decode('utf-8', errors='ignore')
    return decoded_str
    
def decode_string_lau(data_raw: int, bit_offset: int) -> tuple[str | None, int]:
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
    

def calculate_canbus_checksum(data) -> int:
    checksum = sum(data[2:19])
    return checksum & 0xff


def encode_string_fix(value: str | bytes | bytearray | memoryview | None, bit_length: int) -> int:
    if value is None:
        encoded = b""
    elif isinstance(value, memoryview):
        encoded = value.tobytes()
    elif isinstance(value, (bytes, bytearray)):
        encoded = bytes(value)
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        raise ValueError(f"Cannot encode STRING_FIX from {type(value).__name__}")

    byte_length = (bit_length + 7) // 8
    if len(encoded) > byte_length:
        raise ValueError(f"STRING_FIX value is too long for {byte_length} bytes")

    return int.from_bytes(encoded.ljust(byte_length, b"\x00"), byteorder="little", signed=False)


def encode_string_lz(value: str | bytes | bytearray | memoryview | None) -> bytes:
    if value is None:
        return b"\x00\x00"
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        raise ValueError(f"Cannot encode STRING_LZ from {type(value).__name__}")

    encoded = value.encode("utf-8")
    if len(encoded) > 0xFF:
        raise ValueError("STRING_LZ value is too long")
    return bytes([len(encoded)]) + encoded + b"\x00"


def encode_string_lau(value: str | bytes | bytearray | memoryview | None) -> bytes:
    if value is None:
        return b"\x02\x01"
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        raise ValueError(f"Cannot encode STRING_LAU from {type(value).__name__}")

    try:
        encoded = value.encode("ascii")
        is_ascii = 1
    except UnicodeEncodeError:
        encoded = value.encode("utf-16-le")
        is_ascii = 0

    total_length = len(encoded) + 2
    if total_length > 0xFF:
        raise ValueError("STRING_LAU value is too long")
    return bytes([total_length, is_ascii]) + encoded


def encode_bit_lookup(value, bit_lookup_dict: dict[int, str]) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value

    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raise ValueError(f"Cannot encode BITLOOKUP from {type(value).__name__}")

    reverse_lookup = {name: bit for bit, name in bit_lookup_dict.items()}
    encoded_value = 0
    for item in items:
        if isinstance(item, int):
            encoded_value |= 1 << item
            continue

        bit = reverse_lookup.get(str(item).strip())
        if bit is None:
            raise ValueError(f"Unknown BITLOOKUP value: {item}")
        encoded_value |= 1 << bit

    return encoded_value


def normalize_binary_data(value: bytes | bytearray | memoryview | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise ValueError(f"Cannot encode binary data from {type(value).__name__}")


def encode_binary_data(value: bytes | bytearray | memoryview | None) -> int:
    payload = normalize_binary_data(value)
    if not payload:
        return 0
    return int.from_bytes(payload, byteorder="big", signed=False)


def encode_little_endian_data(value: bytes | bytearray | memoryview | None) -> int:
    payload = normalize_binary_data(value)
    if not payload:
        return 0
    return int.from_bytes(payload, byteorder="little", signed=False)


def binary_data_bit_length(value: bytes | bytearray | memoryview | None) -> int:
    return len(normalize_binary_data(value)) * 8


def encode_iso_name(value) -> int:
    if value is None:
        raise ValueError("Cannot encode None as ISO_NAME")

    iso_name = getattr(value, "name", None)
    if isinstance(iso_name, int):
        value = iso_name

    if not isinstance(value, int):
        raise ValueError(f"Cannot encode ISO_NAME from {type(value).__name__}")
    if value < 0:
        raise ValueError("ISO_NAME cannot be negative")

    return value

