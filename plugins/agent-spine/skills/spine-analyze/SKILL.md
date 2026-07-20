---
name: spine-analyze
description: Analyze agent-spine telemetry and propose bounded harness improvements by following the canonical read-only analysis workflow in Claude Code, Codex, or Kimi Code.
---

# Agent Spine Analyze — Host adapter

This skill is a host adapter, not a second workflow definition.

1. Read `../../commands/spine-analyze.md` completely before taking workflow actions.
2. Follow every phase, branch, gate, retry rule, RESULT schema, and stop condition in that file.
3. Apply only the host mappings below. If this file and the canonical workflow differ, the canonical workflow wins.
4. This file may contain host-adapter mapping tables for more than one host (each headed `### <Host> host adapter mapping`). Identify your own host identity from your own runtime context (you already know whether you are Claude Code, Codex, or Kimi Code — this file does not tell you). Apply only the mapping table headed with your host's name. MUST NOT read, follow, or otherwise apply any mapping table headed with a different host's name, even when both tables are present in the same file.

## Host mappings

### Codex host adapter mapping

- Map Claude planning primitives to Codex plan updates and Claude interactive questions to Codex user input.
- Do not edit code, configuration, state, or telemetry as part of analysis.

### Kimi host adapter mapping

- Map Claude planning primitives to Kimi's own todo tool and Claude interactive questions to Kimi's user-input mechanism.
- Do not edit code, configuration, state, or telemetry as part of analysis.

Keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as defined by the canonical workflow.

There are no host-specific lifecycle or scoring rules beyond the mappings above.
