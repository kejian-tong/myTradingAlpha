"""Default-off provider integrations and isolated per-test configuration."""

import os
from unittest.mock import MagicMock, patch

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-provider-integration", action="store_true", default=False,
        help="Explicitly allow separately authorized integration tests to use provider keys",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-provider-integration"):
        disabled = pytest.mark.skip(reason="provider integration requires explicit --run-provider-integration")
        for item in items:
            if item.get_closest_marker("integration") is not None:
                item.add_marker(disabled)


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch, request):
    opted_in = (
        request.config.getoption("--run-provider-integration")
        and request.node.get_closest_marker("integration") is not None
    )
    for env_var in _API_KEY_ENV_VARS:
        value = os.environ.get(env_var) if opted_in else None
        monkeypatch.setenv(env_var, value or "placeholder")


@pytest.fixture(autouse=True)
def _isolate_config():
    """Reset the global dataflows config before and after each test.

    ``set_config`` merges (it never clears keys absent from the override), so a
    test that sets e.g. ``tool_vendors`` would otherwise leak into later tests
    and make routing behavior order-dependent. Replace the global outright so
    every test starts from a clean DEFAULT_CONFIG.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
