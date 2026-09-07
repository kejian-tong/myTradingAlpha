"""Conservative artifact-text redaction shared by production contracts."""

from __future__ import annotations

import re

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
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "aws_access_key_id",
        "aws_secret_access_key",
        "bearer",
        "bearer_token",
        "client_secret",
        "consumer_secret",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "source_locator",
        "terms",
        "token",
    }
)
_ASSIGNMENT_PREFIX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<prefix>(?P<key_quote>\\?[\"']?)"
    r"(?P<key>[A-Za-z][A-Za-z0-9_.-]*)"
    r"(?P=key_quote)\s*[:=])(?P<spacing>\s*)",
    re.IGNORECASE,
)


def _normalize_key(value: str) -> str:
    value = value.replace("\\\"", "").replace("\\'", "")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[-.]", "_", value).casefold()


def _is_sensitive_key(value: str) -> bool:
    return _normalize_key(value) in _SENSITIVE_KEYS


def _value_end(value: str, start: int) -> tuple[int, str]:
    if value.startswith(_REDACTED, start):
        return start + len(_REDACTED), ""
    escaped_quote = value[start : start + 2] if value[start : start + 2] in {'\\"', "\\'"} else ""
    if escaped_quote:
        quote = escaped_quote[1]
        index = start + 2
        while index < len(value):
            if value[index : index + 2] == f"\\{quote}":
                return index + 2, escaped_quote
            if value[index] == "\\":
                index += 2
                continue
            if value[index] == quote:
                return index + 1, escaped_quote
            index += 1
        return len(value), escaped_quote
    if value[start : start + 1] in {'"', "'"}:
        quote = value[start]
        index = start + 1
        while index < len(value):
            if value[index] == "\\":
                index += 2
                continue
            if value[index] == quote:
                return index + 1, quote
            index += 1
        return len(value), quote
    index = start
    while index < len(value) and value[index] not in "\r\n,;}]":
        index += 1
    return index, ""


def _redact_assignments(value: str) -> str:
    output: list[str] = []
    cursor = 0
    for match in _ASSIGNMENT_PREFIX_PATTERN.finditer(value):
        output.append(value[cursor : match.start()])
        if not _is_sensitive_key(match.group("key")):
            output.append(match.group(0))
            cursor = match.end()
            continue
        end, quote = _value_end(value, match.end())
        if quote:
            replacement = (
                f"{match.group('prefix')}{match.group('spacing')}"
                f"{quote}{_REDACTED}{quote}"
            )
        else:
            replacement = f"{match.group('prefix')}{match.group('spacing')}{_REDACTED}"
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


__all__ = ["redact_artifact_text", "validate_artifact_text"]
