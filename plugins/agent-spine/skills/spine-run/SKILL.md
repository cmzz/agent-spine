---
name: spine-run
description: Run the canonical agent-spine implementation, review, fix, and archive workflow natively in Codex. Use for long-running coding goals or existing OpenSpec changes.
---

# Agent Spine Run — Codex host adapter

This skill is a host adapter, not a second workflow definition.

1. Read `../../commands/spine-run.md` completely before taking workflow actions.
2. Follow every phase, branch, gate, retry rule, RESULT schema, and stop condition in that file.
3. Apply only the host mappings below. If this file and the canonical workflow differ on workflow behavior, the canonical workflow wins.

## Host mappings

- Run the canonical `npc init` command with `--runtime-host codex`, preserving its existing `--auto` and other arguments.
- Map Claude `TodoWrite` usage to Codex plan updates.
- Map a Claude `Agent` spawn to an isolated Codex sub-agent. Pass the canonical `.spawn_prompt` unchanged and require the sub-agent to read `.prompt_file` before acting. The sub-agent is the coder; the main session remains the orchestrator.
- Map `AskUserQuestion` to Codex's user-input mechanism. In `--auto` mode, keep the canonical prohibition on asking the user.
- When `npc implement run` or `npc fix run` returns `backend=codex`, invoke every subsequent `npc review run` for that artifact with `--engine claude`. Never fall back to Codex review if Claude is missing or fails; report the existing structured dependency/review failure.
- Keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as defined by the canonical workflow.

Do not rewrite phase logic, directly edit npc state, or perform reviewer work in the coding sub-agent.
