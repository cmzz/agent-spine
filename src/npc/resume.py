"""续跑断点判定。

启动时扫 $NPC_TASK_LOG_DIR/*-plan-state.json 找 status=in-progress 最新一份，
然后扫该 state 的 progress[].phases 找第一个非 archived change 的断点 phase。

断点 phase 规则（schema_version=2）：
- 无 phases → implement
- phases.implement.status != done → implement
- 取最大编号 N 的 review-rN / fix-rN：
  · review-rN.status != done → review-rN
  · fix-rN.status != done → fix-rN
  · review-rN.status == done 且 blocking>0 → fix-r(N+1)
  · review-rN.status == done 且 blocking==0 → archive
- phases.archive.status != done → archive
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from . import _io, paths as _paths, state as _state
from . import owner as _owner


def find_latest_in_progress(task_log_dir: Path) -> Path | None:
    """扫 *-plan-state.json，按 mtime 返回 status=in-progress 的最新一份。"""
    if not task_log_dir.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for p in task_log_dir.glob("*-plan-state.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "in-progress":
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def find_latest_initializing(task_log_dir: Path) -> Path | None:
    """扫 *-plan-state.json，按 mtime 返回 status=initializing 的最新一份。

    initializing 为 npc init 在建 worktree 前落盘的意向骨架，
    表示「worktree 可能已建好但 init-run 尚未执行」的中间态。
    """
    if not task_log_dir.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for p in task_log_dir.glob("*-plan-state.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "initializing":
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def find_latest_orphan_skeleton(task_log_dir: Path) -> Path | None:
    """扫 *-plan-state.json，按 mtime 返回 status=orphan 的最新一份。

    orphan 状态由 _mark_initializing_skeleton_orphan() 写入：
    init 发现 worktree 缺失/残破的 initializing 骨架时将其标记为 orphan，
    使 clean 能发现并回收对应 git worktree 元数据和 spine 分支。
    """
    if not task_log_dir.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for p in task_log_dir.glob("*-plan-state.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "orphan":
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _next_phase_for_entry(entry: dict) -> str:
    """根据 progress 条目的 phases 字典推断下一个 phase。"""
    phases = entry.get("phases") or {}
    if not phases:
        return "implement"

    impl = phases.get("implement") or {}
    if impl.get("status") != "done":
        return "implement"

    # 找最大编号的 review-rN / fix-rN
    max_n = -1
    for k in phases.keys():
        m = re.match(r"^(?:review|fix)-r(\d+)$", k)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n

    if max_n < 0:
        # 只有 implement done 但没进过 review，下一步 review-r0
        return "review-r0"

    review_key = f"review-r{max_n}"
    fix_key = f"fix-r{max_n}"
    review = phases.get(review_key)
    fix = phases.get(fix_key)

    # 先看 review-rN 是否完成
    if review is not None and review.get("status") != "done":
        return review_key
    if fix is not None and fix.get("status") != "done":
        return fix_key

    # review-rN 已 done：根据 blocking 决定下一步
    if review is not None and review.get("status") == "done":
        blocking = review.get("blocking", 0)
        if blocking and blocking > 0:
            return f"fix-r{max_n + 1}"
        # blocking == 0 → archive
        archive = phases.get("archive") or {}
        if archive.get("status") != "done":
            return "archive"

    # fix-rN done 但 review-rN 未启动：进入 review-rN
    if fix is not None and fix.get("status") == "done" and review is None:
        return review_key

    # archive 兜底
    archive = phases.get("archive") or {}
    if archive.get("status") != "done":
        return "archive"
    return "archive"


def _current_round_from_phases(phases: dict) -> int:
    max_n = 0
    for k in phases.keys():
        m = re.match(r"^(?:fix|review)-r(\d+)$", k)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n


TERMINAL_STATUSES = {"archived", "failed", "skipped-auto"}


def _entry_to_parallel_info(entry: dict) -> dict:
    """提取 progress 条目中的并行相关字段（兼容旧 state 无字段）。"""
    phases = entry.get("phases") or {}
    cur_round = _current_round_from_phases(phases)
    next_phase = _next_phase_for_entry(entry)
    return {
        "change_id": entry.get("change_id"),
        "seq": entry.get("seq"),
        "status": entry.get("status"),
        "merge_status": entry.get("merge_status", "pending"),
        "phase": next_phase,
        "round": cur_round,
        "eviction_count": entry.get("eviction_count", 0),
        "change_branch": entry.get("change_branch"),
        "exec_worktree": entry.get("exec_worktree"),
    }


def _is_parallel_state(progress: list[dict]) -> bool:
    """判断 state 是否含有并行字段（有任一 dag_layer 字段则认为是并行 state）。"""
    return any("dag_layer" in e for e in progress)


def compute_resume(state: dict) -> dict:
    """从 state dict 推断续跑断点。

    并行 state（含 dag_layer 字段）：按层重建断点，找第一个未收敛层。
    旧 state（无 dag_layer）：原线性 seq 游标语义。
    """
    progress = state.get("progress") or []

    # ── 旧 state 向后兼容路径 ──────────────────────────────────────────
    if not _is_parallel_state(progress):
        completed = 0
        next_entry = None
        for entry in progress:
            if entry.get("status") in TERMINAL_STATUSES:
                if entry.get("status") == "archived":
                    completed += 1
            if entry.get("status") not in TERMINAL_STATUSES and next_entry is None:
                next_entry = entry

        # 按原逻辑：找第一个非终态
        completed_archived = sum(1 for e in progress if e.get("status") == "archived")
        next_entry_old = None
        for entry in progress:
            if entry.get("status") == "archived":
                continue
            next_entry_old = entry
            break

        if next_entry_old is None:
            return {
                "needs_resume": False,
                "all_done": True,
                "completed_changes": completed_archived,
                "total_changes": len(progress),
            }

        next_phase = _next_phase_for_entry(next_entry_old)
        phases = next_entry_old.get("phases") or {}
        cur_round = _current_round_from_phases(phases)
        return {
            "needs_resume": True,
            "completed_changes": completed_archived,
            "total_changes": len(progress),
            "next_seq": next_entry_old.get("seq"),
            "next_change_id": next_entry_old.get("change_id"),
            "next_phase": next_phase,
            "current_round": cur_round,
            "blocking_trend": next_entry_old.get("blocking_trend", []),
            "rounds_since_strict_decrease": next_entry_old.get("rounds_since_strict_decrease", 0),
        }

    # ── 并行 state 路径：按层重建断点 ──────────────────────────────────
    # 收集所有层
    layers_map: dict[int, list[dict]] = {}
    for entry in progress:
        layer_idx = entry.get("dag_layer", 0)
        layers_map.setdefault(layer_idx, []).append(entry)

    all_layers = sorted(layers_map.keys())
    completed_archived = sum(1 for e in progress if e.get("status") == "archived")
    total = len(progress)

    for layer_idx in all_layers:
        layer_entries = layers_map[layer_idx]
        # 检查该层是否全部收敛
        non_terminal = [e for e in layer_entries if e.get("status") not in TERMINAL_STATUSES]
        if non_terminal:
            # 找到第一个未收敛层
            blocked = [e.get("change_id") for e in layer_entries if e.get("status") in TERMINAL_STATUSES]
            changes_info = [_entry_to_parallel_info(e) for e in layer_entries]
            return {
                "needs_resume": True,
                "completed_changes": completed_archived,
                "total_changes": total,
                "layer": layer_idx,
                "changes": changes_info,
                "blocked": blocked,
                # 单 change 兼容字段
                "next_seq": non_terminal[0].get("seq"),
                "next_change_id": non_terminal[0].get("change_id"),
                "next_phase": _next_phase_for_entry(non_terminal[0]),
                "current_round": _current_round_from_phases(non_terminal[0].get("phases") or {}),
                "blocking_trend": non_terminal[0].get("blocking_trend", []),
                "rounds_since_strict_decrease": non_terminal[0].get("rounds_since_strict_decrease", 0),
            }

    return {
        "needs_resume": False,
        "all_done": True,
        "completed_changes": completed_archived,
        "total_changes": total,
    }


def detect(args: argparse.Namespace) -> None:
    """resume detect。"""
    state_json_override = getattr(args, "state_json", None)
    if state_json_override:
        state_json = Path(state_json_override)
    else:
        # 优先：args.task_log_dir > cwd → repo_root → task_log_dir > env
        task_log_dir: Path | None = None
        explicit = getattr(args, "task_log_dir", None)
        if explicit:
            task_log_dir = Path(explicit)
        else:
            try:
                repo_root = _paths.detect_repo_root()
                task_log_dir = _paths.task_log_dir_for(repo_root)
            except _paths.PathsError:
                env_dir = os.environ.get("NPC_TASK_LOG_DIR")
                if env_dir:
                    task_log_dir = Path(env_dir)
        if task_log_dir is None:
            _io.emit_error(
                "env_missing",
                "未能定位 task_log_dir；请在 git 仓库内运行，或显式 --task-log-dir。",
                exit_code=3,
            )
            return
        latest = find_latest_in_progress(task_log_dir)
        if latest is None:
            _io.emit(
                {
                    "needs_resume": False,
                    "state_json": None,
                    "message": "没有找到 in-progress 旧 run",
                }
            )
            return
        # owner 存活门槛：owner 仍存活的 in-progress state 不视为可续跑候选
        # （他人活跃 run），诊断消息区别于"没有找到 in-progress 旧 run"。
        try:
            _candidate_state = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _candidate_state = {}
        if isinstance(_candidate_state, dict) and _owner.owner_alive(_candidate_state):
            _io.emit(
                {
                    "needs_resume": False,
                    "state_json": None,
                    "message": "找到 in-progress 记录，但 owner 仍存活（他人 run），不建议接管",
                }
            )
            return
        state_json = latest

    try:
        state = _state.read_state(state_json)
    except (OSError, json.JSONDecodeError) as e:
        _io.emit_error("state_unreadable", f"读取 state 失败：{e}", exit_code=1)
        return

    info = compute_resume(state)
    info["state_json"] = str(state_json)
    info["last_updated_at"] = state.get("last_updated_at")
    _io.emit(info)
