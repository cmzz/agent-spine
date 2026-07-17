---
name: spine-spec
description: Create and independently review an OpenSpec change through the canonical agent-spine spec workflow, using Codex to write and Claude to review.
---

# Agent Spine Spec — Codex host adapter

This skill carries the existing spec workflow into Codex without changing it.

1. Read `../../commands/spine-spec.md` completely before taking workflow actions.
2. Follow its interrogate, write, review, fix, round-limit, scope-guard, and stop rules exactly.
3. Apply only these host mappings:

- Run the canonical `npc init` command with `--runtime-host codex`.
- Map each `spine-spec-writer` Claude `Agent` spawn to an isolated Codex sub-agent. Pass `.spawn_prompt` unchanged and require it to read `.prompt_file` before writing artifacts.
- Map `AskUserQuestion` to Codex's user-input mechanism, retaining the canonical `--auto` prohibition.
- Invoke every `npc spec review run` with `--engine claude`. A Claude dependency or execution failure stops the review; Codex MUST NOT review its own spec as a fallback.
- Leave every deterministic `npc` command and every `.ok`/gate/blocking decision in the canonical order.

The main Codex session orchestrates only. It must not write the specification artifacts itself.
