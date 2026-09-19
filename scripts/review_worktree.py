"""Create and remove detached worktrees for exact-head review evidence.

This helper never commits, pushes, merges, or changes the primary worktree.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_OWNER_MARKER_NAME = "codex-review-owner.json"
_OWNER_MARKER_KIND = "codex-review-worktree-owner"
_OWNER_MARKER_KEYS = frozenset(
    {"schema_version", "kind", "repo_root", "worktree_path", "allowed_root", "head_sha"}
)
_MAX_OWNER_MARKER_BYTES = 8192


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise ValueError("git validation failed")
    return result.stdout.strip()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("owner marker malformed") from exc


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate owner marker field")
        result[key] = value
    return result


def _canonical_existing_dir(value: Path, label: str) -> Path:
    candidate = Path(value)
    try:
        mode = candidate.lstat().st_mode
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"{label} must be an existing canonical directory") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be an existing canonical directory")
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise ValueError(f"{label} must be an existing canonical directory") from exc
    if not resolved.is_dir():
        raise ValueError(f"{label} must be an existing canonical directory")
    return resolved


def _canonical_path(value: Path) -> Path:
    try:
        return Path(value).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("review worktree path is not canonical") from exc


def _validate_descendant(path: Path, allowed_root: Path, *, require_absent: bool) -> Path:
    resolved = _canonical_path(path)
    try:
        relative = resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("review worktree path escapes allowed root") from exc
    if not relative.parts:
        raise ValueError("review worktree path must be a strict descendant of allowed root")
    if require_absent:
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ValueError("review worktree destination is not safely inspectable") from exc
        else:
            raise ValueError("review worktree destination must not already exist")
    return resolved


def _canonical_repo(repo: Path) -> Path:
    root = _canonical_existing_dir(repo, "repo")
    try:
        discovered = Path(_git_output(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
        raise ValueError("repo must be a canonical Git repository") from exc
    if discovered != root:
        raise ValueError("repo must be a canonical Git repository")
    return root


def _registered_worktrees(repo: Path) -> list[dict[str, object]]:
    raw = _git_output(repo, "worktree", "list", "--porcelain")
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in raw.splitlines():
        if not line:
            if current is not None:
                records.append(current)
                current = None
            continue
        if line.startswith("worktree "):
            if current is not None:
                records.append(current)
            current = {"path": Path(line[9:]).resolve(), "detached": False}
        elif current is not None and line == "detached":
            current["detached"] = True
        elif current is not None and line.startswith("HEAD "):
            current["registered_head"] = line[5:]
        elif current is not None and line.startswith("branch "):
            current["branch"] = line[7:]
    if current is not None:
        records.append(current)
    return records


def _registered_for_path(repo: Path, path: Path) -> dict[str, object]:
    for record in _registered_worktrees(repo):
        if record.get("path") == path:
            return record
    raise ValueError("review worktree path is not registered to repository")


def _read_git_marker(path: Path) -> Path:
    marker = path / ".git"
    try:
        mode = marker.lstat().st_mode
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("review worktree .git marker is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("review worktree .git marker is invalid")
    try:
        raw = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("review worktree .git marker is invalid") from exc
    if raw.endswith("\n"):
        raw = raw[:-1]
    if "\n" in raw or not raw.startswith("gitdir: "):
        raise ValueError("review worktree .git marker is invalid")
    target = Path(raw[8:])
    if not target.is_absolute():
        target = path / target
    try:
        target = target.resolve(strict=True)
        target_mode = target.lstat().st_mode
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise ValueError("review worktree .git marker is invalid") from exc
    if stat.S_ISLNK(target_mode) or not stat.S_ISDIR(target_mode):
        raise ValueError("review worktree .git marker is invalid")
    for name in ("HEAD", "commondir", "gitdir"):
        try:
            child_mode = (target / name).lstat().st_mode
        except (FileNotFoundError, OSError) as exc:
            raise ValueError("review worktree .git marker is invalid") from exc
        if stat.S_ISLNK(child_mode) or not stat.S_ISREG(child_mode):
            raise ValueError("review worktree .git marker is invalid")
    try:
        backlink = (target / "gitdir").read_text(encoding="utf-8").strip()
        backlink_path = Path(backlink)
        if not backlink_path.is_absolute():
            backlink_path = target / backlink_path
        if backlink_path.resolve() != marker.resolve():
            raise ValueError("review worktree .git marker is invalid")
    except (OSError, UnicodeError, RuntimeError) as exc:
        raise ValueError("review worktree .git marker is invalid") from exc
    return target


def _read_owner_marker(gitdir: Path) -> dict[str, object]:
    marker = gitdir / _OWNER_MARKER_NAME
    candidates = [candidate for candidate in gitdir.glob("*.json") if candidate.is_file()]
    if not marker.exists():
        if candidates:
            raise ValueError("owner marker is ambiguous")
        raise ValueError("owner marker missing")
    if len(candidates) != 1 or candidates[0] != marker:
        raise ValueError("owner marker is ambiguous")
    try:
        mode = marker.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError("owner marker malformed")
        raw = marker.read_bytes()
    except ValueError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ValueError("owner marker malformed") from exc
    if not raw or len(raw) > _MAX_OWNER_MARKER_BYTES:
        raise ValueError("owner marker malformed")
    try:
        text = raw.decode("ascii")
        payload = json.loads(text, object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise ValueError("owner marker malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("owner marker schema mismatch")
    if raw != _canonical_json(payload):
        raise ValueError("owner marker noncanonical")
    if frozenset(payload) != _OWNER_MARKER_KEYS:
        raise ValueError("owner marker schema mismatch")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("owner marker schema mismatch")
    if type(payload["kind"]) is not str or payload["kind"] != _OWNER_MARKER_KIND:
        raise ValueError("owner marker schema mismatch")
    for field in ("repo_root", "worktree_path", "allowed_root", "head_sha"):
        if type(payload[field]) is not str:
            raise ValueError("owner marker schema mismatch")
    if _SHA.fullmatch(payload["head_sha"]) is None:
        raise ValueError("owner marker schema mismatch")
    return payload


def _validate_owner_identity(
    payload: dict[str, object], *, repo: Path, path: Path, allowed_root: Path
) -> None:
    expected = {
        "repo_root": str(repo),
        "worktree_path": str(path),
        "allowed_root": str(allowed_root),
    }
    for field, value in expected.items():
        if payload[field] != value:
            raise ValueError(f"owner marker {field} mismatch")


def _validate_review_state(
    repo: Path, path: Path, allowed_root: Path
) -> tuple[Path, dict[str, object]]:
    record = _registered_for_path(repo, path)
    gitdir = _read_git_marker(path)
    if record.get("detached") is not True:
        raise ValueError("review worktree must be detached")
    try:
        head_file = (gitdir / "HEAD").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("review worktree .git marker is invalid") from exc
    if head_file.startswith("ref:"):
        raise ValueError("review worktree must be detached")
    payload = _read_owner_marker(gitdir)
    _validate_owner_identity(payload, repo=repo, path=path, allowed_root=allowed_root)
    registered_head = record.get("registered_head")
    if isinstance(registered_head, str) and payload["head_sha"] != registered_head:
        raise ValueError("owner marker head_sha mismatch")
    try:
        actual_head = _git_output(path, "rev-parse", "HEAD")
    except ValueError as exc:
        raise ValueError("review worktree head mismatch") from exc
    if payload["head_sha"] != actual_head:
        raise ValueError("review worktree head mismatch")
    try:
        status = _git_output(path, "status", "--porcelain=v1", "--untracked-files=all")
    except ValueError as exc:
        raise ValueError("review worktree is dirty") from exc
    if status:
        raise ValueError("review worktree is dirty")
    return gitdir, payload


def _write_owner_marker(gitdir: Path, payload: dict[str, object]) -> None:
    marker = gitdir / _OWNER_MARKER_NAME
    if marker.exists() or marker.is_symlink():
        raise ValueError("owner marker already exists")
    if any(candidate.is_file() for candidate in gitdir.glob("*.json")):
        raise ValueError("owner marker is ambiguous")
    raw = _canonical_json(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(marker, flags, 0o600)
    except FileExistsError as exc:
        raise ValueError("owner marker already exists") from exc
    except OSError as exc:
        raise RuntimeError("unable to create owner marker") from exc
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(raw):
            offset += os.write(fd, raw[offset:])
        os.fsync(fd)
    except OSError as exc:
        raise RuntimeError("unable to write owner marker") from exc
    finally:
        os.close(fd)


def _safe_rollback(repo: Path, path: Path, allowed_root: Path, expected_head: str) -> bool:
    try:
        if not path.is_dir():
            return False
        record = _registered_for_path(repo, path)
        if record.get("detached") is not True:
            return False
        gitdir = _read_git_marker(path)
        if _git_output(path, "rev-parse", "HEAD") != expected_head:
            return False
        if _git_output(path, "status", "--porcelain=v1", "--untracked-files=all"):
            return False
        marker = gitdir / _OWNER_MARKER_NAME
        marker_present = False
        try:
            marker.lstat()
            marker_present = True
        except FileNotFoundError:
            pass
        if marker_present or any(candidate.is_file() for candidate in gitdir.glob("*.json")):
            payload = _read_owner_marker(gitdir)
            _validate_owner_identity(payload, repo=repo, path=path, allowed_root=allowed_root)
            if payload["head_sha"] != expected_head:
                return False
        _run(repo, "worktree", "remove", str(path))
        return True
    except Exception:
        return False


def create(repo: Path, sha: str, path: Path, *, allowed_root: Path) -> None:
    if not _SHA.fullmatch(sha):
        raise ValueError("review SHA must be a full lowercase 40-character commit SHA")
    allowed = _canonical_existing_dir(allowed_root, "allowed root")
    destination = _validate_descendant(path, allowed, require_absent=True)
    repo_root = _canonical_repo(repo)
    try:
        _git_output(repo_root, "cat-file", "-e", f"{sha}^{{commit}}")
    except ValueError as exc:
        raise ValueError("review SHA must name a commit in repo") from exc
    added = False
    try:
        _run(repo_root, "worktree", "add", "--detach", str(destination), sha)
        added = True
        record = _registered_for_path(repo_root, destination)
        if record.get("detached") is not True:
            raise ValueError("review worktree must be detached")
        gitdir = _read_git_marker(destination)
        actual = _git_output(destination, "rev-parse", "HEAD")
        if actual != sha:
            raise ValueError("created review worktree head mismatch")
        payload: dict[str, object] = {
            "schema_version": 1,
            "kind": _OWNER_MARKER_KIND,
            "repo_root": str(repo_root),
            "worktree_path": str(destination),
            "allowed_root": str(allowed),
            "head_sha": sha,
        }
        _write_owner_marker(gitdir, payload)
        _validate_review_state(repo_root, destination, allowed)
    except Exception:
        if added:
            _safe_rollback(repo_root, destination, allowed, sha)
        raise


def remove(repo: Path, path: Path, *, allowed_root: Path) -> None:
    allowed = _canonical_existing_dir(allowed_root, "allowed root")
    destination = _validate_descendant(path, allowed, require_absent=False)
    repo_root = _canonical_repo(repo)
    _validate_review_state(repo_root, destination, allowed)
    _run(repo_root, "worktree", "remove", str(destination))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "remove"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, required=True)
    parser.add_argument("--sha")
    args = parser.parse_args()
    try:
        if args.action == "create":
            if args.sha is None:
                parser.error("--sha is required for create")
            create(args.repo, args.sha, args.path, allowed_root=args.allowed_root)
        else:
            if args.sha is not None:
                parser.error("--sha is not valid for remove")
            remove(args.repo, args.path, allowed_root=args.allowed_root)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
