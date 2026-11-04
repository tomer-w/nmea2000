"""Regression coverage for release version calculation and persistence."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github" / "scripts" / "set_release_version.py"
RELEASE = runpy.run_path(str(SCRIPT))
PROJECT = '[project]\nname = "nmea2000"\nversion = "2026.10.3"\n\n[tool.example]\nversion = "1.0"\n'


@pytest.mark.parametrize(
    ("current", "tags", "requested", "expected"),
    [
        ("2026.10.3", ["v2026.10.3"], "", "2026.10.4"),
        ("2026.12.8", ["v2026.12.8"], "", "2026.12.9"),
        ("2026.10.3", ["v2026.10.3"], "2026.11.0", "2026.11.0"),
        ("2026.12.8", ["v2026.12.8"], "2027.1.0", "2027.1.0"),
        ("2026.10.3", [], "", "2026.10.3"),
        ("2026.10.3", ["2026.11.0", "v2026.11.4"], "", "2026.11.5"),
        ("2026.10.3", ["v2026.11.9", "v2026.11.10"], "", "2026.11.11"),
        ("2026.11.0", ["v2026.10.3"], "", "2026.11.0"),
        ("2026.11.0", ["v2026.10.3"], "2026.11.0", "2026.11.0"),
        ("2026.11.2", ["v2026.11.1"], "", "2026.11.2"),
        ("2026.11.2", ["2026.11.2"], "", "2026.11.3"),
        ("2026.10.3", ["v2026.11.1.1"], "", "2026.11.2"),
        ("2026.10.3", ["v2026.11.1rc1", "untagged-abcd"], "", "2026.11.2"),
        ("2026.10.3", ["v2026.11.01"], "", "2026.11.2"),
    ],
)
def test_next_calver(current, tags, requested, expected):
    """Reserve numeric tag versions and reuse an unpublished source version."""
    assert RELEASE["next_version"](current, tags, requested) == expected


@pytest.mark.parametrize(
    ("current", "tags", "requested", "message"),
    [
        ("2026.12.0", [], "2026.11.0", "downgrade"),
        ("2026.10.3", ["v2027.1.0"], "2026.11.0", "reuse"),
        ("2026.10.3", ["v2026.13.0"], "", "Invalid calendar"),
        ("2026.10.3", ["v2026.11.0"], "2026.11.0", "reuse"),
        ("2026.10.3", ["2026.11.0"], "2026.11.0", "reuse"),
        ("2026.10.3", ["v2026.11.0.1"], "2026.11.0", "reuse"),
        ("2026.10.3", [], "2026.11.00", "canonical"),
    ],
)
def test_calver_fails_closed(current, tags, requested, message):
    """Never silently downgrade or interpret an ambiguous calendar."""
    with pytest.raises(ValueError, match=message):
        RELEASE["next_version"](current, tags, requested)


@pytest.mark.parametrize(
    "version",
    ["2026.01.0", "2026.1.01", "2026.0.0", "2026.13.0", "2026.1", "2026.1.0.1",
     "2026.1.0rc1", "2026.1.0+local", "1!2026.1.0", "v2026.1.0", "invalid"],
)
def test_source_version_must_be_canonical(version):
    """New releases use only canonical, stable, three-part versions."""
    with pytest.raises(ValueError, match="canonical"):
        RELEASE["calver"](version)


def test_stamp_changes_only_project_version():
    """The Rust crate and unrelated TOML tables are not distribution versions."""
    updated = RELEASE["with_version"](PROJECT, "2026.11.0")
    assert updated == PROJECT.replace('version = "2026.10.3"', 'version = "2026.11.0"')
    assert RELEASE["with_version"](updated, "2026.11.0") == updated
    with pytest.raises(ValueError, match="exactly one"):
        RELEASE["with_version"]('[project]\nname = "nmea2000"\n', "2026.11.0")


@pytest.mark.parametrize("tag", ["v2026.10.3", "2026.10.3"])
def test_verify_does_not_depend_on_calendar_date(tag):
    """Publication and retries verify identity without forcing a month change."""
    assert RELEASE["verify"](PROJECT, tag) == "2026.10.3"


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ("v2026.10.4", "does not match"),
        ("v2026.11.0", "does not match"),
        ("v2026.10.03", "canonical"),
    ],
)
def test_verify_rejects_mismatched_releases(tag, message):
    """Building must not hide an incorrect release by rewriting its source."""
    with pytest.raises(ValueError, match=message):
        RELEASE["verify"](PROJECT, tag)


def git(directory, *args):
    """Execute Git against an isolated fixture repository."""
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], text=True, encoding="utf-8"
    ).strip()


def test_prepare_cli_persists_version_and_reuses_it_on_retry(tmp_path):
    """Exercise tags, source commit, retry, and publication against real Git."""
    version = "2026.10.0"
    project = PROJECT.replace("2026.10.3", version)
    path = tmp_path / "pyproject.toml"
    path.write_text(project, encoding="utf-8")
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "Release tests")
    git(tmp_path, "config", "user.email", "release-tests@example.invalid")
    git(tmp_path, "config", "core.autocrlf", "false")
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "--quiet", "-m", "Checked source")
    tested_ref = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "tag", f"v{version}")
    output = tmp_path / "output"
    env = {**os.environ, "GITHUB_OUTPUT": str(output)}

    def run(*args, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=tmp_path,
            env=environment or env, capture_output=True, text=True, check=False,
        )

    prepared = run("--prepare", tested_ref)
    assert prepared.returncode == 0, prepared.stderr
    expected = "2026.10.1"
    assert output.read_text(encoding="utf-8") == f"value={expected}\n"
    assert RELEASE["project_version"](path.read_text(encoding="utf-8")) == expected
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "--quiet", "-m", "Persist release version")

    retry = run("--prepare", tested_ref)
    assert retry.returncode == 0, retry.stderr
    assert git(tmp_path, "diff") == ""
    assert output.read_text(encoding="utf-8").splitlines() == [f"value={expected}"] * 2
    git(tmp_path, "tag", f"v{expected}")
    published_env = {
        **env, "RELEASE_TAG": f"v{expected}",
    }
    published = run(environment=published_env)
    assert published.returncode == 0, published.stderr
    assert git(tmp_path, "diff") == ""
    previous_output = output.read_text(encoding="utf-8")
    invalid = run(environment={**published_env, "RELEASE_TAG": "v2026.10.9"})
    assert invalid.returncode != 0
    assert "does not match" in invalid.stderr
    assert output.read_text(encoding="utf-8") == previous_output
    assert git(tmp_path, "diff") == ""

    manual = run("--prepare", tested_ref, "--version", "2026.11.0")
    assert manual.returncode == 0, manual.stderr
    assert RELEASE["project_version"](path.read_text(encoding="utf-8")) == "2026.11.0"
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "--quiet", "-m", "Persist manual month change")
    retry = run("--prepare", tested_ref, "--version", "2026.11.0")
    assert retry.returncode == 0, retry.stderr
    assert git(tmp_path, "diff") == ""
    previous_output = output.read_text(encoding="utf-8")
    collision = run("--prepare", tested_ref, "--version", expected)
    assert collision.returncode != 0
    assert "downgrade" in collision.stderr
    assert output.read_text(encoding="utf-8") == previous_output
    assert git(tmp_path, "diff") == ""

    # A stale checked ref can tolerate only an already-persisted version.
    path.write_text(path.read_text(encoding="utf-8").replace("nmea2000", "other"), encoding="utf-8")
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "--quiet", "-m", "Change package configuration")
    stale = run("--prepare", tested_ref)
    assert stale.returncode != 0
    assert "configuration changed" in stale.stderr
    (tmp_path / "code.py").write_text("changed = True\n", encoding="utf-8")
    git(tmp_path, "add", "code.py")
    git(tmp_path, "commit", "--quiet", "-m", "Change code")
    stale = run("--prepare", tested_ref)
    assert stale.returncode != 0
    assert "Main changed" in stale.stderr


def test_workflows_prepare_before_drafting_and_verify_before_building():
    """Keep persistence, draft identity, and publishing gates wired together."""
    build = (ROOT / ".github" / "workflows" / "python-build.yml").read_text(encoding="utf-8")
    draft = build.split("  update_release_draft:", 1)[1]
    required = [
        "Select release version", "Persist package version", "release-drafter/release-drafter@v7",
    ]
    positions = [draft.index(step) for step in required]
    assert positions == sorted(positions)
    assert "needs:\n      - package\n      - quality\n      - test" in draft
    assert 'python .github/scripts/set_release_version.py --prepare "$TESTED_REF" --version "$REQUESTED_VERSION"' in draft
    assert "REQUESTED_VERSION: ${{ inputs.release_version }}" in draft
    assert "git push origin HEAD:main" in draft
    assert "commitish: ${{ steps.source.outputs.sha }}" in draft
    for field in ("version:", "tag:", "name:"):
        assert f"{field} {'v' if field != 'version:' else ''}${{{{ steps.version.outputs.value }}}}" in draft
    assert "workflow_dispatch:" in build
    assert "release_version:" in build
    publish = (ROOT / ".github" / "workflows" / "python-publish.yml").read_text(encoding="utf-8")
    assert publish.count("needs: [release-version]") == 2
    assert "RELEASE_PUBLISHED_AT" not in publish
    assert "Apply release version" not in publish
    assert "id-token: write" in publish
    assert "name: pypi" in publish
    assert "skip-existing" not in publish
    for workflow in (draft, publish):
        assert "group: calver-release" in workflow
        assert "cancel-in-progress: false" in workflow
