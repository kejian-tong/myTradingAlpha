# myTradingAlpha

[![CI](https://github.com/kejian-tong/myTradingAlpha/actions/workflows/ci.yml/badge.svg)](https://github.com/kejian-tong/myTradingAlpha/actions/workflows/ci.yml)
[![CodeQL](https://github.com/kejian-tong/myTradingAlpha/actions/workflows/codeql.yml/badge.svg)](https://github.com/kejian-tong/myTradingAlpha/actions/workflows/codeql.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

`myTradingAlpha` is an independently maintained agentic trading research project based on the open-source [TradingAgents](https://github.com/TauricResearch/TradingAgents) framework originally developed by [TauricResearch](https://github.com/TauricResearch).

The repository keeps the useful multi-agent trading architecture and research workflow of the upstream project while being developed independently under its own Git history, CI policy, and project direction.

> **Research use only.** This project is intended for software engineering, AI-agent, quantitative-finance, and trading-system research. It is not financial, investment, or trading advice.

## Framework Overview

`myTradingAlpha` uses multiple specialized LLM-powered agents to analyze market information, debate competing views, form a trading proposal, evaluate risk, and produce a final portfolio decision.

<p align="center">
  <img src="assets/schema.png" width="100%" alt="Multi-agent trading framework architecture">
</p>

A simplified workflow is:

```text
Market / Company / News Data
            |
            v
      Analyst Team
            |
            v
   Bull / Bear Research
            |
            v
       Trader Agent
            |
            v
    Risk Management
            |
            v
    Portfolio Manager
            |
            v
       Final Decision
```

### Analyst Team

The analysis layer is divided into specialized roles so that different forms of evidence can be evaluated independently before being combined:

- **Fundamentals Analyst** — evaluates company financial information, business performance, valuation signals, and potential fundamental risks.
- **Sentiment Analyst** — evaluates market and social sentiment signals relevant to the target asset.
- **News Analyst** — evaluates company, industry, macroeconomic, and market news that may affect the trading thesis.
- **Technical Analyst** — evaluates price action and technical indicators such as MACD and RSI to identify market patterns and momentum.

### Research Team

Bullish and bearish research agents challenge the analyst findings from opposing perspectives. Their structured debate is intended to expose weak assumptions, conflicting evidence, and asymmetric risks before a trading recommendation is formed.

### Trader Agent

The Trader Agent synthesizes analyst and research outputs into a concrete trading proposal, including the directional thesis and supporting reasoning.

### Risk Management and Portfolio Manager

Risk-management agents evaluate the proposed trade from different risk perspectives. The Portfolio Manager then considers the complete evidence set and produces the final decision.

## Core Capabilities

The current codebase includes:

- multi-agent orchestration built around **LangGraph**;
- specialized analyst, researcher, trader, risk-management, and portfolio-management agents;
- support for multiple LLM providers and OpenAI-compatible endpoints;
- market, company, news, sentiment, and technical-analysis data interfaces;
- structured debate between competing research perspectives;
- persistent decision history and optional checkpoint-based recovery;
- CLI and Python package interfaces;
- automated CI across **Python 3.10, 3.11, 3.12, 3.13, and 3.14**;
- Ruff linting, CodeQL security scanning, and dependency-review checks.

## Installation

Clone this repository:

```bash
git clone https://github.com/kejian-tong/myTradingAlpha.git
cd myTradingAlpha
```

The repository's default development runtime is pinned to **Python 3.14.7** in `.python-version`, while the package remains compatible with Python 3.10 through 3.14. Use Python 3.14 for new local development unless you are explicitly testing an older supported interpreter.

Create and activate a Python virtual environment, then install the package:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install .
```

For development and testing:

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

The project declares Python `>=3.10` for backward compatibility and continuously tests Python 3.10 through 3.14. The Docker runtime and default CI smoke/lint lanes use Python 3.14.

## Configuration

The framework supports multiple LLM and data providers. Configure the credentials required by the providers you choose before running an analysis.

A convenient starting point is:

```bash
cp .env.example .env
```

Then populate the relevant API keys in `.env`.

Provider-specific and enterprise configuration options are available in the repository configuration files, including support for local or OpenAI-compatible model endpoints.

## CLI Usage

Launch the interactive CLI with:

```bash
tradingagents
```

or directly from the source tree:

```bash
python -m cli.main
```

The CLI allows you to select the asset, analysis date, model provider, research depth, and related runtime options.

## Python Usage

The framework can also be used programmatically:

```python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = DEFAULT_CONFIG.copy()
ta = TradingAgentsGraph(debug=True, config=config)

_, decision = ta.propagate("AAPL", "2026-01-15")
print(decision)
```

Configuration can be customized through `DEFAULT_CONFIG` and the corresponding environment variables and configuration files.

## Persistence and Recovery

The project supports persistent decision history so completed analyses can be retained across runs. Optional LangGraph checkpointing can also be enabled so interrupted analyses can resume from saved execution state instead of restarting from the beginning.

These mechanisms are intended to support reproducibility, debugging, experimentation, and longer-running agent workflows.

## Project Independence

`myTradingAlpha` is **not an official TauricResearch repository** and is not maintained by the upstream TradingAgents maintainers.

This repository uses its own Git history and is developed independently. Upstream-derived code may be modified, replaced, extended, or removed as the project evolves.

## Productionization Documentation

The repository-specific productionization plan is maintained in [`docs/productionization/README.md`](docs/productionization/README.md). It describes the boundary between the current research graph and a future `mytradingalpha/` package, including point-in-time evidence, deterministic portfolio/risk controls, simulation, and staged paper/live gates. Only `mytradingalpha.research` may import `tradingagents`; no file under `tradingagents/` may import `mytradingalpha`. Research use only remains the current status.

## Upstream Attribution

This project is derived from:

- **TradingAgents**
- Upstream repository: https://github.com/TauricResearch/TradingAgents
- Original project: TauricResearch and the TradingAgents contributors

The upstream project is distributed under the Apache License 2.0. Attribution to the original project and applicable upstream notices are retained in accordance with that license.

## License

This repository is distributed under the **Apache License 2.0**.

Portions derived from TradingAgents remain subject to the Apache License 2.0. See [LICENSE](LICENSE) for the complete license text and terms governing use, reproduction, modification, and distribution.
