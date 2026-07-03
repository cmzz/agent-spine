"""merge_queue.py — 并行层 merge queue：rebase → 复测 → ff-merge → archive → 拆 worktree。

设计约束（来自 design.md D3）：
- 队列 MUST 串行处理（同一时刻至多一个 change 在合回/archive）
- archive MUST 在合回后的队列串行段执行（openspec/ 树是共享写）
- rebase 冲突或复测失败 → 驱逐 → 在 per-change worktree 中重放 rebase 保留冲突标记
- 驱逐超限 → npc auto-decide --trigger merge-evicted（默认 skip）
- 全程不触碰主 checkout

公开接口：
- ``MergeQueueEntry``：队列条目
- ``MergeQueue``：串行合并队列
- ``build_eviction_context``：构造结构化 eviction 文件内容
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import _io
from . import git_ops as _git_ops
from . import state as _state
from . import telemetry as _telemetry


# ── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class MergeQueueEntry:
    """待合回的 change 描述。"""

    change_id: str
    seq: int
    dag_layer: int
    change_branch: str       # spine/<run_ts>/<change_id>
    exec_worktree: Path      # per-change worktree 路径
    run_branch: str          # spine/<run_ts>（run 分支）
    eviction_count: int = 0


@dataclass
class MergeResult:
    """单次合回结果。"""

    change_id: str
    success: bool
    evicted: bool = False
    eviction_reason: str = ""  # "conflict" | "test-failure"
    eviction_count: int = 0
    archive_commit: str | None = None
    error: str = ""


# ── 辅助：git 操作 ──────────────────────────────────────────────────────────


def _git_run(
    args: list[str],
    cwd: Path,
    runner: Callable = subprocess.run,
    check: bool = False,
) -> subprocess.CompletedProcess:
    return runner(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        **({"check": check} if check else {}),
    )


def _rebase_onto(
    worktree: Path,
    target_branch: str,
    runner: Callable = subprocess.run,
) -> tuple[bool, str]:
    """在 worktree 中执行 git rebase <target_branch>。返回 (success, stderr)。"""
    proc = _git_run(["rebase", target_branch], cwd=worktree, runner=runner)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _rebase_abort(
    worktree: Path,
    runner: Callable = subprocess.run,
) -> None:
    """git rebase --abort（忽略失败，已在 abort 状态直接 OK）。"""
    _git_run(["rebase", "--abort"], cwd=worktree, runner=runner)


def _ff_merge(
    run_root: Path,
    change_branch: str,
    runner: Callable = subprocess.run,
) -> tuple[bool, str]:
    """在 run_root（run worktree）执行 git merge --ff-only <change_branch>。"""
    proc = _git_run(["merge", "--ff-only", change_branch], cwd=run_root, runner=runner)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _conflict_diff(worktree: Path, runner: Callable = subprocess.run) -> str:
    """取当前 rebase 冲突的 diff 文本（最多 8000 字节）。"""
    proc = _git_run(["diff", "--diff-filter=U"], cwd=worktree, runner=runner)
    diff_text = (proc.stdout or "").strip()
    return diff_text[:8000] if diff_text else ""


def _conflicted_files(worktree: Path, runner: Callable = subprocess.run) -> list[str]:
    """返回当前冲突文件列表。"""
    proc = _git_run(
        ["diff", "--name-only", "--diff-filter=U"],
        cwd=worktree,
        runner=runner,
    )
    return [f for f in (proc.stdout or "").splitlines() if f.strip()]


def _worktree_remove(
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    runner: Callable = subprocess.run,
) -> None:
    """移除 worktree 并删除对应分支（尽力完成，失败静默）。"""
    try:
        proc = _git_run(
            ["worktree", "remove", "--force", str(worktree_path)],
            cwd=repo_root,
            runner=runner,
        )
    except Exception:
        pass
    try:
        _git_run(["branch", "-D", branch], cwd=repo_root, runner=runner)
    except Exception:
        pass


# ── eviction 文件 ─────────────────────────────────────────────────────────


def build_eviction_context(
    entry: MergeQueueEntry,
    reason: str,
    conflict_files: list[str],
    conflict_diff: str,
    test_output: str = "",
) -> dict:
    """构造结构化 eviction 上下文（写入 per-change run 目录供 fix prompt 注入）。"""
    return {
        "change_id": entry.change_id,
        "seq": entry.seq,
        "dag_layer": entry.dag_layer,
        "eviction_count": entry.eviction_count,
        "reason": reason,
        "conflict_files": conflict_files,
        "conflict_diff": conflict_diff,
        "test_output": test_output[:4000] if test_output else "",
        "instructions": (
            "你的 working tree 中已有 rebase 停在冲突处（保留冲突标记）。"
            "请：① 解决所有冲突标记（<<<< ==== >>>>）；"
            "② git add 已解决的文件；"
            "③ git rebase --continue 完成 rebase。"
            "MUST NOT 自行发起新的 rebase/reset。"
        )
        if reason == "conflict"
        else (
            "rebase 成功但测试失败。请修复测试失败后重新提交（当前 worktree 已完成 rebase）。"
        ),
    }


def write_eviction_file(
    run_dir: Path,
    change_id: str,
    context: dict,
) -> Path:
    """将 eviction context 写入 run_dir/<change_id>.eviction.json，返回路径。"""
    eviction_file = run_dir / f"{change_id}.eviction.json"
    eviction_file.write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return eviction_file


# ── MergeQueue ────────────────────────────────────────────────────────────


class MergeQueue:
    """串行 merge queue：逐个处理层内收敛的 change。

    参数：
    - ``run_root``：run worktree 路径（spine/<run_ts>）
    - ``repo_root``：主 checkout 路径（用于拆 worktree/删分支）
    - ``run_branch``：run 分支名（spine/<run_ts>）
    - ``state_json`` / ``state_md``：state 文件路径
    - ``run_dir``：run 目录（写 eviction 文件用）
    - ``max_evictions``：驱逐次数上限
    - ``verify_fn``：复测函数，签名 (worktree: Path) -> (bool, str)；返回 (passed, output)
    - ``archive_fn``：archive 函数，签名 (seq: int, run_root: Path) -> (bool, str, commit)
    - ``auto_decide_fn``：auto-decide 函数，签名 (seq: int) -> str（action）
    - ``runner``：可注入的 subprocess.run（测试用）
    """

    def __init__(
        self,
        *,
        run_root: Path,
        repo_root: Path,
        run_branch: str,
        state_json: Path,
        state_md: Path,
        run_dir: Path,
        max_evictions: int = 2,
        verify_fn: Callable[[Path], tuple[bool, str]] | None = None,
        archive_fn: Callable[[int, Path], tuple[bool, str, str | None]] | None = None,
        auto_decide_fn: Callable[[int], str] | None = None,
        runner: Callable = subprocess.run,
        proj_key: str = "",
        run_ts: str = "",
    ) -> None:
        self.run_root = run_root
        self.repo_root = repo_root
        self.run_branch = run_branch
        self.state_json = state_json
        self.state_md = state_md
        self.run_dir = run_dir
        self.max_evictions = max_evictions
        self.verify_fn = verify_fn or self._default_verify
        self.archive_fn = archive_fn or self._default_archive
        self.auto_decide_fn = auto_decide_fn or self._default_auto_decide
        self.runner = runner
        self.proj_key = proj_key
        self.run_ts = run_ts

    def _default_verify(self, worktree: Path) -> tuple[bool, str]:
        """默认复测：调 npc verify tests（需在 worktree 内）。"""
        try:
            proc = subprocess.run(
                ["npc", "verify", "tests"],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                timeout=300,
            )
            return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:
            return False, str(e)

    def _default_archive(
        self, seq: int, run_root: Path
    ) -> tuple[bool, str, str | None]:
        """默认 archive：调 npc archive run --seq N。"""
        try:
            proc = subprocess.run(
                ["npc", "archive", "run", "--seq", str(seq)],
                cwd=str(run_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                try:
                    out = json.loads(proc.stdout or "")
                    commit = out.get("archive_commit")
                except Exception:
                    commit = None
                return True, "", commit
            return False, (proc.stderr or proc.stdout or "").strip(), None
        except Exception as e:
            return False, str(e), None

    def _default_auto_decide(self, seq: int) -> str:
        """默认 auto-decide：调 npc auto-decide --seq N --trigger merge-evicted --apply。"""
        try:
            proc = subprocess.run(
                ["npc", "auto-decide", "--seq", str(seq), "--trigger", "merge-evicted", "--apply"],
                cwd=str(self.run_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = json.loads(proc.stdout or "{}")
            return out.get("action", "skip")
        except Exception:
            return "skip"

    def _emit_telemetry(self, kind: str, entry: MergeQueueEntry, **extra: object) -> None:
        """best-effort telemetry emit。"""
        try:
            _telemetry.emit_event({
                "kind": kind,
                "proj_key": self.proj_key,
                "run_ts": self.run_ts,
                "change_id": entry.change_id,
                "change_seq": entry.seq,
                "dag_layer": entry.dag_layer,
                "eviction_count": entry.eviction_count,
                **extra,
            })
        except Exception:
            pass

    def process_entry(self, entry: MergeQueueEntry) -> MergeResult:
        """处理单个 queue entry：rebase → 复测 → ff-merge → archive → 拆 worktree。

        失败时驱逐并在 per-change worktree 中重放 rebase（保留冲突标记）。
        """
        self._emit_telemetry("merge_enqueued", entry)

        # 更新 merge_status = queued
        try:
            _state.set_parallel_fields(
                self.state_json, self.state_md,
                entry.seq, merge_status="queued",
            )
        except Exception:
            pass

        # 1. rebase 到 run 分支 HEAD
        ok, err = _rebase_onto(entry.exec_worktree, self.run_branch, runner=self.runner)
        if not ok:
            return self._evict(entry, "conflict", conflict_err=err)

        # 2. 复测
        test_ok, test_output = self.verify_fn(entry.exec_worktree)
        if not test_ok:
            # rebase 已成功，复测失败 → 不需 abort rebase，直接驱逐
            return self._evict(entry, "test-failure", test_output=test_output)

        # 3. ff-merge 到 run 分支
        ff_ok, ff_err = _ff_merge(self.run_root, entry.change_branch, runner=self.runner)
        if not ff_ok:
            # ff 失败不应发生（rebase 已 ok），作为保险驱逐
            _rebase_abort(entry.exec_worktree, runner=self.runner)
            return self._evict(entry, "conflict", conflict_err=f"ff-merge failed: {ff_err}")

        # 4. 更新 merge_status = merged
        try:
            _state.set_parallel_fields(
                self.state_json, self.state_md,
                entry.seq, merge_status="merged",
            )
        except Exception:
            pass

        # 5. archive（在 run 分支上串行执行）
        arc_ok, arc_err, arc_commit = self.archive_fn(entry.seq, self.run_root)
        if not arc_ok:
            # archive 失败：记录但不驱逐（保留 merged 状态，上层判断）
            self._emit_telemetry("merge_done", entry, archive_ok=False, error=arc_err)
            return MergeResult(
                change_id=entry.change_id,
                success=False,
                error=f"archive failed: {arc_err}",
                eviction_count=entry.eviction_count,
            )

        # 6. 拆 per-change worktree
        _worktree_remove(self.repo_root, entry.exec_worktree, entry.change_branch, runner=self.runner)

        self._emit_telemetry("merge_done", entry, archive_ok=True, archive_commit=arc_commit)
        return MergeResult(
            change_id=entry.change_id,
            success=True,
            archive_commit=arc_commit,
            eviction_count=entry.eviction_count,
        )

    def _evict(
        self,
        entry: MergeQueueEntry,
        reason: str,
        *,
        conflict_err: str = "",
        test_output: str = "",
    ) -> MergeResult:
        """驱逐：abort queue 侧 rebase（若适用），在 per-change worktree 重放，写 eviction 文件。"""
        # abort 当前 rebase（只有 conflict 场景才可能在 rebase 中间态）
        if reason == "conflict":
            _rebase_abort(entry.exec_worktree, runner=self.runner)
            # 在 per-change worktree 重放 rebase（停在冲突处）
            _rebase_onto(entry.exec_worktree, self.run_branch, runner=self.runner)
            conflict_files = _conflicted_files(entry.exec_worktree, runner=self.runner)
            diff_text = _conflict_diff(entry.exec_worktree, runner=self.runner)
        else:
            conflict_files = []
            diff_text = ""

        new_eviction_count = entry.eviction_count + 1
        context = build_eviction_context(
            entry,
            reason=reason,
            conflict_files=conflict_files,
            conflict_diff=diff_text,
            test_output=test_output,
        )
        context["eviction_count"] = new_eviction_count

        # 写 eviction 文件（供 fix prompt 注入）
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            write_eviction_file(self.run_dir, entry.change_id, context)
        except Exception:
            pass

        # 更新 state
        try:
            _state.set_parallel_fields(
                self.state_json, self.state_md,
                entry.seq,
                merge_status="evicted",
                eviction_count=new_eviction_count,
            )
        except Exception:
            pass

        self._emit_telemetry(
            "merge_evicted", entry,
            reason=reason,
            eviction_count=new_eviction_count,
        )

        # 判断是否超限
        if new_eviction_count >= self.max_evictions:
            self._emit_telemetry("merge_evict_limit", entry, eviction_count=new_eviction_count)
            # 调 auto-decide
            action = self.auto_decide_fn(entry.seq)
            # auto-decide 已 apply（在 _default_auto_decide 中），无需再改 state
            return MergeResult(
                change_id=entry.change_id,
                success=False,
                evicted=True,
                eviction_reason=reason,
                eviction_count=new_eviction_count,
                error=f"eviction-limit-exceeded ({reason})",
            )

        return MergeResult(
            change_id=entry.change_id,
            success=False,
            evicted=True,
            eviction_reason=reason,
            eviction_count=new_eviction_count,
            error=f"evicted-{reason}",
        )

    def process_all(self, entries: list[MergeQueueEntry]) -> list[MergeResult]:
        """逐个处理 queue entries（串行），返回所有结果。"""
        results: list[MergeResult] = []
        for entry in entries:
            result = self.process_entry(entry)
            results.append(result)
        return results
