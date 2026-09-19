from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_OWNER_MARKER_KEYS = {
    "schema_version",
    "kind",
    "repo_root",
    "worktree_path",
    "allowed_root",
    "head_sha",
}
_OWNER_MARKER_KIND = "codex-review-worktree-owner"


def _helper():
    path = ROOT / "scripts/review_worktree.py"
    spec = importlib.util.spec_from_file_location("review_worktree", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return repo, _git(repo, "rev-parse", "HEAD")


def _second_commit(repo: Path) -> str:
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "b.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "second"], check=True)
    return _git(repo, "rev-parse", "HEAD")


def _worktree_gitdir(path: Path) -> Path:
    git_marker = path / ".git"
    if git_marker.is_file():
        prefix, value = git_marker.read_text(encoding="utf-8").split(":", 1)
        assert prefix.strip() == "gitdir"
        gitdir = Path(value.strip())
        return gitdir.resolve() if gitdir.is_absolute() else (path / gitdir).resolve()
    value = _git(path, "rev-parse", "--git-dir")
    gitdir = Path(value)
    return gitdir.resolve() if gitdir.is_absolute() else (path / gitdir).resolve()


def _owner_marker(path: Path) -> tuple[Path, dict[str, object]]:
    gitdir = _worktree_gitdir(path)
    candidates = sorted(candidate for candidate in gitdir.glob("*.json") if candidate.is_file())
    assert len(candidates) == 1, f"expected one JSON owner marker in {gitdir}, found {candidates}"
    marker = candidates[0]
    payload = json.loads(marker.read_bytes())
    assert isinstance(payload, dict)
    assert set(payload) == _OWNER_MARKER_KEYS
    assert type(payload["schema_version"]) is int and payload["schema_version"] == 1
    assert type(payload["kind"]) is str and payload["kind"] == _OWNER_MARKER_KIND
    for field in ("repo_root", "worktree_path", "allowed_root", "head_sha"):
        assert type(payload[field]) is str
    assert len(payload["head_sha"]) == 40
    assert all(character in "0123456789abcdef" for character in payload["head_sha"])
    return marker, payload


def _create_review(
    tmp_path: Path,
) -> tuple[object, Path, str, Path, Path]:
    repo, sha = _init_repo(tmp_path)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    review = allowed_root / "review"
    helper = _helper()
    helper.create(repo, sha, review, allowed_root=allowed_root)
    return helper, repo, sha, allowed_root, review


def test_create_and_remove_exact_detached_worktree(tmp_path: Path) -> None:
    helper, repo, sha, allowed_root, review = _create_review(tmp_path)
    assert _git(review, "rev-parse", "HEAD") == sha
    symbolic = subprocess.run(
        ["git", "-C", str(review), "symbolic-ref", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert symbolic.returncode != 0

    marker, payload = _owner_marker(review)
    assert marker.parent == _worktree_gitdir(review)
    assert payload["schema_version"] == 1
    assert payload["kind"] == _OWNER_MARKER_KIND
    assert payload["repo_root"] == str(repo.resolve())
    assert payload["worktree_path"] == str(review.resolve())
    assert payload["allowed_root"] == str(allowed_root.resolve())
    assert payload["head_sha"] == sha
    assert marker.read_bytes() == _canonical_json(payload)

    helper.remove(repo, review, allowed_root=allowed_root)
    assert not review.exists()
    assert str(review) not in _git(repo, "worktree", "list", "--porcelain")


def test_cli_create_and_remove_require_explicit_allowed_root(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    review = allowed_root / "review"
    script = ROOT / "scripts/review_worktree.py"

    missing = subprocess.run(
        [sys.executable, str(script), "create", "--repo", str(repo), "--path", str(review), "--sha", sha],
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    assert "allowed-root" in missing.stderr

    created = subprocess.run(
        [
            sys.executable,
            str(script),
            "create",
            "--repo",
            str(repo),
            "--path",
            str(review),
            "--sha",
            sha,
            "--allowed-root",
            str(allowed_root),
        ],
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    removed = subprocess.run(
        [
            sys.executable,
            str(script),
            "remove",
            "--repo",
            str(repo),
            "--path",
            str(review),
            "--allowed-root",
            str(allowed_root),
        ],
        capture_output=True,
        text=True,
    )
    assert removed.returncode == 0, removed.stderr
    assert not review.exists()


@pytest.mark.parametrize("boundary", ["equal", "outside", "symlink_escape"])
def test_create_rejects_allowed_root_boundary_and_symlink_escape(
    tmp_path: Path, boundary: str
) -> None:
    helper = _helper()
    repo, sha = _init_repo(tmp_path)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if boundary == "equal":
        review = allowed_root
    elif boundary == "outside":
        review = outside / "review"
    else:
        escape = allowed_root / "escape"
        escape.symlink_to(outside, target_is_directory=True)
        review = escape / "review"

    with pytest.raises(ValueError, match=r"allowed(?:[- _])?root|symlink"):
        helper.create(repo, sha, review, allowed_root=allowed_root)
    assert not (outside / "review").exists()


def test_rejects_non_full_sha_and_existing_destination(tmp_path: Path) -> None:
    helper = _helper()
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    with pytest.raises(ValueError, match="full lowercase"):
        helper.create(tmp_path, "abc", allowed_root / "review", allowed_root=allowed_root)
    destination = allowed_root / "exists"
    destination.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        helper.create(tmp_path, "a" * 40, destination, allowed_root=allowed_root)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("absent", r"(?:owner marker.*(?:missing|absent)|(?:missing|absent).*owner marker)"),
        ("malformed", r"(?:owner marker.*(?:malformed|invalid)|(?:malformed|invalid).*owner marker)"),
        ("noncanonical", r"(?:owner marker.*canonical|canonical.*owner marker)"),
    ],
)
def test_remove_rejects_missing_tampered_or_noncanonical_owner_marker(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    helper, repo, _sha, allowed_root, review = _create_review(tmp_path)
    marker, payload = _owner_marker(review)
    if mutation == "absent":
        marker.unlink()
    elif mutation == "malformed":
        marker.write_bytes(b"not-json")
    else:
        marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        helper.remove(repo, review, allowed_root=allowed_root)
    assert review.exists()


@pytest.mark.parametrize(
    ("field", "expected_error"),
    [
        ("repo_root", "repo_root"),
        ("worktree_path", "worktree_path"),
        ("allowed_root", "allowed_root"),
        ("head_sha", "head_sha"),
    ],
)
def test_remove_rejects_owner_marker_bound_to_another_identity(
    tmp_path: Path, field: str, expected_error: str
) -> None:
    helper, repo, sha, allowed_root, review = _create_review(tmp_path)
    marker, payload = _owner_marker(review)
    replacements = {
        "repo_root": str((tmp_path / "other-repo").resolve()),
        "worktree_path": str((tmp_path / "other-review").resolve()),
        "allowed_root": str((tmp_path / "other-allowed").resolve()),
        "head_sha": "0" * 40 if sha != "0" * 40 else "1" * 40,
    }
    payload[field] = replacements[field]
    marker.write_bytes(_canonical_json(payload))

    with pytest.raises(ValueError, match=expected_error):
        helper.remove(repo, review, allowed_root=allowed_root)
    assert review.exists()


def test_remove_rejects_unregistered_path_without_deleting_directory(tmp_path: Path) -> None:
    helper = _helper()
    repo, _sha = _init_repo(tmp_path)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    unregistered = allowed_root / "unregistered"
    unregistered.mkdir()
    (unregistered / "keep.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(ValueError, match="registered"):
        helper.remove(repo, unregistered, allowed_root=allowed_root)
    assert unregistered.is_dir()
    assert (unregistered / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_remove_rejects_attached_worktree_without_deleting_directory(tmp_path: Path) -> None:
    helper, repo, _sha, allowed_root, attached = _create_review(tmp_path)
    subprocess.run(["git", "-C", str(attached), "checkout", "-q", "-b", "attached-review"], check=True)
    assert _git(attached, "symbolic-ref", "--short", "HEAD") == "attached-review"

    with pytest.raises(ValueError, match=r"attached|detached"):
        helper.remove(repo, attached, allowed_root=allowed_root)
    assert attached.is_dir()


def test_remove_rejects_moved_head_without_deleting_directory(tmp_path: Path) -> None:
    helper, repo, _sha, allowed_root, review = _create_review(tmp_path)
    moved_sha = _second_commit(repo)
    subprocess.run(["git", "-C", str(review), "reset", "--hard", moved_sha], check=True)

    with pytest.raises(ValueError, match="head"):
        helper.remove(repo, review, allowed_root=allowed_root)
    assert review.is_dir()
    assert _git(review, "rev-parse", "HEAD") == moved_sha


@pytest.mark.parametrize("dirty_kind", ["tracked", "untracked"])
def test_remove_rejects_dirty_worktree_without_deleting_directory(
    tmp_path: Path, dirty_kind: str
) -> None:
    helper, repo, _sha, allowed_root, review = _create_review(tmp_path)
    if dirty_kind == "tracked":
        (review / "a.txt").write_text("dirty\n", encoding="utf-8")
    else:
        (review / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dirty"):
        helper.remove(repo, review, allowed_root=allowed_root)
    assert review.is_dir()


def test_remove_rejects_missing_git_marker_without_deleting_directory(tmp_path: Path) -> None:
    helper, repo, _sha, allowed_root, review = _create_review(tmp_path)
    (review / ".git").unlink()

    with pytest.raises(ValueError, match=r"\.git|git marker"):
        helper.remove(repo, review, allowed_root=allowed_root)
    assert review.is_dir()


def test_remove_rejects_stale_registration_without_deleting_directory(tmp_path: Path) -> None:
    helper, repo, _sha, allowed_root, review = _create_review(tmp_path)
    marker, payload = _owner_marker(review)
    marker_name = marker.name
    (review / ".git").unlink()
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"], check=True)
    stale_gitdir = tmp_path / "stale-gitdir"
    stale_gitdir.mkdir()
    (stale_gitdir / marker_name).write_bytes(_canonical_json(payload))
    (review / ".git").write_text(f"gitdir: {stale_gitdir}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"stale|registration|registered"):
        helper.remove(repo, review, allowed_root=allowed_root)
    assert review.is_dir()


def test_remove_never_uses_force_for_candidate_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, repo, _sha, allowed_root, review = _create_review(tmp_path)
    calls: list[tuple[str, ...]] = []
    real_run = helper._run

    def recording_run(command_repo: Path, *args: str) -> None:
        calls.append(args)
        real_run(command_repo, *args)

    monkeypatch.setattr(helper, "_run", recording_run)
    helper.remove(repo, review, allowed_root=allowed_root)
    assert all("--force" not in args for args in calls)
    source = (ROOT / "scripts/review_worktree.py").read_text(encoding="utf-8")
    assert '"worktree", "remove", "--force"' not in source


def test_exact_head_review_documents_session_specific_root_and_fail_closed_recovery() -> None:
    instructions = (ROOT / ".agents/skills/exact-head-review/SKILL.md").read_text(encoding="utf-8")
    lowered = instructions.lower()
    assert "allowed_root" in instructions or "--allowed-root" in instructions
    assert "session-specific" in lowered or "session specific" in lowered
    assert "manual recovery" in lowered
    assert "fail-closed" in lowered or "fail closed" in lowered
