"""Create and remove detached worktrees for exact-head review evidence.

This helper never commits, pushes, merges, or changes the primary worktree.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def create(repo: Path, sha: str, path: Path) -> None:
    repo = repo.resolve()
    path = path.resolve()
    if not _SHA.fullmatch(sha):
        raise ValueError("review SHA must be a full lowercase 40-character commit SHA")
    if path.exists():
        raise ValueError("review worktree destination must not already exist")
    _run(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    _run(repo, "worktree", "add", "--detach", str(path), sha)
    actual = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != sha:
        try:
            _run(repo, "worktree", "remove", "--force", str(path))
        finally:
            raise RuntimeError("created review worktree does not match requested exact SHA")


def remove(repo: Path, path: Path) -> None:
    repo = repo.resolve()
    path = path.resolve()
    _run(repo, "worktree", "remove", "--force", str(path.resolve()))
    _run(repo, "worktree", "prune")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "remove"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.action == "create":
        if args.sha is None:
            parser.error("--sha is required for create")
        create(args.repo, args.sha, args.path)
    else:
        if args.sha is not None:
            parser.error("--sha is not valid for remove")
        remove(args.repo, args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
