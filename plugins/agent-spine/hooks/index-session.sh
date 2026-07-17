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
    # npc proj_key_for() mangles the path as given (no symlink resolution), so a
    # symlinked cwd must be indexed under both keys for detect_via_hook to hit.
    keys = {resolved_cwd.replace("/", "-") or "-"}
    if cwd.startswith("/"):
        keys.add(cwd.rstrip("/").replace("/", "-") or "-")
    cache_dir = pathlib.Path.home() / "task_log" / ".session-cache" / "by-cwd"
    cache_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": resolved_cwd,
        "runtime_host": "codex" if "codex" in str(data.get("source", "")).lower() else data.get("runtime_host"),
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    for proj_key in keys:
        with (cache_dir / f"{proj_key}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line)
except Exception:
    pass
' <<<"$INPUT" 2>/dev/null || true

exit 0
