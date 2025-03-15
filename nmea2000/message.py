import binascii
from dataclasses import dataclass, field
import orjson

# Helper function
def int_to_bytes(value, length):
    return value.to_bytes(length, byteorder="little", signed=True)

# NMEA2000Message class represents a single NMEA 2000 PGN
@dataclass
class NMEA2000Message:
    PGN: int
    id: str
    description: str
    fields: list = field(default_factory=list)
    source: int = 0
    destination: int = 0
    priority: int = 0

    def add_data(self, src, dest, priority):
        self.source = src
        self.destination = dest
        self.priority = priority

    def __repr__(self):
        return f"NMEA2000Message(PGN={self.PGN}, id={self.id}, description={self.description}, fields={self.fields})"

    def to_string_test_style(self):
        fields_str = ', '.join([field.to_string_test_style() for field in self.fields])
        return f"{self.PGN} {self.description}: {fields_str}"

    def to_json(self):
        return orjson.dumps(self.__dict__)

    @staticmethod
    def from_json(json_str):
        data = orjson.loads(json_str)
        msg = NMEA2000Message(
            PGN=data["PGN"],
            id=data["id"],
            description=data["description"],
        )
        msg.fields = [NMEA2000Field(**field) for field in data.get("fields", [])]
        msg.add_data(data["source"], data["destination"], data["priority"])
        return msg

# NMEA2000Field class represents a single NMEA 2000 field
@dataclass
class NMEA2000Field:
    id: str
    name: str
    description: str
    unit_of_measurement: str
    value: str | int | float
    raw_value: int

    def __repr__(self):
        return f"NMEA2000Field(id={self.id}, name={self.name}, description={self.description}, unit_of_measurement={self.unit_of_measurement}, value={self.value}, raw_value={self.raw_value})"

    def to_string_test_style(self):
        if isinstance(self.raw_value, int):
            # Determine the number of bytes needed
            byte_length = (self.raw_value.bit_length() + 8) // 8 or 1
            # Convert integer to bytes (big-endian)
            value_bytes = int_to_bytes(self.raw_value, byte_length)
            # Use binascii.hexlify to convert bytes to hex
            raw_value_hex = binascii.hexlify(value_bytes, " ").decode().upper()
        else:
            raw_value_hex = self.raw_value
        return f'{self.name} = {self.value} (bytes = "{raw_value_hex}")'
