"""test_parallel_state.py — 并行 state 扩展、文件锁、resume 向后兼容测试。

覆盖 spec：
- parallel-layer-scheduling spec.md：并发 record 不丢更新、并行层中断续跑、旧 state 向后兼容
- state.py：set_parallel_fields、acquire/release_state_lock
- resume.py：compute_resume 并行路径 + 旧 state 兼容
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from npc import state as _state
from npc import resume as _resume


# ============================================================
# helpers
# ============================================================


def _make_state(tmp_path: Path, changes: list[str]) -> tuple[Path, Path]:
    """创建一个最简 state.json + state.md，返回 (state_json, state_md)。"""
    state_json = tmp_path / "test-plan-state.json"
    state_md = tmp_path / "test-plan-state.md"
    progress = [
        {
            "seq": i + 1,
            "change_id": cid,
            "status": "pending",
            "blocking_trend": [],
            "categories_seen": [],
            "rounds_since_strict_decrease": 0,
            "phases": {},
        }
        for i, cid in enumerate(changes)
    ]
    state = {
        "schema_version": 2,
        "run_ts": "2026-07-03-1234-000000",
        "started_at": "2026-07-03T12:34:00+00:00",
        "last_updated_at": "2026-07-03T12:34:00+00:00",
        "mode": "interactive",
        "fresh": False,
        "status": "in-progress",
        "project_root": str(tmp_path),
        "proj_key": "-test-proj",
        "git_head_at_start": "abc1234",
        "cc_session": {"session_id": None, "transcript_path": None, "source": "unknown"},
        "plan_order": changes,
        "progress": progress,
    }
    state_json.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state_md.write_text("# test\n", encoding="utf-8")
    return state_json, state_md


# ============================================================
# Task 3.2 / 3.3: set_parallel_fields + 文件锁
# ============================================================


def test_set_parallel_fields_basic(tmp_path):
    """set_parallel_fields 写入 dag_layer / merge_status / eviction_count。"""
    state_json, state_md = _make_state(tmp_path, ["change-a", "change-b"])

    _state.set_parallel_fields(
        state_json, state_md, 1,
        dag_layer=0,
        merge_status="queued",
        eviction_count=1,
        change_branch="spine/2026-07-03-1234/change-a",
        exec_worktree="/tmp/worktree/change-a",
    )

    loaded = _state.read_state(state_json)
    entry = loaded["progress"][0]
    assert entry["dag_layer"] == 0
    assert entry["merge_status"] == "queued"
    assert entry["eviction_count"] == 1
    assert entry["change_branch"] == "spine/2026-07-03-1234/change-a"
    assert entry["exec_worktree"] == "/tmp/worktree/change-a"


def test_set_parallel_fields_invalid_merge_status(tmp_path):
    """非法 merge_status 抛 ValueError。"""
    state_json, state_md = _make_state(tmp_path, ["change-a"])
    with pytest.raises(ValueError, match="merge_status"):
        _state.set_parallel_fields(state_json, state_md, 1, merge_status="invalid")


def test_state_lock_acquire_release(tmp_path):
    """acquire_state_lock + release_state_lock 正常工作。"""
    state_json, _ = _make_state(tmp_path, ["change-a"])
    lock_fh = _state.acquire_state_lock(state_json)
    assert lock_fh is not None
    _state.release_state_lock(lock_fh)


def test_concurrent_state_updates_no_lost_write(tmp_path):
    """并发 record 不丢更新：两个线程同时写 state，最终两次写都反映。

    覆盖 spec Scenario: 并发 record 不丢更新。
    """
    state_json, state_md = _make_state(tmp_path, ["change-a", "change-b"])
    errors = []

    def update_seq(seq, new_status):
        try:
            def mutate(state):
                state["progress"][seq - 1]["status"] = new_status
                state["progress"][seq - 1]["test_marker"] = f"seq{seq}"
            _state.update_state(state_json, state_md, mutate)
        except Exception as e:
            errors.append(str(e))

    t1 = threading.Thread(target=update_seq, args=(1, "implementing"))
    t2 = threading.Thread(target=update_seq, args=(2, "reviewing"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Errors: {errors}"

    loaded = _state.read_state(state_json)
    # 两次更新都应反映
    assert loaded["progress"][0]["status"] == "implementing"
    assert loaded["progress"][0]["test_marker"] == "seq1"
    assert loaded["progress"][1]["status"] == "reviewing"
    assert loaded["progress"][1]["test_marker"] == "seq2"


# ============================================================
# Task 3.5 / 3.6: resume 并行路径 + 旧 state 向后兼容
# ============================================================


def test_resume_old_state_backward_compat(tmp_path):
    """旧 state 无 dag_layer 字段 → 按原线性 seq 游标语义恢复，不报错。

    覆盖 spec Scenario: 旧 state 向后兼容。
    """
    state_json, state_md = _make_state(tmp_path, ["change-a", "change-b", "change-c"])
    # 模拟 change-a 已 archived，change-b 在 fix 中
    state = _state.read_state(state_json)
    state["progress"][0]["status"] = "archived"
    state["progress"][1]["status"] = "in-fix-loop"
    state["progress"][1]["phases"] = {
        "implement": {"status": "done"},
        "review-r0": {"status": "done", "blocking": 2},
        "fix-r1": {"status": "in-progress"},
    }
    _state.write_state(state_json, state_md, state)

    result = _resume.compute_resume(state)
    assert result["needs_resume"] is True
    assert result["next_change_id"] == "change-b"
    assert "layer" not in result or result.get("layer") is None  # 旧 state 路径


def test_resume_parallel_state_find_unconverged_layer(tmp_path):
    """并行 state：run 在层 1（含 a、b）中断，a 已 archived，b 在 fix round 3。

    覆盖 spec Scenario: 并行层中断后续跑。
    """
    state_json, state_md = _make_state(tmp_path, ["change-a", "change-b"])

    # 写并行 state
    state = _state.read_state(state_json)
    state["progress"][0].update({
        "dag_layer": 1,
        "status": "archived",
        "merge_status": "merged",
        "eviction_count": 0,
    })
    state["progress"][1].update({
        "dag_layer": 1,
        "status": "in-fix-loop",
        "merge_status": "pending",
        "eviction_count": 0,
        "phases": {
            "implement": {"status": "done"},
            "review-r0": {"status": "done", "blocking": 2},
            "fix-r1": {"status": "done"},
            "review-r1": {"status": "done", "blocking": 1},
            "fix-r2": {"status": "done"},
            "review-r2": {"status": "done", "blocking": 1},
            "fix-r3": {"status": "in-progress"},
        },
    })
    _state.write_state(state_json, state_md, state)

    result = _resume.compute_resume(state)
    assert result["needs_resume"] is True
    assert result["layer"] == 1
    # b 应在 changes[] 中
    change_ids = [c["change_id"] for c in result["changes"]]
    assert "change-b" in change_ids
    # a 不在待续跑清单（已 archived）
    non_terminal = [c for c in result["changes"] if c["status"] not in _resume.TERMINAL_STATUSES]
    non_terminal_ids = [c["change_id"] for c in non_terminal]
    assert "change-a" not in non_terminal_ids
    assert "change-b" in non_terminal_ids


def test_resume_all_done_parallel_state(tmp_path):
    """并行 state：全部 change archived → all_done=True。"""
    state_json, state_md = _make_state(tmp_path, ["change-a", "change-b"])
    state = _state.read_state(state_json)
    for i in range(2):
        state["progress"][i].update({
            "dag_layer": 0,
            "status": "archived",
            "merge_status": "merged",
        })
    _state.write_state(state_json, state_md, state)

    result = _resume.compute_resume(state)
    assert result["needs_resume"] is False
    assert result.get("all_done") is True


# ============================================================
# Task 3.4: paths.py per-change worktree 工具
# ============================================================


def test_per_change_pointer_write_read(tmp_path):
    """write_per_change_pointer / read_per_change_pointer 往返正确。"""
    from npc.paths import write_per_change_pointer, read_per_change_pointer

    worktree_root = tmp_path / "worktree"
    worktree_root.mkdir()
    state_json = tmp_path / "state.json"

    write_per_change_pointer(
        worktree_root,
        parent_run_ts="2026-07-03-1234-000000",
        parent_task_log_dir=tmp_path,
        parent_state_json=state_json,
    )

    data = read_per_change_pointer(worktree_root)
    assert data is not None
    assert data["parent_run_ts"] == "2026-07-03-1234-000000"
    assert data["parent_task_log_dir"] == str(tmp_path)
    assert data["parent_state_json"] == str(state_json)


def test_per_change_worktree_path(tmp_path):
    """per_change_worktree_path 返回正确路径。"""
    from npc.paths import per_change_worktree_path

    path = per_change_worktree_path(tmp_path, "2026-07-03-1234", "my-change")
    assert path == tmp_path / ".spine" / "worktrees" / "2026-07-03-1234" / "my-change"


def test_per_change_branch_name():
    """per_change_branch_name 返回正确分支名。"""
    from npc.paths import per_change_branch_name

    name = per_change_branch_name("2026-07-03-1234", "my-change")
    assert name == "spine/2026-07-03-1234/my-change"
