# Codex Model Routing Benchmark Policy

Status: execution-harness optimization policy. This document evaluates routing evidence; it does not
change approved production architecture, authorize a roadmap slice, or automatically change a named
production route.

## Goal

Choose the least expensive route that remains adequately reliable and correct for each task class. Do
not optimize credits or latency before safety, comparable task coverage, and correctness. A globally
cheapest model is not a valid routing policy because exploration, implementation, accounting/state-machine
review, and master synthesis have different failure costs.

Use `scripts/model_routing_benchmark.py` on representative replay/shadow records. The script never calls
a model and never edits `.codex` routing; it only evaluates supplied evidence.

## Current official rate-card priors

The Work/Codex rate cards were re-checked on 2026-09-07. The benchmark constants use these token rates:

| Model | Input credits / 1M | Cached input / 1M | Output / 1M | Input $ / 1M | Cached $ / 1M | Output $ / 1M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-5.6 Luna | 5 | 0.5 | 30 | 0.20 | 0.02 | 1.20 |
| GPT-5.6 Terra | 50 | 5 | 300 | 2.00 | 0.20 | 12.00 |
| GPT-5.6 Sol | 100 | 10 | 500 | 4.00 | 0.40 | 20.00 |
| GPT-6 Astra | 250 | 25 | 1,250 | 10.00 | 1.00 | 50.00 |

Official sources:

- credits: https://help.openai.com/en/articles/11481834
- Enterprise token-based USD: https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing

At the current rate, Astra costs 2.5x Sol for the same input/cached/output token mix; Terra costs about
10x Luna for the same mix. Those are only token-rate priors. A stronger route may use fewer attempts or
less wall-clock time, so compare measured **end-to-end attempts**, not assumed per-message cost.

Rate cards are mutable external facts. `RATE_CARD_AS_OF` is part of the benchmark evidence and cost-based
Pareto output is allowed only while that rate card is at most 30 days old relative to the supplied
evaluation date. The CLI uses today's date by default and accepts `--evaluation-date YYYY-MM-DD` for a
reproducible historical run. Library callers that provide no evaluation date receive
`unchecked_rate_card` and no cost frontier. Once the rate card is stale, re-check the official sources
and update constants through a reviewed harness PR before using cost results for routing policy.

## Official capability priors are not repo conclusions

Public OpenAI model evaluations may be used to choose candidates to test, but they are not
myTradingAlpha evidence. A route must prove itself on the same repository tasks, acceptance matrix and
known failure surfaces as its comparison routes. GPT-6 Astra remains a historical/read-only canary and
public model scores never promote it automatically.

## Benchmark V2 decision rule

### Gate A — exact task pairing

Routes are comparable only when every route in one task class covers the **same task IDs**. The benchmark
rejects duplicate `(task_class, model, effort, task_id)` rows so repeated data cannot silently overweight
a route.

Output includes, per task class:

- task IDs for every model/effort route;
- the intersection and union of task IDs;
- missing task IDs per route;
- whether pairing is exact;
- the paired task count.

A different task set produces `incomplete_pairing` and no Pareto frontier. This prevents a cheap route
run on easy PRs from being compared directly with a stronger route run only on difficult PRs.

At least **5 exactly paired tasks** are required before the benchmark produces a Pareto comparison.
One/few-task results remain useful debugging evidence but return `insufficient_sample`. A production
promotion proposal requires at least **10 exactly paired representative tasks** and still requires a
separate reviewed routing PR.

### Gate B — route reliability

Reliability is calculated over **all attempts**, not only successful attempts. Failed attempts remain in:

- quality mean;
- duration mean;
- retry mean;
- token/credit/USD means when token data is observed.

This prevents survivorship bias such as a route failing nine tasks and looking excellent because its one
successful task was cheap and high-scoring.

A route is reliability-eligible only when all of these hold:

- at least 5 task runs are present;
- acceptance rate is at least **95%**;
- there are **zero safety-gate failures**;
- there are **zero missed known BLOCKER/HIGH findings**.

Safety failure or a missed BLOCKER/HIGH is an absolute route-level disqualifier for the comparison sample.
Acceptance is a measured reliability rate rather than an absolute any-failure ban so larger representative
samples can distinguish occasional ordinary failure from systematic inadequacy. Human PAPER/live gates
remain mandatory regardless of any benchmark rate.

### Gate C — observation completeness and rate freshness

A cost frontier is valid only when:

1. the rate card is fresh;
2. exact pairing and the five-task minimum are satisfied;
3. at least one route is reliability-eligible; and
4. **every reliability-eligible route** has all three observed token fields on every attempt.

Token observations are all-or-none per run: `input_tokens`, `cached_input_tokens`, and `output_tokens`.
If a reliable route lacks token evidence, output is `incomplete_cost_observation` and no other route is
allowed to become a false cost winner. Unknown usage stays unknown.

### Gate D — Pareto efficiency

Only after Gates A-C pass does the benchmark compare reliability-eligible routes on:

- higher all-attempt quality mean;
- lower all-attempt duration mean;
- lower all-attempt retry mean;
- lower all-attempt observed token-based credits.

Keep nondominated routes on the Pareto frontier. Do not collapse the frontier into a weighted global score
unless a later reviewed policy defines such a business weighting. A frontier is evidence for discussion,
not permission to edit production routing.

## Comparison statuses

The benchmark deliberately emits explicit non-comparison states:

- `unchecked_rate_card` / `stale_rate_card` / `evaluation_precedes_rate_card_rate_card`;
- `incomplete_pairing`;
- `insufficient_sample`;
- `no_reliable_routes`;
- `incomplete_cost_observation`;
- `complete`.

Only `complete` may contain a cost-based Pareto frontier. `promotion_evidence_ready=true` additionally
requires the 10-task paired target and at least two reliability-eligible comparison routes; it still does
not change routing automatically.

## Benchmark matrix

Initial replay/shadow candidates remain:

| Task class | Current baseline | Candidates |
| --- | --- | --- |
| read-heavy code exploration | Luna / max | Terra / medium, Terra / high |
| test/CI audit | Luna / max | Terra / medium, Terra / high |
| normal bounded implementation | Luna / max | Terra / high, Sol / high |
| elevated accounting/temporal review | Sol / high | Terra / high, Terra / xhigh, Sol / xhigh |
| critical/adjudication review | Sol / xhigh | Astra / xhigh canary; no automatic promotion/downgrade |
| hardest implementation/review synthesis | Sol / xhigh | Astra / xhigh canary; no active-PR authority |
| master synthesis/merge-gate reasoning | Sol / xhigh | Astra / xhigh historical canary only |

Freeze repository state, task prompt/scope, known findings and acceptance matrix before running routes.
Historical SIG-02 is a useful hard case because it has an immutable final result and extensive known
adversarial findings, but one task is not enough for a routing conclusion.

## GPT-6 Astra canary protocol

`astra_canary` is deliberately not a production route. A valid Astra A/B case must be a closed historical
or immutable replay task, use the same evidence and task IDs as Sol/xhigh, run read-only with no child/MCP/
write/merge/broker authority, and score the same acceptance and known-finding matrix. The specific
`astra_canary_pairing` output is retained as a convenience, while the generalized pairing gate now
applies to **all** routes.

Astra promotion remains manual. Require representative paired evidence with zero safety failures and zero
known BLOCKER/HIGH misses, then compare reliability, quality, duration, retries and observed total credits.
Promotion requires a separate reviewed Harness PR naming the exact production role. It never waives human
PAPER/live gates.

## Current routing conclusion

Until representative paired benchmark evidence accumulates, keep current production routes:

- Luna/max stays the default explorer, test auditor, and initial normal/high/critical implementer because
  its token-credit rate is dramatically lower and the repository should demand evidence before paying for
  a stronger route on every task.
- Terra remains the primary challenger where Luna produces missed evidence, repair churn or materially
  longer completion; its roughly 10x same-token Luna rate must buy measured task-level improvement.
- Sol remains the controlling review, boundary, difficult implementation and Master model where
  correctness risk dominates token price.
- Astra/xhigh remains shadow-only until paired historical evidence justifies a separate promotion PR.

## Record format

Each JSONL row contains:

- `task_id`, `task_class`, `model`, `effort`;
- `acceptance_pass`, `safety_gate_pass`, `missed_blocker_high`;
- `quality_score` in 0..100;
- measured `duration_ms` and `retries`;
- optionally, all three observed `input_tokens`, `cached_input_tokens`, and `output_tokens`.

Use one row per route/task identity. Failed attempts remain rows and must retain their observed duration,
retry and token consumption. The benchmark output reports reliability, pairing, freshness, per-route
aggregates and a task-class Pareto frontier when comparison is actually valid; it never grants routing or
merge authority.
