"""Pre-commit hook: verify generated files are up to date."""

import subprocess
import sys
from pathlib import Path

GENERATED_FILES = (Path("nmea2000/pgns.py"), Path("nmea2000/consts.py"))

before = {path: path.read_bytes() for path in GENERATED_FILES}
subprocess.run([sys.executable, "canboat2python.py"], check=True)
changed = [path for path in GENERATED_FILES if path.read_bytes() != before[path]]

if changed:
    print(
        "ERROR: Generated files were out of date: "
        + ", ".join(str(path) for path in changed)
    )
    sys.exit(1)
