import binascii

# NMEA2000Message class represent a single NMEA 2000 PGN
class NMEA2000Message():
    def __init__(
        self,
        PGN,
        id, 
        description, 
    ):
        """Initialize the NMEA2000Message."""
        self.PGN = PGN
        self.id = id
        self.description = description
        self.fields = []

    def add_data(self, src, dest, priority):
        self.source = src
        self.destination = dest
        self.priority = priority
        
    def __repr__(self):
        return f"NMEA2000Message(PGN={self.PGN}, id={self.id}, description={self.description}, fields={self.fields})"        

    def to_string_test_style(self):
        fields_str = ', '.join([field.to_string_test_style() for field in self.fields])
        return f"{self.PGN} {self.description}:  {fields_str}"
    
# NMEA2000Field class represent a single NMEA 2000 field
class NMEA2000Field():
    def __init__(
        self, 
        id, 
        name, 
        description, 
        unit_of_measurement, 
        value,
        raw_value 
    ):
        """Initialize the field."""
        self.id = id
        self.name = name
        self.description = description
        self.unit_of_measurement = unit_of_measurement
        self.value = value
        self.raw_value = raw_value

    def __repr__(self):
        return f"NMEA2000Field(id={self.id}, name={self.name}, description={self.description}, unit_of_measurement={self.unit_of_measurement}, value={self.value}, raw_value={self.raw_value})"

    def to_string_test_style(self):
 #       raw_value_hex = hex(int(self.raw_value)) if isinstance(self.raw_value, int) else self.raw_value
        if isinstance(self.raw_value, int):
            # Determine the number of bytes needed
            byte_length = (self.raw_value.bit_length() + 8) // 8 or 1

            # Convert integer to bytes (big-endian)
            value_bytes = int_to_bytes(self.raw_value, byte_length)

            # Use binascii.hexlify to convert bytes to hex
            hex_value = binascii.hexlify(value_bytes, " ").upper()

            # Convert hex bytes to a string (if needed)
            raw_value_hex = hex_value.decode('utf-8')
        else:
            raw_value_hex = self.raw_value
        return f'{self.name} = {self.value} (bytes = "{raw_value_hex}")'
    
def int_to_bytes(value, length):
    result = value.to_bytes(length, byteorder='little', signed=True)
    return result

