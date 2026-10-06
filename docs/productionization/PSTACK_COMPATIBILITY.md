# pstack compatibility

This PR adapts a bounded set of engineering skills from `cursor/plugins/pstack` version `0.15.13`, commit `e5a8186d7b43be8d6ac4452440fbead5f1a51c70`. The machine-readable provenance and compatibility contract is `.agents/skills/poteto-mode/compatibility.json`.

The adapted files contain Codex-compatible `name` and `description` frontmatter. The local skills preserve useful investigation, design, testing, verification, and writing practices while replacing Cursor-specific routing and autonomy instructions with repository policy.

## Repository authority

Root and scoped `AGENTS.md` files and the six existing repository skills remain authoritative. The Master may delegate bounded first-level work when repository policy allows it. Non-Master nested delegation is prohibited. One production writer and the Master-owned writer lease remain required. Repository TDD, exact-head review, exact-SHA CI, and the Master merge gate remain unchanged. The Master alone merges. Delegated specialists do not push or merge.

The `poteto-mode` skill routes read-only investigation, rationale, design, supplemental adversarial analysis, repository TDD, multi-step planning, writing, and evidence review. `arena` compares candidates sequentially in the same context. `interrogate` is supplemental and cannot replace `exact-head-review`. `tdd` defers to `tdd-red-green-evidence`. `why` uses repository evidence only. `show-me-your-work` uses existing PR, JIT, Git, CI, and review evidence. It does not read raw transcripts or create a separate private log.

The manifest records excluded scripts, agents, MCP configuration, automation packs, and autonomous or shipping workflows. These skills do not change model routing, PAPER/live/broker policy, or roadmap authorization. They do not provide setup, push, merge, deployment, or promotion authority.

The portable reference is `backnotprop/pstack` at `124f622bcaeac490e7e9dac6af83f3ef9611d554`, which records upstream snapshot `cursor/plugins/pstack` version `0.15.9` at `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`. It informed portability review only; canonical content and hashes come from the pinned `0.15.13` source.

The adapted text is distributed under the upstream MIT terms in [`PSTACK_MIT_NOTICE.md`](PSTACK_MIT_NOTICE.md). Revert this Harness-only PR to roll back the integration. It adds no runtime dependency, product behavior, or migration.
