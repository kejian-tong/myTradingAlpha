---
name: sharpen
description: Improve task framing while preserving the user's scope, repository policy, and approval gates.
---

# sharpen

## Prompt rewrite

When the user asks to sharpen a prompt, explicitly rewrite it using available raw-source material and expert methods. Identify the intended result, constraints, and choices that remain open. Keep choices that belong to the user open.

Use one authorized independent outside check only when it is already available, can confirm the result, and fits the user's request, repository policy, current JIT scope, and available evidence. If no independent check is authorized and available, state that evidence gap and use the permitted repository checks.

## Continue the original task

Sharpening improves task framing; it does not replace the work. When the user requested an outcome, continue the original authorized task after framing it, unless the user explicitly asked only for a prompt rewrite. Do not return only a rewritten prompt in place of authorized implementation or research work.

## Scope and authority

Do not weaken or loosen policy, JIT, scope, compatibility, authorization, or human gates. Sharpening adds no authority, waives no approval, and cannot change the work the user authorized. Do not invoke an external system or expand the scope to create a check. Proceed only under the original request and its existing gates.
