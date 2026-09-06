"""Structured JSON logging with context-local correlation and redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from pydantic import BaseModel

_REDACTED = "[REDACTED]"
_PLAIN_DATA_MAX_DEPTH = 64
_PLAIN_DATA_SENSITIVE_FIELDS = frozenset(
    {
        "source_locator",
        "terms",
    }
)
_CORRELATION_FIELDS = (
    "correlation_id",
    "run_id",
    "mode",
    "variant_id",
    "schema_version",
)
_SENSITIVE_FIELD_PATHS = (
    ("aws", "secret", "access", "key"),
    ("aws", "access", "key", "id"),
    ("broker", "account", "id"),
    ("consumer", "secret"),
    ("client", "secret"),
    ("session", "token"),
    ("refresh", "token"),
    ("access", "token"),
    ("bearer", "token"),
    ("auth", "token"),
    ("api", "secret"),
    ("api", "key"),
    ("private", "key"),
    ("account", "number"),
    ("account", "id"),
    ("authorization",),
    ("password",),
    ("secret",),
    ("token",),
)
_SENSITIVE_COMPACT_FIELDS = frozenset(
    "".join(path) for path in _SENSITIVE_FIELD_PATHS if len(path) > 1
)
_CAMEL_ACRONYMS = {"api": "API", "aws": "AWS", "id": "ID"}
_SENSITIVE_CAMEL_SUFFIXES = tuple(
    dict.fromkeys(
        suffix
        for path in _SENSITIVE_FIELD_PATHS
        for suffix in (
            "".join(part.title() for part in path),
            "".join(_CAMEL_ACRONYMS.get(part, part.title()) for part in path),
        )
    )
)
_CAMEL_BOUNDARY_PATTERN = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
_FIELD_PART_PATTERN = re.compile(r"[A-Za-z0-9]+")
_SENSITIVE_ALIAS_PATTERN = "(?:" + "|".join(
    r"[-_.]?".join(path) for path in _SENSITIVE_FIELD_PATHS
) + ")"
_SENSITIVE_CAMEL_KEY_PATTERN = (
    r"(?:[A-Za-z][A-Za-z0-9]*?)(?:"
    + "|".join(re.escape(suffix) for suffix in _SENSITIVE_CAMEL_SUFFIXES)
    + ")"
)
_SENSITIVE_TEXT_KEY_PATTERN = (
    rf"(?:(?:[A-Za-z][A-Za-z0-9]*[-_.]+)*{_SENSITIVE_ALIAS_PATTERN}"
    rf"|(?-i:{_SENSITIVE_CAMEL_KEY_PATTERN}))"
)
_AUTHORIZATION_TEXT_KEY_PATTERN = (
    r"(?:(?:[A-Za-z0-9]+[-_.]+)*authorization"
    r"|(?-i:(?:[A-Za-z][A-Za-z0-9]*?)Authorization))"
)
_BEARER_PATTERN = re.compile(
    r"(\bBearer\s+)(?!\[REDACTED\])[^\s,}\]]+", re.IGNORECASE
)
_AUTHORIZATION_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_.-])"
    rf"(?P<prefix>(?P<key_quote>[\"']?)"
    rf"(?P<key>{_AUTHORIZATION_TEXT_KEY_PATTERN})"
    r"(?P=key_quote)\s*[:=])"
    r"(?!\s*[\"']?\[REDACTED\][\"']?)"
    r"(?P<spacing>\s*)"
    r"(?P<value>"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\r\n,}\]]+))",
    re.IGNORECASE,
)
_KEY_VALUE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_.-])"
    rf"(?P<prefix>(?P<key_quote>[\"']?)"
    rf"(?P<key>{_SENSITIVE_TEXT_KEY_PATTERN})"
    r"(?P=key_quote)\s*[:=])"
    r"(?!\s*[\"']?\[REDACTED\][\"']?)"
    r"(?P<spacing>\s*)"
    r"(?P<value>"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,}\];]+))",
    re.IGNORECASE,
)
_PLAIN_DATA_TEXT_FIELD_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<prefix>(?P<key_quote>[\"']?)(?P<key>source_locator|terms)"
    r"(?P=key_quote)\s*[:=])"
    r"(?!\s*[\"']?\[REDACTED\][\"']?)"
    r"(?P<spacing>\s*)"
    r"(?P<value>"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[[^\]]*\]|[^\s,}\];]+))",
    re.IGNORECASE,
)
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "mytradingalpha_log_context", default=None
)


def _is_sensitive_field(field_name: Any) -> bool:
    if not isinstance(field_name, str):
        return False
    separated = _CAMEL_BOUNDARY_PATTERN.sub("_", field_name)
    parts = tuple(
        part.casefold() for part in _FIELD_PART_PATTERN.findall(separated)
    )
    return any(
        len(parts) >= len(path) and parts[-len(path) :] == path
        for path in _SENSITIVE_FIELD_PATHS
    ) or bool(parts and parts[-1] in _SENSITIVE_COMPACT_FIELDS)


def _redact_text(value: str) -> str:
    value = _PRIVATE_KEY_PATTERN.sub(_REDACTED, value)
    value = _AUTHORIZATION_PATTERN.sub(_replace_sensitive_value, value)
    value = _KEY_VALUE_PATTERN.sub(_replace_sensitive_value, value)
    return _BEARER_PATTERN.sub(rf"\1{_REDACTED}", value)


def redact_text(value: str) -> str:
    """Return text redacted with the same rules used by structured logging."""

    if type(value) is not str:
        raise TypeError("redact_text requires an exact string")
    return _redact_text(value)


def redact_plain_data(value: Any) -> Any:
    """Redact exact built-in JSON data before it is serialized to an artifact."""

    def visit(item: Any, *, field_name: Any, seen: set[int], depth: int) -> Any:
        if depth > _PLAIN_DATA_MAX_DEPTH:
            raise ValueError("plain data exceeds maximum redaction depth")
        item_type = type(item)
        if item_type is str:
            if field_name in _PLAIN_DATA_SENSITIVE_FIELDS or _is_sensitive_field(field_name):
                return _REDACTED
            return _redact_plain_text(item)
        if item_type is float:
            if not isfinite(item):
                raise ValueError("plain data requires finite numbers")
            return item
        if item_type in (int, bool, type(None)):
            return item
        if item_type not in (dict, list, tuple):
            raise TypeError("plain data redaction accepts exact built-in JSON values")
        identity = id(item)
        if identity in seen:
            raise ValueError("plain data contains a cycle")
        seen.add(identity)
        try:
            if item_type is dict:
                result: dict[str, Any] = {}
                for key, child in item.items():
                    if type(key) is not str:
                        raise TypeError("plain data object keys must be exact strings")
                    result[key] = visit(child, field_name=key, seen=seen, depth=depth + 1)
                return result
            return [
                visit(child, field_name=None, seen=seen, depth=depth + 1)
                for child in item
            ]
        finally:
            seen.remove(identity)

    return visit(value, field_name=None, seen=set(), depth=0)


def _replace_sensitive_value(match: re.Match[str]) -> str:
    if not _is_sensitive_field(match.group("key")):
        return match.group(0)
    raw_value = match.group("value")
    if raw_value[0] in {'"', "'"}:
        return (
            f"{match.group('prefix')}{match.group('spacing')}"
            f"{raw_value[0]}{_REDACTED}{raw_value[0]}"
        )
    return f"{match.group('prefix')}{match.group('spacing')}{_REDACTED}"


def _replace_plain_field_value(match: re.Match[str]) -> str:
    raw_value = match.group("value")
    if raw_value[0] in {'"', "'"}:
        return (
            f"{match.group('prefix')}{match.group('spacing')}"
            f"{raw_value[0]}{_REDACTED}{raw_value[0]}"
        )
    return f"{match.group('prefix')}{match.group('spacing')}{_REDACTED}"


def _redact_plain_text(value: str) -> str:
    return _redact_text(
        _PLAIN_DATA_TEXT_FIELD_PATTERN.sub(_replace_plain_field_value, value)
    )


def _redact_value(
    value: Any, *, field_name: Any = None, redact_strings: bool = True
) -> Any:
    if _is_sensitive_field(field_name):
        return _REDACTED
    if isinstance(value, BaseModel):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            key: _redact_value(
                item, field_name=key, redact_strings=redact_strings
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            _redact_value(item, redact_strings=redact_strings) for item in value
        )
    if isinstance(value, list):
        return [_redact_value(item, redact_strings=redact_strings) for item in value]
    if isinstance(value, set):
        return {_redact_value(item, redact_strings=redact_strings) for item in value}
    if isinstance(value, str) and redact_strings:
        return _redact_text(value)
    return value


class RedactionFilter(logging.Filter):
    """Redact sensitive field values and token-like formatted text."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_value(record.msg, redact_strings=False)
        record.args = _redact_value(record.args, redact_strings=False)
        for key, value in tuple(record.__dict__.items()):
            if key not in {"msg", "args"}:
                record.__dict__[key] = _redact_value(
                    value, field_name=key, redact_strings=False
                )
        record.msg = _redact_text(record.getMessage())
        record.args = ()
        if record.exc_text is None and record.exc_info is not None:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if isinstance(record.exc_text, str):
            record.exc_text = _redact_text(record.exc_text)
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = _context.get() or {}
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update({field: context.get(field) for field in _CORRELATION_FIELDS})
        return json.dumps(_redact_value(payload), sort_keys=True, default=str)


@contextmanager
def correlation_scope(**values: Any) -> Iterator[None]:
    """Temporarily merge correlation fields and restore the prior scope."""

    unknown = set(values) - set(_CORRELATION_FIELDS)
    if unknown:
        raise ValueError(f"unknown correlation fields: {sorted(unknown)!r}")
    token = _context.set({**(_context.get() or {}), **values})
    try:
        yield
    finally:
        _context.reset(token)


def configure_logging(*, logger: logging.Logger, stream: Any) -> logging.Logger:
    """Install one redacted JSON stream handler on ``logger``."""

    # Configure a dedicated logger before starting producers. An earlier caller-owned
    # handler could emit a record before our redaction filter sees it. Do not silently
    # remove or take ownership of another component's sinks.
    if any(
        not getattr(handler, "_mytradingalpha_structured", False)
        for handler in logger.handlers
    ):
        raise ValueError("structured logging requires a dedicated logger")

    for handler in list(logger.handlers):
        if getattr(handler, "_mytradingalpha_structured", False):
            logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(stream)
    handler._mytradingalpha_structured = True  # type: ignore[attr-defined]
    handler.addFilter(RedactionFilter())
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


__all__ = [
    "RedactionFilter",
    "configure_logging",
    "correlation_scope",
    "redact_plain_data",
    "redact_text",
]
