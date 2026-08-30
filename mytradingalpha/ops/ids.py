"""Stable, non-secret identifiers for operational correlation."""

from __future__ import annotations

from uuid import uuid4


def new_run_id() -> str:
    """Return a new opaque run identifier."""

    return f"run-{uuid4().hex}"


def new_correlation_id() -> str:
    """Return a new opaque log-correlation identifier."""

    return f"corr-{uuid4().hex}"


__all__ = ["new_correlation_id", "new_run_id"]
