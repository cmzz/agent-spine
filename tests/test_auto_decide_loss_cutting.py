"""回归测试：auto-decide-loss-cutting

覆盖以下 spec 场景：
- 同一 trigger 连续 3 次 → abort（任务 3.1）
- skipped-auto 比例超阈值 → abort（任务 3.2）
- 未达阈值 → 原有 skip/retry 语义不变（任务 3.3）
- archive-failed 二次触发收敛到 skip（任务 3.4）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc import auto_decide as _ad


# ── 辅助：构造 progress entry ──────────────────────────────────────────

def _entry(
    *,
    status: str = "needs-user-decision",
    reason: str | None = None,
    last_trigger: str | None = None,
    blocking_trend: list | None = None,
    categories_seen: list | None = None,
    retries: dict | None = None,
) -> dict:
    """retries: {trigger: count} — 例如 {"implementer-failed": 1}，键名含连字符。"""
    e: dict = {"status": status}
    if reason is not None:
        e["reason"] = reason
    if last_trigger is not None:
        e["last_trigger"] = last_trigger
    if blocking_trend is not None:
        e["blocking_trend"] = blocking_trend
    if categories_seen is not None:
        e["categories_seen"] = categories_seen
    if retries:
        for trigger, count in retries.items():
            key = f"auto_retry_{trigger}"  # e.g. auto_retry_implementer-failed
            if count:
                e[key] = count
    return e


# ── _is_systemic_block 单元测试 ───────────────────────────────────────

class TestIsSystemicBlock:
    def test_consecutive_trigger_below_threshold(self):
        """前序只有 1 次同 trigger（+current=2，< 3）不触发 abort。"""
        progress = [
            _entry(reason="implementer-failed-after-auto-retry", last_trigger="implementer-failed"),
            _entry(status="pending"),
        ]
        # current trigger 算 1，加上 1 个前序 = 2 < 3
        assert not _ad._is_systemic_block(progress, "implementer-failed")

    def test_consecutive_trigger_at_threshold(self):
        """前序已有 2 次 + current = 3 次 → 触发 abort。"""
        progress = [
            _entry(reason="implementer-failed-after-auto-retry", last_trigger="implementer-failed"),
            _entry(reason="implementer-failed-after-auto-retry", last_trigger="implementer-failed"),
            _entry(status="needs-user-decision"),  # 当前 entry，last_trigger 尚未记录
        ]
        assert _ad._is_systemic_block(progress, "implementer-failed")

    def test_consecutive_broken_by_different_trigger(self):
        """中间出现不同 trigger，连续链断开，末尾 1 个 + current = 2 < 3，不触发。"""
        progress = [
            _entry(reason="implementer-failed-after-auto-retry", last_trigger="implementer-failed"),
            _entry(reason="fixer-failed-after-auto-retry", last_trigger="fixer-failed"),
            _entry(reason="implementer-failed-after-auto-retry", last_trigger="implementer-failed"),
            _entry(status="needs-user-decision"),  # 当前 entry
        ]
        # 末尾连续 implementer-failed：1 前序 + 1 current = 2 < 3
        assert not _ad._is_systemic_block(progress, "implementer-failed")

    def test_skip_ratio_below_threshold(self):
        """skipped-auto 占比 33%（< 50%）且数量 < 3 → 不触发。"""
        progress = [
            _entry(status="skipped-auto"),
            _entry(status="archived"),
            _entry(status="archived"),
        ]
        assert not _ad._is_systemic_block(progress, "stale")

    def test_skip_ratio_at_threshold_but_below_min_count(self):
        """占比 50% 但绝对数量 < 3 → 不触发。"""
        progress = [
            _entry(status="skipped-auto"),
            _entry(status="skipped-auto"),
            _entry(status="archived"),
            _entry(status="archived"),
        ]
        assert not _ad._is_systemic_block(progress, "stale")

    def test_skip_ratio_triggers_abort(self):
        """skipped-auto 占比 ≥ 50% 且数量 ≥ 3 → 触发 abort。"""
        progress = [
            _entry(status="skipped-auto"),
            _entry(status="skipped-auto"),
            _entry(status="skipped-auto"),
            _entry(status="archived"),
            _entry(status="archived"),
            _entry(status="archived"),
        ]
        assert _ad._is_systemic_block(progress, "stale")

    def test_empty_progress(self):
        assert not _ad._is_systemic_block([], "stale")


# ── _decide 集成测试：abort 可达 ──────────────────────────────────────

class TestDecideAbortReachable:
    """任务 3.1：同一 trigger 连续 3 次 → _decide 返回 abort。"""

    def _make_progress_with_consecutive(self, trigger: str, count: int) -> list[dict]:
        return [
            _entry(reason=f"{trigger}-after-auto-retry", last_trigger=trigger)
            for _ in range(count)
        ]

    def test_abort_on_three_consecutive_implementer_failed(self):
        progress = self._make_progress_with_consecutive("implementer-failed", 3)
        current_entry = _entry(status="needs-user-decision")
        result = _ad._decide(current_entry, "implementer-failed", progress)
        assert result["action"] == "abort"
        assert result["reason"] == "systemic-failure"
        assert result.get("set_aborted") is True

    def test_abort_on_three_consecutive_fixer_failed(self):
        progress = self._make_progress_with_consecutive("fixer-failed", 3)
        current_entry = _entry(status="needs-user-decision")
        result = _ad._decide(current_entry, "fixer-failed", progress)
        assert result["action"] == "abort"

    def test_no_abort_below_threshold(self):
        """任务 3.3：未达阈值时不误触 abort（前序 1 次 + current = 2 < 3）。"""
        progress = self._make_progress_with_consecutive("implementer-failed", 1)
        current_entry = _entry()
        result = _ad._decide(current_entry, "implementer-failed", progress)
        # 未达阈值，走 continue-retry（第一次 auto-retry）
        assert result["action"] == "continue-retry"

    def test_no_abort_without_progress(self):
        """无 progress 传入时退化为单 change 决策。"""
        entry = _entry()
        result = _ad._decide(entry, "implementer-failed", [])
        assert result["action"] == "continue-retry"


class TestDecideAbortOnSkipRatio:
    """任务 3.2：skip 比例超阈值 → abort。"""

    def _make_progress_heavy_skip(self) -> list[dict]:
        return [
            _entry(status="skipped-auto"),
            _entry(status="skipped-auto"),
            _entry(status="skipped-auto"),
            _entry(status="archived"),
            _entry(status="archived"),
            _entry(status="archived"),
        ]

    def test_abort_on_skip_ratio(self):
        progress = self._make_progress_heavy_skip()
        entry = _entry()
        result = _ad._decide(entry, "stale", progress)
        assert result["action"] == "abort"
        assert result["reason"] == "systemic-failure"

    def test_abort_on_skip_ratio_with_implementer_trigger(self):
        progress = self._make_progress_heavy_skip()
        entry = _entry()
        result = _ad._decide(entry, "implementer-failed", progress)
        assert result["action"] == "abort"


class TestDecideOriginalSemanticsPreserved:
    """任务 3.3：未达阈值时保留既有语义。"""

    def test_first_retry(self):
        entry = _entry()
        result = _ad._decide(entry, "implementer-failed", [])
        assert result["action"] == "continue-retry"
        assert result.get("increment_retry_key") == "auto_retry_implementer-failed"

    def test_skip_after_retry(self):
        entry = _entry(retries={"implementer-failed": 1})
        result = _ad._decide(entry, "implementer-failed", [])
        assert result["action"] == "skip"
        assert result["set_status"] == "skipped-auto"

    def test_stale_force_archive_when_acceptable(self):
        entry = _entry(blocking_trend=[2, 1, 2])
        result = _ad._decide(entry, "stale", [])
        assert result["action"] == "force-archive"

    def test_stale_skip_when_oversized(self):
        entry = _entry(blocking_trend=[5, 4, 3])
        result = _ad._decide(entry, "stale", [])
        assert result["action"] == "skip"

    def test_codex_failed_always_skip(self):
        entry = _entry()
        result = _ad._decide(entry, "codex-failed", [])
        assert result["action"] == "skip"
        assert result["reason"] == "codex-failed-after-internal-retry"

    def test_agent_timeout_skip(self):
        entry = _entry()
        result = _ad._decide(entry, "agent-timeout-exhausted", [])
        assert result["action"] == "skip"


class TestArchiveFailedSecondaryDecision:
    """任务 3.4：archive-failed 二次触发收敛到 skip，不再 force-archive 死循环。"""

    def test_archive_failed_first_time_retries(self):
        """第一次 archive-failed → continue-retry（给一次机会）。"""
        entry = _entry()
        result = _ad._decide(entry, "archive-failed", [])
        assert result["action"] == "continue-retry"

    def test_archive_failed_second_time_skips(self):
        """第二次 archive-failed（已 retry 过一次）→ skip，是终态。"""
        entry = _entry(retries={"archive-failed": 1})
        result = _ad._decide(entry, "archive-failed", [])
        assert result["action"] == "skip"
        assert result["set_status"] == "skipped-auto"

    def test_archive_failed_skip_is_terminal_state(self):
        """skip 状态是 finalize 接受的终态，不触发 incomplete 错误。"""
        # 验证 set_status 的值是 finalize 接受的状态之一
        from npc.state import VALID_PROGRESS_STATUS
        entry = _entry(retries={"archive-failed": 1})
        result = _ad._decide(entry, "archive-failed", [])
        assert result["set_status"] in VALID_PROGRESS_STATUS

    def test_archive_failed_not_subject_to_systemic_abort(self):
        """archive-failed 不触发系统性 abort（防止 force-archive 兜底路径被误中断）。"""
        # 即使有大量 skipped-auto，archive-failed 也不被 systemic check 拦截
        heavy_skip = [_entry(status="skipped-auto") for _ in range(6)] + [
            _entry(status="archived"),
            _entry(status="archived"),
        ]
        entry = _entry()
        result = _ad._decide(entry, "archive-failed", heavy_skip)
        # 应走正常的 continue-retry，而非 abort
        assert result["action"] == "continue-retry"

    def test_stale_force_archive_then_archive_failed_converges_to_skip(self):
        """端到端路径：stale → force-archive（--apply）→ archive-failed → 必须收敛为终态 skip。

        这是 F1 修复的核心回归：--apply 后 last_trigger="stale" 写入 entry；
        下一次 archive-failed 触发时检测到 last_trigger 为 stale，直接返回 skip
        而非 continue-retry，防止死循环。
        """
        # 模拟 stale → force-archive --apply 后的 entry 状态：
        # last_trigger 被写为 "stale"，无 auto_retry_archive-failed 计数
        entry_after_force_archive = _entry(
            blocking_trend=[2, 1, 2],
            last_trigger="stale",
        )
        result = _ad._decide(entry_after_force_archive, "archive-failed", [])
        assert result["action"] == "skip", (
            f"stale→force-archive→archive-failed 应收敛为 skip，实际得到 {result['action']}"
        )
        assert result["set_status"] == "skipped-auto"
        assert result["reason"] == "archive-failed-after-force-archive"

    def test_max_rounds_force_archive_then_archive_failed_converges_to_skip(self):
        """max-rounds → force-archive（--apply）→ archive-failed 同样应收敛为终态 skip。"""
        entry_after_force_archive = _entry(
            blocking_trend=[1, 1, 1],
            last_trigger="max-rounds",
        )
        result = _ad._decide(entry_after_force_archive, "archive-failed", [])
        assert result["action"] == "skip"
        assert result["set_status"] == "skipped-auto"
        assert result["reason"] == "archive-failed-after-force-archive"

    def test_archive_failed_without_force_archive_still_retries(self):
        """没有 force-archive 前置（last_trigger 不是 stale/max-rounds）→ 保留 continue-retry 语义。"""
        # 前一个触发是 implementer-failed，不是 stale/max-rounds
        entry = _entry(last_trigger="implementer-failed")
        result = _ad._decide(entry, "archive-failed", [])
        assert result["action"] == "continue-retry", (
            "非 force-archive 路径下首次 archive-failed 应仍给 continue-retry 机会"
        )


# ── CLI --apply 集成测试 ──────────────────────────────────────────────

class TestCliApplyAbort:
    """验证 --apply 时 abort 决策写入 state.aborted=True 且 last_trigger 被记录。"""

    @pytest.fixture
    def state_files(self, tmp_path: Path):
        """构造临时 state.json + state.md 和三条 progress 记录（前两条已触发同 trigger）。"""
        state = {
            "schema_version": 2,
            "status": "in-progress",
            "plan_order": ["change-a", "change-b", "change-c"],
            "progress": [
                {
                    "change_id": "change-a",
                    "status": "skipped-auto",
                    "reason": "implementer-failed-after-auto-retry",
                    "last_trigger": "implementer-failed",
                },
                {
                    "change_id": "change-b",
                    "status": "skipped-auto",
                    "reason": "implementer-failed-after-auto-retry",
                    "last_trigger": "implementer-failed",
                },
                {
                    "change_id": "change-c",
                    "status": "needs-user-decision",
                },
            ],
        }
        state_json = tmp_path / "state.json"
        state_md = tmp_path / "state.md"
        state_json.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        state_md.write_text("")
        return state_json, state_md

    def test_apply_abort_sets_top_level_aborted(self, state_files, monkeypatch, env_setup):
        """当第三次同 trigger 触发 abort 且 --apply 时，state.aborted 被置为 True。"""
        import argparse
        from npc import auto_decide as ad, paths as _paths

        state_json, state_md = state_files
        # 通过环境变量注入 state 路径（env fallback 路径，优先于 active.json 发现）
        monkeypatch.setenv("NPC_STATE_JSON", str(state_json))
        monkeypatch.setenv("NPC_STATE_MD", str(state_md))
        monkeypatch.setattr(_paths, "read_active", lambda *_a, **_kw: None)

        args = argparse.Namespace(
            state_json=None,
            run_ts=None,
            task_log_dir=None,
            seq=3,
            trigger="implementer-failed",
            apply=True,
        )

        output: list[dict] = []

        def fake_emit(data: dict) -> None:
            output.append(data)

        monkeypatch.setattr("npc._io.emit", fake_emit)

        ad.cli(args)

        assert output, "cli 没有 emit 任何输出"
        result = output[0]
        assert result["action"] == "abort", f"expected abort, got {result['action']}"
        assert result["applied"] is True

        # 验证 state.json 被更新
        state_after = json.loads(state_json.read_text())
        assert state_after.get("aborted") is True, "state.aborted 未被设置为 True"
        # 验证 last_trigger 被记录
        entry3 = state_after["progress"][2]
        assert entry3.get("last_trigger") == "implementer-failed"


# ── F2 round-4 回归：merge-evicted 绕过系统性 abort ─────────────────

class TestMergeEvictedAlwaysSkips:
    """F2 round-4 回归：merge-evicted 触发 _decide 时始终返回 skip，
    不受系统性 abort 拦截，即使已有大量 skipped-auto 或连续 merge-evicted 记录。

    spec 契约：merge-queue-eviction spec 要求 merge-evicted 默认 action=skip，
    写 skipped-auto / skipped_reason=merge-evicted，不阻塞层屏障。
    """

    def test_merge_evicted_returns_skip_without_progress(self):
        """无 progress 时 merge-evicted 仍返回 skip。"""
        entry = _entry()
        result = _ad._decide(entry, "merge-evicted", [])
        assert result["action"] == "skip"
        assert result["set_status"] == "skipped-auto"
        assert result.get("skipped_reason") == "merge-evicted"

    def test_merge_evicted_returns_skip_with_high_skip_ratio(self):
        """即使 skipped-auto 占比已超 systemic 阈值，merge-evicted 仍返回 skip（不 abort）。"""
        heavy_skip = [_entry(status="skipped-auto") for _ in range(6)] + [
            _entry(status="archived"),
            _entry(status="archived"),
        ]
        entry = _entry()
        result = _ad._decide(entry, "merge-evicted", heavy_skip)
        assert result["action"] == "skip", (
            f"merge-evicted must skip even with high skip ratio, got {result['action']}"
        )
        assert result.get("skipped_reason") == "merge-evicted"
        assert result.get("set_aborted") is not True

    def test_merge_evicted_returns_skip_with_consecutive_merge_evicted(self):
        """连续多个 merge-evicted 记录（达到或超过 systemic 阈值）时仍返回 skip，不 abort。

        这是 F2 的核心回归：前序已有 3 个 merge-evicted last_trigger 记录，
        按旧逻辑 _is_systemic_block 会计为 consecutive=4 ≥ 3 → abort；
        修复后 merge-evicted 分支在 systemic check 前返回。
        """
        # 3 条前序 merge-evicted 记录（连续，即系统性检测会触发 abort）
        consecutive_evicted = [
            _entry(last_trigger="merge-evicted") for _ in range(3)
        ]
        entry = _entry()
        result = _ad._decide(entry, "merge-evicted", consecutive_evicted)
        assert result["action"] == "skip", (
            f"merge-evicted must always skip, even after 3 consecutive; got {result['action']}"
        )
        assert result["set_status"] == "skipped-auto"
        assert result.get("skipped_reason") == "merge-evicted"
        assert result.get("set_aborted") is not True

    def test_merge_evicted_skip_reason_is_correct(self):
        """确认 skipped_reason 字段精确值为 'merge-evicted'（供 apply 写入 state）。"""
        entry = _entry()
        result = _ad._decide(entry, "merge-evicted")
        assert result.get("skipped_reason") == "merge-evicted"
        assert result["reason"] == "merge-evicted-limit-exceeded"
