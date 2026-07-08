"""spec_attribution_counts 进入聚合与 spec_attributable_blocking_rate 的回归。

对应 openspec change: spec-attribution-telemetry。
"""

from __future__ import annotations

from npc import telemetry as _telemetry


def _seed_events(events: list[dict]) -> None:
    for e in events:
        _telemetry.emit_event(e)


def test_aggregate_spec_attributable_blocking_rate(isolate_telemetry):
    """两条事件的 spec_attribution_counts 合并后，比率 == (spec-silent+ambiguous+contradicted)/(该和+impl-deviation)。"""
    _seed_events([
        {"kind": "review.round", "proj_key": "p", "phase": "review-r0",
         "round": 0, "status": "done",
         "spec_attribution_counts": {"spec-silent": 2, "impl-deviation": 2, "unknown": 0}},
        {"kind": "review.round", "proj_key": "p", "phase": "review-r0",
         "round": 0, "status": "done",
         "spec_attribution_counts": {"spec-ambiguous": 1, "impl-deviation": 3, "unknown": 5}},
    ])
    out = _telemetry.aggregate(_telemetry.iter_events(), by="phase")
    bucket = out["review-r0"]
    assert bucket["spec_attribution_counts"]["spec-silent"] == 2
    assert bucket["spec_attribution_counts"]["spec-ambiguous"] == 1
    assert bucket["spec_attribution_counts"]["impl-deviation"] == 5
    assert bucket["spec_attribution_counts"]["unknown"] == 5
    assert bucket["spec_attributable_blocking_rate"] == 0.375


def test_aggregate_spec_attributable_blocking_rate_null_when_only_unknown(isolate_telemetry):
    """全部事件仅含 unknown → 比率为 None（JSON null），不得为 0。"""
    _seed_events([
        {"kind": "review.round", "proj_key": "p", "phase": "review-r0",
         "round": 0, "status": "done",
         "spec_attribution_counts": {"unknown": 3}},
    ])
    out = _telemetry.aggregate(_telemetry.iter_events(), by="phase")
    bucket = out["review-r0"]
    assert bucket["spec_attributable_blocking_rate"] is None


def test_aggregate_ignores_events_missing_spec_attribution_counts(isolate_telemetry):
    """历史事件缺 spec_attribution_counts 键 → 被忽略，不破坏聚合，不影响比率。"""
    _seed_events([
        {"kind": "review.round", "proj_key": "p", "phase": "review-r0",
         "round": 0, "status": "done"},  # 历史事件：无该键
        {"kind": "review.round", "proj_key": "p", "phase": "review-r0",
         "round": 0, "status": "done",
         "spec_attribution_counts": {"spec-silent": 1, "impl-deviation": 1}},
    ])
    out = _telemetry.aggregate(_telemetry.iter_events(), by="phase")
    bucket = out["review-r0"]
    assert bucket["spec_attribution_counts"]["spec-silent"] == 1
    assert bucket["spec_attribution_counts"]["impl-deviation"] == 1
    assert bucket["spec_attributable_blocking_rate"] == 0.5


def test_aggregate_missing_spec_attribution_counts_defaults_empty(isolate_telemetry):
    _seed_events([
        {"kind": "phase.exit", "proj_key": "p", "phase": "implement",
         "status": "done", "duration_ms": 1000},
    ])
    out = _telemetry.aggregate(_telemetry.iter_events(), by="phase")
    assert out["implement"]["spec_attribution_counts"] == {}
    assert out["implement"]["spec_attributable_blocking_rate"] is None


def test_cli_agg_exit_zero_with_mixed_historical_events(isolate_telemetry, capsys, make_args):
    """npc telemetry agg 在混有大量无 spec_attribution_counts 的历史事件时 exit 0。"""
    _seed_events([
        {"kind": "review.round", "proj_key": "p", "phase": "review-r0",
         "round": 0, "status": "done"},
        {"kind": "phase.exit", "proj_key": "p", "phase": "implement", "status": "done"},
    ])
    _telemetry.cli_agg(make_args(since=None, by=None, no_write=True))
    captured = capsys.readouterr()
    assert captured.out.strip()
