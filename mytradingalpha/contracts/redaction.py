"""Conservative artifact-text redaction shared by production contracts."""

from __future__ import annotations

import re
from math import isfinite
from typing import Any

_REDACTED = "[REDACTED]"
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER_PATTERN = re.compile(
    r"(\bBearer\s+)(?!\[REDACTED\])[^\s,}\]]+",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{8,}"
    r"|(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])"
)
_SENSITIVE_KEY_PATHS = (
    ("access", "token"),
    ("api", "key"),
    ("api", "secret"),
    ("authorization",),
    ("aws", "access", "key", "id"),
    ("aws", "secret", "access", "key"),
    ("bearer",),
    ("bearer", "token"),
    ("auth", "token"),
    ("broker", "account", "id"),
    ("client", "secret"),
    ("consumer", "secret"),
    ("account", "number"),
    ("account", "id"),
    ("password",),
    ("private", "key"),
    ("refresh", "token"),
    ("secret",),
    ("session", "token"),
    ("source", "locator"),
    ("terms",),
    ("token",),
)
_SENSITIVE_COMPACT_KEYS = frozenset(
    "".join(path) for path in _SENSITIVE_KEY_PATHS if len(path) > 1
)
_PLAIN_DATA_MAX_DEPTH = 64
_PLAIN_DATA_SENSITIVE_FIELDS = frozenset({"source_locator", "terms"})
_ASSIGNMENT_PREFIX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<prefix>(?P<key_escape>\\*)(?P<key_quote>[\"']?)"
    r"(?P<key>[A-Za-z][A-Za-z0-9_.-]*)"
    r"(?P=key_escape)(?P=key_quote)\s*[:=])(?P<spacing>\s*)",
    re.IGNORECASE,
)


def _key_parts(value: str) -> tuple[str, ...]:
    value = value.replace("\\", "").replace('"', "").replace("'", "")
    value = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
        "_",
        value,
    )
    return tuple(part.casefold() for part in re.findall(r"[A-Za-z0-9]+", value))


def _is_sensitive_key(value: str) -> bool:
    parts = _key_parts(value)
    if not parts:
        return False
    compact = "".join(parts)
    if any(compact.endswith(key) for key in _SENSITIVE_COMPACT_KEYS):
        return True
    return any(
        len(parts) >= len(path) and parts[-len(path) :] == path
        for path in _SENSITIVE_KEY_PATHS
    )


def _quoted_value_bounds(value: str, start: int) -> tuple[int, str, str] | None:
    index = start
    while index < len(value) and value[index] == "\\":
        index += 1
    if index >= len(value) or value[index] not in {'"', "'"}:
        return None
    quote = value[index]
    escape_depth = index - start
    content_start = index + 1
    cursor = content_start
    while cursor < len(value):
        if value[cursor] == quote:
            run = 0
            preceding = cursor - 1
            while preceding >= content_start and value[preceding] == "\\":
                run += 1
                preceding -= 1
            if run == escape_depth or (escape_depth == 0 and run % 2 == 0):
                return cursor + 1, value[start : content_start], value[cursor - run : cursor + 1]
        cursor += 1
    return len(value), value[start : content_start], ""


def _value_end(value: str, start: int) -> tuple[int, str, str]:
    quoted = _quoted_value_bounds(value, start)
    if quoted is not None:
        return quoted
    if value.startswith(_REDACTED, start):
        return start + len(_REDACTED), "", ""
    index = start
    while index < len(value) and value[index] not in "\r\n,;}]":
        index += 1
    return index, "", ""


def _redact_assignments(value: str) -> str:
    output: list[str] = []
    cursor = 0
    for match in _ASSIGNMENT_PREFIX_PATTERN.finditer(value):
        if match.start() < cursor:
            continue
        output.append(value[cursor : match.start()])
        if not _is_sensitive_key(match.group("key")):
            output.append(match.group(0))
            cursor = match.end()
            continue
        end, quote_prefix, quote_suffix = _value_end(value, match.end())
        prefix = f"{match.group('prefix')}{match.group('spacing')}"
        if quote_prefix:
            replacement = f"{prefix}{quote_prefix}{_REDACTED}{quote_suffix}"
        else:
            replacement = f"{prefix}{_REDACTED}"
        output.append(replacement)
        cursor = end
    output.append(value[cursor:])
    return "".join(output)


def redact_artifact_text(value: str) -> str:
    """Redact sensitive artifact text with deterministic, idempotent rules."""

    if type(value) is not str:
        raise TypeError("artifact redaction requires an exact string")
    redacted = _PRIVATE_KEY_PATTERN.sub(_REDACTED, value)
    for _ in range(3):
        updated = _redact_assignments(redacted)
        updated = _BEARER_PATTERN.sub(rf"\1{_REDACTED}", updated)
        updated = _TOKEN_PATTERN.sub(_REDACTED, updated)
        if updated == redacted:
            break
        redacted = updated
    return redacted


def validate_artifact_text(value: str) -> str:
    """Return safe artifact text or fail closed when redaction would change it."""

    if type(value) is not str:
        raise TypeError("artifact validation requires an exact string")
    if redact_artifact_text(value) != value:
        raise ValueError("artifact text contains sensitive material")
    return value


def redact_plain_data(value: Any) -> Any:
    """Redact exact built-in JSON data before it is serialized to an artifact."""

    def visit(item: Any, *, field_name: Any, seen: set[int], depth: int) -> Any:
        if depth > _PLAIN_DATA_MAX_DEPTH:
            raise ValueError("plain data exceeds maximum redaction depth")
        item_type = type(item)
        if item_type is str:
            if type(field_name) is str and (
                field_name in _PLAIN_DATA_SENSITIVE_FIELDS
                or _is_sensitive_key(field_name)
            ):
                return _REDACTED
            return redact_artifact_text(item)
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
                for key, child in dict.items(item):
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


__all__ = ["redact_artifact_text", "redact_plain_data", "validate_artifact_text"]
