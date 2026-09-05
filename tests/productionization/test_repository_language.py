"""English-prose regression guard, not a complete natural-language classifier.

Scan tracked Markdown/TOML and Python comments/docstrings, never execute source.
Product localization strings are data. English review of PR/commit prose is manual.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]")


def _prose_findings(path: Path, source: str) -> list[int]:
    if path.suffix in {".md", ".toml"}:
        return [n for n, line in enumerate(source.splitlines(), 1) if HAN.search(line)]
    if path.suffix != ".py":
        return []
    lines = [token.start[0] for token in tokenize.generate_tokens(io.StringIO(source).readline)
             if token.type == tokenize.COMMENT and HAN.search(token.string)]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None and HAN.search(text):
                lines.append(node.body[0].lineno)
    return sorted(set(lines))


@pytest.mark.parametrize(("suffix", "source", "forbidden"), [
    (".md", "# English notes\n", False),
    (".md", "# " + chr(0x4E2D), True),
    (".toml", '# ' + chr(0x4E2D) + '\nname = "worker"', True),
    (".py", '# ' + chr(0x4E2D) + '\nVALUE = 1', True),
    (".py", '"\\u4e2d"\nVALUE = 1', True),
    (".py", 'def f():\n    "\\u4e2d"\n    return 1', True),
    (".py", 'class C:\n    "\\u4e2d"\n    pass', True),
    (".py", 'LABEL = "' + chr(0x4E2D) + '"', False),
    (".py", 'TEXT = "# ' + chr(0x4E2D) + '"', False),
    (".py", 'def f():\n    return "' + chr(0x4E2D) + '"', False),
])
def test_prose_is_distinct_from_localized_data(suffix, source, forbidden) -> None:
    assert bool(_prose_findings(Path("candidate" + suffix), source)) is forbidden


def test_tracked_repository_prose_has_no_han_characters() -> None:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                            capture_output=True, timeout=15)
    paths = [Path(name) for name in result.stdout.decode("utf-8").split("\0") if name]
    assert paths, "a tracked source checkout is required for this check"
    findings = []
    for path in paths:
        if path.suffix in {".md", ".toml", ".py"}:
            for line in _prose_findings(path, (ROOT / path).read_text(encoding="utf-8")):
                findings.append(f"{path}:{line}: authored prose must be English")
    assert findings == [], "\n".join(findings)


def test_language_policy_fits_root_instruction_budget() -> None:
    raw = (ROOT / "AGENTS.md").read_bytes()
    assert len(raw) <= 32 * 1024
    introduction = raw[:4096].decode("utf-8")
    assert "## Repository language" in introduction
    for subject in ("English", "Chinese", "comments", "docstrings", "commit messages", "PR"):
        assert subject in introduction
