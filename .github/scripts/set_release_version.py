"""Persist a release version before drafting, or verify tagged source identity."""

import argparse
import os
import re
import subprocess
import tomllib
from pathlib import Path

from packaging.version import InvalidVersion, Version


def calver(value: str) -> Version:
    """Require a canonical, stable YYYY.M.PATCH package version."""
    if not re.fullmatch(r"[1-9][0-9]{3}\.(?:[1-9]|1[0-2])\.(?:0|[1-9][0-9]*)", value):
        raise ValueError(f"Expected canonical YYYY.M.PATCH version, got {value!r}")
    return Version(value)


def next_version(current: str, tags: list[str], requested: str = "") -> str:
    """Reuse an unpublished version or bump its patch; month changes are manual."""
    source = calver(current)
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
    if requested:
        candidate = calver(requested)
        if candidate < source or any(candidate <= version for version in tagged):
            raise ValueError("Requested version must not downgrade source or reuse an existing tag version")
        return str(candidate)
    if all(source > version for version in tagged):
        return str(source)
    latest = max([source, *tagged])
    year, month, patch = latest.release[:3]
    return f"{year}.{month}.{patch + 1}"


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


def prepare(project: str, tested_ref: str, requested: str = "") -> str:
    """Only prepare checked code; allow a previous run's version-only commit."""
    changed = git("diff", "--name-only", tested_ref, "HEAD").splitlines()
    if set(changed) - {"pyproject.toml"}:
        raise ValueError("Main changed since CI ran; rerun the workflow on current main")
    tested_project = git("show", f"{tested_ref}:pyproject.toml")
    if with_version(tested_project, project_version(project)) != project:
        raise ValueError("Package configuration changed since CI ran; rerun on current main")
    return next_version(
        project_version(project), git("tag", "--list").splitlines(), requested
    )


def verify(project: str, tag: str) -> str:
    """Check release identity without rewriting the tagged source."""
    version = tag.removeprefix("v")
    calver(version)
    if project_version(project) != version:
        raise ValueError(f"Release tag {tag!r} does not match the committed package version")
    return version


def main() -> None:
    """Run release preparation or fail-closed publication verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", metavar="TESTED_REF")
    parser.add_argument("--version", default="", help="Explicit YYYY.M.PATCH for a manual month/year change")
    args = parser.parse_args()
    if args.version and not args.prepare:
        parser.error("--version requires --prepare")
    path = Path("pyproject.toml")
    project = path.read_text(encoding="utf-8")
    try:
        if args.prepare:
            version = prepare(project, args.prepare, args.version)
            path.write_text(with_version(project, version), encoding="utf-8")
        else:
            version = verify(project, os.environ["RELEASE_TAG"])
    except ValueError as error:
        raise SystemExit(str(error)) from error
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        print(f"value={version}", file=output)


if __name__ == "__main__":
    main()
