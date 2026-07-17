"""paths 模块测试。"""

from __future__ import annotations

import os
import json
from dataclasses import replace
from pathlib import Path

import pytest

from npc import paths as _paths


def test_proj_key_mangling():
    assert _paths.proj_key_for(Path("/Users/you/code/foo")) == "-Users-you-code-foo"
    assert _paths.proj_key_for(Path("/")) == "-"


def test_proj_key_relative_path_rejected():
    with pytest.raises(_paths.PathsError):
        _paths.proj_key_for(Path("relative/path"))


def test_compute_paths_layout(fake_home: Path):
    p = _paths.compute_paths(
        Path("/Users/you/code/foo"), run_ts="2026-05-22-1545", home=fake_home
    )
    assert p.proj_key == "-Users-you-code-foo"
    assert p.task_log_dir == fake_home / "task_log" / "-Users-you-code-foo"
    assert p.run_dir == p.task_log_dir / "2026-05-22-1545"
    assert p.state_json == p.task_log_dir / "2026-05-22-1545-plan-state.json"
    assert p.state_md == p.task_log_dir / "2026-05-22-1545-plan-state.md"
    assert p.index_file == p.task_log_dir / "index.jsonl"
    assert p.schema_path == fake_home / "task_log" / ".new-plan-review-schema.json"
    assert p.run_events == p.run_dir / "run.events.jsonl"


def test_compute_paths_run_ts_default_format(fake_home: Path):
    p = _paths.compute_paths(Path("/Users/you/foo"), home=fake_home)
    # YYYY-MM-DD-HHMM-<suffix>
    # suffix = SS(2) + pid(4) + cnt(1+)，最短 7 位，随计数器增长可更长
    import re

    assert re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}-[0-9a-f]{7,}$", p.run_ts)


def test_detect_repo_root(fake_repo: Path):
    root = _paths.detect_repo_root(fake_repo)
    assert root.resolve() == fake_repo.resolve()


def test_detect_repo_root_non_repo(tmp_path: Path):
    with pytest.raises(_paths.PathsError):
        _paths.detect_repo_root(tmp_path)


def test_ensure_dirs_creates_layout(computed_paths: _paths.Paths):
    assert computed_paths.task_log_dir.is_dir()
    assert computed_paths.run_dir.is_dir()
    assert computed_paths.schema_path.parent.is_dir()


def test_to_env_roundtrip(computed_paths: _paths.Paths, monkeypatch):
    for k, v in computed_paths.to_env().items():
        monkeypatch.setenv(k, v)
    p2 = _paths.load_paths_from_env()
    assert p2.repo_root == computed_paths.repo_root
    assert p2.proj_key == computed_paths.proj_key
    assert p2.run_ts == computed_paths.run_ts
    assert p2.state_json == computed_paths.state_json


def test_codex_runtime_env_roundtrip(computed_paths: _paths.Paths, monkeypatch):
    codex_paths = replace(computed_paths, runtime_host="codex")
    for key, value in codex_paths.to_env().items():
        monkeypatch.setenv(key, value)
    assert _paths.load_paths_from_env().runtime_host == "codex"


def test_load_paths_missing_env(monkeypatch):
    for k in (
        "NPC_REPO_ROOT",
        "NPC_PROJ_KEY",
        "NPC_TASK_LOG_DIR",
        "NPC_RUN_TS",
        "NPC_RUN_DIR",
        "NPC_STATE_JSON",
        "NPC_STATE_MD",
        "NPC_INDEX_FILE",
        "NPC_SCHEMA_PATH",
        "NPC_RUN_EVENTS",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(_paths.PathsError) as ei:
        _paths.load_paths_from_env()
    assert "NPC_REPO_ROOT" in str(ei.value)


def test_base_for_zero_pads(computed_paths: _paths.Paths):
    base = _paths.base_for(computed_paths, 3, "add-foo")
    assert base.name == "003-add-foo"
    assert base.parent == computed_paths.run_dir


# ============================================================
# v0.2: run.json / active.json 持久化
# ============================================================


def test_write_and_read_run_json(computed_paths: _paths.Paths):
    target = _paths.write_run_json(computed_paths)
    assert target == computed_paths.run_dir / "run.json"
    assert target.is_file()
    restored = _paths.read_run_json(target)
    assert restored == computed_paths


def test_run_json_codex_runtime_roundtrip(computed_paths: _paths.Paths):
    codex_paths = replace(computed_paths, runtime_host="codex")
    target = _paths.write_run_json(codex_paths)
    assert json.loads(target.read_text(encoding="utf-8"))["runtime_host"] == "codex"
    assert _paths.read_run_json(target).runtime_host == "codex"


def test_legacy_run_json_defaults_runtime_host_to_claude(computed_paths: _paths.Paths):
    target = _paths.write_run_json(computed_paths)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.pop("runtime_host")
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert _paths.read_run_json(target).runtime_host == "claude"


def test_read_run_json_missing_field(tmp_path: Path):
    bad = tmp_path / "run.json"
    bad.write_text('{"schema_version":1,"repo_root":"/x"}', encoding="utf-8")
    with pytest.raises(_paths.PathsError) as ei:
        _paths.read_run_json(bad)
    assert "缺少字段" in str(ei.value)


def test_set_and_read_active(computed_paths: _paths.Paths):
    target = _paths.set_active(computed_paths.task_log_dir, computed_paths.run_ts)
    assert target == computed_paths.task_log_dir / "active.json"
    assert _paths.read_active(computed_paths.task_log_dir) == computed_paths.run_ts


def test_read_active_missing_returns_none(tmp_path: Path):
    assert _paths.read_active(tmp_path) is None


def test_load_paths_resolves_via_active_json(
    computed_paths: _paths.Paths, fake_repo: Path, monkeypatch
):
    """cwd 在 git 仓库 + active.json 指向有效 run.json → 不靠环境变量也能 resolve。"""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: computed_paths.task_log_dir.parent.parent))
    _paths.write_run_json(computed_paths)
    _paths.set_active(computed_paths.task_log_dir, computed_paths.run_ts)
    # 清空所有 NPC_* env，确保走文件路径
    for k in list(computed_paths.to_env().keys()):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(fake_repo)

    import argparse

    args = argparse.Namespace(state_json=None, run_ts=None, task_log_dir=None)
    p = _paths.load_paths(args)
    assert p.run_ts == computed_paths.run_ts
    assert p.run_dir == computed_paths.run_dir
    assert _paths.load_paths.last_source == "run_json_active"


def test_load_paths_explicit_run_ts(computed_paths: _paths.Paths, monkeypatch):
    _paths.write_run_json(computed_paths)
    for k in list(computed_paths.to_env().keys()):
        monkeypatch.delenv(k, raising=False)
    import argparse

    args = argparse.Namespace(
        state_json=None,
        run_ts=computed_paths.run_ts,
        task_log_dir=str(computed_paths.task_log_dir),
    )
    p = _paths.load_paths(args)
    assert p == computed_paths
    assert _paths.load_paths.last_source == "run_json_explicit"


def test_load_paths_state_json_override(computed_paths: _paths.Paths, monkeypatch, tmp_path: Path):
    _paths.write_run_json(computed_paths)
    override = tmp_path / "custom-state.json"
    import argparse

    args = argparse.Namespace(
        state_json=str(override),
        run_ts=computed_paths.run_ts,
        task_log_dir=str(computed_paths.task_log_dir),
    )
    p = _paths.load_paths(args)
    assert p.state_json == override
    assert p.runtime_host == computed_paths.runtime_host
    # 其它字段保持不变
    assert p.run_dir == computed_paths.run_dir


def test_load_paths_fallback_to_env(computed_paths: _paths.Paths, monkeypatch, tmp_path: Path):
    """无 run.json，env 完整 → 回退 env。"""
    monkeypatch.chdir(tmp_path)  # 非 git 仓库
    for k, v in computed_paths.to_env().items():
        monkeypatch.setenv(k, v)
    import argparse

    args = argparse.Namespace(state_json=None, run_ts=None, task_log_dir=None)
    p = _paths.load_paths(args)
    assert p.run_ts == computed_paths.run_ts
    assert _paths.load_paths.last_source == "env"


def test_load_paths_all_missing_raises(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    for k in (
        "NPC_REPO_ROOT",
        "NPC_PROJ_KEY",
        "NPC_TASK_LOG_DIR",
        "NPC_RUN_TS",
        "NPC_RUN_DIR",
        "NPC_STATE_JSON",
        "NPC_STATE_MD",
        "NPC_INDEX_FILE",
        "NPC_SCHEMA_PATH",
        "NPC_RUN_EVENTS",
    ):
        monkeypatch.delenv(k, raising=False)
    import argparse

    args = argparse.Namespace(state_json=None, run_ts=None, task_log_dir=None)
    with pytest.raises(_paths.PathsError):
        _paths.load_paths(args)


# ============================================================
# run-ts-unique-suffix: 唯一性与格式回归测试
# ============================================================


def test_make_run_ts_same_minute_returns_different_values():
    """Scenario: 同分钟两次调用产出不同 run_ts（task 2.1）。"""
    from datetime import datetime

    fixed_now = datetime(2026, 6, 26, 17, 58, 0)
    ts1 = _paths.make_run_ts(now=fixed_now)
    ts2 = _paths.make_run_ts(now=fixed_now)
    # 前缀相同（同一分钟），后缀不同（UUID 保证）
    assert ts1 != ts2
    assert ts1.startswith("2026-06-26-1758-")
    assert ts2.startswith("2026-06-26-1758-")


def test_make_run_ts_prefix_format_and_sortability():
    """Scenario: 前缀保持可读且可排序（task 2.2）。"""
    import re
    from datetime import datetime

    t_early = datetime(2026, 1, 1, 9, 0, 0)
    t_late = datetime(2026, 12, 31, 23, 59, 0)
    ts_early = _paths.make_run_ts(now=t_early)
    ts_late = _paths.make_run_ts(now=t_late)

    # suffix = SS(2) + pid(4) + cnt(1+)，最短 7 位，随计数器增长可更长
    pattern = r"^\d{4}-\d{2}-\d{2}-\d{4}-[0-9a-f]{7,}$"
    assert re.match(pattern, ts_early), f"格式不匹配: {ts_early}"
    assert re.match(pattern, ts_late), f"格式不匹配: {ts_late}"
    # 字典序与时间顺序一致
    assert ts_early < ts_late


def test_resume_parse_new_format_run_ts(fake_repo: Path, fake_home: Path):
    """Scenario: 既有 run_ts 解析不破坏——新格式 run_ts 作为完整字符串还原（task 2.3）。"""
    # 新格式 run_ts（含唯一后缀）
    new_ts = "2026-06-26-1758-ab12cd34"
    p = _paths.compute_paths(fake_repo, run_ts=new_ts, home=fake_home)
    _paths.ensure_dirs(p)
    # 写入 run.json + active.json
    _paths.write_run_json(p)
    _paths.set_active(p.task_log_dir, new_ts)
    # 读回，确认 run_ts 完整还原，无截断
    restored = _paths.read_run_json(_paths.run_json_path_for(p.task_log_dir, new_ts))
    assert restored.run_ts == new_ts
    # 通过 active.json 指针也能还原
    assert _paths.read_active(p.task_log_dir) == new_ts


def test_resume_parse_old_format_run_ts(fake_repo: Path, fake_home: Path):
    """Scenario: 旧格式 run_ts（无后缀）的 run.json 仍可正确解析（向后兼容）。"""
    old_ts = "2026-05-22-1545"
    p = _paths.compute_paths(fake_repo, run_ts=old_ts, home=fake_home)
    _paths.ensure_dirs(p)
    _paths.write_run_json(p)
    restored = _paths.read_run_json(_paths.run_json_path_for(p.task_log_dir, old_ts))
    assert restored.run_ts == old_ts


# ============================================================
# run-ts-unique-suffix: 真实并发回归（F1 fix 验证）
# ============================================================


def test_make_run_ts_suffix_contains_seconds_and_pid():
    """验证 suffix 包含当前秒和完整进程 PID（不截断），而非随机 UUID。"""
    import re
    from datetime import datetime

    fixed_now = datetime(2026, 6, 26, 17, 58, 42)  # second=42
    ts = _paths.make_run_ts(now=fixed_now)
    # 格式：YYYY-MM-DD-HHMM-SS<pid_hex><cnt_hex>
    # SS=42 -> "42"（前两字符），pid=完整 PID hex（变长），cnt=hex（1+）
    assert ts.startswith("2026-06-26-1758-")
    suffix = ts.split("-", 4)[4]
    # suffix 格式：SS(2) + pid_full_hex(1+) + cnt(1+)，最短 4 位（理论最小）
    assert len(suffix) >= 3, f"suffix 过短: {suffix}"
    assert re.match(r"^[0-9a-f]+$", suffix), f"suffix 含非法字符: {suffix}"
    # SS 部分（前 2 字符）必须是 "42"（十进制，秒数）
    assert suffix[:2] == "42", f"期望 SS=42，实际 suffix={suffix}"
    # PID 部分：完整 PID hex，验证 suffix 中间段包含 os.getpid() 的 hex 表示
    import os

    expected_pid_hex = f"{os.getpid():x}"
    # suffix = "42" + pid_hex + cnt_hex
    # pid_hex 紧跟 SS 之后
    pid_start = 2
    pid_end = pid_start + len(expected_pid_hex)
    assert suffix[pid_start:pid_end] == expected_pid_hex, (
        f"期望完整 PID hex={expected_pid_hex}，实际 suffix={suffix}"
    )


def test_make_run_ts_concurrent_no_collision():
    """真实并发回归：多线程同时调用 make_run_ts，产出值全部唯一（无碰撞）。

    该测试触发真实的 _run_ts_lock 和 _run_ts_counter 代码路径。
    """
    import threading
    from datetime import datetime

    fixed_now = datetime(2026, 6, 26, 17, 58, 5)
    results: list[str] = []
    errors: list[Exception] = []
    lock = threading.Lock()
    n_threads = 64

    def worker() -> None:
        try:
            ts = _paths.make_run_ts(now=fixed_now)
            with lock:
                results.append(ts)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"线程异常: {errors}"
    assert len(results) == n_threads, f"期望 {n_threads} 个结果，实际 {len(results)}"
    # 核心断言：无任何碰撞
    assert len(set(results)) == n_threads, (
        f"发现碰撞！unique={len(set(results))}，total={n_threads}，"
        f"重复值: {[ts for ts in results if results.count(ts) > 1]}"
    )


def test_make_run_ts_no_wraparound_beyond_256():
    """回归测试：同进程同秒调用超过 256 次，所有产出值仍全部唯一（无回绕碰撞）。

    Round 1 fix 中 cnt & 0xFF 会在第 257 次调用与第 1 次产出相同 cnt，
    导致 run_ts 碰撞。本测试直接覆盖该回绕路径，确保移除截断后无碰撞。
    触发真实代码路径：_run_ts_lock + _run_ts_counter（不截断）。
    """
    from datetime import datetime

    fixed_now = datetime(2026, 6, 26, 17, 58, 42)
    n_calls = 300  # 超过 256，覆盖回绕区域

    results = [_paths.make_run_ts(now=fixed_now) for _ in range(n_calls)]

    assert len(results) == n_calls
    assert len(set(results)) == n_calls, (
        f"发现碰撞！unique={len(set(results))}，total={n_calls}，"
        f"重复值（前 5）: {[ts for ts in results if results.count(ts) > 1][:5]}"
    )


def test_make_run_ts_identical_low16_pids_no_collision(monkeypatch):
    """回归测试（F1 根因修复验证）：两个低 16 位相同但完整 PID 不同的进程
    在同一秒以 cnt=0 起步时，产出不同的 run_ts。

    场景：PID=100 与 PID=65636（= 100 + 65536）低 16 位均为 0x0064，
    使用旧实现（os.getpid() & 0xFFFF）会产出相同 pid_hex="0064"，
    在同秒同 cnt 下碰撞。本测试通过 monkeypatch 模拟两个 PID，
    验证完整 PID 修复后不再碰撞。

    触发真实代码路径：make_run_ts → os.getpid()（monkeypatched） + _run_ts_lock。
    """
    import npc.paths as _p
    from datetime import datetime

    fixed_now = datetime(2026, 6, 26, 17, 58, 0)

    # 保存并重置计数器，确保两次模拟都从 cnt=0 起步
    original_counter = _p._run_ts_counter

    # --- 模拟 PID=100，cnt 从 0 起步 ---
    monkeypatch.setattr(os, "getpid", lambda: 100)
    with _p._run_ts_lock:
        _p._run_ts_counter = 0
    ts_pid100 = _p.make_run_ts(now=fixed_now)

    # --- 模拟 PID=65636（= 100 + 65536），cnt 从 0 起步 ---
    monkeypatch.setattr(os, "getpid", lambda: 65636)
    with _p._run_ts_lock:
        _p._run_ts_counter = 0
    ts_pid65636 = _p.make_run_ts(now=fixed_now)

    # 恢复计数器（monkeypatch 会自动还原 os.getpid）
    with _p._run_ts_lock:
        _p._run_ts_counter = original_counter

    # 两者低 16 位相同（0x0064），在旧实现下必然碰撞；修复后应不同
    assert ts_pid100 != ts_pid65636, (
        f"PID=100 与 PID=65636（低 16 位均为 0x0064）在同秒 cnt=0 时发生碰撞！\n"
        f"  ts_pid100={ts_pid100}\n  ts_pid65636={ts_pid65636}"
    )
    # 验证 suffix 中 PID 段确实包含完整 PID hex
    suffix100 = ts_pid100.split("-", 4)[4]
    suffix65636 = ts_pid65636.split("-", 4)[4]
    assert "0064" in suffix100, f"PID=100 的 hex(0x64) 应在 suffix 中: {suffix100}"
    assert "10064" in suffix65636, f"PID=65636 的 hex(0x10064) 应在 suffix 中: {suffix65636}"


def test_make_run_ts_cross_process_suffix_differs():
    """跨进程调用（通过 subprocess）产出不同 PID 部分，验证进程标识有效性。"""
    import subprocess
    import sys

    script = (
        "import sys; sys.path.insert(0, 'src'); "
        "from npc import paths; "
        "from datetime import datetime; "
        "print(paths.make_run_ts(now=datetime(2026, 6, 26, 17, 58, 15)))"
    )
    # 启动两个子进程，各自调用 make_run_ts
    r1 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd="/Users/ethan/Workspace/agent-spine",
    )
    r2 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd="/Users/ethan/Workspace/agent-spine",
    )
    assert r1.returncode == 0, f"子进程 1 失败: {r1.stderr}"
    assert r2.returncode == 0, f"子进程 2 失败: {r2.stderr}"

    ts1 = r1.stdout.strip()
    ts2 = r2.stdout.strip()
    # 两个子进程的 PID 不同 → suffix 中 PID 部分不同 → run_ts 不同
    # （极端情况：PID 重用且 cnt 相同；但 OS 不会在如此短时间内重用 PID）
    assert ts1 != ts2, f"跨进程应产出不同 run_ts，实际均为: {ts1}"
