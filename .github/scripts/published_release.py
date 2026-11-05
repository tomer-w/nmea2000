"""Prepare title-selected release source and align only its triggering tag."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from set_release_version import calver, git, next_version, project_version, verify, with_version


def releases(repository: str) -> list[dict]:
    """Propagate API failures instead of treating a failed read as absence."""
    pages = json.loads(subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"],
        text=True, encoding="utf-8",
    ))
    return [release for page in pages for release in page]


def identity(event: dict, live_releases: list[dict]) -> tuple[dict, str]:
    """Require an unchanged published release and a canonical title-selected version."""
    release = event["release"]
    if event["action"] != "published" or release["draft"] or release["prerelease"]:
        raise ValueError("Only a newly published stable release can start publication")
    version = release["name"].strip().removeprefix("v")
    calver(version)
    if release["tag_name"] != f"v{version}":
        raise ValueError("Create a matching new vVERSION tag; the release title selects VERSION")
    matching = [item for item in live_releases if item["id"] == release["id"]]
    if len(matching) != 1:
        raise ValueError("Triggering release no longer exists")
    live = matching[0]
    for field in ("name", "tag_name", "published_at", "draft", "prerelease"):
        if live[field] != release[field]:
            raise ValueError("Triggering release changed since publication")
    for other in live_releases:
        if other["id"] == release["id"]:
            continue
        if other["tag_name"] == release["tag_name"]:
            raise ValueError("Another release already owns the triggering tag")
        if other["published_at"] and other["published_at"] > release["published_at"]:
            raise ValueError("A newer release was published; refusing to modify an older release")
    return release, version


def checked_source(initial_sha: str, release_id: int, run_id: str) -> str:
    """Permit only original main or this run's one version-only preparation commit."""
    sha = git("rev-parse", "HEAD").strip()
    if sha != initial_sha:
        message = git("show", "-s", "--format=%B", "HEAD").splitlines()
        if f"Release-Id: {release_id}" not in message or f"Release-Run: {run_id}" not in message:
            raise ValueError("Release source is not current main or this run's preparation commit")
        if git("rev-parse", "HEAD^").strip() != initial_sha:
            raise ValueError("Main changed since release publication")
        project = Path("pyproject.toml").read_text(encoding="utf-8")
        original = git("show", f"{initial_sha}:pyproject.toml")
        changed = git("diff", "--name-only", initial_sha, sha).splitlines()
        if set(changed) - {"pyproject.toml"} or with_version(original, project_version(project)) != project:
            raise ValueError("Prepared release changed more than the package version")
    return sha


def tag_target(tag: str) -> tuple[str, str]:
    """Read the raw ref for compare-and-swap, plus its peeled commit if annotated."""
    refs = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    targets = dict(line.split()[::-1] for line in refs.splitlines())
    if f"refs/tags/{tag}" not in targets:
        raise ValueError("Triggering release tag is missing")
    oid = targets[f"refs/tags/{tag}"]
    return oid, targets.get(f"refs/tags/{tag}^{{}}", oid)


def prepare(repository: str, event: dict, initial_sha: str, run_id: str) -> dict[str, str]:
    """Commit the title-selected version before any release build, without moving tags."""
    live_releases = releases(repository)
    release, version = identity(event, live_releases)
    sha = checked_source(initial_sha, release["id"], run_id)
    oid, target = tag_target(release["tag_name"])
    if target not in (initial_sha, sha):
        raise ValueError("Triggering tag changed or does not target the release source")
    path = Path("pyproject.toml")
    project = path.read_text(encoding="utf-8")
    reserved = [tag for tag in git("tag", "--list").splitlines() if tag != release["tag_name"]]
    reserved.extend(item["tag_name"] for item in live_releases if item["id"] != release["id"])
    next_version(project_version(project), reserved, version)
    updated = with_version(project, version)
    if updated != project:
        path.write_text(updated, encoding="utf-8")
        git("config", "user.name", "github-actions[bot]")
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
        git("add", "pyproject.toml")
        git(
            "commit", "-m", f"Prepare release {release['tag_name']}",
            "-m", f"Release-Id: {release['id']}\nRelease-Run: {run_id}",
        )
        sha = git("rev-parse", "HEAD").strip()
    # Even a no-op preparation must reject a concurrent non-fast-forward main push.
    git("push", "origin", "HEAD:main")
    previous = [
        item for item in live_releases
        if item["id"] != release["id"] and item["published_at"] and not item["prerelease"]
    ]
    previous_ref = (
        max(previous, key=lambda item: item["published_at"])["tag_name"]
        if previous else git("rev-list", "--max-parents=0", "HEAD").splitlines()[0]
    )
    return {"value": version, "sha": sha, "tag_oid": oid, "previous_ref": previous_ref}


def finalize(
    repository: str, event: dict, initial_sha: str, run_id: str,
    prepared_sha: str, expected_oid: str, notes: str,
) -> None:
    """After verification, lease-update only this release's ref and generated notes."""
    release, _ = identity(event, releases(repository))
    sha = checked_source(initial_sha, release["id"], run_id)
    if sha != prepared_sha:
        raise ValueError("Release checkout does not match verified source")
    verify(Path("pyproject.toml").read_text(encoding="utf-8"), release["tag_name"])
    if not notes.strip():
        raise ValueError("Release notes generation returned an empty body")
    git("merge-base", "--is-ancestor", sha, "origin/main")
    oid, target = tag_target(release["tag_name"])
    if target != sha:
        if oid != expected_oid or target != initial_sha:
            raise ValueError("Triggering tag changed; refusing to overwrite it")
        git(
            "push", f"--force-with-lease=refs/tags/{release['tag_name']}:{expected_oid}",
            "origin", f"{sha}:refs/tags/{release['tag_name']}",
        )
    subprocess.check_call([
        "gh", "api", "--method", "PATCH", f"repos/{repository}/releases/{release['id']}",
        "-f", f"target_commitish={sha}", "-f", f"body={notes}",
    ])


def main() -> None:
    """Use the immutable release event payload, not interpolated title/branch shell text."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finalize"))
    args = parser.parse_args()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    repository, initial_sha, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"]
    try:
        if args.phase == "prepare":
            outputs = prepare(repository, event, initial_sha, run_id)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
                for name, value in outputs.items():
                    print(f"{name}={value}", file=output)
        else:
            finalize(
                repository, event, initial_sha, run_id, os.environ["RELEASE_SHA"],
                os.environ["RELEASE_TAG_OID"], os.environ["RELEASE_NOTES"],
            )
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
