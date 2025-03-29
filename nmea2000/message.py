from datetime import datetime
import binascii
from dataclasses import dataclass, field
import orjson
from .consts import PhysicalQuantities, FieldTypes
from .utils import kelvin_to_celsius, kelvin_to_fahrenheit, pascal_to_bar, pascal_to_PSI

# Helper function
def int_to_bytes(value, length):
    return value.to_bytes(length, byteorder="little", signed=True)

# NMEA2000Message class represents a single NMEA 2000 PGN
@dataclass
class NMEA2000Message:
    PGN: int
    id: str = ''
    description: str = ''
    fields: list = field(default_factory=list)
    source: int = 0
    destination: int = 0
    priority: int = 0
    timestamp: datetime = datetime.now()

    def add_data(self, src:int, dest: int, priority:int, timestamp: datetime):
        self.source = src
        self.destination = dest
        self.priority = priority
        self.timestamp = timestamp

    def apply_preferred_units(self, preferred_units: dict[PhysicalQuantities, str]):
        if len(preferred_units) == 0:
            return
        for f in self.fields:
            if f.physical_quantities == PhysicalQuantities.TEMPERATURE:
                requested_unit = preferred_units.get(PhysicalQuantities.TEMPERATURE, None)
                if requested_unit == "c":
                    f.unit_of_measurement = "C"
                    f.value = kelvin_to_celsius(f.value)
                elif requested_unit == "f":
                    f.unit_of_measurement = "F"
                    f.value = kelvin_to_fahrenheit(f.value)
            if f.physical_quantities == PhysicalQuantities.PRESSURE:
                requested_unit = preferred_units.get(PhysicalQuantities.PRESSURE, None)
                if requested_unit == "bar":
                    f.unit_of_measurement = "Bar"
                    f.value = pascal_to_bar(f.value)
                elif requested_unit == "psi":
                    f.unit_of_measurement = "PSI"
                    f.value = pascal_to_PSI(f.value)

    def __repr__(self):
        return f"NMEA2000Message(PGN={self.PGN}, id={self.id}, pri={self.priority}, src={self.source}, dest={self.destination}, description={self.description}, fields={self.fields})"

    def to_string_test_style(self):
        fields_str = ', '.join([field.to_string_test_style() for field in self.fields])
        return f"{self.PGN} {self.description}: {fields_str}"

    def to_json(self):
        return orjson.dumps(self.__dict__)

    @staticmethod
    def from_json(json_str):
        data = orjson.loads(json_str)
        msg = NMEA2000Message(**data)
        msg.fields = [NMEA2000Field(**field) for field in data.get("fields", [])]
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
    physical_quantities: PhysicalQuantities
    type: FieldTypes
    part_of_primary_key: bool

    def __repr__(self):
        return f"NMEA2000Field(id={self.id}, name={self.name}, description={self.description}, unit_of_measurement={self.unit_of_measurement}, value={self.value}, raw_value={self.raw_value}, physical_quantities={self.physical_quantities}, type={self.type}, part_of_primary_key = {self.part_of_primary_key})"

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

class LookupFieldTypeEnumeration:
    name: str
    field_type: FieldTypes
    resolution: float
    unit: str
    bits: int
    lookup_enumeration: str

    def __init__(self, name: str, field_type: FieldTypes, resolution: float, unit: str, bits: int, lookup_enumeration: str):
        self.name = name
        self.field_type = field_type
        self.resolution = resolution
        self.unit = unit
        self.bits = bits
        self.lookup_enumeration = lookup_enumeration
