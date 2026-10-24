---
name: ketchup
description: Catch the user up on verified changes since their last message using existing conversation and repository evidence.
---

# ketchup

Use this skill when the user asks for a concise catch-up. Keep the work read-only and use only existing conversation messages and existing artifacts already available in the conversation or repository.

Use the last human message as the boundary for new activity. Assistant replies, notifications, and subagent results do not move that boundary. Separate verified facts from pending work and unknowns. Give each change enough context to explain its effect, and include only action items that require a decision or action from the user.

## User-owned decisions, actions, and calls

For every affected item that needs a user decision or action, provide a self-contained record with an available link when one exists, a recommendation, supporting evidence, risks, prerequisites, and unknowns. Include only actions that belong to the user; agent-owned work is not a user action item.

Include older already-evidenced unresolved calls even when they predate the last human message cutoff. Carry them forward only as existing context supported by available artifacts; their age does not make them a new request.

This is a read-only skill. Do not start an app or job, capture or post anything, or retrieve any transcript. Do not invent screenshots, visuals, statuses, or other evidence. Include a visual only when it already exists in the available artifacts and makes the change clearer. Do not rely on skills or tools that are absent from this repository.
