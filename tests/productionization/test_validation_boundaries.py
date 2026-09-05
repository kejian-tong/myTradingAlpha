"""Offline regressions for audit A04/A05; canaries never reach a service."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _probe(tmp_path: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    (tmp_path / "conftest.py").write_text((ROOT / "tests/conftest.py").read_text())
    (tmp_path / "test_probe.py").write_text(
        'import os\nimport pytest\n'
        '@pytest.fixture(autouse=True)\ndef _isolate_config(): yield\n'
        '@pytest.mark.integration\ndef test_explicit_integration():\n'
        '    assert os.environ["DEEPSEEK_API_KEY"] == "AUDIT_CANARY_NOT_A_SECRET"\n'
        '    print("INTEGRATION_SENTINEL")\n'
        'def test_ordinary():\n'
        '    assert os.environ["DEEPSEEK_API_KEY"] == "placeholder"\n'
    )
    # No real credential, user pytest configuration, or model client is used.
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "DEEPSEEK_API_KEY": "AUDIT_CANARY_NOT_A_SECRET"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", *arguments],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15,
    )


def test_real_looking_key_alone_never_arms_integration(tmp_path: Path) -> None:
    result = _probe(tmp_path, [])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 skipped" in result.stdout
    assert "INTEGRATION_SENTINEL" not in result.stdout


def test_marker_selection_alone_never_arms_integration(tmp_path: Path) -> None:
    result = _probe(tmp_path, ["-m", "integration"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "INTEGRATION_SENTINEL" not in result.stdout


def test_explicit_opt_in_preserves_key_only_for_integration(tmp_path: Path) -> None:
    result = _probe(tmp_path, ["--run-provider-integration"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    assert "INTEGRATION_SENTINEL" in result.stdout


def _smoke_module():
    path = ROOT / "scripts/smoke_installed.py"
    assert path.is_file(), "missing installed-origin smoke checker"
    spec = importlib.util.spec_from_file_location("audit_installed_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_rejects_checkout_shadowing(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "audit_shadow_package.py").write_text('VALUE = "source"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    module = _smoke_module()
    with pytest.raises(RuntimeError, match="outside installed"):
        module.check_modules(("audit_shadow_package",))


def test_smoke_accepts_genuine_installed_module() -> None:
    module = _smoke_module()
    origins = module.check_modules(("pydantic",))
    assert "site-packages" in origins["pydantic"]


def test_smoke_missing_package_is_not_success() -> None:
    module = _smoke_module()
    with pytest.raises(ModuleNotFoundError):
        module.check_modules(("audit_package_that_does_not_exist",))


def test_ci_smoke_uses_isolated_interpreter_outside_checkout() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'cd "$(mktemp -d)"' in workflow
    assert '-I "$GITHUB_WORKSPACE/scripts/smoke_installed.py"' in workflow
    assert 'PYTHON="$GITHUB_WORKSPACE/.venv/bin/python"' in workflow
