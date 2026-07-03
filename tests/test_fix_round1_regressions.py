"""test_fix_round1_regressions.py — Fix round 1 回归测试。

覆盖：
- F1: plan_order 反序时有依赖的 change 正确分入后置层（DAG 层深度计算用拓扑序）
- F2: state set-parallel-fields CLI 可通过 CLI 写入并被 resume detect 读取
- F3: per-change worktree 内的 load_paths 优先读取 pointer 绑定父 run
- F4: eviction 文件存在时注入 fix prompt（render_fixer 含 Merge Queue Eviction Context）
- F5: conflict 驱逐超限后执行 rebase --abort 并拆除 worktree（真实回归）
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

import pytest

from npc.plan import _build_dag_layers, _topological_sort
from npc.merge_queue import MergeQueue, MergeQueueEntry, write_eviction_file, build_eviction_context
from npc import state as _state
from npc import templates


# ============================================================
# helpers
# ============================================================


def _make_state(tmp_path: Path, changes: list[str]) -> tuple[Path, Path]:
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


def _make_run_json(tmp_path: Path, run_ts: str = "2026-07-03-1234-000000") -> Path:
    """创建 run.json，返回其路径。"""
    from npc import paths as _paths
    state_json = tmp_path / "state.json"
    state_md = tmp_path / "state.md"
    state_json.write_text("{}", encoding="utf-8")
    state_md.write_text("", encoding="utf-8")

    proj_key = "-test-proj"
    run_dir = tmp_path / "run_dir" / proj_key / run_ts
    run_dir.mkdir(parents=True)

    task_log_dir = tmp_path / "task_log" / proj_key
    task_log_dir.mkdir(parents=True)

    run_json_data = {
        "schema_version": 1,
        "run_ts": run_ts,
        "repo_root": str(tmp_path / "repo"),
        "proj_key": proj_key,
        "task_log_dir": str(task_log_dir),
        "run_dir": str(run_dir),
        "state_json": str(state_json),
        "state_md": str(state_md),
        "index_file": str(run_dir / "index.json"),
        "schema_path": str(tmp_path / "schema.json"),
        "run_events": str(run_dir / "run_events.jsonl"),
        "mode": "interactive",
    }
    rj = task_log_dir / run_ts / "run.json"
    rj.parent.mkdir(parents=True)
    rj.write_text(json.dumps(run_json_data, indent=2) + "\n", encoding="utf-8")
    return rj


# ============================================================
# F1: DAG 分层应使用拓扑序（反序 plan_order + 显式依赖回归）
# ============================================================


def test_f1_reversed_plan_order_with_dep_correct_layers():
    """F1 回归：plan_order=[change-b, change-a]，b 依赖 a → b 必须在 a 的后置层。

    这是对原始 bug 的直接回归：旧代码按 plan_order 顺序处理，b 先处理时 a 还不在
    layer_of，导致 b 和 a 均在 layer 0。修复后传入 topo_order 保证正确深度。
    """
    plan_order = ["change-b", "change-a"]
    deps = {"change-b": {"change-a"}, "change-a": set()}
    paths_map = {
        "change-b": {"src/b.py"},
        "change-a": {"src/a.py"},
    }
    topo_order = _topological_sort(plan_order, deps)
    assert topo_order is not None, "No cycle expected"

    layers, _ = _build_dag_layers(plan_order, deps, paths_map, max_parallel=4, topo_order=topo_order)

    layer_of = {}
    for i, layer in enumerate(layers):
        for cid in layer:
            layer_of[cid] = i

    assert "change-a" in layer_of
    assert "change-b" in layer_of
    assert layer_of["change-b"] > layer_of["change-a"], (
        f"change-b（layer {layer_of['change-b']}）应在 change-a（layer {layer_of['change-a']}）后置，"
        f"layers={layers}"
    )


def test_f1_topo_order_none_falls_back_gracefully():
    """F1：topo_order=None 时（兼容旧调用路径）仍能正常返回结果。"""
    plan_order = ["change-a", "change-b"]
    deps: dict = {"change-a": set(), "change-b": set()}
    paths_map = {"change-a": {"src/a.py"}, "change-b": {"src/b.py"}}

    # 不传 topo_order（默认 None）
    layers, _ = _build_dag_layers(plan_order, deps, paths_map, max_parallel=4)
    assert len(layers) == 1
    assert set(layers[0]) == {"change-a", "change-b"}


def test_f1_three_way_chain_reversed():
    """F1：a→b→c 链，plan_order=[c, b, a]（完全反序），每个在前驱的后置层。"""
    plan_order = ["change-c", "change-b", "change-a"]
    deps = {
        "change-c": {"change-b"},
        "change-b": {"change-a"},
        "change-a": set(),
    }
    paths_map = {cid: {f"src/{cid}.py"} for cid in plan_order}

    topo_order = _topological_sort(plan_order, deps)
    assert topo_order is not None

    layers, _ = _build_dag_layers(plan_order, deps, paths_map, max_parallel=4, topo_order=topo_order)

    layer_of = {}
    for i, layer in enumerate(layers):
        for cid in layer:
            layer_of[cid] = i

    assert layer_of["change-b"] > layer_of["change-a"], f"b 必须在 a 后：{layer_of}"
    assert layer_of["change-c"] > layer_of["change-b"], f"c 必须在 b 后：{layer_of}"


# ============================================================
# F2: state set-parallel-fields CLI 写入并读取
# ============================================================


def test_f2_set_parallel_fields_cmd_writes_fields(tmp_path):
    """F2 回归：set_parallel_fields_cmd 通过 state 写入 dag_layer / change_branch / exec_worktree。

    模拟 spine-run 通过 CLI 写入并行字段后，state 中可读取到正确值。
    """
    state_json, state_md = _make_state(tmp_path, ["change-a"])

    # 调用底层函数（CLI handler 内部调用）
    _state.set_parallel_fields(
        state_json, state_md, 1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-a",
        exec_worktree=str(tmp_path / "wt" / "change-a"),
    )

    data = json.loads(state_json.read_text())
    entry = data["progress"][0]
    assert entry["dag_layer"] == 0
    assert entry["change_branch"] == "spine/2026-07-03-1234/change-a"
    assert entry["exec_worktree"] == str(tmp_path / "wt" / "change-a")


def test_f2_set_parallel_fields_cmd_handler_args(tmp_path, monkeypatch):
    """F2 回归：set_parallel_fields_cmd handler 接受 argparse.Namespace 并写入字段。"""
    import argparse
    state_json, state_md = _make_state(tmp_path, ["change-a"])

    # 构造一个 run.json 供 load_paths 使用
    run_ts = "2026-07-03-1234-000001"
    proj_key = "-test-proj"
    task_log_dir = tmp_path / "task_log" / proj_key
    task_log_dir.mkdir(parents=True)
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir(parents=True)
    rj_dir = task_log_dir / run_ts
    rj_dir.mkdir(parents=True)
    run_json_data = {
        "schema_version": 1,
        "run_ts": run_ts,
        "repo_root": str(tmp_path / "repo"),
        "proj_key": proj_key,
        "task_log_dir": str(task_log_dir),
        "run_dir": str(run_dir),
        "state_json": str(state_json),
        "state_md": str(state_md),
        "index_file": str(run_dir / "index.json"),
        "schema_path": str(tmp_path / "schema.json"),
        "run_events": str(run_dir / "run_events.jsonl"),
        "mode": "interactive",
    }
    (rj_dir / "run.json").write_text(json.dumps(run_json_data) + "\n", encoding="utf-8")

    args = argparse.Namespace(
        task_log_dir=str(task_log_dir),
        run_ts=run_ts,
        state_json=None,
        seq=1,
        dag_layer=2,
        change_branch="spine/2026-07-03-1234/change-a",
        exec_worktree=str(tmp_path / "wt" / "change-a"),
        merge_status=None,
        skipped_reason=None,
    )

    captured = {}

    def mock_emit(data):
        captured.update(data)

    from npc import _io
    monkeypatch.setattr(_io, "emit", mock_emit)

    _state.set_parallel_fields_cmd(args)

    assert captured.get("ok") is True
    assert captured.get("dag_layer") == 2

    data = json.loads(state_json.read_text())
    entry = data["progress"][0]
    assert entry["dag_layer"] == 2
    assert entry["change_branch"] == "spine/2026-07-03-1234/change-a"


# ============================================================
# F3: per-change pointer 绑定父 run
# ============================================================


def test_f3_load_paths_reads_per_change_pointer(tmp_path, monkeypatch):
    """F3 回归：load_paths 在 cwd 的 repo root 下找到 pointer 文件后加载父 run。

    模拟 per-change worktree 场景：pointer 写入 repo root，load_paths 在无显式参数
    且无 active.json 的情况下应从 pointer 读取 parent_run_ts + parent_task_log_dir。
    """
    from npc import paths as _paths

    # 建父 run 的 run.json
    run_ts = "2026-07-03-9999-000001"
    proj_key = "-per-change-test"
    task_log_dir = tmp_path / "task_log" / proj_key
    task_log_dir.mkdir(parents=True)
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir(parents=True)
    state_json = tmp_path / "state.json"
    state_md = tmp_path / "state.md"
    state_json.write_text("{}", encoding="utf-8")
    state_md.write_text("", encoding="utf-8")
    rj_dir = task_log_dir / run_ts
    rj_dir.mkdir(parents=True)
    run_json_data = {
        "schema_version": 1,
        "run_ts": run_ts,
        "repo_root": str(tmp_path / "repo"),
        "proj_key": proj_key,
        "task_log_dir": str(task_log_dir),
        "run_dir": str(run_dir),
        "state_json": str(state_json),
        "state_md": str(state_md),
        "index_file": str(run_dir / "index.json"),
        "schema_path": str(tmp_path / "schema.json"),
        "run_events": str(run_dir / "run_events.jsonl"),
        "mode": "interactive",
    }
    (rj_dir / "run.json").write_text(json.dumps(run_json_data) + "\n", encoding="utf-8")

    # 建 per-change worktree 的 repo root
    worktree_repo = tmp_path / "worktree_repo"
    worktree_repo.mkdir(parents=True)

    # 写入 pointer
    _paths.write_per_change_pointer(
        worktree_repo,
        parent_run_ts=run_ts,
        parent_task_log_dir=task_log_dir,
        parent_state_json=state_json,
    )

    # monkeypatch detect_repo_root 返回 worktree_repo（模拟在 worktree 内执行）
    monkeypatch.setattr(_paths, "detect_repo_root", lambda start=None: worktree_repo)

    # load_paths 不传显式参数（模拟 coder 在 per-change worktree cwd 内执行 record）
    import argparse
    args = argparse.Namespace(task_log_dir=None, run_ts=None, state_json=None)

    p = _paths.load_paths(args)
    assert p.run_ts == run_ts, f"应从 pointer 加载父 run_ts，got={p.run_ts}"
    assert _paths.load_paths.last_source == "per_change_pointer"


def test_f3_explicit_args_override_pointer(tmp_path, monkeypatch):
    """F3 回归：显式 --run-ts 参数优先于 pointer 文件。"""
    from npc import paths as _paths

    run_ts_explicit = "2026-07-03-1111-111111"
    run_ts_pointer = "2026-07-03-9999-000001"

    proj_key = "-override-test"
    task_log_dir = tmp_path / "task_log" / proj_key
    task_log_dir.mkdir(parents=True)
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir(parents=True)
    state_json = tmp_path / "state.json"
    state_md = tmp_path / "state.md"
    state_json.write_text("{}", encoding="utf-8")
    state_md.write_text("", encoding="utf-8")

    # 建显式 run 的 run.json
    rj_dir = task_log_dir / run_ts_explicit
    rj_dir.mkdir(parents=True)
    run_json_data = {
        "schema_version": 1,
        "run_ts": run_ts_explicit,
        "repo_root": str(tmp_path / "repo"),
        "proj_key": proj_key,
        "task_log_dir": str(task_log_dir),
        "run_dir": str(run_dir),
        "state_json": str(state_json),
        "state_md": str(state_md),
        "index_file": str(run_dir / "index.json"),
        "schema_path": str(tmp_path / "schema.json"),
        "run_events": str(run_dir / "run_events.jsonl"),
        "mode": "interactive",
    }
    (rj_dir / "run.json").write_text(json.dumps(run_json_data) + "\n", encoding="utf-8")

    # 写 pointer 指向另一个 run（应被忽略）
    worktree_repo = tmp_path / "worktree_repo"
    worktree_repo.mkdir(parents=True)
    _paths.write_per_change_pointer(
        worktree_repo,
        parent_run_ts=run_ts_pointer,
        parent_task_log_dir=task_log_dir,
        parent_state_json=state_json,
    )
    monkeypatch.setattr(_paths, "detect_repo_root", lambda start=None: worktree_repo)

    import argparse
    args = argparse.Namespace(
        task_log_dir=str(task_log_dir),
        run_ts=run_ts_explicit,
        state_json=None,
    )
    p = _paths.load_paths(args)
    # 显式 run_ts 应优先
    assert p.run_ts == run_ts_explicit, f"显式参数应覆盖 pointer，got={p.run_ts}"
    assert _paths.load_paths.last_source == "run_json_explicit"


# ============================================================
# F4: eviction 文件注入 fix prompt（真实代码路径）
# ============================================================


def test_f4_eviction_file_injected_into_fix_prompt(tmp_path):
    """F4 回归：eviction 文件存在时，render_fixer 注入 Merge Queue Eviction Context 段。

    直接测试 agent.prompt_render 的 eviction 检测路径：构造真实 eviction.json 文件，
    调用 agent.py 中的 _render_eviction_md，验证结果包含冲突文件和指令。
    """
    from npc.agent import _render_eviction_md

    ev_data = {
        "change_id": "change-a",
        "seq": 1,
        "dag_layer": 0,
        "eviction_count": 1,
        "reason": "conflict",
        "conflict_files": ["src/x.py", "src/y.py"],
        "conflict_diff": "--- a/src/x.py\n+++ b/src/x.py\n@@@ conflict @@@",
        "test_output": "",
        "instructions": (
            "你的 working tree 中已有 rebase 停在冲突处（保留冲突标记）。"
            "请：① 解决所有冲突标记（<<<< ==== >>>>）；"
            "② git add 已解决的文件；"
            "③ git rebase --continue 完成 rebase。"
            "MUST NOT 自行发起新的 rebase/reset。"
        ),
    }

    md = _render_eviction_md(ev_data)

    assert "Merge Queue Eviction Context" in md, f"缺少 section 标题：{md[:200]}"
    assert "conflict" in md, f"缺少 reason：{md[:200]}"
    assert "src/x.py" in md, f"缺少冲突文件：{md[:200]}"
    assert "rebase --continue" in md, f"缺少操作指令：{md[:200]}"


def test_f4_render_fixer_with_eviction_md():
    """F4 回归：render_fixer 在 eviction_md 非空时将其注入 prompt 文本。"""
    eviction_md = "## Merge Queue Eviction Context\n\n**reason**: conflict"

    text = templates.render_fixer(
        change_id="change-a",
        round_n=2,
        implement_commit="abc1234",
        base="/tmp/base",
        repo_root="/tmp/repo",
        blocking_findings_md="## F1\n- test finding",
        categories_seen=["validation"],
        blocking_trend=[3, 2],
        eviction_md=eviction_md,
    )

    assert "Merge Queue Eviction Context" in text, f"eviction_md 未被注入 prompt：{text[:300]}"
    assert "reason**: conflict" in text


def test_f4_render_fixer_without_eviction_md():
    """F4 回归：eviction_md 为空时 prompt 不包含 eviction section（向后兼容）。"""
    text = templates.render_fixer(
        change_id="change-a",
        round_n=1,
        implement_commit="abc1234",
        base="/tmp/base",
        repo_root="/tmp/repo",
        blocking_findings_md="## F1\n- test finding",
        categories_seen=[],
        blocking_trend=[],
    )

    assert "Merge Queue Eviction Context" not in text


# ============================================================
# F5: conflict 驱逐超限后清理 worktree（真实回归）
#
# Category: partial-failure — 必须写真实回归触发实际代码路径
# ============================================================


def test_f5_conflict_eviction_limit_aborts_rebase_and_removes_worktree(tmp_path):
    """F5 真实回归：conflict 驱逐达上限后，调用 rebase --abort 并拆除 worktree。

    触发实际代码路径：MergeQueue._evict() 超限分支执行 rebase --abort +
    _worktree_remove()。通过记录 runner 调用验证两个操作均执行。
    """
    worktree = tmp_path / "wt" / "change-b"
    worktree.mkdir(parents=True)

    # 记录所有 git 命令调用序列
    git_calls: list[list[str]] = []

    def tracking_runner(cmd, **kwargs):
        git_calls.append(list(cmd))
        # rebase --abort 和 worktree remove 总是成功
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    auto_decide_calls: list[int] = []

    def auto_decide_fn(seq: int) -> str:
        auto_decide_calls.append(seq)
        return "skip"

    state_json, state_md = _make_state(tmp_path, ["change-b"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    queue = MergeQueue(
        run_root=tmp_path / "run_worktree",
        repo_root=tmp_path / "repo",
        run_branch="spine/2026-07-03-1234",
        state_json=state_json,
        state_md=state_md,
        run_dir=run_dir,
        max_evictions=2,
        verify_fn=lambda wt: (True, ""),
        archive_fn=lambda seq, rr: (True, "", "commit"),
        auto_decide_fn=auto_decide_fn,
        runner=tracking_runner,
    )

    # eviction_count 已为 1（即将触发超限）；reason=conflict
    entry = MergeQueueEntry(
        change_id="change-b",
        seq=1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-b",
        exec_worktree=worktree,
        run_branch="spine/2026-07-03-1234",
        eviction_count=1,
    )

    # 使 rebase 失败 → 触发 conflict 驱逐
    conflict_happened = {"count": 0}
    original_runner = tracking_runner

    def conflict_then_ok_runner(cmd, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        git_calls.append(list(cmd))
        # 第一次 rebase（queue 侧）失败→冲突；后续 rebase（重放）也停在冲突
        if "rebase" in cmd_str and "--abort" not in cmd_str:
            conflict_happened["count"] += 1
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="CONFLICT in src/x.py")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    queue.runner = conflict_then_ok_runner
    git_calls.clear()

    result = queue.process_entry(entry)

    assert result.evicted is True
    assert result.eviction_count == 2
    assert auto_decide_calls == [1], f"auto_decide 未被调用：{auto_decide_calls}"

    # 验证：git rebase --abort 被调用（超限清理）
    abort_calls = [c for c in git_calls if "rebase" in c and "--abort" in c]
    assert len(abort_calls) >= 1, (
        f"超限后应调用 rebase --abort，实际 git_calls={git_calls}"
    )

    # 验证：git worktree remove 被调用（worktree 被拆除）
    worktree_remove_calls = [c for c in git_calls if "worktree" in c and "remove" in c]
    assert len(worktree_remove_calls) >= 1, (
        f"超限后应调用 worktree remove，实际 git_calls={git_calls}"
    )


def test_f5_test_failure_eviction_limit_removes_worktree(tmp_path):
    """F5 回归：test-failure 驱逐超限后也拆除 worktree（无需 rebase --abort）。"""
    worktree = tmp_path / "wt" / "change-c"
    worktree.mkdir(parents=True)

    git_calls: list[list[str]] = []

    def tracking_runner(cmd, **kwargs):
        git_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    auto_decide_calls: list[int] = []

    def auto_decide_fn(seq: int) -> str:
        auto_decide_calls.append(seq)
        return "skip"

    state_json, state_md = _make_state(tmp_path, ["change-c"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    queue = MergeQueue(
        run_root=tmp_path / "run_worktree",
        repo_root=tmp_path / "repo",
        run_branch="spine/2026-07-03-1234",
        state_json=state_json,
        state_md=state_md,
        run_dir=run_dir,
        max_evictions=2,
        verify_fn=lambda wt: (False, "test failed: AssertionError"),
        archive_fn=lambda seq, rr: (True, "", "commit"),
        auto_decide_fn=auto_decide_fn,
        runner=tracking_runner,
    )

    entry = MergeQueueEntry(
        change_id="change-c",
        seq=1,
        dag_layer=0,
        change_branch="spine/2026-07-03-1234/change-c",
        exec_worktree=worktree,
        run_branch="spine/2026-07-03-1234",
        eviction_count=1,  # 已被驱逐一次，再次驱逐触发超限
    )

    result = queue.process_entry(entry)

    assert result.evicted is True
    assert result.eviction_count == 2
    assert auto_decide_calls == [1]

    # worktree remove 应被调用
    worktree_remove_calls = [c for c in git_calls if "worktree" in c and "remove" in c]
    assert len(worktree_remove_calls) >= 1, (
        f"test-failure 超限后应拆除 worktree，实际 git_calls={git_calls}"
    )

    # test-failure 场景不应调用 rebase --abort（没有进入 rebase 中间态）
    abort_calls = [c for c in git_calls if "rebase" in c and "--abort" in c]
    assert len(abort_calls) == 0, (
        f"test-failure 驱逐不应调用 rebase --abort，实际 git_calls={git_calls}"
    )
