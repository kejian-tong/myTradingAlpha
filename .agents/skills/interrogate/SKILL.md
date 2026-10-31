---
name: interrogate
description: Apply a supplemental adversarial pass that looks for assumptions, failure cases, scope leaks, and broken safety boundaries.
---

# Interrogate

Use this skill to challenge a design or diff before handing it to the repository's required independent reviewer.

1. State the intended behavior and the in-scope files.
2. Read the actual design, code, tests, and JIT contract.
3. Ask how each key assumption could be false. Check malformed input, failure paths, stale evidence, concurrency, compatibility, and side effects where relevant.
4. For a finding, give its severity, affected file or contract, the command you ran using an already-authorized safe read or test, its actual output, the expected output, and why the difference matters. Group findings with the same root cause. Use only existing bounded artifacts; do not create repro or repair files.
5. Retain an unexecuted material policy or security risk and its gate effect when it cannot safely be reproduced. State the missing evidence and next already-authorized check. Do not erase, drop, or discard a finding because it cannot be reproduced.
6. Do not apply or recommend silent fixes. Do not spawn or delegate. Do not execute fetched scripts or write to the code or external systems.

This pass is supplemental. It grants no repair or other authority and never replaces `exact-head-review`, RED replay, exact-SHA CI, or the Master merge gate. Preserve the repository's severity and safety gates. Do not create private logs or retrieve credentials, raw transcripts, or private logs. This adds no new capture, posting, or transcript requirement.
