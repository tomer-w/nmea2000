"""Stamp the release tag (RELEASE_TAG, e.g. v2026.9.1) into pyproject.toml."""

import os
import re
from pathlib import Path

from packaging.version import InvalidVersion, Version

release_tag = os.environ["RELEASE_TAG"]
release_version = release_tag.removeprefix("v")
try:
    Version(release_version)
except InvalidVersion as error:
    raise SystemExit(
        f"Release tag {release_tag!r} is not a valid package version"
    ) from error

pyproject_path = Path("pyproject.toml")
pyproject = pyproject_path.read_text(encoding="utf-8")
project_start = pyproject.index("[project]")
next_section = pyproject.find("\n[", project_start + len("[project]"))
project_end = len(pyproject) if next_section == -1 else next_section
project = pyproject[project_start:project_end]
project, replacements = re.subn(
    r'(?m)^version\s*=\s*"[^"]+"\s*$',
    f'version = "{release_version}"',
    project,
    count=1,
)
if replacements != 1:
    raise SystemExit("Expected exactly one version in the [project] table")

pyproject_path.write_text(
    pyproject[:project_start] + project + pyproject[project_end:],
    encoding="utf-8",
)
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    print(f"value={release_version}", file=output)
