---
name: spine-run
description: Run the canonical agent-spine implementation, review, fix, and archive workflow natively in Claude Code, Codex, or Kimi Code. Use for long-running coding goals or existing OpenSpec changes.
---

# Agent Spine Run — Host adapter

This skill is a host adapter, not a second workflow definition.

1. Read `../../commands/spine-run.md` completely before taking workflow actions.
2. Follow every phase, branch, gate, retry rule, RESULT schema, and stop condition in that file.
3. Apply only the host mappings below. If this file and the canonical workflow differ, the canonical workflow wins.
4. This file may contain host-adapter mapping tables for more than one host (each headed `### <Host> host adapter mapping`). Identify your own host identity from your own runtime context (you already know whether you are Claude Code, Codex, or Kimi Code — this file does not tell you). Apply only the mapping table headed with your host's name. MUST NOT read, follow, or otherwise apply any mapping table headed with a different host's name, even when both tables are present in the same file.

## Host mappings

### Codex host adapter mapping

- Run the canonical `npc init` command with `--runtime-host codex`, preserving its existing `--auto` and other arguments.
- Map Claude `TodoWrite` usage to Codex plan updates.
- Map a Claude `Agent` spawn to an isolated Codex sub-agent. Pass the canonical `.spawn_prompt` unchanged and require the sub-agent to read `.prompt_file` before acting. The sub-agent is the coder; the main session remains the orchestrator.
- Map `AskUserQuestion` to Codex's user-input mechanism. In `--auto` mode, keep the canonical prohibition on asking the user.
- When `npc implement run` or `npc fix run` returns `backend=codex`, invoke every subsequent `npc review run` for that artifact with `--engine claude`. Never fall back to Codex review if Claude is missing or fails; report the existing structured dependency/review failure.

### Kimi host adapter mapping

- Run the canonical `npc init` command with `--runtime-host kimi`, preserving its existing `--auto` and other arguments.
- Map Claude `TodoWrite` usage to Kimi's own todo tool.
- Call the `Agent` tool without explicitly passing `subagent_type` (or explicitly pass `subagent_type="coder"`, Kimi's built-in default profile) — a custom profile named for this agent-spine coder is not assumed to exist. Pass the canonical `.spawn_prompt` unchanged and require the sub-agent to read `.prompt_file` before acting. The sub-agent is the coder; the main session remains the orchestrator.
- Map `AskUserQuestion` to Kimi's user-input mechanism. In `--auto` mode, keep the canonical prohibition on asking the user.
- When `npc implement run` or `npc fix run` returns `backend=kimi`, invoke every subsequent `npc review run` for that artifact with `--engine claude`. Never fall back to Kimi review if Claude is missing or fails; report the existing structured dependency/review failure.

Keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as defined by the canonical workflow.

Do not rewrite phase logic, directly edit npc state, or perform reviewer work in the coding sub-agent.
