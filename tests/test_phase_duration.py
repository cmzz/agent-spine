"""phase 计时鲁棒性回归：

- started_ms 缺失时由 started_at 回退计算 duration_ms
- 两者皆缺才 null
- 同一 phase 二次 exit（重试路径）仍保有正确 duration_ms

对应 openspec change: implement-phase-duration。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from npc import pipeline as _pipeline
from npc import state as _state


def _bootstrap(env_setup, make_args, capsys):
    _state.init_run(make_args(plan_order=json.dumps(["add-foo"])))
    capsys.readouterr()
    _state.add_change(make_args(seq=1, change_id="add-foo", base=None))
    capsys.readouterr()


def _set_phase(p, phase: str, fields: dict) -> None:
    def mutate(s):
        e = s["progress"][0]
        e.setdefault("phases", {})[phase] = fields
    _state.update_state(p.state_json, p.state_md, mutate)


def _phase(p, phase: str) -> dict:
    s = json.loads(p.state_json.read_text())
    return s["progress"][0]["phases"][phase]


def test_duration_from_started_at_when_no_started_ms(env_setup, make_args, capsys):
    """仅有 started_at（无 started_ms）→ duration 非空且≈两时刻差。"""
    p = env_setup
    _bootstrap(env_setup, make_args, capsys)
    started_at = (datetime.now().astimezone() - timedelta(minutes=5)).isoformat(timespec="seconds")
    _set_phase(p, "implement", {"status": "in-progress", "started_at": started_at})

    _pipeline._do_phase_exit(p, 1, "implement", status="done")

    ph = _phase(p, "implement")
    assert ph["duration_ms"] is not None
    # ≈5min，允许宽松下界（≥ 4min）
    assert ph["duration_ms"] >= 4 * 60 * 1000


def test_duration_null_when_no_timestamps(env_setup, make_args, capsys):
    """既无 started_ms 也无 started_at → duration=null，不抛错。"""
    p = env_setup
    _bootstrap(env_setup, make_args, capsys)
    _set_phase(p, "implement", {"status": "in-progress"})

    _pipeline._do_phase_exit(p, 1, "implement", status="done")

    assert _phase(p, "implement")["duration_ms"] is None


def test_second_exit_preserves_duration(env_setup, make_args, capsys):
    """enter → exit(failed) → exit(done)：二次 exit duration 仍非空，started_at 不变。"""
    p = env_setup
    _bootstrap(env_setup, make_args, capsys)

    _pipeline._do_phase_enter(p, 1, "implement")
    first_started_at = _phase(p, "implement")["started_at"]

    _pipeline._do_phase_exit(p, 1, "implement", status="failed")
    _pipeline._do_phase_exit(p, 1, "implement", status="done")

    ph = _phase(p, "implement")
    assert ph["status"] == "done"
    assert ph["duration_ms"] is not None
    assert ph["started_at"] == first_started_at
