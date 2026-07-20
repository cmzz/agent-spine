#!/usr/bin/env bash
# Provider-neutral SessionStart index for npc.session.detect_via_hook.
# Best-effort only: a malformed payload or unwritable cache must never block startup.
#
# Runtime-host identification priority (add-kimi-native-runtime D5):
#   1. Explicit CLI `--runtime-host <value>` (only Kimi's manifest-declared hook
#      passes this today; Claude/Codex hooks.json invocations never pass argv
#      and are unaffected).
#   2. Existing `source` string containing "codex" (Codex back-compat, unchanged).
#   3. `data.runtime_host` payload field passed straight through (legacy fallback).
#   4. None of the above → unset; downstream interprets missing as "claude".

set -u

RUNTIME_HOST_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --runtime-host)
            RUNTIME_HOST_ARG="${2:-}"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

INPUT="$(cat)"
NPC_HOOK_RUNTIME_HOST_ARG="$RUNTIME_HOST_ARG" python3 -c '
import json
import os
import pathlib
import sys

try:
    data = json.loads(sys.stdin.read())
    cwd = data.get("cwd")
    session_id = data.get("session_id")
    # Kimi'"'"'s SessionStart payload structurally never carries transcript_path
    # (design.md Verified Platform Facts #6); required fields are narrowed to
    # cwd/session_id so this partial-index case is not swallowed whole by the
    # except-Exception fallback below. Missing transcript_path is recorded as
    # an empty string rather than the record being dropped.
    if not all(isinstance(v, str) and v for v in (cwd, session_id)):
        raise ValueError("missing common session fields")
    transcript_path_raw = data.get("transcript_path")
    transcript_path = transcript_path_raw if isinstance(transcript_path_raw, str) else ""
    resolved_cwd = str(pathlib.Path(cwd).resolve())
    # npc proj_key_for() mangles the path as given (no symlink resolution), so a
    # symlinked cwd must be indexed under both keys for detect_via_hook to hit.
    keys = {resolved_cwd.replace("/", "-") or "-"}
    if cwd.startswith("/"):
        keys.add(cwd.rstrip("/").replace("/", "-") or "-")
    cache_dir = pathlib.Path.home() / "task_log" / ".session-cache" / "by-cwd"
    cache_dir.mkdir(parents=True, exist_ok=True)
    explicit_runtime_host = os.environ.get("NPC_HOOK_RUNTIME_HOST_ARG") or ""
    if explicit_runtime_host:
        runtime_host = explicit_runtime_host
    elif "codex" in str(data.get("source", "")).lower():
        runtime_host = "codex"
    else:
        runtime_host = data.get("runtime_host")
    record = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": resolved_cwd,
        "runtime_host": runtime_host,
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    for proj_key in keys:
        with (cache_dir / f"{proj_key}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line)
except Exception:
    pass
' <<<"$INPUT" 2>/dev/null || true

exit 0
