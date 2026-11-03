"""Regression coverage for canboat release generation and sync ordering."""

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("version", ["9.0.0", "9.1.0"])
def test_generation_updates_version_and_native_units(tmp_path, monkeypatch, version):
    """A version-only update still regenerates the schema marker."""
    schema = {
        "Version": version,
        "PGNs": [
            {
                "Id": "engineParametersRapidUpdate",
                "Fields": [
                    {"Id": "speed", "Unit": "rpm", "Resolution": 0.25},
                    {"Id": "tiltTrim", "Unit": "%", "Resolution": 1},
                ],
            }
        ],
    }
    (tmp_path / "canboat.json").write_text(json.dumps(schema), encoding="utf-8")
    (tmp_path / "nmea2000").mkdir()
    monkeypatch.chdir(tmp_path)

    runpy.run_path(str(ROOT / "canboat2python.py"))
    generated = runpy.run_path(str(tmp_path / "nmea2000" / "native_units.py"))

    assert generated["CANBOAT_VERSION"] == version
    assert generated["NATIVE_UNITS"] == {
        ("engineParametersRapidUpdate", "speed"): ("rpm", 0.25, 0),
        ("engineParametersRapidUpdate", "tiltTrim"): ("%", 1, 0),
    }


def test_sync_regenerates_with_updated_package_before_creating_pr():
    """Keep the automated PR self-contained and fail closed on generation errors."""
    workflow = (ROOT / ".github" / "workflows" / "copy-canboat-json.yml").read_text(
        encoding="utf-8"
    )
    steps = workflow.split("\n      - name: ")[1:]
    names = [step.splitlines()[0] for step in steps]
    required = [
        "Update Cargo.lock",
        "Set up Python",
        "Install updated package",
        "Regenerate Python code",
        "Create Pull Request",
    ]
    positions = [names.index(name) for name in required]
    assert positions == sorted(positions)
    for position in positions:
        step = steps[position]
        assert "if: steps.release.outputs.changed == 'true'" in step
        assert "continue-on-error" not in step
    assert 'python -m pip install -e ".[dev]"' in steps[positions[2]]
    regeneration = steps[positions[3]]
    assert regeneration.index("python canboat2python.py") < regeneration.index(
        "python check_generated_files.py"
    )
    assert "add-paths:" not in steps[positions[4]]
