"""owner 存活判定模块测试（worktree-owner-liveness change）。

覆盖 capture_owner_fields / owner_alive 的写入侧快照与判定侧算法：
pid 探测为主、24h 心跳新鲜度为兜底。
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta

import pytest

from npc import owner as _owner


def _dead_pid() -> int:
    """获取一个确定已退出且已回收的 pid。"""
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _iso_hours_ago(hours: float) -> str:
    return (datetime.now().astimezone() - timedelta(hours=hours)).isoformat(timespec="seconds")


# ----------------------------- capture_owner_fields -----------------------------


def test_capture_owner_fields_returns_pid_and_heartbeat(monkeypatch):
    """capture_owner_fields() 返回 owner_pid（= os.getppid()）与 ISO 心跳。"""
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    fields = _owner.capture_owner_fields()
    assert fields["owner_pid"] == 4242
    hb = fields["owner_heartbeat_at"]
    assert isinstance(hb, str)
    # ISO8601 可解析，且就是刚才（秒级）
    parsed = datetime.fromisoformat(hb)
    assert abs((datetime.now().astimezone() - parsed).total_seconds()) < 60


def test_capture_owner_fields_now_iso_override(monkeypatch):
    monkeypatch.setattr(os, "getppid", lambda: 4242)
    fields = _owner.capture_owner_fields(now_iso="2026-01-01T00:00:00+00:00")
    assert fields["owner_heartbeat_at"] == "2026-01-01T00:00:00+00:00"


# ----------------------------- owner_alive -----------------------------


def test_owner_alive_empty_state_is_dead():
    """无任何 owner 字段 → False（无信息即孤儿候选，向后兼容旧 schema）。"""
    assert _owner.owner_alive({}) is False


def test_owner_alive_live_pid_no_heartbeat_is_alive():
    """pid 存活 + 无心跳字段 → True（信任 pid，心跳缺失不判死）。"""
    assert _owner.owner_alive({"owner_pid": os.getpid()}) is True


def test_owner_alive_dead_pid_is_dead():
    """pid 确认不存在（ProcessLookupError）→ False，不受心跳阈值影响。"""
    dead = _dead_pid()
    assert _owner.owner_alive({"owner_pid": dead}) is False
    # 即使心跳新鲜也不复活
    assert (
        _owner.owner_alive(
            {"owner_pid": dead, "owner_heartbeat_at": _iso_hours_ago(0.1)}
        )
        is False
    )


def test_owner_alive_live_pid_stale_heartbeat_is_dead():
    """pid 存活 + 心跳 25 小时前 → False（心跳过期，疑似 pid 复用）。"""
    state = {"owner_pid": os.getpid(), "owner_heartbeat_at": _iso_hours_ago(25)}
    assert _owner.owner_alive(state) is False


def test_owner_alive_live_pid_fresh_heartbeat_is_alive():
    """pid 存活 + 心跳 1 小时前 → True。"""
    state = {"owner_pid": os.getpid(), "owner_heartbeat_at": _iso_hours_ago(1)}
    assert _owner.owner_alive(state) is True


def test_owner_alive_permission_error_treated_as_alive(monkeypatch):
    """os.kill 抛 PermissionError → 视为存在，走心跳二次确认分支。"""

    def _raise_perm(pid, sig):
        raise PermissionError("not permitted")

    monkeypatch.setattr(os, "kill", _raise_perm)
    # 心跳新鲜 → 存活
    assert (
        _owner.owner_alive(
            {"owner_pid": 99999, "owner_heartbeat_at": _iso_hours_ago(1)}
        )
        is True
    )
    # 心跳过期 → 不存活
    assert (
        _owner.owner_alive(
            {"owner_pid": 99999, "owner_heartbeat_at": _iso_hours_ago(25)}
        )
        is False
    )
    # 心跳缺失 → 信任 pid 判定
    assert _owner.owner_alive({"owner_pid": 99999}) is True


def test_owner_alive_invalid_pid_falls_back_to_heartbeat():
    """非法 owner_pid（字符串 / 负数 / 零）→ 退化为仅心跳判定。"""
    # 心跳缺失 → False
    assert _owner.owner_alive({"owner_pid": "not-a-pid"}) is False
    assert _owner.owner_alive({"owner_pid": -5}) is False
    assert _owner.owner_alive({"owner_pid": 0}) is False
    # 心跳新鲜 → True
    assert (
        _owner.owner_alive(
            {"owner_pid": "not-a-pid", "owner_heartbeat_at": _iso_hours_ago(1)}
        )
        is True
    )
    assert (
        _owner.owner_alive(
            {"owner_pid": -5, "owner_heartbeat_at": _iso_hours_ago(1)}
        )
        is True
    )
    # 心跳过期 → False
    assert (
        _owner.owner_alive(
            {"owner_pid": "not-a-pid", "owner_heartbeat_at": _iso_hours_ago(25)}
        )
        is False
    )


def test_owner_alive_heartbeat_only_no_pid():
    """owner_pid 缺失但有心跳：按心跳新鲜度判定（spec 第 1 步退化路径）。"""
    assert _owner.owner_alive({"owner_heartbeat_at": _iso_hours_ago(1)}) is True
    assert _owner.owner_alive({"owner_heartbeat_at": _iso_hours_ago(25)}) is False


def test_owner_alive_unparseable_heartbeat_treated_as_missing():
    """心跳不可解析 → 视为缺失：pid 存活则信任 pid，否则不存活。"""
    assert (
        _owner.owner_alive({"owner_pid": os.getpid(), "owner_heartbeat_at": "junk"})
        is True
    )
    assert _owner.owner_alive({"owner_heartbeat_at": "junk"}) is False


def test_heartbeat_staleness_constant():
    assert _owner.OWNER_HEARTBEAT_STALENESS_SECONDS == 24 * 60 * 60
