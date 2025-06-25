from __future__ import annotations

import binascii
from datetime import date, datetime, time, timedelta
from dataclasses import dataclass, field
import hashlib
import logging
from typing import Any
import orjson
from .consts import PhysicalQuantities, FieldTypes
from .utils import kelvin_to_celsius, kelvin_to_fahrenheit, mps_to_knots, pascal_to_bar, pascal_to_PSI, radians_to_degrees

logger = logging.getLogger(__name__)

# Helper function
def int_to_bytes(value):
    # Determine the number of bytes needed
    byte_length = (value.bit_length() + 8) // 8 or 1
    return value.to_bytes(byte_length, byteorder="big", signed=False)

# NMEA2000Message class represents a single NMEA 2000 PGN
@dataclass
class NMEA2000Message:
    PGN: int
    id: str = ''
    description: str = ''
    ttl: timedelta | None = None
    fields: list[NMEA2000Field] = field(default_factory=list)
    source: int = 0
    destination: int = 0
    priority: int = 0
    timestamp: datetime = datetime.now()
    source_iso_name: IsoName | None = None
    hash: str | None = None
    
    def add_data(self, src:int, dest: int, priority:int, timestamp: datetime, source_iso_name: IsoName, build_network_map: bool):
        self.source = src
        self.destination = dest
        self.priority = priority
        self.timestamp = timestamp
        self.source_iso_name = source_iso_name
        self.hash = None

        if build_network_map:
            # Using MD5 as we don't need secure hashing and speed matters
            primary_key = f"{self.id}_{self.source_iso_name.name}"
            for nmea_field in self.fields:
                if nmea_field.part_of_primary_key:
                    primary_key += "_" + str(nmea_field.raw_value)
            logger.debug("primary key: %s. iso name: %s", primary_key, self.source_iso_name)
            self.hash = hashlib.md5(primary_key.encode()).hexdigest()


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
            if f.physical_quantities == PhysicalQuantities.ANGLE:
                requested_unit = preferred_units.get(PhysicalQuantities.ANGLE, None)
                if requested_unit == "deg":
                    f.unit_of_measurement = "Deg"
                    f.value = radians_to_degrees(f.value)
            if f.physical_quantities == PhysicalQuantities.SPEED:
                requested_unit = preferred_units.get(PhysicalQuantities.SPEED, None)
                if requested_unit == "kts":
                    f.unit_of_measurement = "kts"
                    f.value = mps_to_knots(f.value)

    def __repr__(self):
        return f"NMEA2000Message(PGN={self.PGN}, id={self.id}, pri={self.priority}, src={self.source}, source_iso_name={self.source_iso_name}, dest={self.destination}, description={self.description}, fields={self.fields})"

    def to_string_test_style(self):
        fields_str = ', '.join([field.to_string_test_style() for field in self.fields])
        return f"{self.PGN} {self.description}: {fields_str}"

    def to_json(self):
        def default(obj: Any) -> Any:
            type_obj = type(obj)
            if type_obj is bytes:
                return obj.hex()
            raise TypeError
        return orjson.dumps(self.__dict__,   default=default).decode()

    @staticmethod
    def from_json(json_str):
        data = orjson.loads(json_str)
        msg = NMEA2000Message(**data)
        msg.fields = [NMEA2000Field(**field) for field in data.get("fields", [])]
        return msg
    
    def get_field_by_id(self, id: str) -> NMEA2000Field:
        field = next((f for f in self.fields if f.id == id), None)
        if field is None:
            raise ValueError(f"PGN: {self.id}: Field with id '{id}' is missing.")
        return field

    def get_field_int_value_by_id(self, id: str, default_value: int | None = None) -> int:
        field = self.get_field_by_id(id)
        if not isinstance(field.value, int):
            if default_value is not None:
                return default_value
            raise ValueError(f"PGN: {self.id}: Field with id '{id}' is not an integer. It is {type(field.value).__name__}.")
        return field.value

    def get_field_str_value_by_id(self, id: str) -> str | None:
        field = self.get_field_by_id(id)
        if field.value is None:
            logger.warning("PGN: %s: Field with id '%s' is None. Raw value is: %s", self.id, id, field.raw_value)
            return None
        if not isinstance(field.value, str):
            raise ValueError(f"PGN: {self.id}: Field with id '{id}' is not a string. It is {type(field.value).__name__}.")
        return field.value
    
# NMEA2000Field class represents a single NMEA 2000 field
@dataclass
class NMEA2000Field:
    id: str
    name: str | None = None
    description: str | None = None
    unit_of_measurement: str | None = None
    value: str | int | float | bytes | time | date | None = 0
    raw_value: int | float | str | bytes | None = 0
    physical_quantities: PhysicalQuantities | None = None
    type: FieldTypes = FieldTypes.NUMBER
    part_of_primary_key: bool | None = None

    def __repr__(self):
        return f"NMEA2000Field(id={self.id}, name={self.name}, description={self.description}, unit_of_measurement={self.unit_of_measurement}, value={self.value}, raw_value={self.raw_value}, physical_quantities={self.physical_quantities}, type={self.type}, part_of_primary_key = {self.part_of_primary_key})"

    def to_string_test_style(self):
        if isinstance(self.raw_value, int):
            # Convert integer to bytes (big-endian)
            value_bytes = int_to_bytes(self.raw_value)
            # Use binascii.hexlify to convert bytes to hex
            raw_value_hex = binascii.hexlify(value_bytes, " ").decode().upper()
        else:
            raw_value_hex = self.raw_value
        return f'{self.name} = {self.value} (bytes = "{raw_value_hex}")'
    
class LookupFieldTypeEnumeration:
    name: str
    field_type: FieldTypes
    resolution: float | None
    unit: str | None
    bits: int
    lookup_enumeration: str | None

    def __init__(self, name: str, field_type: FieldTypes, resolution: float | None, unit: str | None, bits: int, lookup_enumeration: str | None):
        self.name = name
        self.field_type = field_type
        self.resolution = resolution
        self.unit = unit
        self.bits = bits
        self.lookup_enumeration = lookup_enumeration

@dataclass
class IsoName:
    unique_number: int
    manufacturer_code: str
    device_instance: int
    device_function: str
    device_class: str
    system_instance: int
    industry_group: str
    arbitrary_address_capable: bool
    name: int

    def __init__(self, message: NMEA2000Message, name: int):
        """
        Initialize an IsoName object from an NMEA2000Message.

        Args:
            message: An NMEA2000Message object containing the NAME field data.
            name: The 64-bit NAME field value as an integer.
        """
        self.name = name
        self.unique_number = message.get_field_int_value_by_id('uniqueNumber', 0)
        self.manufacturer_code = message.get_field_str_value_by_id('manufacturerCode')
        self.device_instance = (
            message.get_field_int_value_by_id('deviceInstanceUpper', 0) << 3
        ) | message.get_field_int_value_by_id('deviceInstanceLower', 0)
        self.device_function = message.get_field_str_value_by_id('deviceFunction')
        self.device_class = message.get_field_str_value_by_id('deviceClass')
        self.system_instance = message.get_field_int_value_by_id('systemInstance', 0)
        self.industry_group = message.get_field_str_value_by_id('industryGroup')
        self.arbitrary_address_capable = message.get_field_str_value_by_id('arbitraryAddressCapable') == "Yes"

    def __repr__(self):
        return (
            f"IsoName(unique_number={self.unique_number}, "
            f"manufacturer_code='{self.manufacturer_code}', "
            f"device_instance={self.device_instance}, "
            f"device_function='{self.device_function}', "
            f"device_class='{self.device_class}', "
            f"system_instance={self.system_instance}, "
            f"industry_group='{self.industry_group}', "
            f"arbitrary_address_capable={self.arbitrary_address_capable}, "
            f"name={self.name})"
        )