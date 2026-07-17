"""Codex-native plugin surface and shared hook compatibility."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from npc import session as _session


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "agent-spine"


def test_codex_manifest_and_native_skills_exist():
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "agent-spine"
    assert manifest["skills"] == "./skills/"
    for name in ("spine-run", "spine-spec", "spine-analyze"):
        skill = PLUGIN_ROOT / "skills" / name / "SKILL.md"
        assert skill.is_file()
        text = skill.read_text(encoding="utf-8")
        assert f"../../commands/{name}.md" in text
    marketplace = json.loads(
        (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    assert marketplace["name"] == "agent-spine"
    assert marketplace["plugins"][0]["source"]["path"] == "./plugins/agent-spine"


def test_codex_coding_skills_require_claude_review():
    run_skill = (PLUGIN_ROOT / "skills" / "spine-run" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    spec_skill = (PLUGIN_ROOT / "skills" / "spine-spec" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "--runtime-host codex" in run_skill
    assert "--engine claude" in run_skill
    assert "--runtime-host codex" in spec_skill
    assert "--engine claude" in spec_skill


def test_session_start_hook_indexes_codex_common_payload(tmp_path: Path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    transcript = tmp_path / "codex-session.jsonl"
    home.mkdir()
    repo.mkdir()
    transcript.write_text("{}\n", encoding="utf-8")
    payload = {
        "session_id": "codex-session",
        "transcript_path": str(transcript),
        "cwd": str(repo),
        "runtime_host": "codex",
    }
    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.run(
        ["bash", str(PLUGIN_ROOT / "hooks" / "index-session.sh")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0
    proj_key = str(repo.resolve()).replace("/", "-")
    index = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    record = json.loads(index.read_text(encoding="utf-8").splitlines()[-1])
    assert record["session_id"] == "codex-session"
    assert record["transcript_path"] == str(transcript)
    assert _session.detect_via_hook(proj_key, home) == (
        "codex-session",
        str(transcript),
    )
