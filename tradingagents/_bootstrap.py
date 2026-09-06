"""One-shot initialization for ordinary TradingAgents runtimes."""

from __future__ import annotations

import contextlib
import threading
import warnings

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED = False


def bootstrap_ordinary_runtime() -> None:
    """Load ordinary runtime environment and warning configuration once."""

    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return

        # find_dotenv(usecwd=True) makes the installed console script load the
        # caller's project files. The default override=False preserves values
        # already exported by the process.
        try:
            from dotenv import find_dotenv, load_dotenv

            load_dotenv(find_dotenv(usecwd=True))
            load_dotenv(find_dotenv(".env.enterprise", usecwd=True), override=False)
        except ImportError:
            pass

        # langchain-core installs its warning filters during import. Preload it
        # before adding the narrower checkpoint compatibility suppression.
        with contextlib.suppress(ImportError):
            import langchain_core  # noqa: F401

        warnings.filterwarnings(
            "ignore",
            message=r"The default value of `allowed_objects`.*",
            category=PendingDeprecationWarning,
        )
        _BOOTSTRAPPED = True


__all__ = ["bootstrap_ordinary_runtime"]
