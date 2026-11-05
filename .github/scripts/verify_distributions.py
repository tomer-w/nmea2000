"""Verify every wheel and sdist belongs to the prepared release source."""

import os
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.utils import parse_sdist_filename, parse_wheel_filename


def check_metadata(content: str, version: str) -> None:
    """Require exact package name and canonical version in distribution metadata."""
    metadata = Parser().parsestr(content)
    if metadata["Name"] != "nmea2000" or metadata["Version"] != version:
        raise ValueError("Distribution metadata does not match the prepared package version")


def verify_distributions(directory: Path, project: str, tag: str) -> None:
    """Reject mixed, missing or mismatched artifacts before installing any wheel."""
    version = tomllib.loads(project)["project"]["version"]
    if tag != f"v{version}":
        raise ValueError("Release tag does not match the prepared project")
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 8 or len(sdists) != 1 or len(list(directory.iterdir())) != 9:
        raise ValueError("Expected exactly eight platform wheels and one source distribution")
    for wheel in wheels:
        name, built_version, _, _ = parse_wheel_filename(wheel.name)
        if name != "nmea2000" or str(built_version) != version:
            raise ValueError(f"Wheel filename does not match release: {wheel.name}")
        with zipfile.ZipFile(wheel) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError(f"Expected one wheel METADATA file: {wheel.name}")
            check_metadata(archive.read(metadata[0]).decode("utf-8"), version)
    sdist = sdists[0]
    name, built_version = parse_sdist_filename(sdist.name)
    if name != "nmea2000" or str(built_version) != version:
        raise ValueError("Source distribution filename does not match release")
    with tarfile.open(sdist) as archive:
        root = sdist.name.removesuffix(".tar.gz")
        for filename in ("PKG-INFO", "pyproject.toml"):
            member = archive.extractfile(f"{root}/{filename}")
            if member is None:
                raise ValueError(f"Source distribution is missing {filename}")
            content = member.read().decode("utf-8")
            if filename == "PKG-INFO":
                check_metadata(content, version)
            elif content != project:
                raise ValueError("Source distribution pyproject.toml differs from prepared source")


def main() -> None:
    """Fail closed if any downloaded distribution has the wrong identity."""
    try:
        verify_distributions(
            Path("dist"), Path("pyproject.toml").read_text(encoding="utf-8"), os.environ["RELEASE_TAG"],
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
