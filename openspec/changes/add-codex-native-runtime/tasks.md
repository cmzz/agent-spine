## 1. Runtime host contract

- [x] 1.1 Add failing tests for Codex runtime persistence, init payload, legacy fallback, environment fallback, and state-path override preservation
- [x] 1.2 Add the validated `--runtime-host` init option and persist `runtime_host` in run metadata with Claude as the backward-compatible default
- [x] 1.3 Run the paths/init test suites and confirm existing Claude initialization behavior remains green

## 2. Native generation and review routing

- [x] 2.1 Add failing coder tests for Codex-runtime default backend/in-session dispatch and unchanged Claude/configured routing
- [x] 2.2 Implement runtime-aware unconfigured coder defaults while retaining the existing Codex headless error path
- [x] 2.3 Add failing state/routing tests proving implement/fix records retain actual generator backend and Codex code review selects Claude
- [x] 2.4 Persist generator backend across phase enter/exit and enforce review routing against the actual generator identity
- [x] 2.5 Add failing spec tests proving Codex-runtime writer identity selects Claude review and explicit Codex self-review is rejected
- [x] 2.6 Implement runtime-aware spec writer identity and Claude review selection without changing non-Codex routing

## 3. Codex plugin surface

- [x] 3.1 Add a valid Codex plugin manifest beside the existing Claude manifest
- [x] 3.2 Add run, spec, and analyze skills that read the canonical command workflows and map only host primitives
- [x] 3.3 Add packaging/structure tests proving both plugin surfaces exist and the Codex skills reference their canonical workflows
- [x] 3.4 Validate the plugin with the official Codex plugin validator

## 4. Hook and session compatibility

- [x] 4.1 Add failing tests for Codex SessionStart indexing and SubagentStop payloads without Claude-specific message fields
- [x] 4.2 Add the fail-open compatibility branch and provider-neutral session index hook while preserving Claude RESULT validation
- [x] 4.3 Run hook and session tests for both Codex and Claude payload shapes

## 5. Documentation and regression

- [x] 5.1 Document Codex installation, scoped external-directory permissions, workflow invocation, and Codex-to-Claude review behavior
- [x] 5.2 Run strict OpenSpec validation and complete all checklist items
- [x] 5.3 Run targeted tests followed by the full test suite
- [x] 5.4 Confirm the feature worktree contains only intended changes and the original checkout remains untouched
