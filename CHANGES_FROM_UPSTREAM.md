# Changes from the Upstream Snapshot

This file records the repository-specific differences for baseline `212dcef3a7b6865f513b9400436e59b7aa967984` compared with upstream snapshot `a33fd4c0f134485a43553a2c23a63cb14adbd88f`. The comparison is path/content based because the independent histories have no merge base.

## Current differences

| Path | Difference | Operational intent |
| --- | --- | --- |
| [`README.md`](README.md) | Replaced the upstream framework README with a project README for `myTradingAlpha`, including independent-maintenance attribution, current capabilities, local install instructions, and a productionization documentation link. | Make the project's status and scope explicit without representing it as upstream. |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Extends the upstream Python matrix with Python 3.14 while retaining install, test, smoke-import, and Ruff jobs. | Keep the project CI policy explicit for the supported interpreter range. |
| [`.github/workflows/codeql.yml`](.github/workflows/codeql.yml) | Adds scheduled and pull-request CodeQL analysis for Python with security-extended queries. | Add repository security scanning. |
| [`.github/workflows/dependency-review.yml`](.github/workflows/dependency-review.yml) | Adds pull-request dependency review with a moderate-severity failure threshold. | Detect dependency risk before merge. |

No production portfolio, broker, OMS, reconciliation, or point-in-time data implementation is claimed by these differences. The existing `tradingagents/` code remains the research-oriented graph. The documentation under `docs/productionization/` is a forward implementation plan, not evidence that those systems have shipped.

## What is retained

The current tree retains upstream-derived source, tests, assets, package metadata, and the Apache-2.0 license text. Existing fixes such as the news UTC/end-exclusive boundary, same-day OHLCV cache refresh, typed agent outputs, checkpointing, provider routing, and graph router maps remain part of the baseline. Future source changes must mark material modifications and preserve applicable notices.

## Safe future adoption

The safe procedure is described in [`UPSTREAM.md`](UPSTREAM.md): fetch, review, select, and cherry-pick or apply a reviewed diff. Do not infer ancestry from a triple-dot comparison when no merge base exists. Every adopted commit needs a focused test result and a rollback note.

## License note

The repository is distributed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0), subject to the complete [`LICENSE`](LICENSE) text. Apache-2.0 attribution and modification notices do not grant upstream trademarks or third-party data, model, or broker rights. No `NOTICE` file is currently present; add one if a dependency or upstream notice requires it. This is a documentation record, not legal advice.
