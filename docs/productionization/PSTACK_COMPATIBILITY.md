# pstack compatibility

This Harness integration adapts a bounded set of skills from `cursor/plugins/pstack` version `0.15.25`, commit `e5136d82418d2db3165ea1050d17577cd618cc05`, whose `pstack` subtree is `de8e53ebbeca0fe9351e950095e720655da08349`. The previous pin was version `0.15.13`, commit `e5a8186d7b43be8d6ac4452440fbead5f1a51c70`, with subtree `6a8c28c4bdd81315ac46392fc86d8013cca8a684`. The previous commit is an ancestor of the new commit. The machine-readable source and adaptation contract is `.agents/skills/poteto-mode/compatibility.json`.

The selected source inventory contains 16 previously selected skills and the three new root skills `ketchup`, `in-your-own-words`, and `sharpen`. The compatibility manifest pins the exact source-file SHA-256 values from the new Git commit and the SHA-256 of each adapted local file. Skill frontmatter contains only the Codex `name` and `description`. The manifest remains schema version 1 and preserves its existing authority, exclusion, and portable-reference records.

## Skill purposes

| Skill | Adaptation purpose |
| --- | --- |
| `architect` | Shape a repository-aligned design from explicit requirements and constraints. |
| `arena` | Compare design options sequentially within one context. |
| `figure-it-out` | Investigate unclear behavior through bounded repository evidence. |
| `how` | Explain how a repository capability or workflow works. |
| `in-your-own-words` | Restate the user's goal and problem without authorizing or executing work. |
| `interrogate` | Surface adversarial questions as supplemental analysis. |
| `ketchup` | Catch the user up from existing evidence since the last human message. |
| `poteto-mode` | Route supported engineering tasks through repository-owned policy. |
| `principle-separate-before-serializing-shared-state` | Keep shared mutable state separate until an explicit serialization boundary. |
| `principles-design` | Explore design choices while preserving repository constraints. |
| `principles-verification` | Turn work into deterministic, behavior-focused verification. |
| `sharpen` | Improve task framing while retaining authorized scope and approval gates. |
| `show-me-your-work` | Summarize decisions using existing PR and repository evidence. |
| `tdd` | Guide test-first work through the repository's authoritative TDD procedure. |
| `technical-writing` | Improve engineering prose while following repository language policy. |
| `why` | Explain reasons using repository evidence only. |

## Upstream change disposition

The pinned source delta contains 31 pstack commits and 96 changed paths. The table accounts for the complete delta by path category.

| Changed paths | Disposition |
| --- | --- |
| 40 root skill documents | Adapt the three new skills and reconcile the 12 changed source documents among the 16 previously selected skills. Four previously selected source documents are byte-identical across the pins. The remaining 25 changed root skills are excluded: `automate-me`, `benchmark-checklist`, `blast-radius`, `correct`, `create-verification-skill`, `principle-attack-the-premise`, `principle-build-the-lever`, `principle-encode-lessons-in-structure`, `principle-explain-the-number`, `principle-fix-root-causes`, `principle-guard-the-context-window`, `principle-laziness-protocol`, `principle-make-operations-idempotent`, `principle-minimize-reader-load`, `principle-model-the-domain`, `principle-never-block-on-the-human`, `principle-subtract-before-you-add`, `principle-type-system-discipline`, `no-comments`, `poteto-help`, `recall`, `reflect`, `setup-pstack`, `swarm`, and `unslop`. For selected skills whose upstream edits are compression, repository-equivalent wording, or prohibited routing, the prior compatible local text remains unchanged. The substantive design and verification principle updates are incorporated in the two combined local principle skills. |
| 17 references and 18 playbooks | Excluded. These supporting prompts and operating workflows are not part of the selected standalone skill inventory and may encode Cursor-specific routing, automation, or authority. No upstream reference or playbook file is imported. |
| 13 scripts and script tests | Excluded. This includes plan and orchestration scripts, their tests and package metadata, PR-watcher code/tests, and worktree auditing. No runtime, dependency, watcher, scheduler, or executable is added. |
| 6 plugin metadata and guide files | Excluded. `.cursor-plugin/plugin.json`, `plugin.json`, `README.md`, and the three changed setup, design, and principles guide pages do not define this repository's agent authority or runtime. |
| 2 agent definitions | Excluded. The pstack agent prompts do not change this repository's named roles, model routing, or collaboration policy. |

The adapted `ketchup` skill is a concise, evidence-backed, read-only recap bounded by the last human message. It uses messages and artifacts already available, distinguishes verified, pending, and unknown facts, and prohibits app/job starts, capture, posting, transcript retrieval, and dependencies outside this repository. `in-your-own-words` restates the goal and problem without executing work or adding authority. `sharpen` improves task framing and retains an outside check only when the original authorization, current JIT, repository policy, and available evidence permit it. None of these skills widens scope or changes an approval gate.

The combined design principle considers the complete impact of a requirement and delivers approved changes incrementally through existing repository gates. It does not require a fixed number of design candidates. The combined verification principle tests observable contracts rather than private implementation details; it accepts direct invariant checks and denied-effect checks paired with positive controls, and asks whether a test detects a broken behavior while surviving internal refactoring.

## Repository authority and safety

Root and scoped `AGENTS.md` files and the six authoritative Harness skills remain authoritative. The Master may delegate bounded first-level work when repository policy allows it; non-Master nested delegation is prohibited. One production writer and the Master-owned writer lease remain required. Repository TDD, exact-head review, exact-SHA CI, and the Master merge gate remain unchanged. The Master alone merges. Delegated specialists do not push or merge.

`poteto-mode` routes the three new skills while preserving those boundaries. It does not choose models or provide fallback routes. The manifest preserves all authority and excluded-capability fields, including `autonomous_landing: false`, prohibited shipping/autopilot capabilities, unchanged PAPER/live/broker policy, and unchanged model routing. The skills add no setup, push, merge, deployment, promotion, credential, or roadmap-slice authority.

The user fork [`kejian-tong/pstack`](https://github.com/kejian-tong/pstack) is monitored separately from the historical portable reference. At this update, the fork's `main` commit is `e5136d82418d2db3165ea1050d17577cd618cc05` and its `pstack` tree is `de8e53ebbeca0fe9351e950095e720655da08349`, exactly matching the canonical pin above; no fork-only divergence is present. The historical portable reference remains `backnotprop/pstack` commit `124f622bcaeac490e7e9dac6af83f3ef9611d554`, which records the `cursor/plugins/pstack` version `0.15.9` snapshot at commit `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`. It informed portability review only. Canonical content and hashes come from the pinned `cursor/plugins/pstack` `0.15.25` source above.

The upstream MIT license is unchanged between the old and new pins. Its SHA-256 is `bc957ca6bee02792566a1a028d105e02e247c6e77cf057061674273da77b200e`; the applicable notice is [`PSTACK_MIT_NOTICE.md`](PSTACK_MIT_NOTICE.md).

## Hourly source synchronization

A native hourly Master-gated synchronization already exists outside this repository. It is separate from pstack's excluded autonomous-landing capability. This PR adds no scheduler, automation settings, credentials, or runtime code.

Each run resolves and records the exact canonical source commit and `pstack` tree hash, then separately resolves the `kejian-tong/pstack` fork commit and tree. It inspects and attributes any fork-only divergence separately; fork-only content does not silently replace or become canonical upstream content. If the source pin is unchanged and no sync PR is pending, the run exits without creating a PR. If a PR is already pending, resume and reconcile that PR even when the upstream pin is unchanged; do not open a duplicate. When the canonical source changes, the sync uses only the bounded metadata and selected skill blobs needed for review.

Each scheduled run performs a bounded probe. On a transient source/API failure, rate limit, or active or blocked writer lease, it stops and backs off to a later scheduled run; it does not poll or overlap another writer. A real source change follows repository RED/GREEN validation, a fresh exact-head review, and required CI. Only the Master may merge, through the expected-SHA merge gate. Pstack's `autonomous_landing` remains false and cannot waive repository or human approval gates.

Revert this Harness-only change to restore the prior local skills and source pins. There is no product/runtime migration.
