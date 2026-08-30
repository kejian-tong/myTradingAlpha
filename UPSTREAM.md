# Upstream Relationship

This repository is an independently maintained derivative of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents). It is not an official upstream repository, and upstream maintainers do not operate this project.

## Snapshot and history

The productionization documentation is anchored to the following read-only snapshot:

| Item | Value |
| --- | --- |
| Current repository baseline | `212dcef3a7b6865f513b9400436e59b7aa967984` (`origin/main`) |
| Upstream comparison snapshot | `a33fd4c0f134485a43553a2c23a63cb14adbd88f` (`upstream/main`) |
| Upstream release tag | `v0.3.1` at `01477f9` |
| Origin | `git@github.com:kejian-tong/myTradingAlpha.git` |
| Upstream | `https://github.com/TauricResearch/TradingAgents.git` |

The two repositories have independent single-root histories and no merge base. A triple-dot diff or merge-base-based statement is therefore not evidence of ancestry. The current tree was compared by path and blob content instead. At this baseline it matches the upstream comparison tree except for the project README and the GitHub workflow changes described in [`CHANGES_FROM_UPSTREAM.md`](CHANGES_FROM_UPSTREAM.md).

Six upstream commits after the `v0.3.1` release are already represented in the current tree:

1. `d78c698` — same-day OHLCV cache refresh.
2. `40774ca` — UTC and end-exclusive Yahoo news window.
3. `3f6c082` — usable-terminal reporting in the CLI.
4. `030b434` — stop priming tool calls in schema-only structured agents.
5. `7bbe33a` — trending badge documentation.
6. `a33fd4c` — streamlined upstream README header.

The list is a provenance aid, not a recommendation to import every future upstream change.

## Sync policy

Because history is unrelated, a future sync should:

1. fetch upstream into a review-only ref;
2. compare the selected paths and behavior against the current baseline;
3. record the upstream commit and rationale;
4. cherry-pick selected commits or apply a reviewed diff onto a dedicated branch; and
5. run the repository's validation plus the affected productionization phase checks.

Do not merge an invented `upstream/main` ancestry into this repository. This policy preserves the independent history and makes each adopted change auditable. `tradingagents/` remains the upstream-derived research graph. The future `mytradingalpha/` package owns production contracts and must not be imported by `tradingagents/` portfolio, risk, or execution paths.

## Attribution and legal boundary

See [`LICENSE`](LICENSE), [`CHANGES_FROM_UPSTREAM.md`](CHANGES_FROM_UPSTREAM.md), and [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). Data-provider, model-provider, and broker terms are separate from the repository license; this document is not legal advice.
