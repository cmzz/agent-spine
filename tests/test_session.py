"""session 模块测试。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from npc import session as _session


def test_detect_via_mtime_recent_jsonl(tmp_path: Path):
    home = tmp_path
    proj_key = "-repo"
    cc = home / ".claude" / "projects" / proj_key
    cc.mkdir(parents=True)
    f = cc / "018f-aaaa.jsonl"
    f.write_text("{}\n")
    # mtime 已是当前，落入 60s 窗口
    result = _session.detect_via_mtime(proj_key, home)
    assert result is not None
    sid, tx = result
    assert sid == "018f-aaaa"
    assert tx == str(f)


def test_detect_via_mtime_outside_window(tmp_path: Path):
    home = tmp_path
    proj_key = "-repo"
    cc = home / ".claude" / "projects" / proj_key
    cc.mkdir(parents=True)
    f = cc / "old.jsonl"
    f.write_text("{}\n")
    # 把 mtime 调到 5 分钟前
    old = time.time() - 300
    os.utime(f, (old, old))
    assert _session.detect_via_mtime(proj_key, home) is None


def test_detect_via_mtime_no_cc_dir(tmp_path: Path):
    assert _session.detect_via_mtime("-foo", tmp_path) is None


def test_detect_via_mtime_picks_latest(tmp_path: Path):
    home = tmp_path
    proj_key = "-repo"
    cc = home / ".claude" / "projects" / proj_key
    cc.mkdir(parents=True)
    f1 = cc / "old.jsonl"
    f2 = cc / "new.jsonl"
    f1.write_text("{}\n")
    f2.write_text("{}\n")
    older = time.time() - 30
    os.utime(f1, (older, older))
    # f2 用当前 mtime
    result = _session.detect_via_mtime(proj_key, home)
    assert result is not None
    assert result[0] == "new"


def test_detect_via_hook_reads_last_line(tmp_path: Path):
    home = tmp_path
    proj_key = "-repo"
    by_cwd = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    by_cwd.parent.mkdir(parents=True)
    tx_path = home / "tx.jsonl"
    tx_path.write_text("{}\n")
    lines = [
        {"session_id": "old-sid", "transcript_path": "/no/such/path"},
        {"session_id": "current-sid", "transcript_path": str(tx_path)},
    ]
    by_cwd.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    result = _session.detect_via_hook(proj_key, home)
    assert result is not None
    assert result[0] == "current-sid"


def test_detect_via_hook_rejects_stale_transcript(tmp_path: Path):
    home = tmp_path
    proj_key = "-repo"
    by_cwd = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    by_cwd.parent.mkdir(parents=True)
    tx_path = home / "old-tx.jsonl"
    tx_path.write_text("{}\n")
    # transcript 7 小时前
    old = time.time() - 7 * 3600
    os.utime(tx_path, (old, old))
    by_cwd.write_text(json.dumps({"session_id": "sid", "transcript_path": str(tx_path)}) + "\n")
    assert _session.detect_via_hook(proj_key, home) is None


def test_detect_session_fallback_unknown(tmp_path: Path):
    sid, tx, src = _session.detect_session("-no-such-project", home=tmp_path)
    assert sid == "-"
    assert tx == "-"
    assert src == "unknown"


def test_detect_session_prefers_mtime(tmp_path: Path):
    home = tmp_path
    proj_key = "-repo"
    cc = home / ".claude" / "projects" / proj_key
    cc.mkdir(parents=True)
    (cc / "mtime-sid.jsonl").write_text("{}\n")

    by_cwd = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    by_cwd.parent.mkdir(parents=True)
    tx = home / "tx.jsonl"
    tx.write_text("{}\n")
    by_cwd.write_text(
        json.dumps({"session_id": "hook-sid", "transcript_path": str(tx)}) + "\n"
    )

    sid, _, src = _session.detect_session(proj_key, home=home)
    assert sid == "mtime-sid"
    assert src == "mtime-1min"


# ============================================================
# add-kimi-native-runtime：Kimi SessionStart 部分索引降级（tasks.md 4.1）
# ============================================================


def test_detect_via_hook_rejects_empty_transcript_path(tmp_path: Path):
    """(a) Kimi 的 SessionStart 结构性永远不带 transcript_path；index-session.sh
    放宽字段校验后仍会写入一行缓存记录，但 transcript_path 字段为空字符串。
    detect_via_hook 对这种"部分索引"条目必须与完全无条目一视同仁，返回 None。"""
    home = tmp_path
    proj_key = "-repo"
    by_cwd = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    by_cwd.parent.mkdir(parents=True)
    by_cwd.write_text(
        json.dumps(
            {"session_id": "kimi-sid", "transcript_path": "", "cwd": "/tmp", "runtime_host": "kimi"}
        )
        + "\n"
    )
    assert _session.detect_via_hook(proj_key, home) is None


def test_detect_session_partial_hook_index_reports_not_found(tmp_path: Path):
    """(b) mtime 未命中 + hook cache 只有部分索引条目（无 transcript_path）时，
    detect_session 的公共入口必须返回 ("-", "-", "unknown")，不报错、不误判为命中。"""
    home = tmp_path
    proj_key = "-repo"
    # 无 .claude/projects/<proj_key> 目录 → mtime 探测天然未命中
    by_cwd = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    by_cwd.parent.mkdir(parents=True)
    by_cwd.write_text(
        json.dumps({"session_id": "kimi-sid", "transcript_path": "", "cwd": "/tmp"}) + "\n"
    )
    sid, tx, src = _session.detect_session(proj_key, home=home)
    assert (sid, tx, src) == ("-", "-", "unknown")


def test_detect_via_hook_does_not_call_detect_via_mtime(tmp_path: Path, monkeypatch):
    """(c) detect_via_hook 保持 hook-only 职责边界，不在内部调用 detect_via_mtime
    （避免 round-3 F3 指出的"hook 内部自行回退 mtime"这种职责混淆重新引入）。"""
    calls: list[str] = []
    monkeypatch.setattr(
        _session, "detect_via_mtime", lambda *a, **kw: calls.append(1) or None
    )
    home = tmp_path
    proj_key = "-repo"
    by_cwd = home / "task_log" / ".session-cache" / "by-cwd" / f"{proj_key}.jsonl"
    by_cwd.parent.mkdir(parents=True)
    tx_path = home / "tx.jsonl"
    tx_path.write_text("{}\n")
    by_cwd.write_text(
        json.dumps({"session_id": "sid", "transcript_path": str(tx_path)}) + "\n"
    )
    result = _session.detect_via_hook(proj_key, home)
    assert result is not None
    assert calls == []
