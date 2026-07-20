"""Kimi-native plugin surface and shared hook compatibility (add-kimi-native-runtime).

对称于 tests/test_codex_plugin.py；额外覆盖 round-2/round-3 fix 引入的
F1（宿主选择边界）与 F2（工作流忠实性指令逐字一致）边界测试。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from npc import session as _session


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "agent-spine"

_SKILL_NAMES = ("spine-run", "spine-spec", "spine-analyze")

_SELECTION_RULE_SUBSTRING = (
    "MUST NOT read, follow, or otherwise apply any mapping table headed with "
    "a different host's name"
)


def _skill_text(name: str) -> str:
    return (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _host_section_bounds(text: str, host: str) -> tuple[int, int]:
    """定位 `### {host} host adapter mapping` 标题 + 紧随其后的 bullet 列表的
    字节区间（到第一个非 bullet/非空白行为止，即遇到下一个标题或收尾段落）。"""
    marker = f"### {host} host adapter mapping"
    start = text.index(marker)
    after = text[start + len(marker):]
    lines = after.splitlines(keepends=True)
    idx = 0
    offset = 0
    while idx < len(lines) and lines[idx].strip() == "":
        offset += len(lines[idx])
        idx += 1
    while idx < len(lines) and lines[idx].lstrip().startswith("-"):
        offset += len(lines[idx])
        idx += 1
    end = start + len(marker) + offset
    return start, end


def _extract_host_section(text: str, host: str) -> str:
    """切出 `### {host} host adapter mapping` 标题 + 其 bullet 列表的字符串区间。"""
    start, end = _host_section_bounds(text, host)
    return text[start:end]


def _common_text_excluding_host_sections(text: str) -> str:
    """挖空 Codex 与 Kimi 两个 host-mapping 区间，得到公共（宿主无关）文本。"""
    codex_bounds = _host_section_bounds(text, "Codex")
    kimi_bounds = _host_section_bounds(text, "Kimi")
    result = text
    for start, end in sorted([codex_bounds, kimi_bounds], reverse=True):
        result = result[:start] + result[end:]
    return result


# ============================================================
# 3.1/3.2 — manifest + hooks 数组字段
# ============================================================


def test_kimi_manifest_and_native_skills_exist():
    manifest = json.loads(
        (PLUGIN_ROOT / ".kimi-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "agent-spine"
    assert manifest["skills"] == "./skills/"
    for name in _SKILL_NAMES:
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


def test_kimi_manifest_hooks_array_declares_session_start_and_subagent_stop():
    manifest = json.loads(
        (PLUGIN_ROOT / ".kimi-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    hooks = manifest["hooks"]
    assert isinstance(hooks, list)
    by_event = {h["event"]: h for h in hooks}
    assert "SessionStart" in by_event
    assert "SubagentStop" in by_event
    assert "--runtime-host kimi" in by_event["SessionStart"]["command"]
    # round-2 F2 修复：matcher 必须是 "coder"，不是 "spine-coder"（Kimi 无此 profile）。
    assert by_event["SubagentStop"]["matcher"] == "coder"
    assert "index-session.sh" in by_event["SessionStart"]["command"]
    assert "verify-subagent-result.sh" in by_event["SubagentStop"]["command"]


def test_kimi_manifest_hooks_matcher_is_not_spine_coder():
    manifest = json.loads(
        (PLUGIN_ROOT / ".kimi-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    by_event = {h["event"]: h for h in manifest["hooks"]}
    assert by_event["SubagentStop"]["matcher"] != "spine-coder"


# ============================================================
# 3.3 — SKILL.md 断言项（对称于 test_codex_coding_skills_require_claude_review）
# ============================================================


def test_kimi_coding_skills_require_claude_review():
    run_skill = _skill_text("spine-run")
    spec_skill = _skill_text("spine-spec")
    assert "--runtime-host kimi" in run_skill
    assert "--engine claude" in run_skill
    assert "--runtime-host kimi" in spec_skill
    assert "--engine claude" in spec_skill


def test_all_skills_state_host_selection_rule():
    for name in _SKILL_NAMES:
        text = _skill_text(name)
        assert _SELECTION_RULE_SUBSTRING in text


# ============================================================
# round-2 F1 边界测试：Codex/Kimi 区间互不交叉引用
# ============================================================


def test_host_mapping_sections_do_not_cross_reference():
    for name in _SKILL_NAMES:
        text = _skill_text(name)
        codex_section = _extract_host_section(text, "Codex")
        kimi_section = _extract_host_section(text, "Kimi")
        assert "--runtime-host kimi" not in codex_section
        assert "--runtime-host codex" not in kimi_section
        assert "subagent_type=spine-coder" not in kimi_section
        assert 'subagent_type="spine-coder"' not in kimi_section


# ============================================================
# round-3 F2 边界测试：工作流忠实性指令逐字一致，只有 host-mapping 表不同
# ============================================================


def test_workflow_fidelity_directives_identical_apart_from_host_mapping():
    for name in _SKILL_NAMES:
        text = _skill_text(name)
        common = _common_text_excluding_host_sections(text)
        assert f"Read `../../commands/{name}.md` completely" in common
        assert (
            "Follow every phase, branch, gate, retry rule, RESULT schema, "
            "and stop condition" in common
        )
        assert "Apply only the host mappings below" in common
        assert "If this file and the canonical workflow differ, the canonical workflow wins" in common
        assert (
            "Keep all `npc` state, record, telemetry, gate, archive, and "
            "finalization calls exactly as defined by the canonical workflow." in common
        )


# ============================================================
# 4.1 — Kimi SessionStart 索引（对称于 test_session_start_hook_indexes_codex_common_payload）
# ============================================================


def test_session_start_hook_indexes_kimi_payload_without_transcript_path(tmp_path: Path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    # Kimi's SessionStart payload structurally never carries transcript_path
    # (design.md Verified Platform Facts #6): triggerSessionStart(source) only
    # ever sends {source} plus the common session_id/cwd fields.
    payload = {
        "source": "kimi",
        "session_id": "kimi-session",
        "cwd": str(repo),
    }
    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.run(
        [
            "bash",
            str(PLUGIN_ROOT / "hooks" / "index-session.sh"),
            "--runtime-host",
            "kimi",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    proj_key = str(repo.resolve()).replace("/", "-")
    index = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    record = json.loads(index.read_text(encoding="utf-8").splitlines()[-1])
    assert record["session_id"] == "kimi-session"
    assert record["transcript_path"] == ""
    assert record["runtime_host"] == "kimi"
    # detect_via_hook must treat this partial index the same as an absent entry.
    assert _session.detect_via_hook(proj_key, home) is None


def test_session_start_hook_explicit_runtime_host_arg_takes_priority(tmp_path: Path):
    """显式 --runtime-host 优先级最高，覆盖 source 字符串猜测（design.md D5）。"""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    payload = {
        "source": "codex-would-normally-win",
        "session_id": "kimi-session-2",
        "cwd": str(repo),
    }
    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.run(
        [
            "bash",
            str(PLUGIN_ROOT / "hooks" / "index-session.sh"),
            "--runtime-host",
            "kimi",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    proj_key = str(repo.resolve()).replace("/", "-")
    index = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    record = json.loads(index.read_text(encoding="utf-8").splitlines()[-1])
    assert record["runtime_host"] == "kimi"


def test_session_start_hook_codex_source_guess_unaffected_by_new_arg_parsing(
    tmp_path: Path
):
    """未显式传 --runtime-host 时，既有 Codex source 字符串猜测行为不变（向后兼容）。"""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    transcript = tmp_path / "codex-session.jsonl"
    home.mkdir()
    repo.mkdir()
    transcript.write_text("{}\n", encoding="utf-8")
    payload = {
        "source": "codex-cli",
        "session_id": "codex-session-3",
        "transcript_path": str(transcript),
        "cwd": str(repo),
    }
    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.run(
        ["bash", str(PLUGIN_ROOT / "hooks" / "index-session.sh")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    proj_key = str(repo.resolve()).replace("/", "-")
    index = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    record = json.loads(index.read_text(encoding="utf-8").splitlines()[-1])
    assert record["runtime_host"] == "codex"
