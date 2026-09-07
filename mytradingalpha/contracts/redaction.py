"""Conservative artifact-text redaction shared by production contracts."""

from __future__ import annotations

import json
import re
import unicodedata
from math import isfinite
from typing import Any
from urllib.parse import unquote_plus

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
_PERCENT_MAX_UNESCAPE_ATTEMPTS = 5
_ANALYSIS_MAX_ITERATIONS = max(_JSON_MAX_UNESCAPE_ATTEMPTS, _PERCENT_MAX_UNESCAPE_ATTEMPTS)
_PERCENT_MAX_WORK = 1_000_000
_JSON_MAX_FRAGMENT_BYTES = 1_048_576
_JSON_MAX_FRAGMENTS = 32
_MAX_ASSIGNMENT_KEY_CHARS = 256
_MAX_ASSIGNMENT_KEY_COMPONENTS = 16
_MAX_ASSIGNMENT_WORK = 1_000_000
_ASSIGNMENT_KEY_SEPARATORS = frozenset("_./:-\\\"'")


def _decode_unicode_escapes(
    value: str,
    *,
    attempts: int = _JSON_MAX_UNESCAPE_ATTEMPTS,
    report_unresolved: bool = True,
) -> tuple[str, bool]:
    candidate = value
    invalid = any(0xD800 <= ord(character) <= 0xDFFF for character in candidate)
    for _ in range(attempts):
        if re.search(r"\\u(?![0-9a-fA-F]{4})", candidate, re.IGNORECASE):
            invalid = True
        updated = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda match: chr(int(match.group(1), 16)),
            candidate,
            flags=re.IGNORECASE,
        )
        if updated == candidate:
            break
        candidate = updated
        if any(0xD800 <= ord(character) <= 0xDFFF for character in candidate):
            invalid = True
    if report_unresolved and re.search(r"\\u[0-9a-fA-F]{4}", candidate):
        invalid = True
    return candidate, invalid


def _decode_key_escapes(value: str) -> tuple[str, bool]:
    return _decode_unicode_escapes(value)


def _percent_sensitive_prefix(value: str, index: int) -> bool:
    start = index - 1
    scanned = 0
    while start >= 0 and _assignment_key_char(value[start]):
        scanned += 1
        if scanned > _MAX_ASSIGNMENT_KEY_CHARS:
            return True
        start -= 1
    return _is_sensitive_key(value[start + 1 : index])


def _decode_percent_escapes(
    value: str,
    *,
    attempts: int = _PERCENT_MAX_UNESCAPE_ATTEMPTS,
    report_unresolved: bool = True,
) -> tuple[str, bool]:
    candidate = value
    unresolved = False
    for _ in range(attempts):
        if len(candidate) > _PERCENT_MAX_WORK:
            return candidate, True
        try:
            updated = unquote_plus(candidate, encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            return candidate, True
        if updated == candidate:
            break
        candidate = updated
    if report_unresolved and re.search(r"%[0-9a-fA-F]{2}", candidate):
        unresolved = True
    index = 0
    while index < len(candidate):
        if candidate[index] == "%":
            valid_escape = (
                index + 2 < len(candidate)
                and all(
                    character in "0123456789abcdefABCDEF"
                    for character in candidate[index + 1 : index + 3]
                )
            )
            if (not valid_escape or report_unresolved) and _percent_sensitive_prefix(candidate, index):
                unresolved = True
            index += 1
            continue
        index += 1
    return candidate, unresolved


def _normalize_encoded_analysis(value: str) -> tuple[str, bool]:
    """Alternate bounded Unicode and percent decoding to one fixed point."""

    candidate = value
    for _ in range(_ANALYSIS_MAX_ITERATIONS):
        unicode_candidate, unicode_bad = _decode_unicode_escapes(
            candidate, attempts=1, report_unresolved=False
        )
        if unicode_bad:
            return candidate, True
        percent_candidate, percent_bad = _decode_percent_escapes(
            unicode_candidate, attempts=1, report_unresolved=False
        )
        if percent_bad:
            return candidate, True
        if percent_candidate == candidate:
            return candidate, False
        candidate = percent_candidate

    probe_unicode, unicode_bad = _decode_unicode_escapes(
        candidate, attempts=1, report_unresolved=False
    )
    if unicode_bad or probe_unicode != candidate:
        return candidate, True
    probe_percent, percent_bad = _decode_percent_escapes(
        candidate, attempts=1, report_unresolved=False
    )
    if percent_bad or probe_percent != candidate:
        return candidate, True
    return candidate, False


def _key_parts(value: str) -> tuple[str, ...]:
    value, _ = _decode_key_escapes(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\\", "").replace('"', "").replace("'", "")
    value = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
        "_",
        value,
    )
    return tuple(part.casefold() for part in re.findall(r"[A-Za-z0-9]+", value))


def _is_sensitive_key(value: str) -> bool:
    decoded, invalid = _decode_key_escapes(value)
    if _is_sensitive_parts(_key_parts(decoded)):
        return True
    return bool(invalid)


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
    if re.search(r"\\u(?![0-9a-fA-F]{4})", lowered):
        return True
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
    spans, _ = _json_fragment_spans_bounded(value)
    return spans


def _json_fragment_spans_bounded(
    value: str,
) -> tuple[tuple[tuple[int, int], ...], bool]:
    spans: list[tuple[int, int]] = []
    index = 0
    stack: list[str] = []
    start: int | None = None
    quoted = False
    escaped = False
    while index < len(value):
        if not stack and value.startswith(_REDACTED, index):
            index += len(_REDACTED)
            continue
        character = value[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            index += 1
            continue
        if character == '"' and stack:
            quoted = True
            index += 1
            continue
        if character in "[{":
            if not stack:
                start = index
            stack.append("]" if character == "[" else "}")
            index += 1
            continue
        if character in "]}":
            if not stack or character != stack[-1] or start is None:
                return tuple(spans), True
            stack.pop()
            index += 1
            if not stack:
                spans.append((start, index))
                start = None
                if len(spans) > _JSON_MAX_FRAGMENTS:
                    return tuple(spans[:_JSON_MAX_FRAGMENTS]), True
            continue
        index += 1
    if stack or quoted:
        return tuple(spans), True
    return tuple(spans), False


def _redact_structural_json(value: str) -> str:
    if len(value.encode("utf-8")) > _JSON_MAX_FRAGMENT_BYTES and (
        "{" in value or "[" in value
    ):
        return _REDACTED
    full = _parse_and_redact_json(value)
    if full is not None:
        return value if full == "" else full
    spans, exhausted = _json_fragment_spans_bounded(value)
    if exhausted:
        return _REDACTED
    replacements: dict[tuple[int, int], str] = {}
    recognized = False
    for start, end in spans:
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
    while index < len(value):
        if value.startswith(_REDACTED, index):
            index += len(_REDACTED)
            continue
        if value[index] in "[{":
            spans, malformed = _json_fragment_spans_bounded(value[index:])
            if spans and not malformed and spans[0][0] == 0:
                return index + spans[0][1], "", ""
        if value[index] in "\r\n,;}]":
            break
        index += 1
    return index, "", ""


def _assignment_key_char(character: str) -> bool:
    normalized = unicodedata.normalize("NFKC", character)
    return normalized.isalnum() or normalized in _ASSIGNMENT_KEY_SEPARATORS or normalized.isspace()


def _scan_assignment_prefix(
    value: str,
    delimiter: int,
    cursor: int,
    work: int,
) -> tuple[int, int, str, int] | None:
    position = delimiter - 1
    scanned = 0
    while position >= 0 and value[position].isspace():
        position -= 1
        scanned += 1
    if position < 0:
        return None
    scan_end = position + 1
    while position >= 0:
        scanned += 1
        if scanned > _MAX_ASSIGNMENT_KEY_CHARS:
            raise OverflowError("assignment key scan exceeded its bound")
        character = value[position]
        if character == "=" or character in "\r\n,;{}[]":
            break
        if not _assignment_key_char(character):
            break
        position -= 1
    start = position + 1
    while start < scan_end and value[start].isspace():
        start += 1
    candidate = value[start:scan_end].strip()
    if not candidate or not any(character.isalnum() for character in candidate):
        return None
    components = _key_parts(candidate)
    if not components or len(components) > _MAX_ASSIGNMENT_KEY_COMPONENTS:
        raise OverflowError("assignment key components exceeded their bound")
    value_start = delimiter + 1
    while value_start < len(value) and value[value_start].isspace():
        value_start += 1
    if start < cursor:
        return None
    return start, value_start, candidate, work + scanned


def _redact_assignments(value: str) -> str:
    output: list[str] = []
    cursor = 0
    index = 0
    work = 0
    while index < len(value):
        if value[index] not in ":=":
            index += 1
            continue
        try:
            scanned = _scan_assignment_prefix(value, index, cursor, work)
        except OverflowError:
            return _REDACTED
        if scanned is None:
            index += 1
            continue
        start, value_start, candidate, work = scanned
        if work > _MAX_ASSIGNMENT_WORK:
            return _REDACTED
        if not _is_sensitive_key(candidate):
            index += 1
            continue
        end, quote_prefix, quote_suffix = _value_end(value, value_start)
        output.append(value[cursor:start])
        prefix = value[start:value_start]
        if quote_prefix:
            output.append(f"{prefix}{quote_prefix}{_REDACTED}{quote_suffix}")
        else:
            output.append(f"{prefix}{_REDACTED}")
        cursor = end
        index = max(end, index + 1)
    output.append(value[cursor:])
    return "".join(output)


def _redact_analysis_text(value: str) -> str:
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


def redact_artifact_text(value: str) -> str:
    """Redact sensitive artifact text with deterministic, idempotent rules."""

    if type(value) is not str:
        raise TypeError("artifact redaction requires an exact string")
    analysis, malformed = _normalize_encoded_analysis(value)
    if malformed:
        return _REDACTED
    analysis = unicodedata.normalize("NFKC", analysis)
    redacted = _redact_analysis_text(analysis)
    return value if redacted == analysis else redacted


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
        if _is_sensitive_parts(path_parts):
            return _REDACTED
        item_type = type(item)
        if item_type is str:
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
