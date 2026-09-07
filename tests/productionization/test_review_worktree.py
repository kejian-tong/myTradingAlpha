from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _helper():
    path = ROOT / "scripts/review_worktree.py"
    spec = importlib.util.spec_from_file_location("review_worktree", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def test_create_and_remove_exact_detached_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    sha = _git(repo, "rev-parse", "HEAD")

    review = tmp_path / "review"
    helper = _helper()
    helper.create(repo, sha, review)
    assert _git(review, "rev-parse", "HEAD") == sha
    symbolic = subprocess.run(
        ["git", "-C", str(review), "symbolic-ref", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert symbolic.returncode != 0
    helper.remove(repo, review)
    assert not review.exists()


def test_rejects_non_full_sha_and_existing_destination(tmp_path: Path) -> None:
    helper = _helper()
    with pytest.raises(ValueError, match="full lowercase"):
        helper.create(tmp_path, "abc", tmp_path / "review")
    destination = tmp_path / "exists"
    destination.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        helper.create(tmp_path, "a" * 40, destination)
