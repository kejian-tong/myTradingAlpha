# Context Management Policy

Keep the facts needed for safe decisions visible while preserving complete source and validation
evidence. These are context budgets, not permission to reduce required work.

## Summary budgets

- Default task, result, and handoff summaries target 4096 bytes. Include the decision, current scope,
  unresolved risks, next action, and durable evidence references.
- Search and log summaries should use bounded source windows. Identify each window by source path, commit
  or tree SHA, symbol or line range, and relevant output. Keep complete logs and canonical artifacts at
  their durable source; do not copy full histories into task summaries.
- Put stable instructions and invariants before variable status. Expand a source window when a decision,
  conflict, or safety finding needs surrounding context.

## Required reads and evidence

Read full root and scoped instructions, the complete applicable JIT, and complete phase design and
implementation documents before work that requires them. Summary budgets never permit skipping required
source reads, independent review, RED replay, full tests, validation, CI, or evidence needed to verify the
result. Preserve safety findings and unresolved questions in full enough detail to act on them. Never
truncate or delete complete test output, review records, validation receipts, or other canonical evidence
to meet a summary target.

## Native Codex automatic compaction

Trusted-project configuration may set the native root-level `model_auto_compact_token_limit = 128000`
and `model_auto_compact_token_limit_scope = "total"` settings prospectively. They express client
configuration intent; precedence, current-session loading, and what context is retained remain subject
to Codex behavior and higher-priority configuration. These settings do not reduce required reads,
validation, or durable evidence. Keep source identities and recovery references available and re-read
changed or conflicting sources after compaction. Native compaction does not authorize transcript
ingestion or a history collector.

## Reuse and recovery

Reuse a verified fact only while its source identity remains current. Re-read changed instructions, scope,
head, or conflicting evidence. Point to immutable history and exact PRs or commits; load cold history only
for a specific recovery question. Current GitHub and repository state remain authoritative.

Stable prefixes may improve cache reuse; edits to them can reduce that benefit. Byte counts are practical
proxies for context size, not measurements of tokens, cache hits, cost, threshold exposure, or savings.
Reviewed native automatic compaction is authorized prospectively through the exact project settings above.
It authorizes no transcript ingestion or history collector and does not reduce required reads or evidence
retention.
