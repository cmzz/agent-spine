"""Tests for in-session coder timeout budget chain (change: in-session-coder-timeout).

Covers:
  3.1 状态链：budget → record-timeout (×N) → exhausted 标志翻转
  3.2 exhausted 后 auto-decide 返回 skip（agent-timeout-exhausted trigger）
  3.3 守卫测试：spine-run.md 含 timeout-budget 调用（skill 契约不回退）
  3.4 回归：fix 阶段同样有预算追踪
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc import agent as _agent
from npc import auto_decide as _auto_decide
from npc import state as _state


# ============================================================
# Bootstrap helpers
# ============================================================


def _bootstrap(env_setup, capsys, make_args, *change_ids: str) -> None:
    sjson = str(env_setup.state_json)
    _state.init_run(make_args(plan_order=json.dumps(list(change_ids)), state_json=sjson))
    capsys.readouterr()
    for i, cid in enumerate(change_ids, start=1):
        _state.add_change(make_args(seq=i, change_id=cid, base=None, state_json=sjson))
        capsys.readouterr()


def _mk(env_setup, make_args, **kwargs):
    return make_args(state_json=str(env_setup.state_json), **kwargs)


def _read_emit(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _set_retries(env_setup, seq: int, phase: str, retries: int) -> None:
    """直接写入 state 的 timeout_retries 字段，模拟多次超时后的状态。"""
    s = json.loads(env_setup.state_json.read_text())
    entry = s["progress"][seq - 1]
    entry.setdefault("phases", {}).setdefault(phase, {})["timeout_retries"] = retries
    env_setup.state_json.write_text(json.dumps(s, indent=2))


# ============================================================
# 3.1  状态链：budget → record-timeout (×N) → exhausted 翻转
# ============================================================


class TestTimeoutStateChain:
    """验证 timeout_retries 从 0 累积到 exhausted 阈值的完整状态链。"""

    def test_initial_budget_not_exhausted(self, env_setup, capsys, make_args):
        """起始 retries=0，budget 返回 1800s，exhausted=False。"""
        _bootstrap(env_setup, capsys, make_args, "cid-chain")
        _agent.timeout_budget(_mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None))
        payload = _read_emit(capsys)
        assert payload["ok"] is True
        assert payload["timeout_sec"] == 1800
        assert payload["retries"] == 0
        assert payload["exhausted"] is False

    def test_record_timeout_once_increments_retries(self, env_setup, capsys, make_args):
        """record-timeout 第 1 次：retries=1，next_timeout_sec=2160，exhausted=False。"""
        _bootstrap(env_setup, capsys, make_args, "cid-chain")
        _agent.record_timeout(
            _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
        )
        payload = _read_emit(capsys)
        assert payload["retries"] == 1
        assert payload["next_timeout_sec"] == 2160  # 1800 * 1.2
        assert payload["exhausted"] is False

    def test_record_timeout_chain_to_exhausted(self, env_setup, capsys, make_args):
        """连续 record-timeout 5 次后 exhausted 标志翻转为 True。"""
        _bootstrap(env_setup, capsys, make_args, "cid-chain")
        for i in range(1, 6):
            _agent.record_timeout(
                _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
            )
            payload = _read_emit(capsys)
            assert payload["retries"] == i
        # retries == 5 → exhausted
        assert payload["exhausted"] is True
        # 最后一次 budget 查询也应显示 exhausted
        _agent.timeout_budget(
            _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
        )
        budget = _read_emit(capsys)
        assert budget["exhausted"] is True

    def test_exhausted_flag_at_threshold_boundary(self, env_setup, capsys, make_args):
        """retries=4（阈值-1）→ 未 exhausted；retries=5（阈值）→ exhausted。"""
        _bootstrap(env_setup, capsys, make_args, "cid-chain")
        # 设置 retries=4（边界前一步）
        _set_retries(env_setup, 1, "implement", 4)
        _agent.timeout_budget(
            _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
        )
        payload = _read_emit(capsys)
        assert payload["exhausted"] is False

        # record-timeout 一次：retries 变为 5，exhausted 翻转
        _agent.record_timeout(
            _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
        )
        payload = _read_emit(capsys)
        assert payload["retries"] == 5
        assert payload["exhausted"] is True

    def test_budget_progression_matches_formula(self, env_setup, capsys, make_args):
        """验证退避公式：budget[n] = min(1800 * 1.2^n, 3600)。"""
        _bootstrap(env_setup, capsys, make_args, "cid-chain")
        expected = [int(min(1800 * (1.2 ** n), 3600)) for n in range(6)]
        for n, exp in enumerate(expected):
            _set_retries(env_setup, 1, "implement", n)
            _agent.timeout_budget(
                _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
            )
            payload = _read_emit(capsys)
            assert payload["timeout_sec"] == exp, f"retries={n}: expected {exp}, got {payload['timeout_sec']}"

    def test_fix_phase_has_independent_budget_tracking(self, env_setup, capsys, make_args):
        """fix-r1 和 implement 各自维护独立的 timeout_retries 计数器。"""
        _bootstrap(env_setup, capsys, make_args, "cid-chain")
        # implement 超时 2 次
        for _ in range(2):
            _agent.record_timeout(
                _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
            )
            capsys.readouterr()

        # fix-r1 初始预算仍应为 1800（独立计数）
        _agent.timeout_budget(
            _mk(env_setup, make_args, seq=1, phase="fix-r1", base=None, mult=None, max_sec=None)
        )
        payload = _read_emit(capsys)
        assert payload["timeout_sec"] == 1800
        assert payload["retries"] == 0
        assert payload["exhausted"] is False


# ============================================================
# 3.2  exhausted → auto-decide 返回 skip
# ============================================================


class TestTimeoutExhaustedAutoDecide:
    """验证预算耗尽后 auto-decide --trigger agent-timeout-exhausted 返回 skip。"""

    def test_agent_timeout_exhausted_trigger_returns_skip(self, env_setup, capsys, make_args):
        """agent-timeout-exhausted trigger → action=skip，set_status=skipped-auto。"""
        sjson = str(env_setup.state_json)
        _state.init_run(make_args(plan_order=json.dumps(["cid-timeout"]), state_json=sjson))
        capsys.readouterr()
        _state.add_change(make_args(seq=1, change_id="cid-timeout", base=None, state_json=sjson))
        capsys.readouterr()

        _auto_decide.cli(
            _mk(env_setup, make_args, seq=1, trigger="agent-timeout-exhausted", apply=False)
        )
        payload = _read_emit(capsys)
        assert payload["ok"] is True
        assert payload["action"] == "skip"
        assert payload["set_status"] == "skipped-auto"
        assert "exhausted" in payload["reason"] or "oversized" in payload["reason"]

    def test_agent_timeout_exhausted_apply_writes_status(self, env_setup, capsys, make_args):
        """--apply 时 skipped-auto 状态被写入 state。"""
        sjson = str(env_setup.state_json)
        _state.init_run(make_args(plan_order=json.dumps(["cid-timeout"]), state_json=sjson))
        capsys.readouterr()
        _state.add_change(make_args(seq=1, change_id="cid-timeout", base=None, state_json=sjson))
        capsys.readouterr()

        _auto_decide.cli(
            _mk(env_setup, make_args, seq=1, trigger="agent-timeout-exhausted", apply=True)
        )
        capsys.readouterr()

        s = json.loads(env_setup.state_json.read_text())
        entry = s["progress"][0]
        assert entry["status"] == "skipped-auto"
        assert entry.get("last_trigger") == "agent-timeout-exhausted"

    def test_trigger_in_valid_triggers_set(self):
        """agent-timeout-exhausted 必须在 VALID_TRIGGERS 中（契约不回退守卫）。"""
        assert "agent-timeout-exhausted" in _auto_decide.VALID_TRIGGERS

    def test_budget_exhausted_then_auto_decide_flow(self, env_setup, capsys, make_args):
        """完整状态链：5次 record-timeout → exhausted=True → auto-decide → skip 且写入 state。"""
        _bootstrap(env_setup, capsys, make_args, "cid-flow")

        # 累积到 exhausted
        for _ in range(5):
            _agent.record_timeout(
                _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
            )
            capsys.readouterr()

        # 确认 exhausted
        _agent.timeout_budget(
            _mk(env_setup, make_args, seq=1, phase="implement", base=None, mult=None, max_sec=None)
        )
        budget = _read_emit(capsys)
        assert budget["exhausted"] is True

        # auto-decide
        _auto_decide.cli(
            _mk(env_setup, make_args, seq=1, trigger="agent-timeout-exhausted", apply=True)
        )
        decision = _read_emit(capsys)
        assert decision["action"] == "skip"

        # 验证 state
        s = json.loads(env_setup.state_json.read_text())
        assert s["progress"][0]["status"] == "skipped-auto"


# ============================================================
# 3.3  守卫测试：spine-run.md 含 timeout-budget 调用（skill 契约不回退）
# ============================================================


class TestSpineRunSkillContract:
    """验证 spine-run.md 文件中含有 timeout-budget 关键调用，确保 skill 契约不被意外回退。"""

    @pytest.fixture(autouse=True)
    def spine_run_text(self) -> str:
        spine_run = Path(__file__).parent.parent / "plugins" / "agent-spine" / "commands" / "spine-run.md"
        return spine_run.read_text(encoding="utf-8")

    def test_spine_run_contains_timeout_budget_call(self, spine_run_text):
        """spine-run.md 的 deferred=true 路径必须有 timeout-budget 调用。"""
        assert "timeout-budget" in spine_run_text

    def test_spine_run_contains_record_timeout_call(self, spine_run_text):
        """spine-run.md 的超时路径必须有 record-timeout 调用。"""
        assert "record-timeout" in spine_run_text

    def test_spine_run_contains_agent_timeout_exhausted_trigger(self, spine_run_text):
        """spine-run.md 必须引用 agent-timeout-exhausted trigger。"""
        assert "agent-timeout-exhausted" in spine_run_text

    def test_spine_run_guardrail_no_infinite_wait(self, spine_run_text):
        """spine-run.md 的 Guardrails 必须含有 in-session coder spawn 超时约束说明。"""
        assert "in-session coder spawn" in spine_run_text or "in-session" in spine_run_text
        assert "timeout" in spine_run_text.lower()

    def test_spine_run_timeout_budget_before_spawn(self, spine_run_text):
        """timeout-budget 必须出现在 spawn 操作（Agent subagent_type）前，
        验证 skill 契约中取预算→spawn 的正确顺序。"""
        tb_pos = spine_run_text.find("timeout-budget")
        spawn_pos = spine_run_text.find("Agent subagent_type=spine-coder")
        assert tb_pos != -1, "timeout-budget call not found"
        assert spawn_pos != -1, "Agent spawn call not found"
        assert tb_pos < spawn_pos, "timeout-budget must appear before Agent spawn"

    def test_spine_run_decision_table_contains_timeout_trigger(self, spine_run_text):
        """3d 决策点的 trigger 表必须包含 agent-timeout-exhausted 行。"""
        assert "agent-timeout-exhausted" in spine_run_text
