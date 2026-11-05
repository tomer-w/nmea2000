"""Release artifact identity and non-destructive GitHub publication coverage."""

import io
import json
import runpy
import subprocess
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
SHA = "a" * 40
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


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    """Capture publication operations; never contact or mutate the real repository."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    (tmp_path / "pyproject.toml").write_text(PROJECT, encoding="utf-8")
    script = runpy.run_path(str(SCRIPTS / "create_release.py"))
    create = script["create_release"]
    monkeypatch.setitem(create.__globals__, "git", lambda *args: SHA)
    return create


def invoke(publisher, monkeypatch, refs="", releases=None):
    """Provide read-only API fixtures and record all attempted writes."""
    calls = []

    def command(*args):
        calls.append(args)
        if args[:2] == ("git", "ls-remote"):
            return refs
        if args[:4] == ("gh", "api", "--paginate", "--slurp"):
            return json.dumps([releases or []])
        return ""

    monkeypatch.setitem(publisher.__globals__, "command", command)
    publisher("owner/repo", TAG, SHA, "Generated notes")
    return calls


def release(draft=False, sha=SHA):
    """Represent the release identity fields needed to validate a retry."""
    return {"id": 123, "tag_name": TAG, "target_commitish": sha, "name": TAG, "prerelease": False, "draft": draft}


def test_new_release_creates_exact_tag_before_release(publisher, monkeypatch):
    """A tag push cannot auto-select main or force-replace an existing ref."""
    calls = invoke(publisher, monkeypatch)
    assert calls[2] == ("git", "push", "origin", f"{SHA}:refs/tags/{TAG}")
    assert calls[3][:5] == ("gh", "api", "--method", "POST", "repos/owner/repo/releases")
    assert f"target_commitish={SHA}" in calls[3]
    assert "draft=false" in calls[3]


def test_retry_after_tag_creation_reuses_annotated_tag(publisher, monkeypatch):
    """A failed release creation can resume without recreating its tag."""
    refs = f"{'b' * 40}\trefs/tags/{TAG}\n{SHA}\trefs/tags/{TAG}^{{}}\n"
    calls = invoke(publisher, monkeypatch, refs=refs)
    assert not any(call[:2] == ("git", "push") for call in calls)
    assert calls[-1][3] == "POST"


def test_published_retry_is_read_only(publisher, monkeypatch):
    """An exact already-published release must remain untouched."""
    calls = invoke(publisher, monkeypatch, refs=f"{SHA}\trefs/tags/{TAG}\n", releases=[release()])
    assert len(calls) == 2


def test_matching_old_draft_can_be_published(publisher, monkeypatch):
    """Allow the previous workflow's draft only when it targets this exact source."""
    calls = invoke(publisher, monkeypatch, releases=[release(draft=True)])
    assert calls[-1][:5] == ("gh", "api", "--method", "PATCH", "repos/owner/repo/releases/123")
    assert "draft=false" in calls[-1]
    assert not any(arg.startswith("tag_name=") for arg in calls[-1])


def test_untagged_ancestor_draft_can_follow_new_main(publisher, monkeypatch):
    """Merging this workflow must not strand the prior version-preparation draft."""
    previous_sha = "b" * 40
    git_calls = []

    def git(*args):
        git_calls.append(args)
        return PROJECT if args[0] == "show" else SHA

    monkeypatch.setitem(publisher.__globals__, "git", git)
    calls = invoke(publisher, monkeypatch, releases=[release(draft=True, sha=previous_sha)])
    assert ("merge-base", "--is-ancestor", previous_sha, SHA) in git_calls
    assert ("show", f"{previous_sha}:pyproject.toml") in git_calls
    assert f"target_commitish={SHA}" in calls[-1]


@pytest.mark.parametrize("ancestor", [True, False])
def test_unrelated_or_wrong_version_drafts_fail_before_writes(publisher, monkeypatch, ancestor):
    """Migration cannot adopt a draft from another source line or package version."""
    calls = []

    def git(*args):
        if args[0] == "merge-base" and not ancestor:
            raise subprocess.CalledProcessError(1, ["git", *args])
        return PROJECT.replace(VERSION, "2026.10.4") if args[0] == "show" else SHA

    def command(*args):
        calls.append(args)
        return "" if args[0] == "git" else json.dumps([[release(draft=True, sha="b" * 40)]])

    monkeypatch.setitem(publisher.__globals__, "git", git)
    monkeypatch.setitem(publisher.__globals__, "command", command)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        publisher("owner/repo", TAG, SHA, "Generated notes")
    assert not any(call[:2] == ("git", "push") or "--method" in call for call in calls)


@pytest.mark.parametrize(
    ("refs", "releases", "message"),
    [
        (f"{'b' * 40}\trefs/tags/{TAG}\n", [], "will not be moved"),
        ("", [release(draft=True, sha="main")], "does not match"),
        (f"{SHA}\trefs/tags/{TAG}\n", [release(draft=True, sha="b" * 40)], "does not match"),
        ("", [release()], "missing"),
    ],
)
def test_collisions_never_write(publisher, monkeypatch, refs, releases, message):
    """Conflicts with historic tags/releases must fail before any remote mutation."""
    calls = []

    def command(*args):
        calls.append(args)
        return refs if args[0] == "git" else json.dumps([releases])

    monkeypatch.setitem(publisher.__globals__, "command", command)
    with pytest.raises(ValueError, match=message):
        publisher("owner/repo", TAG, SHA, "Generated notes")
    assert not any(call[:2] == ("git", "push") or "--method" in call for call in calls)


def test_remote_read_errors_are_not_collisions_or_absence(publisher, monkeypatch):
    """Authentication/network failure must stop before creating a tag or release."""
    def command(*args):
        raise RuntimeError("remote unavailable")

    monkeypatch.setitem(publisher.__globals__, "command", command)
    with pytest.raises(RuntimeError, match="remote unavailable"):
        publisher("owner/repo", TAG, SHA, "Generated notes")


@pytest.mark.parametrize(("sha", "notes"), [("b" * 40, "notes"), (SHA, "")])
def test_bad_source_or_notes_fail_before_remote_access(publisher, sha, notes):
    """Publication requires both the verified checkout and generated release notes."""
    with pytest.raises(ValueError):
        publisher("owner/repo", TAG, sha, notes)


def test_tag_creation_race_is_non_destructive(tmp_path, monkeypatch):
    """Exercise Git's non-forced refspec against a real, isolated remote."""
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    monkeypatch.chdir(source)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    (source / "pyproject.toml").write_text(PROJECT, encoding="utf-8")

    def git(*args):
        return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()

    git("config", "user.name", "Release tests")
    git("config", "user.email", "release-tests@example.invalid")
    git("add", "pyproject.toml")
    git("commit", "--quiet", "-m", "Prepared source")
    sha = git("rev-parse", "HEAD")
    git("remote", "add", "origin", str(remote))
    git("push", "--quiet", "origin", f"HEAD:refs/tags/{TAG}")
    (source / "code.py").write_text("changed = True\n", encoding="utf-8")
    git("add", "code.py")
    git("commit", "--quiet", "-m", "Other source")
    current_sha = git("rev-parse", "HEAD")
    script = runpy.run_path(str(SCRIPTS / "create_release.py"))
    create = script["create_release"]
    actual_command = create.__globals__["command"]
    calls = []

    def command(*args):
        calls.append(args)
        if args[:2] == ("git", "ls-remote"):
            return ""  # Simulate a tag appearing just after the read.
        if args[0] == "gh":
            return "[[]]"
        return actual_command(*args)

    monkeypatch.setitem(create.__globals__, "command", command)
    with pytest.raises(subprocess.CalledProcessError):
        create("owner/repo", TAG, current_sha, "Generated notes")
    assert git("ls-remote", "--tags", "origin", f"refs/tags/{TAG}").split()[0] == sha
    assert not any("--method" in call for call in calls)
