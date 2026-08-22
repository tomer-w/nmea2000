"""Generate Python constant and PGN modules from the canboat JSON schema."""

import json
import keyword
import os
import re

from jinja2 import Environment, FileSystemLoader

# Load the JSON data
with open("canboat.json", encoding="utf-8") as f:
    json_data = json.load(f)


def bits_to_hex(bit_length: int) -> str:
    """Return a hexadecimal mask with all bits up to bit_length set."""
    num = (1 << bit_length) - 1
    return f"0x{num:X}"


def generate_field_id(field_id, field_type, field_offset):
    """Replace reserved field identifiers with a synthetic offset-based name."""
    if field_type == "RESERVED":
        return "reserved_" + str(field_offset)
    return field_id


FIELD_NAME_PATTERN = r"[^a-zA-Z0-9]"


def generate_field_python_name(field_name, field_type, field_offset):
    """Convert a canboat field label into a safe lower-case Python identifier."""
    if field_type == "RESERVED":
        return "reserved_" + str(field_offset)
    temp = re.sub(FIELD_NAME_PATTERN, "_", field_name).lower()
    if temp[0].isdigit() or keyword.iskeyword(temp):
        temp = "__" + temp
    return temp


# Set up the Jinja2 environment
file_loader = FileSystemLoader(searchpath="./")
env = Environment(loader=file_loader, extensions=["jinja2.ext.loopcontrols"])
env.globals["bits_to_hex"] = bits_to_hex
env.globals["generate_field_id"] = generate_field_id
env.globals["generate_field_python_name"] = generate_field_python_name
env.filters["pyrepr"] = lambda value: repr(str(value))

# Load the Jinja2 template
template = env.get_template("python.consts.j2")

# Render the template with the JSON data
output = template.render(data=json_data)

# Save the generated Python code to a file
with open(os.path.join("nmea2000", "consts.py"), "w", encoding="utf-8") as f:
    f.write(output)

# Load the Jinja2 template
template = env.get_template("python.PGNs.j2")

# Render the template with the JSON data
output = template.render(data=json_data)

# Save the generated Python code to a file
with open(os.path.join("nmea2000", "pgns.py"), "w", encoding="utf-8") as f:
    f.write(output)

print("Python code generated successfully!")
