---
name: spine-spec
description: Create and independently review an OpenSpec change through the canonical agent-spine spec workflow in Claude Code, Codex, or Kimi Code — using the host's coding agent to write and Claude to review.
---

# Agent Spine Spec — Host adapter

This skill is a host adapter, not a second workflow definition.

1. Read `../../commands/spine-spec.md` completely before taking workflow actions.
2. Follow every phase, branch, gate, retry rule, RESULT schema, and stop condition in that file.
3. Apply only the host mappings below. If this file and the canonical workflow differ, the canonical workflow wins.
4. This file may contain host-adapter mapping tables for more than one host (each headed `### <Host> host adapter mapping`). Identify your own host identity from your own runtime context (you already know whether you are Claude Code, Codex, or Kimi Code — this file does not tell you). Apply only the mapping table headed with your host's name. MUST NOT read, follow, or otherwise apply any mapping table headed with a different host's name, even when both tables are present in the same file.

## Host mappings

### Codex host adapter mapping

- Run the canonical `npc init` command with `--runtime-host codex`.
- Map each `spine-spec-writer` Claude `Agent` spawn to an isolated Codex sub-agent. Pass `.spawn_prompt` unchanged and require it to read `.prompt_file` before writing artifacts.
- Map `AskUserQuestion` to Codex's user-input mechanism, retaining the canonical `--auto` prohibition.
- `npc spec review run` has built-in backend-aware routing: with no explicit `[spec_review].engine` configured, specs written by a Codex sub-agent default to Claude review, so no explicit `--engine` is needed. An explicit engine choice is always honored (subject only to the generation⊥verification orthogonality and MiMo-exec-only invariants). A dependency or execution failure stops the review; Codex MUST NOT review its own spec as a fallback.

### Kimi host adapter mapping

- Run the canonical `npc init` command with `--runtime-host kimi`.
- Map each `spine-spec-writer` Claude `Agent` spawn to Kimi's `Agent` tool, called without explicitly passing `subagent_type` (or explicitly passing `subagent_type="coder"`, Kimi's built-in default profile) — a custom profile named for this agent-spine writer is not assumed to exist. Pass `.spawn_prompt` unchanged and require it to read `.prompt_file` before writing artifacts.
- Map `AskUserQuestion` to Kimi's user-input mechanism, retaining the canonical `--auto` prohibition.
- `npc spec review run` has built-in backend-aware routing: with no explicit `[spec_review].engine` configured, specs written by a Kimi sub-agent default to Codex review (only codex-written specs default to Claude review). An explicit engine choice (e.g. `--engine claude`) is always honored. A dependency or execution failure stops the review; Kimi MUST NOT review its own spec as a fallback.

Keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as defined by the canonical workflow.

The main session orchestrates only. It must not write the specification artifacts itself.
