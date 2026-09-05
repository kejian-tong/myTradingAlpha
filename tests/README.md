# Test execution boundaries

Install the reviewed environment with `uv sync --locked --extra dev`; run the default
suite using `uv run --no-sync pytest -q`. Provider integration tests are disabled by
default, including when a non-placeholder key exists in the shell. Ordinary tests
receive placeholder provider keys; tests that need a specific fake value set it locally.

A separately authorized operator may explicitly run external integration tests with:

```bash
uv run --no-sync pytest -m integration --run-provider-integration
```

That command can incur costs and contact external services. It is not part of ordinary
CI or the remediation validation. A marker alone or a key alone does not enable it.
The opt-in mechanism is not an OS network sandbox: native clients, collection-time
code, and unmarked tests require source review and environment-level network isolation
when validating untrusted changes. Never include real credentials in test fixtures.

The `clean-install smoke` job installs without editable source and runs the exact
installed interpreter with `-I` outside the checkout. `scripts/smoke_installed.py`
checks definition imports and their site-packages origins; it does not run a graph.

The dependency-direction checker covers static imports and recognizable literal
`importlib.import_module` / `__import__` calls, aliases, and ordinary local shadowing.
Computed targets on recognized loaders fail with a manual-review diagnostic. This is
bounded static analysis, not proof against arbitrary reflective Python execution.
