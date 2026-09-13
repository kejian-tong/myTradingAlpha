"""Offline regressions for audit A04/A05; canaries never reach a service."""

from __future__ import annotations

import importlib.util
import os
import re
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


def _network_probe(tmp_path: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "conftest.py").write_text((ROOT / "tests/conftest.py").read_text())
    (tmp_path / "test_network_probe.py").write_text(
        "import inspect\n"
        "import socket\n"
        "import pytest\n\n"
        "def _denied(action):\n"
        "    try:\n"
        "        action()\n"
        "    except Exception as exc:\n"
        "        return type(exc).__name__, str(exc)\n"
        "    raise AssertionError('network action was not denied')\n\n"
        "def _raw_connect():\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    try:\n"
        "        sock.connect(('127.0.0.1', 9))\n"
        "    finally:\n"
        "        sock.close()\n\n"
        "def _raw_connect_ex():\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    try:\n"
        "        sock.connect_ex(('127.0.0.1', 9))\n"
        "    finally:\n"
        "        sock.close()\n\n"
        "def _udp_sendto():\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "    try:\n"
        "        sock.sendto(b'AUDIT_NETWORK_CANARY', ('127.0.0.1', 9))\n"
        "    finally:\n"
        "        sock.close()\n\n"
        "def test_ordinary_network_actions_are_denied():\n"
        "    actions = (\n"
        "        lambda: socket.getaddrinfo('localhost', 9, type=socket.SOCK_STREAM),\n"
        "        lambda: socket.create_connection(('localhost', 9), timeout=0.01),\n"
        "        _raw_connect,\n"
        "        _raw_connect_ex,\n"
        "        _udp_sendto,\n"
        "    )\n"
        "    failures = [_denied(action) for action in actions]\n"
        "    assert {name for name, _message in failures} == {'NetworkDeniedError'}\n"
        "    assert len(set(failures)) == 1\n\n"
        "@pytest.mark.integration\n"
        "def test_explicit_integration_sees_original_socket_callables():\n"
        "    assert socket.getaddrinfo.__module__ == 'socket'\n"
        "    assert socket.create_connection.__module__ == 'socket'\n"
        "    assert inspect.ismethoddescriptor(socket.socket.connect)\n"
        "    assert inspect.ismethoddescriptor(socket.socket.connect_ex)\n"
        "    assert inspect.ismethoddescriptor(socket.socket.sendto)\n"
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", *arguments],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _workflow_job(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)", text
    )
    assert match is not None, f"missing workflow job: {name}"
    return match.group("body")


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


def test_network_denial_canary_is_default_off_and_opt_in_preserves_callables(tmp_path: Path) -> None:
    denied = _network_probe(tmp_path / "denied", [])
    assert denied.returncode == 0, denied.stdout + denied.stderr
    assert "1 passed, 1 skipped" in denied.stdout

    opted_in = _network_probe(tmp_path / "opted-in", ["--run-provider-integration"])
    assert opted_in.returncode == 0, opted_in.stdout + opted_in.stderr
    assert "2 passed" in opted_in.stdout


def test_ci_lint_job_has_history_bound_diff_check_and_network_canary() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    lint_job = _workflow_job(workflow, "lint")
    assert "uses: actions/checkout@v4" in lint_job
    assert "fetch-depth: 0" in lint_job
    assert "git diff --check" in lint_job
    assert "HEAD" in lint_job
    assert "github.event.pull_request.base.sha" in lint_job or "github.event.before" in lint_job
    assert not re.search(r"git diff --check\s*$", lint_job, flags=re.MULTILINE)
    assert "tests/productionization/test_validation_boundaries.py" in lint_job
    assert "network" in lint_job.lower()
    assert "deny" in lint_job.lower()


def test_audit_protocol_limits_network_guard_to_python_test_phase() -> None:
    text = (ROOT / "docs/productionization/AGENT_AUDIT_PROTOCOL.md").read_text(encoding="utf-8")
    assert "Python-level pytest test-phase evidence" in text
    assert "not an OS egress sandbox" in text
    assert "subprocess/native bypasses" in text


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
