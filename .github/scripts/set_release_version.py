"""Prepare UTC CalVer drafts, or verify an immutable release's source version."""

import argparse
import os
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from packaging.version import InvalidVersion, Version


def calver(value: str) -> Version:
    """Require a canonical, stable YYYY.M.PATCH package version."""
    if not re.fullmatch(r"[1-9][0-9]{3}\.(?:[1-9]|1[0-2])\.(?:0|[1-9][0-9]*)", value):
        raise ValueError(f"Expected canonical YYYY.M.PATCH version, got {value!r}")
    return Version(value)


def next_version(current: str, tags: list[str], now: datetime) -> str:
    """Reuse an unpublished source version, otherwise advance beyond all tags."""
    source = calver(current)
    if now.utcoffset() is None:
        raise ValueError("CalVer calculation requires a timezone-aware timestamp")
    today = now.astimezone(UTC)
    month = (today.year, today.month)
    versions = [source]
    tagged = []
    for tag in tags:
        try:
            version = Version(tag.removeprefix("v"))
        except InvalidVersion:
            continue  # Non-version tags, such as GitHub's old untagged drafts.
        parts = version.release
        if len(parts) < 3 or not 1000 <= parts[0] <= 9999:
            continue
        if not 1 <= parts[1] <= 12:
            raise ValueError(f"Invalid calendar month in tag {tag!r}")
        # Historical releases include fourth numeric components. Reserve their
        # entire patch number rather than producing a lower three-part version.
        tagged.append(version)
        versions.append(version)
    if any(version.release[:2] > month for version in versions):
        raise ValueError("Source or tags are ahead of the current UTC month; refusing a downgrade")
    monthly_tags = [version for version in tagged if version.release[:2] == month]
    if source.release[:2] == month and all(source > version for version in monthly_tags):
        return str(source)
    patch = max((version.release[2] for version in monthly_tags), default=-1) + 1
    return f"{today.year}.{today.month}.{patch}"


def project_version(project: str) -> str:
    """Read the authoritative Python distribution version."""
    return tomllib.loads(project)["project"]["version"]


def with_version(project: str, version: str) -> str:
    """Change only the version inside the project table."""
    calver(version)
    project_start = project.index("[project]")
    next_section = project.find("\n[", project_start + len("[project]"))
    project_end = len(project) if next_section == -1 else next_section
    table, replacements = re.subn(
        r'(?m)^version[ \t]*=[ \t]*"[^"]+"[ \t]*$',
        f'version = "{version}"',
        project[project_start:project_end],
    )
    if replacements != 1:
        raise ValueError("Expected exactly one version in the [project] table")
    return project[:project_start] + table + project[project_end:]


def git(*args: str) -> str:
    """Read Git state, propagating command failures."""
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8")


def prepare(project: str, tested_ref: str) -> str:
    """Only prepare checked code; allow a previous run's version-only commit."""
    changed = git("diff", "--name-only", tested_ref, "HEAD").splitlines()
    if set(changed) - {"pyproject.toml"}:
        raise ValueError("Main changed since CI ran; rerun the workflow on current main")
    tested_project = git("show", f"{tested_ref}:pyproject.toml")
    if with_version(tested_project, project_version(project)) != project:
        raise ValueError("Package configuration changed since CI ran; rerun on current main")
    return next_version(
        project_version(project), git("tag", "--list").splitlines(), datetime.now(UTC)
    )


def verify(project: str, tag: str, published_at: str) -> str:
    """Check release identity without rewriting the tagged source."""
    version = tag.removeprefix("v")
    parsed = calver(version)
    published = datetime.fromisoformat(published_at)
    if published.utcoffset() is None:
        raise ValueError("Release publication timestamp must include a timezone")
    published = published.astimezone(UTC)
    if parsed.release[:2] != (published.year, published.month):
        raise ValueError("Release tag is not in its publication's UTC month; refresh the draft before publishing")
    if project_version(project) != version:
        raise ValueError(f"Release tag {tag!r} does not match the committed package version")
    return version


def main() -> None:
    """Run release preparation or fail-closed publication verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", metavar="TESTED_REF")
    args = parser.parse_args()
    path = Path("pyproject.toml")
    project = path.read_text(encoding="utf-8")
    try:
        if args.prepare:
            version = prepare(project, args.prepare)
            path.write_text(with_version(project, version), encoding="utf-8")
        else:
            version = verify(project, os.environ["RELEASE_TAG"], os.environ["RELEASE_PUBLISHED_AT"])
    except ValueError as error:
        raise SystemExit(str(error)) from error
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        print(f"value={version}", file=output)


if __name__ == "__main__":
    main()
