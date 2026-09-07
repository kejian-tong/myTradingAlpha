# Codex Model Routing Benchmark Policy

Status: execution-harness optimization policy. This document evaluates routing evidence; it does not
change approved production architecture, authorize a roadmap slice, or automatically change a named
production route.

## Goal

Choose the least expensive route that remains adequately correct for each task class. Do not optimize
credits or latency before correctness and safety. A globally cheapest model is not a valid routing
policy because exploration, implementation, accounting/state-machine review, and master synthesis have
different failure costs.

Use `scripts/model_routing_benchmark.py` on representative replay/shadow records. The script never calls
a model and never edits `.codex` routing; it only evaluates supplied evidence.

## Current official rate-card priors

As of 2026-09-07, the current ChatGPT Work/Codex token-based credit rate card lists:

| Model | Input credits / 1M | Cached input / 1M | Output / 1M |
| --- | ---: | ---: | ---: |
| GPT-5.6 Luna | 5 | 0.5 | 30 |
| GPT-5.6 Terra | 50 | 5 | 300 |
| GPT-5.6 Sol | 100 | 10 | 500 |
| GPT-6 Astra | 250 | 25 | 1,250 |

Source: https://help.openai.com/en/articles/11481834

The corresponding current Enterprise token-based USD rates are:

| Model | Input $ / 1M | Cached input $ / 1M | Output $ / 1M |
| --- | ---: | ---: | ---: |
| GPT-5.6 Luna | 0.20 | 0.02 | 1.20 |
| GPT-5.6 Terra | 2.00 | 0.20 | 12.00 |
| GPT-5.6 Sol | 4.00 | 0.40 | 20.00 |
| GPT-6 Astra | 10.00 | 1.00 | 50.00 |

Source: https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing

At the current token rate, Astra costs 2.5x Sol for the same input/cached/output token mix. That is only
a token-rate prior: Astra may use fewer tokens or finish a task in fewer attempts, so compare measured
end-to-end task cost rather than multiplying a per-token ratio into an assumed conclusion.

Rate cards are mutable external facts. Re-verify the official sources before a future policy change and
update the benchmark constants only through a reviewed harness PR. Do not mix older launch/API list
prices or legacy approximate per-message averages into the current token-based calculation.

## Official capability priors are not repo conclusions

OpenAI's published GPT-5.6 evaluations show why task stratification matters. On Agents' Last Exam, Sol,
Terra, and Luna are relatively close, while on Big Finance Bench Terra materially exceeds Luna and Sol
remains strongest. Treat those public evaluations only as priors when selecting which routes to replay;
they do not prove performance on myTradingAlpha's PIT, accounting, replay, OMS, or safety contracts.

Source: https://openai.com/index/gpt-5-6/

OpenAI describes GPT-6 Astra as its most capable model for the hardest end-to-end work, including complex
reasoning and coding, and documents `gpt-6-astra` with reasoning efforts through `xhigh` and `max`. The
current Work/Codex rate card also notes that Astra requires Codex CLI 0.153.0 or newer and that rollout
availability can vary. These are capability/availability priors only; they do not promote Astra in this
repository.

Sources:

- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/guides/latest-model
- https://help.openai.com/en/articles/11481834

## Three-stage decision rule

### Gate A — correctness and safety eligibility

A benchmark run is ineligible when any of these is true:

- acceptance criteria fail;
- an applicable safety gate fails;
- the route misses any known BLOCKER/HIGH finding.

No credit or latency advantage can compensate for ineligibility. Critical/live/promotion boundaries
retain explicit human gates regardless of benchmark outcome.

### Gate B — task-specific quality floor

Compare routes within a task class against the current production baseline using representative historical
or shadow tasks. Score an explicit acceptance matrix rather than prose style. Include negative cases,
architecture/scope findings, determinism, compatibility, and defect recall as applicable.

A lower-cost route must meet the class quality floor before it can be considered for production routing.
Do not infer a quality floor from a single PR.

### Gate C — Pareto efficiency

Among eligible routes with complete observed token and duration evidence, compare:

- higher quality;
- lower end-to-end duration;
- lower observed token-based credits;
- fewer repair/retry rounds.

Keep nondominated routes on the Pareto frontier. Do not collapse the frontier into one weighted global
score unless a later reviewed policy defines a business-specific weighting. If token observations are
missing, report cost comparison as incomplete rather than estimating hidden usage.

## Benchmark matrix

Initial replay/shadow candidates should include:

| Task class | Current baseline | Candidates |
| --- | --- | --- |
| read-heavy code exploration | Luna / max | Terra / medium, Terra / high |
| test/CI audit | Luna / max | Terra / medium, Terra / high |
| normal bounded implementation | Luna / max | Terra / high, Sol / high |
| elevated accounting/temporal review | Sol / high | Terra / high, Terra / xhigh, Sol / xhigh |
| critical/adjudication review | Sol / xhigh | Astra / xhigh canary; no automatic promotion/downgrade |
| hardest implementation/review synthesis | Sol / xhigh | Astra / xhigh canary; no active-PR authority |
| master synthesis/merge-gate reasoning | Sol / xhigh | Astra / xhigh historical canary only |

Keep prompts, repository state, acceptance matrix, and exact task evidence equivalent across compared
runs. Prefer at least 10 representative tasks per ordinary task class before replacing a production
baseline. A critical reviewer/master route change requires a separate reviewed policy change and must
not be triggered automatically by a cost result.

## GPT-6 Astra canary protocol

`astra_canary` is deliberately not a production route. It exists to compare Astra/xhigh against the
current Sol/xhigh hardest/critical baseline without changing active work.

A valid Astra A/B case must:

1. be a closed historical task or immutable replay fixture, never an active candidate PR;
2. freeze the same repository/base/head evidence, task scope, acceptance matrix, known findings and
   validation evidence before either route is scored;
3. use Sol/xhigh as the baseline and Astra/xhigh as the canary so the first comparison changes the model,
   not both model and nominal effort;
4. run in read-only contexts with no child delegation, MCP, commit, push, review approval, merge, broker,
   credential, or paper/live authority;
5. record acceptance/safety, known BLOCKER/HIGH recall, quality score, measured duration/retries and token
   counts only when the runtime exposes them;
6. mark unavailable, uncomparable or partially observed runs `insufficient_evidence` rather than filling
   missing fields with estimates.

Canary promotion is intentionally manual. Before proposing Astra for any production role, require a
representative set of hardest/critical replay cases with zero acceptance/safety failures and zero known
BLOCKER/HIGH misses, then compare quality, wall-clock, retries and observed credits against Sol/xhigh.
Astra's public benchmarks or stronger average score alone are insufficient. Promotion requires a new
reviewed harness PR that names the exact production role being changed; it never waives human paper/live
gates.

This harness PR establishes the canary role and evaluation contract only. It does not claim that a
repo-specific Astra replay has run in this GitHub-only maintenance session, and therefore it does not
promote Astra from canary to production.

## Current routing conclusion

Until repo-specific benchmark evidence accumulates, keep the current production routes:

- Luna/max remains the default code explorer, test auditor, and initial normal/high/critical implementer
  because its current token-credit rate is about one tenth of Terra and about one twentieth of Sol on
  input while it remains capable enough to justify empirical testing rather than pre-emptive replacement.
- Terra is the primary benchmark candidate where Luna causes missed evidence, repair churn, or materially
  longer completion. Its roughly 10x Luna token-credit rate must buy measurable task-level improvement.
- Sol remains the controlling independent review, boundary, difficult implementation, and master model
  where correctness risk dominates raw token price.
- Astra/xhigh remains shadow-only until the canary protocol produces representative repo-specific evidence
  strong enough to justify a separate promotion PR. Same-token usage currently costs 2.5x Sol, so any
  promotion should demonstrate meaningful quality, latency, retry or total-task efficiency gains.

This is a benchmark starting position, not a permanent model ranking. Promotion/demotion requires
representative evidence plus a separate reviewed harness change.

## Record format

Each JSONL row supplied to `scripts/model_routing_benchmark.py` contains:

- `task_id`, `task_class`, `model`, `effort`;
- `acceptance_pass`, `safety_gate_pass`, `missed_blocker_high`;
- `quality_score` in 0..100;
- measured `duration_ms` and `retries`;
- optionally, all three observed `input_tokens`, `cached_input_tokens`, and `output_tokens`.

Token fields are all-or-none. Missing token data remains unknown. The benchmark output reports per-route
aggregates and a task-class Pareto frontier; it never grants routing or merge authority.
