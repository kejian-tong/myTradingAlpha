"""Conservative artifact-text redaction shared by production contracts."""

from __future__ import annotations

import json
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
    "".join(path) for path in _SENSITIVE_KEY_PATHS
)
_PLAIN_DATA_MAX_DEPTH = 64
_JSON_MAX_UNESCAPE_ATTEMPTS = 5
_JSON_MAX_FRAGMENT_BYTES = 1_048_576
_JSON_MAX_FRAGMENTS = 32
_ASSIGNMENT_PREFIX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<prefix>(?P<key_escape>\\*)(?P<key_quote>[\"']?)"
    r"(?P<key>[A-Za-z0-9_.-]+)"
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
    return _is_sensitive_parts(_key_parts(value))


def _is_sensitive_parts(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    compact = "".join(parts)
    if any(compact.endswith(key) for key in _SENSITIVE_COMPACT_KEYS):
        return True
    return any(
        len(parts) >= len(path) and parts[-len(path) :] == path
        for path in _SENSITIVE_KEY_PATHS
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sensitive_structural_hint(value: str) -> bool:
    lowered = value.casefold()
    return any(
        len(path) > 1
        and all(
            re.search(rf"(?<![a-z0-9]){re.escape(part)}(?![a-z0-9])", lowered)
            for part in path
        )
        for path in _SENSITIVE_KEY_PATHS
    )


def _parse_and_redact_json(value: str) -> str | None:
    candidate = value
    for _ in range(_JSON_MAX_UNESCAPE_ATTEMPTS):
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if type(parsed) in (dict, list):
            try:
                redacted = redact_plain_data(parsed)
                if redacted == parsed:
                    return ""
                return _canonical_json(redacted)
            except (TypeError, ValueError, OverflowError, UnicodeError):
                return _REDACTED
        if type(parsed) is str:
            candidate = parsed
            continue
        return None
    return None


def _json_fragment_spans(value: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(value) and len(spans) < _JSON_MAX_FRAGMENTS:
        if value[index] not in "[{":
            index += 1
            continue
        start = index
        stack = ["]" if value[index] == "[" else "}"]
        quoted = False
        escaped = False
        index += 1
        while index < len(value) and stack:
            character = value[index]
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                stack.append("]" if character == "[" else "}")
            elif character in "]}":
                if character != stack[-1]:
                    stack.clear()
                    break
                stack.pop()
            index += 1
        if not stack:
            spans.append((start, index))
        else:
            index = start + 1
    return tuple(spans)


def _redact_structural_json(value: str) -> str:
    if len(value.encode("utf-8")) > _JSON_MAX_FRAGMENT_BYTES:
        return _REDACTED if _sensitive_structural_hint(value) else value
    full = _parse_and_redact_json(value)
    if full is not None:
        return value if full == "" else full
    replacements: dict[tuple[int, int], str] = {}
    recognized = False
    for start, end in _json_fragment_spans(value):
        fragment = value[start:end]
        parsed = _parse_and_redact_json(fragment)
        if parsed is None:
            if _sensitive_structural_hint(fragment):
                replacements[(start, end)] = _REDACTED
        else:
            recognized = True
            if parsed:
                replacements[(start, end)] = parsed
    if replacements:
        output: list[str] = []
        cursor = 0
        for start, end in sorted(replacements):
            output.append(value[cursor:start])
            output.append(replacements[(start, end)])
            cursor = end
        output.append(value[cursor:])
        return "".join(output)
    if recognized:
        return value
    has_array = re.search(r"\[(?!REDACTED\])", value) is not None
    if ("{" in value or has_array) and _sensitive_structural_hint(value):
        return _REDACTED
    return value


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
    if value[start : start + 1] in "[{":
        spans = _json_fragment_spans(value[start:])
        if spans and spans[0][0] == 0:
            return start + spans[0][1], '"', '"'
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
    redacted = _redact_structural_json(value)
    redacted = _PRIVATE_KEY_PATTERN.sub(_REDACTED, redacted)
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

    def visit(
        item: Any,
        *,
        path_parts: tuple[str, ...],
        seen: set[int],
        depth: int,
    ) -> Any:
        if depth > _PLAIN_DATA_MAX_DEPTH:
            raise ValueError("plain data exceeds maximum redaction depth")
        item_type = type(item)
        if item_type is str:
            if _is_sensitive_parts(path_parts):
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
                    result[key] = visit(
                        child,
                        path_parts=path_parts + _key_parts(key),
                        seen=seen,
                        depth=depth + 1,
                    )
                return result
            return [
                visit(child, path_parts=path_parts, seen=seen, depth=depth + 1)
                for child in item
            ]
        finally:
            seen.remove(identity)

    return visit(value, path_parts=(), seen=set(), depth=0)


__all__ = ["redact_artifact_text", "redact_plain_data", "validate_artifact_text"]
