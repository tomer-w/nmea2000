"""Create a release only for the verified source, without replacing any tag."""

import json
import os
import re
import subprocess
from pathlib import Path

from set_release_version import git, verify


def command(*args: str) -> str:
    """Propagate GitHub API and push failures instead of treating them as absence."""
    return subprocess.check_output(args, text=True, encoding="utf-8")


def create_release(repository: str, tag: str, sha: str, notes: str) -> None:
    """Resume an exact tag/release, but refuse conflicting tags and drafts."""
    verify(Path("pyproject.toml").read_text(encoding="utf-8"), tag)
    if git("rev-parse", "HEAD").strip() != sha:
        raise ValueError("Release checkout does not match the verified source SHA")
    if not notes.strip():
        raise ValueError("Release notes generation returned an empty body")

    refs = command("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    targets = dict(line.split()[::-1] for line in refs.splitlines())
    target = targets.get(f"refs/tags/{tag}^{{}}", targets.get(f"refs/tags/{tag}"))
    if target is not None and target != sha:
        raise ValueError(f"Existing tag {tag!r} points to another source; it will not be moved")

    pages = json.loads(command("gh", "api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"))
    releases = [release for page in pages for release in page if release["tag_name"] == tag]
    if len(releases) > 1:
        raise ValueError(f"Multiple releases claim tag {tag!r}")
    existing = releases[0] if releases else None
    if existing is not None:
        if existing["name"] != tag or existing["prerelease"]:
            raise ValueError(f"Existing release {tag!r} does not match the prepared source")
        previous_sha = existing["target_commitish"]
        if previous_sha != sha:
            # The old preparation workflow may have left this version's draft
            # on an earlier main commit. Retarget only an untagged ancestor draft.
            if not existing["draft"] or target is not None or not re.fullmatch(r"[0-9a-f]{40}", previous_sha):
                raise ValueError(f"Existing release {tag!r} does not match the prepared source")
            git("merge-base", "--is-ancestor", previous_sha, sha)
            verify(git("show", f"{previous_sha}:pyproject.toml"), tag)
        if not existing["draft"]:
            if target != sha:
                raise ValueError("Published release is missing its matching tag")
            print(f"Release {tag} already exists for {sha}; leaving it unchanged")
            return

    if target is None:
        # Explicit SHA and a non-forced refspec: a racing tag creation fails closed.
        command("git", "push", "origin", f"{sha}:refs/tags/{tag}")
    if existing is None:
        command(
            "gh", "api", "--method", "POST", f"repos/{repository}/releases",
            "-f", f"tag_name={tag}", "-f", f"target_commitish={sha}",
            "-f", f"name={tag}", "-f", f"body={notes}",
            "-F", "draft=false", "-F", "prerelease=false",
        )
    else:
        command(
            "gh", "api", "--method", "PATCH", f"repos/{repository}/releases/{existing['id']}",
            "-f", f"target_commitish={sha}", "-f", f"body={notes}", "-F", "draft=false",
        )


def main() -> None:
    """Publish generated notes only after the workflow's verification gates."""
    try:
        create_release(
            os.environ["GITHUB_REPOSITORY"], os.environ["RELEASE_TAG"],
            os.environ["RELEASE_SHA"], os.environ["RELEASE_NOTES"],
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
