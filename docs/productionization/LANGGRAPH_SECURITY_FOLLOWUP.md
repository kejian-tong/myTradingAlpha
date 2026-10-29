# LangGraph SDK Path Encoding Security Follow-up

## Chronology and fix

The 2026-10-29 dependency-graph refresh surfaced LangGraph security alerts 15 and 16 under
[GHSA-3fx2-cqw9-xr3c](https://github.com/advisories/GHSA-3fx2-cqw9-xr3c). These alerts were absent from
the earlier dependency snapshot. PR #108 had already fixed its 12 scoped alerts; this follow-up addresses
the newly observed remainder without attributing it to PR #108.

In `langgraph-sdk` 0.4.4, the synchronous and asynchronous thread stream helpers interpolated thread and
assistant identifiers into the `thread.output` state request and `thread.agent.get_tree()` graph request.
HTTPX can normalize dot segments and interpret query or fragment characters in those values. The upstream
fix quotes each identifier as one path segment. LangGraph 1.2.14 requires `langgraph-sdk>=0.4.6,<0.5`, so
the project floor is raised to `langgraph>=1.2.14,<2`; the lock selects exactly LangGraph 1.2.14 and SDK
0.4.6.

The offline regression in `tests/test_langgraph_sdk_path_security.py` drives all four public call paths
through real SDK request construction and HTTPX `MockTransport`. It checks ordinary IDs plus traversal,
query, fragment, percent, and Unicode cases against literal raw-path expectations. Every captured request
must retain the fixed mock HTTPS origin and synthetic API key. The mock permits only the expected target
GET and a bounded lifecycle SSE subscription; it makes no live request.

## Impact boundary

The advisory concerns same-origin authenticated GET path and query confusion. The available evidence does
not establish cross-origin credential disclosure or a write primitive. This repository uses local
`StateGraph` and checkpointing and has no SDK `RemoteGraph` call site, so application exploitability is
conditional on a remote SDK path being used with an attacker-controlled identifier.

## Compatibility and rollback

The change preserves the Research Graph API, local graph and checkpoint behavior, and existing serialized
artifacts. It adds no direct SDK dependency or data migration. The `pyproject.toml` floor protects pip
fallback installations as well as lock-based installs. Reverting these patched versions requires an
explicit reviewed security decision; any rollback must retain a safe dependency floor.

The upstream implementation and package metadata are available in the
[LangGraph fix commit](https://github.com/langchain-ai/langgraph/commit/d89c7e100ec6fc1512544d23b0a7c5169699ef3e),
[LangGraph 1.2.14 metadata](https://pypi.org/pypi/langgraph/1.2.14/json), and
[langgraph-sdk 0.4.6 metadata](https://pypi.org/pypi/langgraph-sdk/0.4.6/json).
