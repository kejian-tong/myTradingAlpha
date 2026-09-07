"""Block a narrow set of directly invoked destructive Bash commands before execution.

This is a supplemental Codex PreToolUse guard, not a shell sandbox or complete command
policy. It recognizes direct top-level command segments and deliberately avoids parsing
nested shells or arbitrary echoed text as executable commands.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

_DENY_EVENT = "PreToolUse"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEPARATORS = {";", "&&", "||", "|", "&"}
_DANGEROUS_RM_TARGETS = {"/", "/*", ".", "..", "~", "~/", "$HOME", "${HOME}"}


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token in _SEPARATORS or token and set(token) <= {";", "&", "|"}:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _unwrap_prefix(tokens: list[str]) -> list[str]:
    result = list(tokens)
    while result and _ASSIGNMENT.match(result[0]):
        result.pop(0)
    if result and Path(result[0]).name == "sudo":
        result.pop(0)
        while result and result[0].startswith("-"):
            option = result.pop(0)
            if option in {"-u", "-g", "-h", "-p", "-C", "-T"} and result:
                result.pop(0)
    if result and Path(result[0]).name == "env":
        result.pop(0)
        while result and (result[0].startswith("-") or _ASSIGNMENT.match(result[0])):
            result.pop(0)
    return result


def _git_subcommand(args: list[str]) -> tuple[str | None, list[str]]:
    index = 0
    options_with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
    while index < len(args):
        token = args[index]
        if token in options_with_value:
            index += 2
            continue
        if any(token.startswith(prefix) for prefix in ("--git-dir=", "--work-tree=", "--namespace=")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token, args[index + 1 :]
    return None, []


def _git_reason(tokens: list[str]) -> str | None:
    subcommand, args = _git_subcommand(tokens[1:])
    if subcommand == "push" and any(
        arg in {"-f", "--force"} or arg.startswith("--force-with-lease") for arg in args
    ):
        return "force-push is prohibited by the project PreToolUse guard"
    if subcommand == "reset" and "--hard" in args:
        return "git reset --hard is prohibited by the project PreToolUse guard"
    if subcommand == "clean" and any(
        arg == "--force" or (arg.startswith("-") and not arg.startswith("--") and "f" in arg[1:])
        for arg in args
    ):
        return "forced git clean is prohibited by the project PreToolUse guard"
    if subcommand == "branch" and "-D" in args:
        return "forced branch deletion is prohibited by the project PreToolUse guard"
    return None


def _rm_reason(tokens: list[str]) -> str | None:
    recursive = False
    forced = False
    targets: list[str] = []
    for token in tokens[1:]:
        if token == "--":
            continue
        if token.startswith("--"):
            recursive = recursive or token == "--recursive"
            forced = forced or token == "--force"
            continue
        if token.startswith("-") and token != "-":
            flags = token[1:]
            recursive = recursive or "r" in flags or "R" in flags
            forced = forced or "f" in flags
            continue
        targets.append(token)
    if recursive and forced and any(target in _DANGEROUS_RM_TARGETS for target in targets):
        return "recursive forced removal of a root/home/current-directory target is prohibited"
    return None


def destructive_command_reason(command: str) -> str | None:
    try:
        segments = _segments(command)
    except ValueError:
        return "malformed Bash command cannot be safely classified by the project PreToolUse guard"
    for raw in segments:
        tokens = _unwrap_prefix(raw)
        if not tokens:
            continue
        executable = Path(tokens[0]).name
        if executable == "git":
            reason = _git_reason(tokens)
        elif executable == "rm":
            reason = _rm_reason(tokens)
        else:
            reason = None
        if reason is not None:
            return reason
    return None


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": _DENY_EVENT,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(_deny("malformed PreToolUse hook input"), separators=(",", ":")))
        return 0
    if type(event) is not dict:
        print(json.dumps(_deny("malformed PreToolUse hook input"), separators=(",", ":")))
        return 0
    if event.get("hook_event_name") != _DENY_EVENT or event.get("tool_name") != "Bash":
        return 0
    tool_input = event.get("tool_input")
    if type(tool_input) is not dict or type(tool_input.get("command")) is not str:
        print(json.dumps(_deny("Bash PreToolUse input is missing a string command"), separators=(",", ":")))
        return 0
    reason = destructive_command_reason(tool_input["command"])
    if reason is not None:
        print(json.dumps(_deny(reason), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
