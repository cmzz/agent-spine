#!/usr/bin/env bash
# Provider-neutral SessionStart index for npc.session.detect_via_hook.
# Best-effort only: a malformed payload or unwritable cache must never block startup.

set -u

INPUT="$(cat)"
python3 -c '
import json
import pathlib
import sys

try:
    data = json.loads(sys.stdin.read())
    cwd = data.get("cwd")
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")
    if not all(isinstance(v, str) and v for v in (cwd, session_id, transcript_path)):
        raise ValueError("missing common session fields")
    resolved_cwd = str(pathlib.Path(cwd).resolve())
    proj_key = resolved_cwd.replace("/", "-") or "-"
    target = pathlib.Path.home() / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": resolved_cwd,
        "runtime_host": "codex" if "codex" in str(data.get("source", "")).lower() else data.get("runtime_host"),
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
except Exception:
    pass
' <<<"$INPUT" 2>/dev/null || true

exit 0
