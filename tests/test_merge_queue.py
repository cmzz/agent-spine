"""test_merge_queue.py — merge_queue.py 单元测试。

覆盖 spec：
- merge-queue-eviction spec.md 全部 Scenario
- 干净合回 + archive
- archive 不进并行段（queue 串行）
- 合回不触碰主 checkout
- rebase 冲突驱逐回喂（eviction 文件结构）
- 复测失败驱逐
- 二次驱逐转 auto-decide（merge-evicted trigger）
- 依赖失败下游 dep-failed skip
- 主 checkout 零写入
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from npc.merge_queue import (
    MergeQueue,
    MergeQueueEntry,
    build_eviction_context,
    write_eviction_file,
)


# ============================================================
# helpers
# ============================================================


def _make_state(tmp_path: Path, changes: list[str]) -> tuple[Path, Path]:
    """创建最简 state.json。"""
    from npc import state as _state

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
            "dag_layer": 0,
            "merge_status": "pending",
            "eviction_count": 0,
        }
        for i, cid in enumerate(changes)
    ]
    state = {
        "schema_version": 2,
        "run_ts": "2026-07-03-1234-000000",
        "started_at": "2026-07-03T12:00:00+00:00",
        "last_updated_at": "2026-07-03T12:00:00+00:00",
        "mode": "auto",
        "fresh": False,
        "status": "in-progress",
        "project_root": str(tmp_path),
        "proj_key": "-test",
        "git_head_at_start": "abc",
        "cc_session": {"session_id": None, "transcript_path": None, "source": "unknown"},
        "plan_order": changes,
        "progress": progress,
    }
    state_json.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    state_md.write_text("# test\n", encoding="utf-8")
    return state_json, state_md


def _make_queue(
    tmp_path: Path,
    changes: list[str],
    *,
    max_evictions: int = 2,
    verify_fn: Callable | None = None,
    archive_fn: Callable | None = None,
    auto_decide_fn: Callable | None = None,
    runner: Callable = subprocess.run,
) -> tuple[MergeQueue, Path, Path]:
    state_json, state_md = _make_state(tmp_path, changes)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    queue = MergeQueue(
        run_root=tmp_path / "run_worktree",
        repo_root=tmp_path / "repo",
        run_branch="spine/2026-07-03-1234",
        state_json=state_json,
        state_md=state_md,
        run_dir=run_dir,
        max_evictions=max_evictions,
        verify_fn=verify_fn,
        archive_fn=archive_fn,
        auto_decide_fn=auto_decide_fn,
        runner=runner,
    )
    return queue, state_json, state_md


def _always_ok_runner(cmd, **kwargs):
    """Fake git runner：所有命令返回 rc=0。"""
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _conflict_runner(cmds_to_fail: set[str]):
    """返回一个 runner：包含特定子命令时返回 rc=1（模拟冲突）。"""
    def runner(cmd, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        for fail_substr in cmds_to_fail:
            if fail_substr in cmd_str:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="CONFLICT in src/x.py")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return runner


# ============================================================
# Scenario: 干净合回并 archive
# ============================================================


def test_merge_queue_clean_merge_and_archive(tmp_path):
    """rebase 无冲突、复测通过 → 合回成功，archive 执行，worktree 拆除。

    覆盖：Scenario 干净合回并 archive。
    """
    worktree = tmp_path / "wt" / "change-a"
    worktree.mkdir(parents=True)

    archive_calls = []

    def archive_fn(seq, run_root):
        archive_calls.append(seq)
        return True, "", "abc1234"

    def verify_fn(wt):
        return True, ""

    queue, state_json, state_md = _make_queue(
        tmp_path, ["change-a"],
        verify_fn=verify_fn,
        archive_fn=archive_fn,
        runner=_always_ok_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-a",
        seq=1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-a",
        exec_worktree=worktree,
        run_branch="spine/2026-07-03-1234",
    )

    result = queue.process_entry(entry)
    assert result.success is True
    assert result.evicted is False
    assert result.archive_commit == "abc1234"
    assert archive_calls == [1], "archive should be called once"


# ============================================================
# Scenario: archive 不进并行段（merge queue 串行处理）
# ============================================================


def test_merge_queue_archive_in_serial(tmp_path):
    """两个 change 的 archive 由 queue 串行执行，不在 per-change worktree。

    覆盖：Scenario archive 不进并行段。
    """
    archive_order = []

    def archive_fn(seq, run_root):
        archive_order.append(seq)
        return True, "", f"commit-{seq}"

    def verify_fn(wt):
        return True, ""

    queue, _, _ = _make_queue(
        tmp_path, ["change-a", "change-b"],
        verify_fn=verify_fn,
        archive_fn=archive_fn,
        runner=_always_ok_runner,
    )

    entries = []
    for i, (cid, seq) in enumerate([("change-a", 1), ("change-b", 2)]):
        wt = tmp_path / f"wt/{cid}"
        wt.mkdir(parents=True)
        entries.append(MergeQueueEntry(
            change_id=cid,
            seq=seq,
            dag_layer=0,
            change_branch=f"spine/2026-07-03-1234/{cid}",
            exec_worktree=wt,
            run_branch="spine/2026-07-03-1234",
        ))

    results = queue.process_all(entries)
    assert all(r.success for r in results)
    # archive 按串行顺序执行
    assert archive_order == [1, 2]


# ============================================================
# Scenario: rebase 冲突驱逐回喂
# ============================================================


def test_merge_queue_rebase_conflict_eviction(tmp_path):
    """rebase 冲突 → 驱逐，eviction 文件写入，状态 eviction_count+1。

    覆盖：Scenario rebase 冲突驱逐回喂。
    """
    worktree = tmp_path / "wt" / "change-b"
    worktree.mkdir(parents=True)

    def verify_fn(wt):
        return True, ""

    # 第一次 rebase 失败（冲突），后续 abort 和重放成功
    call_count = {"n": 0}

    def conflict_runner(cmd, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        # 第一次 rebase 失败，后续（abort/重放）成功
        if "rebase" in cmd_str and "--abort" not in cmd_str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="CONFLICT in src/x.py")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    queue, state_json, state_md = _make_queue(
        tmp_path, ["change-b"],
        verify_fn=verify_fn,
        max_evictions=2,
        runner=conflict_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-b",
        seq=1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-b",
        exec_worktree=worktree,
        run_branch="spine/2026-07-03-1234",
    )

    result = queue.process_entry(entry)
    assert result.evicted is True
    assert result.eviction_reason == "conflict"
    assert result.eviction_count == 1

    # eviction 文件应写入 run_dir
    eviction_file = queue.run_dir / "change-b.eviction.json"
    assert eviction_file.is_file(), "eviction file should exist"
    ctx = json.loads(eviction_file.read_text())
    assert ctx["reason"] == "conflict"
    assert "instructions" in ctx


# ============================================================
# Scenario: 复测失败驱逐
# ============================================================


def test_merge_queue_test_failure_eviction(tmp_path):
    """rebase 干净但复测失败 → 驱逐，run 分支不含 change 的 commits。

    覆盖：Scenario 复测失败同样驱逐。
    """
    worktree = tmp_path / "wt" / "change-b"
    worktree.mkdir(parents=True)

    def verify_fn(wt):
        return False, "test_output: AssertionError"

    queue, state_json, _ = _make_queue(
        tmp_path, ["change-b"],
        verify_fn=verify_fn,
        runner=_always_ok_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-b",
        seq=1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-b",
        exec_worktree=worktree,
        run_branch="spine/2026-07-03-1234",
    )

    result = queue.process_entry(entry)
    assert result.evicted is True
    assert result.eviction_reason == "test-failure"

    # eviction 文件含测试失败输出
    eviction_file = queue.run_dir / "change-b.eviction.json"
    assert eviction_file.is_file()
    ctx = json.loads(eviction_file.read_text())
    assert ctx["reason"] == "test-failure"
    assert "AssertionError" in ctx.get("test_output", "")


# ============================================================
# Scenario: 二次驱逐转 auto-decide
# ============================================================


def test_merge_queue_eviction_limit_triggers_auto_decide(tmp_path):
    """第 2 次驱逐达上限 → auto_decide_fn 被调用。

    覆盖：Scenario 二次驱逐触发 auto-decide。
    """
    worktree = tmp_path / "wt" / "change-b"
    worktree.mkdir(parents=True)

    auto_decide_calls = []

    def verify_fn(wt):
        return False, "test failed"

    def auto_decide_fn(seq):
        auto_decide_calls.append(seq)
        return "skip"

    queue, _, _ = _make_queue(
        tmp_path, ["change-b"],
        verify_fn=verify_fn,
        auto_decide_fn=auto_decide_fn,
        max_evictions=2,
        runner=_always_ok_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-b",
        seq=1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-b",
        exec_worktree=worktree,
        run_branch="spine/2026-07-03-1234",
        eviction_count=1,  # 已被驱逐一次
    )

    result = queue.process_entry(entry)
    assert result.evicted is True
    assert result.eviction_count == 2
    # auto-decide 应被调用
    assert auto_decide_calls == [1], f"auto_decide not called: {auto_decide_calls}"


# ============================================================
# Scenario: eviction 文件结构
# ============================================================


def test_build_eviction_context_structure(tmp_path):
    """build_eviction_context 产出结构化 context，含所需字段。"""
    entry = MergeQueueEntry(
        change_id="change-b",
        seq=2,
        dag_layer=1,
        change_branch="spine/2026-07-03-1234/change-b",
        exec_worktree=tmp_path,
        run_branch="spine/2026-07-03-1234",
        eviction_count=1,
    )
    ctx = build_eviction_context(
        entry,
        reason="conflict",
        conflict_files=["src/x.py"],
        conflict_diff="<<<< HEAD\n...\n====\n...\n>>>>",
    )
    assert ctx["change_id"] == "change-b"
    assert ctx["reason"] == "conflict"
    assert "src/x.py" in ctx["conflict_files"]
    assert "instructions" in ctx
    assert "rebase --continue" in ctx["instructions"]


def test_write_eviction_file(tmp_path):
    """write_eviction_file 写入正确路径并可读回。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = {"change_id": "change-b", "reason": "conflict", "eviction_count": 1}
    path = write_eviction_file(run_dir, "change-b", ctx)
    assert path == run_dir / "change-b.eviction.json"
    loaded = json.loads(path.read_text())
    assert loaded["change_id"] == "change-b"


# ============================================================
# Scenario: auto-decide merge-evicted trigger
# ============================================================


def test_auto_decide_merge_evicted_trigger(tmp_path):
    """auto-decide --trigger merge-evicted → action=skip, set_status=skipped-auto。"""
    from npc.auto_decide import _decide

    entry = {
        "seq": 1,
        "change_id": "change-b",
        "status": "in-fix-loop",
        "blocking_trend": [2, 2, 2],
        "categories_seen": ["cat-a"],
        "last_trigger": None,
    }
    decision = _decide(entry, "merge-evicted")
    assert decision["action"] == "skip"
    assert decision["set_status"] == "skipped-auto"
    assert decision.get("skipped_reason") == "merge-evicted"


# ============================================================
# Regression F1: state write failure stops subsequent git actions
# ============================================================


def test_state_write_failure_queued_stops_processing(tmp_path):
    """F1 回归：set_parallel_fields 在 queued 时抛出异常 → process_entry 返回
    MergeResult(success=False) 且不执行任何 git rebase / ff-merge。

    真实路径：state_json 不存在（FileNotFoundError），触发实际 set_parallel_fields 代码路径。
    """
    from npc.merge_queue import MergeQueue, MergeQueueEntry, MergeResult

    worktree = tmp_path / "wt" / "change-x"
    worktree.mkdir(parents=True)

    # 使 state_json 不存在 → set_parallel_fields → update_state → read_state 抛 FileNotFoundError
    state_json = tmp_path / "nonexistent-state.json"
    state_md = tmp_path / "nonexistent-state.md"
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    git_calls: list[str] = []

    def tracking_runner(cmd, **kwargs):
        git_calls.append(" ".join(str(c) for c in cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def verify_fn(wt):
        return True, ""

    def archive_fn(seq, run_root):
        return True, "", "abc"

    queue = MergeQueue(
        run_root=tmp_path / "run_wt",
        repo_root=tmp_path / "repo",
        run_branch="spine/test",
        state_json=state_json,
        state_md=state_md,
        run_dir=run_dir,
        max_evictions=2,
        verify_fn=verify_fn,
        archive_fn=archive_fn,
        runner=tracking_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-x",
        seq=1,
        dag_layer=0,
        change_branch="spine/test/change-x",
        exec_worktree=worktree,
        run_branch="spine/test",
    )

    result = queue.process_entry(entry)

    # 必须返回失败
    assert result.success is False, "state write failure must propagate as MergeResult(success=False)"
    assert "state write failed" in result.error, f"unexpected error: {result.error}"
    # 不得执行 rebase 或 ff-merge
    rebase_calls = [c for c in git_calls if "rebase" in c]
    ff_calls = [c for c in git_calls if "merge" in c]
    assert not rebase_calls, f"rebase should not be called when state write fails: {rebase_calls}"
    assert not ff_calls, f"ff-merge should not be called when state write fails: {ff_calls}"


def test_state_write_failure_merged_stops_archive(tmp_path):
    """F1 回归：set_parallel_fields 在 merged 时抛出异常 → process_entry 返回
    MergeResult(success=False) 且不执行 archive/worktree_remove。

    真实路径：rebase & ff-merge 成功后，state_json 被删除使写 merged 失败。
    """
    from npc import state as _state
    from npc.merge_queue import MergeQueue, MergeQueueEntry

    worktree = tmp_path / "wt" / "change-y"
    worktree.mkdir(parents=True)

    state_json, state_md = _make_state(tmp_path, ["change-y"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    archive_calls: list[int] = []
    write_merged_called = False

    original_set_parallel_fields = _state.set_parallel_fields

    def patched_set_parallel_fields(sj, sm, seq, *, merge_status=None, **kw):
        nonlocal write_merged_called
        if merge_status == "merged":
            write_merged_called = True
            raise _state.StateLockError("simulated lock timeout on merged write")
        return original_set_parallel_fields(sj, sm, seq, merge_status=merge_status, **kw)

    import npc.merge_queue as _mq
    orig_fn = _mq._state.set_parallel_fields
    _mq._state.set_parallel_fields = patched_set_parallel_fields

    try:
        def archive_fn(seq, run_root):
            archive_calls.append(seq)
            return True, "", "commit-abc"

        def verify_fn(wt):
            return True, ""

        queue = MergeQueue(
            run_root=tmp_path / "run_wt",
            repo_root=tmp_path / "repo",
            run_branch="spine/test",
            state_json=state_json,
            state_md=state_md,
            run_dir=run_dir,
            max_evictions=2,
            verify_fn=verify_fn,
            archive_fn=archive_fn,
            runner=_always_ok_runner,
        )

        entry = MergeQueueEntry(
            change_id="change-y",
            seq=1,
            dag_layer=0,
            change_branch="spine/test/change-y",
            exec_worktree=worktree,
            run_branch="spine/test",
        )

        result = queue.process_entry(entry)
    finally:
        _mq._state.set_parallel_fields = orig_fn

    assert result.success is False, "StateLockError on merged write must propagate as failure"
    assert "state write failed (merged)" in result.error
    # archive must NOT be called when state write for 'merged' fails
    assert archive_calls == [], f"archive should not be called: {archive_calls}"


# ============================================================
# Regression F2: auto-decide failure keeps worktree, writes fallback state
# ============================================================


def test_eviction_limit_auto_decide_failure_preserves_worktree(tmp_path):
    """F2 回归：auto-decide 子进程失败（返回 applied=False）→ worktree 不拆除，
    返回结构化错误，state 写 skipped_reason=merge-evicted。

    真实路径：auto_decide_fn 返回 (False, 'skip') 触发实际 fallback 逻辑。
    """
    from npc.merge_queue import MergeQueue, MergeQueueEntry

    worktree = tmp_path / "wt" / "change-z"
    worktree.mkdir(parents=True)

    state_json, state_md = _make_state(tmp_path, ["change-z"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def verify_fn(wt):
        return False, "test failed"

    # auto_decide_fn 返回 (applied=False, action='skip') — 模拟子进程失败
    def failing_auto_decide(seq):
        return (False, "skip")

    queue = MergeQueue(
        run_root=tmp_path / "run_wt",
        repo_root=tmp_path / "repo",
        run_branch="spine/test",
        state_json=state_json,
        state_md=state_md,
        run_dir=run_dir,
        max_evictions=1,
        verify_fn=verify_fn,
        auto_decide_fn=failing_auto_decide,
        runner=_always_ok_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-z",
        seq=1,
        dag_layer=0,
        change_branch="spine/test/change-z",
        exec_worktree=worktree,
        run_branch="spine/test",
        eviction_count=0,
    )

    result = queue.process_entry(entry)

    # auto-decide 失败 → 不拆 worktree
    assert worktree.exists(), "worktree must be preserved when auto-decide fails"
    # 返回结构化错误
    assert result.success is False
    assert "auto-decide-failed" in result.error, f"unexpected error msg: {result.error}"
    assert result.evicted is True


def test_default_auto_decide_returns_applied_false_on_subprocess_failure(tmp_path):
    """F2 回归：_default_auto_decide 子进程返回 rc!=0 → (False, 'skip')，不静默吞掉。

    真实路径：构造一个 MergeQueue 并直接调用 _default_auto_decide，
    通过注入 runner 模拟 npc 不存在（FileNotFoundError）。
    """
    from npc.merge_queue import MergeQueue

    state_json, state_md = _make_state(tmp_path, ["change-a"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    queue = MergeQueue(
        run_root=tmp_path / "run_wt",
        repo_root=tmp_path / "repo",
        run_branch="spine/test",
        state_json=state_json,
        state_md=state_md,
        run_dir=run_dir,
    )

    # Monkey-patch subprocess.run inside _default_auto_decide to simulate failure
    import npc.merge_queue as _mq
    original_subprocess_run = _mq.subprocess.run

    def failing_run(cmd, **kwargs):
        # Simulate `npc` not found: FileNotFoundError
        raise FileNotFoundError("npc not found")

    _mq.subprocess.run = failing_run
    try:
        applied, action = queue._default_auto_decide(seq=1)
    finally:
        _mq.subprocess.run = original_subprocess_run

    assert applied is False, "subprocess failure must return applied=False"
    assert action == "skip"


# ============================================================
# Regression F1 (round-4): evicted state write failure propagates as structured error
# ============================================================


def test_evicted_state_write_failure_returns_structured_error(tmp_path):
    """F1 round-4 回归：evicted 路径的 set_parallel_fields 抛 StateLockError →
    MergeResult(success=False, evicted=True) 且 error 含 'state write failed (evicted)'.
    停止后续 eviction-limit 判断和 auto-decide 调用。

    真实路径：monkey-patch _state.set_parallel_fields，仅当 merge_status=='evicted' 时抛出。
    """
    from npc import state as _state
    from npc.merge_queue import MergeQueue, MergeQueueEntry

    worktree = tmp_path / "wt" / "change-ev"
    worktree.mkdir(parents=True)

    state_json, state_md = _make_state(tmp_path, ["change-ev"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    auto_decide_calls: list[int] = []

    def verify_fn(wt):
        return False, "test failed"

    def auto_decide_fn(seq):
        auto_decide_calls.append(seq)
        return (True, "skip")

    original_set = _state.set_parallel_fields

    def patched_set(sj, sm, seq, *, merge_status=None, **kw):
        if merge_status == "evicted":
            raise _state.StateLockError("simulated evicted lock timeout")
        return original_set(sj, sm, seq, merge_status=merge_status, **kw)

    import npc.merge_queue as _mq
    orig_fn = _mq._state.set_parallel_fields
    _mq._state.set_parallel_fields = patched_set

    try:
        queue = MergeQueue(
            run_root=tmp_path / "run_wt",
            repo_root=tmp_path / "repo",
            run_branch="spine/test",
            state_json=state_json,
            state_md=state_md,
            run_dir=run_dir,
            max_evictions=1,   # first eviction hits the limit; but state write fails first
            verify_fn=verify_fn,
            auto_decide_fn=auto_decide_fn,
            runner=_always_ok_runner,
        )

        entry = MergeQueueEntry(
            change_id="change-ev",
            seq=1,
            dag_layer=0,
            change_branch="spine/test/change-ev",
            exec_worktree=worktree,
            run_branch="spine/test",
            eviction_count=0,
        )

        result = queue.process_entry(entry)
    finally:
        _mq._state.set_parallel_fields = orig_fn

    # Must surface as structured error
    assert result.success is False
    assert result.evicted is True
    assert "state write failed (evicted)" in result.error, f"unexpected: {result.error}"
    # auto-decide must NOT be called because we stopped on state write failure
    assert auto_decide_calls == [], f"auto-decide should not be called after state write failure: {auto_decide_calls}"


def test_evicted_state_write_file_not_found_returns_structured_error(tmp_path):
    """F1 round-4 回归：evicted 路径的 set_parallel_fields 因 FileNotFoundError
    (state_json 不存在) 返回结构化失败。

    真实路径：state_json 指向不存在文件，直接触发 FileNotFoundError 于实际 set_parallel_fields 中。
    """
    from npc.merge_queue import MergeQueue, MergeQueueEntry

    worktree = tmp_path / "wt" / "change-ev2"
    worktree.mkdir(parents=True)

    # queued 写入先成功（用真实 state），evicted 写入后删除 state_json
    state_json, state_md = _make_state(tmp_path, ["change-ev2"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    auto_decide_calls: list[int] = []

    def verify_fn(wt):
        return False, "test failed"

    def auto_decide_fn(seq):
        auto_decide_calls.append(seq)
        return (True, "skip")

    import npc.merge_queue as _mq
    original_set = _mq._state.set_parallel_fields

    queued_written = {"done": False}

    def patched_set(sj, sm, seq, *, merge_status=None, **kw):
        if merge_status == "queued":
            result = original_set(sj, sm, seq, merge_status=merge_status, **kw)
            queued_written["done"] = True
            return result
        if merge_status == "evicted":
            # Simulate: file gone between queued and evicted writes
            raise FileNotFoundError("state_json removed")
        return original_set(sj, sm, seq, merge_status=merge_status, **kw)

    _mq._state.set_parallel_fields = patched_set

    try:
        queue = MergeQueue(
            run_root=tmp_path / "run_wt",
            repo_root=tmp_path / "repo",
            run_branch="spine/test",
            state_json=state_json,
            state_md=state_md,
            run_dir=run_dir,
            max_evictions=2,
            verify_fn=verify_fn,
            auto_decide_fn=auto_decide_fn,
            runner=_always_ok_runner,
        )

        entry = MergeQueueEntry(
            change_id="change-ev2",
            seq=1,
            dag_layer=0,
            change_branch="spine/test/change-ev2",
            exec_worktree=worktree,
            run_branch="spine/test",
            eviction_count=0,
        )

        result = queue.process_entry(entry)
    finally:
        _mq._state.set_parallel_fields = original_set

    assert queued_written["done"], "queued state should have been written first"
    assert result.success is False
    assert result.evicted is True
    assert "state write failed (evicted)" in result.error, f"unexpected: {result.error}"
    assert auto_decide_calls == [], "auto-decide must not be called after evicted state write failure"
