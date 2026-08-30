# Repository, License, and Upstream Strategy

## Repository identity

The repository is `kejian-tong/myTradingAlpha`, independently maintained from [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents). Current baseline is `212dcef3a7b6865f513b9400436e59b7aa967984`; upstream comparison snapshot is `a33fd4c0f134485a43553a2c23a63cb14adbd88f`. The histories are unrelated and have no merge base. See [`UPSTREAM.md`](../../UPSTREAM.md) for the path/blob comparison and six post-release upstream commits represented in the tree.

## Apache-2.0 obligations

The current repository includes [`LICENSE`](../../LICENSE) with the Apache License 2.0 text. The productionization work should:

- retain the license text in distributions;
- retain existing copyright, attribution, and third-party notices;
- mark material modifications in changed upstream-derived files or a suitable modification record;
- preserve source and binary redistribution notices required by Apache-2.0; and
- document which new `mytradingalpha/` files are project-owned while keeping their license metadata consistent with repository policy.

There is currently no `NOTICE` file. That is a fact about this tree, not permission to omit notices required by a dependency or upstream contribution. Add or update `NOTICE` only after reviewing applicable source and dependency terms. Apache-2.0 does not grant upstream trademarks, logos, or endorsement rights.

## Separate terms

Data vendors, model providers, news/social APIs, broker APIs, exchange data, and hosted services carry separate contracts, retention rules, rate limits, and redistribution restrictions. A repository license does not grant a right to cache, redistribute, train on, or trade from any particular data or model output. Store only the minimum raw data permitted by each contract, keep provider terms in deployment records, and redact credentials from artifacts. This document is not legal advice; obtain qualified legal review for distribution, commercial use, and live trading.

## Upstream sync procedure

1. Fetch `upstream` into a review-only ref without changing the current branch.
2. Record the exact upstream commit and paths under review.
3. Compare by path/content; do not rely on a merge-base or triple-dot history view.
4. Review license headers, notices, API behavior, and tests.
5. Cherry-pick only selected commits or apply a reviewed diff onto a dedicated branch.
6. Run focused tests, full local checks, and the affected phase gate.
7. Record adoption, rejection, migration, and rollback evidence.

The repository must not merge a synthetic upstream ancestry. `tradingagents/` remains the upstream-derived Research Graph. Production-owned package code may depend on the Research Graph through an adapter; upstream code must not gain a dependency on production portfolio, risk, or execution modules.

## Change records

Every upstream-derived modification should identify:

| Field | Example shape |
| --- | --- |
| Source | upstream commit hash and URL |
| Local change | file/symbol and behavior summary |
| License action | retained notice, added notice, or legal review required |
| Validation | exact command and result |
| Rollback | revert selected commit or disable adapter |

Do not copy user-provided attachment paths into public citations. Public references are the upstream repository, [paper](https://arxiv.org/abs/2412.20138), [Apache License](https://www.apache.org/licenses/LICENSE-2.0), and relevant GitHub documentation.
