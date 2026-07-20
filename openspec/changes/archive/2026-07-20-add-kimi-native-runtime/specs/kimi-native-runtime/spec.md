## ADDED Requirements

### Requirement: Kimi-native plugin entrypoints
The plugin SHALL be natively discoverable by Kimi Code and SHALL expose run, spec, and analyze skills whose only host-specific content is a bounded host-primitive mapping section. For each of run, spec, and analyze, the skill's workflow-fidelity directives — read the canonical command file completely, follow every phase, branch, gate, retry rule, RESULT schema, and stop condition it defines, defer to the canonical workflow on any conflict, and keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as that file defines them — SHALL be worded identically, apart from the host name, to the existing Claude and Codex entrypoints for that same canonical workflow. This makes "executes the same canonical workflow" a machine-checkable textual invariant (Scenario below) rather than a claim only demonstrated by the presence of a file reference.

#### Scenario: Kimi discovers all workflows
- **WHEN** a user installs the agent-spine plugin in Kimi Code
- **THEN** Kimi discovers native skills for run, spec, and analyze
- **AND** each skill identifies the corresponding canonical workflow as its source of behavior

#### Scenario: Claude and Codex entrypoints remain unchanged
- **WHEN** the same plugin is loaded by Claude Code or Codex
- **THEN** the existing run, spec, analyze commands, agent definitions, and Codex host-adapter mappings remain available with their existing semantics

#### Scenario: Host mapping selection is unambiguous when multiple host-adapter tables share one skill file
- **WHEN** a skill file contains host-adapter mapping tables for more than one host
- **THEN** the file states an explicit, host-identity-based selection rule instructing each host to apply only its own mapping table and never another host's mapping table
- **AND** each host's mapping table is delimited by a heading that literally identifies that host, so the boundary between tables is machine-checkable rather than only described in prose

#### Scenario: Workflow-fidelity directives are identical across host adapters, for each of run, spec, and analyze
- **WHEN** the Kimi host-adapter section of a SKILL.md file (`spine-run`, `spine-spec`, or `spine-analyze`), excluding its own host-mapping table, is compared against the existing Codex host-adapter section of the same file, excluding its own host-mapping table
- **THEN** the numbered workflow-fidelity directives (read the canonical command file completely; follow every phase, branch, gate, retry rule, RESULT schema, and stop condition it defines; defer to the canonical workflow on conflict) and the closing instruction to keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as the canonical workflow defines them are worded identically apart from the host name
- **AND** only each host's mapping table differs, containing solely host-primitive substitutions (init command host flag, sub-agent spawn/backend mapping, `TodoWrite`/`AskUserQuestion` equivalents, and forced review-engine enforcement) — never a restatement, addition, or alteration of phase order, gates, retry rules, or stop conditions

### Requirement: Kimi runtime host identity is persistent and backward compatible
The system SHALL persist an explicitly selected `kimi` runtime host for a run and MUST interpret omitted or legacy runtime-host metadata as Claude, without changing the existing Codex runtime host resolution.

#### Scenario: Kimi initializes a run
- **WHEN** Kimi initializes a run with runtime host `kimi`
- **THEN** the run metadata and initialization result identify the runtime host as `kimi`

#### Scenario: Existing initialization remains Claude or Codex
- **WHEN** initialization omits a runtime host or an existing run lacks that field
- **THEN** the effective runtime host is `claude`
- **AND** a run explicitly initialized with runtime host `codex` continues to resolve to `codex`, unaffected by the addition of the `kimi` value

### Requirement: Kimi native generation uses in-session agents
The system SHALL use Kimi as the unconfigured default coder and spec writer inside a Kimi runtime, and SHALL dispatch the default Kimi coder in-session without invoking a headless Kimi coder process.

#### Scenario: Unconfigured Kimi code generation
- **WHEN** an implement or fix phase runs in a Kimi runtime without an explicit coder backend or dispatch
- **THEN** the selected backend is `kimi`
- **AND** the phase returns a deferred in-session agent request

#### Scenario: Explicit routing remains authoritative
- **WHEN** a coder backend or dispatch is explicitly supplied by CLI or project configuration in a Kimi runtime
- **THEN** the existing CLI and configuration precedence remains authoritative
- **AND** an explicitly configured headless Kimi coder reports the existing not-implemented error rather than silently falling back to another backend

#### Scenario: Unconfigured Kimi spec writer resolves to Kimi in-session
- **WHEN** a spec write or spec fix phase runs in a Kimi runtime without an explicit spec writer backend
- **THEN** the resolved spec writer generation identity is `kimi`
- **AND** the phase returns a deferred in-session agent request

#### Scenario: Unsatisfiable explicit spec writer is rejected
- **WHEN** a Kimi runtime has an explicit spec writer backend configured to a non-Kimi value
- **THEN** spec pipeline entrypoints report a spec routing violation identifying the host mismatch
- **AND** the configured value is not silently ignored or rewritten

#### Scenario: Claude and Codex defaults are unchanged
- **WHEN** an implement or fix phase runs in a Claude or Codex runtime without explicit routing
- **THEN** backend and dispatch resolve exactly as they did before Kimi runtime support

### Requirement: Kimi generation is reviewed by Claude
The system MUST route LLM review of Kimi-generated code and specifications to Claude. Review-engine validation MUST apply in this fixed order, independent of which backend generated the artifact under review: (1) first, reject any requested review-engine value that is outside the supported engine set (`claude`, `codex`) as an unknown review engine — this includes `kimi`, which is never a valid `review.engine` value and is therefore always rejected at this step rather than at step (2), regardless of whether the actual generator was Kimi; (2) only for a requested engine that passes step (1) (in practice this can only be `codex`, since a requested `claude` engine is never a violation) — if the actual generator of the artifact under review was Kimi, MUST reject the request as a routing violation rather than executing the requested engine (never a silent pass-through to the requested engine, and never a silent re-route to Claude in place of it). Because step (1) always intercepts `kimi` before step (2) is ever evaluated, a single input can never receive both classifications.

#### Scenario: Explicit kimi review engine is rejected as unsupported, independent of the Kimi-generator routing check
- **WHEN** a review is explicitly requested with review engine `kimi`, for code or for a specification, regardless of which backend generated the artifact under review
- **THEN** the review does not execute
- **AND** the result reports an unknown review engine error, and this classification is never superseded by, or in tension with, the separate Kimi-generator routing-violation check in the scenarios below

#### Scenario: Default code review after Kimi coding
- **WHEN** the latest implementation or fix artifact was generated by Kimi and no review engine override is supplied
- **THEN** the review engine is Claude

#### Scenario: Explicit supported non-Claude code review is rejected for Kimi-generated artifacts
- **WHEN** the latest implementation or fix artifact was generated by Kimi and code review is explicitly requested with the supported non-Claude engine `codex`
- **THEN** the review does not execute
- **AND** the result reports a routing violation rather than executing the requested engine

#### Scenario: Default spec review after Kimi writing
- **WHEN** a specification was written in a Kimi runtime and no spec review engine override is supplied
- **THEN** the spec review engine is Claude

#### Scenario: Explicit supported non-Claude spec review is rejected for a Kimi-written specification
- **WHEN** a specification was written in a Kimi runtime and spec review is explicitly requested with the supported non-Claude engine `codex`
- **THEN** the spec review does not execute
- **AND** the result reports a spec routing violation rather than executing the requested engine

#### Scenario: Non-Kimi generation keeps existing review routing
- **WHEN** the actual generator backend is not Kimi (including Claude, Codex, or MiMo)
- **THEN** review engine resolution follows the existing CLI and configuration precedence unaffected by Kimi runtime support

#### Scenario: Claude reviewer unavailable does not fall back to self-review for Kimi-generated code
- **WHEN** the latest implementation or fix artifact was generated by Kimi, review resolves to the Claude engine by default, and the Claude CLI binary cannot be located
- **THEN** the review does not execute
- **AND** the result reports the existing structured dependency-missing error
- **AND** no Codex or Kimi review is executed as a substitute, and no result is reported as a passing review

#### Scenario: Claude reviewer execution failure does not fall back to self-review for Kimi-generated code
- **WHEN** the latest implementation or fix artifact was generated by Kimi, review resolves to the Claude engine by default, and the Claude review process exits with a failure
- **THEN** the result reports the existing structured Claude execution-failure error
- **AND** no Codex or Kimi review is executed as a substitute, and no result is reported as a passing review

#### Scenario: Claude reviewer unavailable or failing does not fall back to self-review for a Kimi-written specification
- **WHEN** a specification was written in a Kimi runtime, spec review resolves to the Claude engine by default, and the Claude CLI is either unavailable or the Claude spec review process fails
- **THEN** the spec review does not execute
- **AND** the result reports the existing structured dependency-missing error or Claude execution-failure error, matching which condition occurred
- **AND** no Codex or Kimi spec review is executed as a substitute, and no result is reported as a passing review

### Requirement: Actual generator identity is retained for Kimi routing
The system SHALL retain the actual backend selected for each new implement and fix phase, including `kimi`, and SHALL use that identity when enforcing generation-review orthogonality, sharing the same persistence mechanism already used for Codex.

#### Scenario: New Kimi coder phase records backend
- **WHEN** an implement or fix phase starts with `kimi` as the selected backend
- **THEN** that backend remains present in the completed phase record

#### Scenario: Legacy phase remains reviewable
- **WHEN** a historical phase has no recorded generator backend
- **THEN** review falls back to the existing configuration-based backend resolution, regardless of the current runtime host

### Requirement: Hook and session behavior is Kimi compatible
The plugin SHALL make Kimi session metadata available to the existing run initialization path using only the metadata Kimi's `SessionStart` event actually provides (session id and working directory, never a transcript path), MUST NOT reject a Kimi sub-agent solely because its stop payload omits Claude-specific message fields, and MUST degrade gracefully when a Kimi session-start payload omits transcript metadata.

Note (round-2 F3 fix): an earlier draft of this Requirement included a scenario claiming Kimi invokes the session-start hook "with transcript metadata," implying full-transcript resolution is a reachable Kimi path. `design.md` "Verified Platform Facts" #6 established this is structurally never true for Kimi 0.27.0 (`triggerSessionStart` only ever sends `{source}` plus the common `session_id`/`cwd` fields) — that scenario has been removed as unreachable rather than left as an unfulfillable promise. The scenario below is the only Kimi-relevant session-start indexing behavior this Requirement covers.

#### Scenario: Kimi session start without transcript metadata degrades to a partial index
- **WHEN** Kimi invokes the plugin session-start hook with session and working-directory metadata but without a transcript path
- **THEN** the hook still records the available session and working-directory metadata, with the transcript field recorded as empty rather than the record being dropped
- **AND** hook-based session detection treats that partial entry the same as an absent entry — no false match and no error — rather than reporting it as a resolved session

#### Scenario: Partial hook index with no other match reports the session as not found
- **WHEN** the modification-time heuristic finds no recent session and the hook cache holds only a partial entry (no transcript path) for the current working directory
- **THEN** session detection reports the session as not found
- **AND** no error is raised and run initialization continues without a resolved session

#### Scenario: Host identity is read from an explicit hook parameter
- **WHEN** a plugin-declared session-start hook invocation carries an explicit runtime-host CLI parameter, as Kimi's own plugin-manifest-declared hook does because that declaration is exclusive to Kimi and is never shared with another host's hook configuration
- **THEN** the hook records that explicit value as the session's runtime host
- **AND** the existing Codex payload-source string inference remains available as a fallback only when no explicit value is provided

#### Scenario: Kimi stop payload omits Claude message field
- **WHEN** a Kimi sub-agent stop payload does not contain the Claude-specific final-message field
- **THEN** the compatibility hook exits successfully
- **AND** the deterministic record command remains responsible for result validation

#### Scenario: Hook fail-open never substitutes for the deterministic record gate
- **WHEN** the compatibility hook exits successfully for a Kimi sub-agent stop payload because it cannot inspect a Claude-shaped final message, as in the scenario above
- **THEN** that successful hook exit MUST NOT be treated as, or reported as, evidence that the phase's RESULT is valid
- **AND** the phase is not marked complete, and no review is started, until the deterministic `npc implement record` or `npc fix record` command runs its full existing validation and reports success

#### Scenario: Missing or malformed Kimi RESULT is rejected by the deterministic record command
- **WHEN** the text produced by a Kimi-dispatched in-session coder phase and passed to `npc implement record` or `npc fix record` has no `RESULT:` line, or is missing a key required by the applicable RESULT schema
- **THEN** record reports the existing structured `result-line-missing` or `result-missing-keys` error
- **AND** the phase is marked failed rather than completed, and no review is started for that phase

#### Scenario: An unresolvable or off-branch commit reported by Kimi is rejected by the deterministic record command
- **WHEN** a Kimi-dispatched in-session coder phase reports a commit sha that does not exist in the repository's object database, or that exists but is not an ancestor of the run's current `HEAD`
- **THEN** record reports the existing structured `commit-not-found` or `commit-not-on-run-branch` error
- **AND** the phase is marked failed rather than completed, and no review is started for that phase

#### Scenario: Failing tests reported by Kimi are rejected by the deterministic record command
- **WHEN** a Kimi-dispatched in-session coder phase reports `tests=fail`, or reports `tests=pass` while the deterministic test rerun fails
- **THEN** record reports the existing structured failure outcome, or the existing `rerun-tests-failed` outcome, respectively
- **AND** the phase is marked failed rather than completed, and no review is started for that phase

#### Scenario: Out-of-scope changes or an unexpected commit from a Kimi-dispatched spec writer are rejected by the deterministic spec record command
- **WHEN** a Kimi-dispatched in-session spec writer phase leaves the working tree with changes outside `openspec/changes/<change-id>/`, or the repository `HEAD` has moved since the phase's baseline marker was recorded
- **THEN** `npc spec write record` or `npc spec fix record` reports the existing structured `out_of_scope_changes` or `unexpected_commit` error, respectively
- **AND** the phase is marked failed rather than completed, and no spec review is started for that phase

#### Scenario: Claude and Codex stop validation remain active
- **WHEN** a Claude spine coder stop payload contains the existing final-message field
- **THEN** the hook applies the existing RESULT and commit validation behavior
- **AND** the existing Codex stop-payload compatibility behavior is unaffected by the addition of Kimi support

### Requirement: Kimi permissions are scoped and explicit
The plugin SHALL document the external directories required by agent-spine for Kimi installations and MUST NOT automatically modify user-global Kimi configuration or credentials.

#### Scenario: User prepares Kimi permissions
- **WHEN** a user follows the Kimi installation instructions
- **THEN** the instructions identify the worktree and task-log directories that require scoped access
- **AND** no plugin installation step writes user-global credentials or permission configuration

#### Scenario: Kimi has no shell-level plugin installation command
- **WHEN** a user reads the Kimi installation instructions
- **THEN** the instructions describe enabling the plugin through Kimi's own plugin management mechanism
- **AND** the instructions do not claim a shell-level install command that Kimi 0.27.0 does not provide

### Requirement: Kimi version baseline is fixed and version drift blocks implementation
This capability's Requirements and Scenarios target exactly Kimi Code `0.27.0` as their verified compatibility baseline; every manifest-schema, hook-declaration-schema, default sub-agent profile name, and `SessionStart`/`SubagentStop` payload-shape claim they rely on MUST be re-verified against the actual locally installed Kimi binary before the corresponding implementation task proceeds. This change does not add multi-version support or a compatibility matrix: it commits to `0.27.0` as the sole supported baseline, and treats a version or behavior mismatch as a condition that blocks implementation of the affected behavior rather than a signal to silently adapt.

#### Scenario: Verification confirms the recorded baseline
- **WHEN** an implementer runs the version and `strings`-based verification commands recorded in `design.md`/`tasks.md` against the locally installed Kimi binary before implementing this capability
- **THEN** the verification confirms a reported version of `0.27.0`, together with manifest-path, hook-schema, and default sub-agent profile strings that match the values recorded in `design.md` "Verified Platform Facts"
- **AND** implementation proceeds unchanged on that confirmed baseline

#### Scenario: Version or behavior drift blocks implementation rather than silently adapting
- **WHEN** the locally installed Kimi binary reports a version other than `0.27.0`, or the `strings`-based verification of the manifest path, hook schema, or default sub-agent profile no longer matches the values recorded in `design.md` "Verified Platform Facts"
- **THEN** implementation of the affected Kimi-native behavior MUST stop, and the mismatch MUST be reported rather than the implementer proceeding on the stale assumption or silently adapting to the new binary's actual behavior
- **AND** resuming implementation requires either restoring a `0.27.0` binary or a separate follow-up change that re-verifies and updates the affected Requirements, Scenarios, and `design.md` facts for the new version
