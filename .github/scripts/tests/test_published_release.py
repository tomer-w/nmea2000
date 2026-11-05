"""Real Git coverage for title-driven preparation and leased triggering-tag updates."""

import copy
import runpy
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
PROJECT = '[project]\nname = "nmea2000"\nversion = "2026.10.5"\n'
VERSION = "2026.11.0"
TAG = f"v{VERSION}"
RUN_ID = "12345"


@pytest.fixture
def publication(tmp_path, monkeypatch):
    """Use an isolated bare remote and mock only GitHub API operations."""
    remote, source = tmp_path / "remote.git", tmp_path / "source"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(source)], check=True)
    monkeypatch.chdir(source)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    script = runpy.run_path(str(SCRIPTS / "published_release.py"))
    api = script["prepare"].__globals__
    git = api["git"]
    git("config", "user.name", "Release tests")
    git("config", "user.email", "release-tests@example.invalid")
    git("config", "core.autocrlf", "false")
    (source / "pyproject.toml").write_text(PROJECT, encoding="utf-8")
    git("add", "pyproject.toml")
    git("commit", "--quiet", "-m", "Release source")
    initial_sha = git("rev-parse", "HEAD").strip()
    git("remote", "add", "origin", str(remote))
    git("tag", "v2026.10.4")
    git("tag", TAG)
    git("push", "--quiet", "origin", "HEAD:main", "--tags")
    release = {
        "id": 99, "name": TAG, "tag_name": TAG, "draft": False,
        "prerelease": False, "published_at": "2026-11-05T10:00:00Z",
    }
    event = {"action": "published", "release": copy.deepcopy(release)}
    previous = {
        **release, "id": 1, "name": "v2026.10.4", "tag_name": "v2026.10.4",
        "published_at": "2026-10-23T10:00:00Z",
    }
    live = [release, previous]
    monkeypatch.setitem(api, "releases", lambda repository: copy.deepcopy(live))
    calls = []
    monkeypatch.setattr(subprocess, "check_call", lambda command: calls.append(command))
    return script, event, live, initial_sha, remote, calls


def prepare(publication, event=None, run_id=RUN_ID):
    """Run source preparation against the fixture's published-release snapshot."""
    script, original, _, initial_sha, _, _ = publication
    return script["prepare"]("owner/repo", event or original, initial_sha, run_id)


def finalize(publication, outputs, notes="Generated notes", run_id=RUN_ID):
    """Run finalization only against the exact prepared SHA and expected raw tag ref."""
    script, event, _, initial_sha, _, _ = publication
    script["finalize"](
        "owner/repo", event, initial_sha, run_id,
        outputs["sha"], outputs["tag_oid"], notes,
    )


def test_title_version_persisted_before_only_triggering_tag_moves(publication):
    """Source, tag and metadata identity are aligned without changing historical refs."""
    script, _, _, initial_sha, _, calls = publication
    outputs = prepare(publication)
    assert outputs["value"] == VERSION
    assert outputs["sha"] != initial_sha
    assert outputs["previous_ref"] == "v2026.10.4"
    assert script["tag_target"](TAG)[1] == initial_sha
    assert VERSION in Path("pyproject.toml").read_text(encoding="utf-8")
    assert script["git"]("show", "origin/main:pyproject.toml").strip().endswith(f'version = "{VERSION}"')
    finalize(publication, outputs)
    assert script["tag_target"](TAG)[1] == outputs["sha"]
    assert script["tag_target"]("v2026.10.4")[1] == initial_sha
    assert calls[0][:5] == ["gh", "api", "--method", "PATCH", "repos/owner/repo/releases/99"]
    assert f"target_commitish={outputs['sha']}" in calls[0]
    assert not any(arg.startswith(("tag_name=", "name=", "draft=")) for arg in calls[0])


def test_full_run_retry_reuses_prepared_source_and_aligned_tag(publication):
    """Retry the same event/run after both preparation and finalization."""
    first = prepare(publication)
    assert prepare(publication) == first
    finalize(publication, first)
    retry = prepare(publication)
    assert retry["sha"] == first["sha"]
    assert retry["value"] == first["value"]
    finalize(publication, retry)


@pytest.mark.parametrize("title", ["v2026.11.0", "2026.11.0"])
def test_title_accepts_optional_v(publication, title):
    """The version comes from the release title, not a dispatch input."""
    _, event, live, _, _, _ = publication
    event["release"]["name"] = title
    live[0]["name"] = title
    assert prepare(publication)["value"] == VERSION


@pytest.mark.parametrize("title", ["v2026.011.0", "v2026.11.00", "v2026.11.0rc1", "Release 2026.11.0", "invalid"])
def test_invalid_title_fails_without_source_or_tag_changes(publication, title):
    """No mutation should precede canonical title validation."""
    script, event, live, initial_sha, _, calls = publication
    event["release"]["name"] = title
    live[0]["name"] = title
    with pytest.raises(ValueError):
        prepare(publication)
    assert script["git"]("rev-parse", "HEAD").strip() == initial_sha
    assert script["tag_target"](TAG)[1] == initial_sha
    assert not calls


def test_mismatched_title_and_tag_fail(publication):
    """Changing only a title cannot authorize moving an unrelated historical tag."""
    _, event, live, _, _, _ = publication
    event["release"]["name"] = "v2026.12.0"
    live[0]["name"] = "v2026.12.0"
    with pytest.raises(ValueError, match="matching new"):
        prepare(publication)


@pytest.mark.parametrize("change", ["title", "newer", "owner", "draft", "prerelease"])
def test_changed_or_historical_release_fails_closed(publication, change):
    """Only the unchanged stable triggering release is eligible for tag movement."""
    _, _, live, _, _, calls = publication
    if change == "title":
        live[0]["name"] = "v2026.12.0"
    elif change == "newer":
        live.append({**live[0], "id": 100, "tag_name": "v2026.12.0", "published_at": "2026-11-05T11:00:00Z"})
    elif change == "owner":
        live.append({**live[0], "id": 100})
    else:
        live[0][change] = True
    with pytest.raises(ValueError):
        prepare(publication)
    assert not calls


def test_alias_collision_does_not_reuse_historical_version(publication):
    """Exclude only the triggering tag, not other aliases of its numeric version."""
    script, _, _, _, _, _ = publication
    script["git"]("tag", VERSION)
    with pytest.raises(ValueError, match="reuse"):
        prepare(publication)
    assert Path("pyproject.toml").read_text(encoding="utf-8") == PROJECT


def test_stale_release_source_and_wrong_run_fail(publication):
    """No unrelated main commit or different workflow may claim the version commit."""
    script, _, _, _, _, _ = publication
    prepare(publication)
    with pytest.raises(ValueError, match="this run"):
        prepare(publication, run_id="another-run")
    Path("code.py").write_text("changed = True\n", encoding="utf-8")
    script["git"]("add", "code.py")
    script["git"]("commit", "--quiet", "-m", "Other main change")
    with pytest.raises(ValueError, match="this run"):
        prepare(publication)


def test_tag_lease_rejects_racing_update_without_overwriting(publication, monkeypatch):
    """Exercise real Git compare-and-swap when the tag changes after its final read."""
    script, _, _, _, remote, calls = publication
    outputs = prepare(publication)
    api = script["finalize"].__globals__
    git = api["git"]
    tree = git("rev-parse", "HEAD^{tree}").strip()
    other_sha = git("commit-tree", tree, "-p", outputs["sha"], "-m", "Racing tag owner").strip()
    git("push", "--quiet", "origin", f"{other_sha}:refs/heads/racer")

    def race(*args):
        if args[0] == "push" and args[1].startswith("--force-with-lease"):
            subprocess.run(["git", "--git-dir", str(remote), "update-ref", f"refs/tags/{TAG}", other_sha], check=True)
        return git(*args)

    monkeypatch.setitem(api, "git", race)
    with pytest.raises(subprocess.CalledProcessError):
        finalize(publication, outputs)
    assert script["tag_target"](TAG)[1] == other_sha
    assert not calls


def test_remote_error_stops_before_preparation(publication, monkeypatch):
    """An API outage is not an empty release list or permission to mutate refs."""
    script, _, _, initial_sha, _, _ = publication

    def unavailable(repository):
        raise RuntimeError("GitHub unavailable")

    monkeypatch.setitem(script["prepare"].__globals__, "releases", unavailable)
    with pytest.raises(RuntimeError, match="unavailable"):
        prepare(publication)
    assert script["git"]("rev-parse", "HEAD").strip() == initial_sha


def test_empty_notes_cannot_move_tag(publication):
    """Failed release-note generation must not align a tag or reach PyPI."""
    script, _, _, initial_sha, _, calls = publication
    outputs = prepare(publication)
    with pytest.raises(ValueError, match="empty"):
        finalize(publication, outputs, notes="")
    assert script["tag_target"](TAG)[1] == initial_sha
    assert not calls
