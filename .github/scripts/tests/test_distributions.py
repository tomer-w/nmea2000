"""Release distribution identity coverage."""

import io
import runpy
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github" / "scripts"
ARTIFACTS = runpy.run_path(str(SCRIPTS / "verify_distributions.py"))
PROJECT = '[project]\nname = "nmea2000"\nversion = "2026.10.5"\n'
VERSION = "2026.10.5"
TAG = f"v{VERSION}"
PLATFORMS = [
    "manylinux_2_17_x86_64", "manylinux_2_17_aarch64", "manylinux_2_17_armv7l",
    "musllinux_1_2_x86_64", "musllinux_1_2_aarch64",
    "macosx_11_0_arm64", "macosx_10_12_x86_64", "win_amd64",
]


def distributions(directory, version=VERSION, project=PROJECT, metadata_version=VERSION):
    """Create small but real archives without requiring cross-platform builds."""
    metadata = f"Metadata-Version: 2.1\nName: nmea2000\nVersion: {metadata_version}\n"
    for platform in PLATFORMS:
        with zipfile.ZipFile(directory / f"nmea2000-{version}-cp311-abi3-{platform}.whl", "w") as archive:
            archive.writestr(f"nmea2000-{version}.dist-info/METADATA", metadata)
    with tarfile.open(directory / f"nmea2000-{version}.tar.gz", "w:gz") as archive:
        for filename, content in (("PKG-INFO", metadata), ("pyproject.toml", project)):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"nmea2000-{version}/{filename}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_all_distributions_match_prepared_source(tmp_path):
    """Check all eight platform archives, not just the current runner's wheel."""
    distributions(tmp_path)
    ARTIFACTS["verify_distributions"](tmp_path, PROJECT, TAG)


@pytest.mark.parametrize(
    ("version", "project", "metadata_version", "message"),
    [
        ("2026.10.4", PROJECT, VERSION, "filename"),
        (VERSION, PROJECT, "2026.10.4", "metadata"),
        (VERSION, PROJECT.replace("nmea2000", "other"), VERSION, "differs"),
    ],
)
def test_mixed_distribution_identity_fails(tmp_path, version, project, metadata_version, message):
    """Reject incorrect filenames, wheel metadata and source configuration."""
    distributions(tmp_path, version, project, metadata_version)
    with pytest.raises(ValueError, match=message):
        ARTIFACTS["verify_distributions"](tmp_path, PROJECT, TAG)


def test_missing_and_unrelated_artifacts_fail(tmp_path):
    """A missing platform or mixed-in CI build must not reach publication."""
    distributions(tmp_path)
    extra = tmp_path / "ci.whl"
    extra.write_bytes(b"unrelated")
    with pytest.raises(ValueError, match="exactly eight"):
        ARTIFACTS["verify_distributions"](tmp_path, PROJECT, TAG)
    extra.unlink()
    next(tmp_path.glob("*.whl")).unlink()
    with pytest.raises(ValueError, match="exactly eight"):
        ARTIFACTS["verify_distributions"](tmp_path, PROJECT, TAG)


def test_sdist_metadata_is_verified_independently(tmp_path):
    """Correct wheel metadata cannot mask a mismatched source distribution."""
    distributions(tmp_path)
    path = tmp_path / f"nmea2000-{VERSION}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        data = b"Name: nmea2000\nVersion: 2026.10.4\n"
        info = tarfile.TarInfo(f"nmea2000-{VERSION}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="metadata"):
        ARTIFACTS["verify_distributions"](tmp_path, PROJECT, TAG)
