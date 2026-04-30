"""Pre-commit hook: verify generated files are up to date."""

import subprocess
import sys

subprocess.check_call([sys.executable, "canboat2python.py"])
result = subprocess.run(
    ["git", "diff", "--exit-code", "nmea2000/pgns.py", "nmea2000/consts.py"]
)
if result.returncode != 0:
    print(
        "ERROR: Generated files are out of date. Run 'python canboat2python.py' and stage the results."
    )
sys.exit(result.returncode)
