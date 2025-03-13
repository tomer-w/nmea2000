import json
import re
from jinja2 import Environment, FileSystemLoader

# Load the JSON data
with open('canboat.json') as f:
    data = json.load(f)

def bits_to_hex(len):
    num = 0
    for i in range(len):
        num = (num << 1) ^ 1
    return f'0x{num:X}'

pattern = r'[^a-zA-Z0-9]'
def generate_field_name(field_name, field_type, field_offset):
    if field_type == "RESERVED":
        return 'reserved_' + str(field_offset)
    temp =  re.sub(pattern, '_', field_name).lower()
    if temp[0].isdigit():
        temp = '__' + temp
    return temp

# Set up the Jinja2 environment
file_loader = FileSystemLoader(searchpath="./")
env = Environment(loader=file_loader)
env.globals['bits_to_hex'] = bits_to_hex
env.globals['generate_field_name'] = generate_field_name

# Load the Jinja2 template
template = env.get_template('python.template.j2')

# Render the template with the JSON data
output = template.render(lookups=data['LookupEnumerations'], pgns=data['PGNs'])

# Save the generated Python code to a file
with open('nmea2000/pgns.py', 'w') as f:
    f.write(output)

print("Python code generated successfully!")
