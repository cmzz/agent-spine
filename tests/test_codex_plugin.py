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


def test_session_start_hook_indexes_symlinked_cwd_under_both_keys(tmp_path: Path):
    """symlink cwd 下 raw / resolved 两个 proj_key 都要能命中缓存。

    npc 的 ``proj_key_for(repo_root)`` 不解析 symlink，而宿主传来的 cwd 可能是
    链接路径——hook 必须双键落盘，detect_via_hook 用任一 key 都能解析。
    """
    home = tmp_path / "home"
    real = tmp_path / "real-repo"
    link = tmp_path / "link-repo"
    transcript = tmp_path / "codex-session.jsonl"
    home.mkdir()
    real.mkdir()
    link.symlink_to(real)
    transcript.write_text("{}\n", encoding="utf-8")
    payload = {
        "session_id": "codex-session",
        "transcript_path": str(transcript),
        "cwd": str(link),
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
    raw_key = str(link).replace("/", "-")
    resolved_key = str(link.resolve()).replace("/", "-")
    assert raw_key != resolved_key
    for key in (raw_key, resolved_key):
        assert _session.detect_via_hook(key, home) == (
            "codex-session",
            str(transcript),
        )
