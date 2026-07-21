"""review 模块测试。"""

from __future__ import annotations

import json

import pytest

from npc import review as _review


SAMPLE_REVIEW = {
    "verdict": "changes-requested",
    "findings": [
        {
            "id": "F1",
            "severity": "critical",
            "category": "validation",
            "title": "缺长度校验",
            "file": "src/a.go",
            "line_range": "42-58",
            "detail": "...",
            "recommendation": "...",
            "in_scope": True,
        },
        {
            "id": "F2",
            "severity": "high",
            "category": "concurrency",
            "title": "锁未释放",
            "file": "src/b.go",
            "line_range": "10",
            "detail": "...",
            "recommendation": "...",
            "in_scope": True,
        },
        {
            "id": "F3",
            "severity": "medium",
            "category": "style",
            "title": "命名",
            "file": "src/c.go",
            "line_range": "1",
            "detail": "...",
            "recommendation": "...",
            "in_scope": True,
        },
        {
            "id": "F4",
            "severity": "critical",
            "category": "performance",
            "title": "全局问题",
            "file": "src/d.go",
            "line_range": "100",
            "detail": "...",
            "recommendation": "...",
            "in_scope": False,
        },
    ],
}


def test_parse_review_counts():
    out = _review.parse_review(SAMPLE_REVIEW)
    assert out["blocking"] == 2  # F1, F2
    assert out["advisory"] == 2  # F3 (low severity), F4 (out of scope)
    assert out["verdict"] == "changes-requested"


def test_parse_review_categories_ordered_unique():
    out = _review.parse_review(SAMPLE_REVIEW)
    assert out["categories"] == ["validation", "concurrency", "style", "performance"]


def test_parse_review_blocking_findings_sorted_by_id():
    out = _review.parse_review(SAMPLE_REVIEW)
    ids = [f["id"] for f in out["blocking_findings"]]
    assert ids == ["F1", "F2"]


def test_parse_review_empty_findings():
    out = _review.parse_review({"verdict": "approve", "findings": []})
    assert out["blocking"] == 0
    assert out["advisory"] == 0
    assert out["categories"] == []
    assert out["blocking_findings"] == []


def test_parse_review_invalid_findings_type():
    with pytest.raises(ValueError):
        _review.parse_review({"verdict": "?", "findings": "not-a-list"})


# ============================================================
# spec_attribution_counts 派生 + 向后兼容
# ============================================================


def test_parse_review_missing_spec_attribution_counts_as_unknown():
    """历史 review.json 无 spec_attribution 键 → 不抛异常，计入 unknown。"""
    data = {
        "verdict": "changes-requested",
        "findings": [
            {
                "id": "F1", "severity": "high", "category": "validation",
                "title": "x", "file": "a.go", "line_range": "1",
                "detail": "d", "recommendation": "r", "in_scope": True,
            },
            {
                "id": "F2", "severity": "critical", "category": "concurrency",
                "title": "y", "file": "b.go", "line_range": "2",
                "detail": "d", "recommendation": "r", "in_scope": True,
            },
        ],
    }
    out = _review.parse_review(data)
    assert out["spec_attribution_counts"]["unknown"] == 2
    assert out["blocking"] == 2


def test_parse_review_mixed_spec_attribution_counted():
    data = {
        "verdict": "changes-requested",
        "findings": [
            {
                "id": "F1", "severity": "high", "category": "validation",
                "title": "x", "file": "a.go", "line_range": "1",
                "detail": "d", "recommendation": "r", "in_scope": True,
                "spec_attribution": "spec-silent",
            },
            {
                "id": "F2", "severity": "critical", "category": "concurrency",
                "title": "y", "file": "b.go", "line_range": "2",
                "detail": "d", "recommendation": "r", "in_scope": True,
                "spec_attribution": "spec-silent",
            },
            {
                "id": "F3", "severity": "high", "category": "edge-case",
                "title": "z", "file": "c.go", "line_range": "3",
                "detail": "d", "recommendation": "r", "in_scope": True,
                "spec_attribution": "impl-deviation",
            },
        ],
    }
    out = _review.parse_review(data)
    assert out["spec_attribution_counts"]["spec-silent"] == 2
    assert out["spec_attribution_counts"]["impl-deviation"] == 1
    assert out["spec_attribution_counts"]["unknown"] == 0


def test_parse_review_advisory_finding_not_counted_in_attribution():
    """advisory（severity=low）finding 即便带归因，也不计入 spec_attribution_counts。"""
    data = {
        "verdict": "passed-with-advisory",
        "findings": [
            {
                "id": "F1", "severity": "low", "category": "style",
                "title": "x", "file": "a.go", "line_range": "1",
                "detail": "d", "recommendation": "r", "in_scope": True,
                "spec_attribution": "spec-silent",
            },
        ],
    }
    out = _review.parse_review(data)
    assert sum(out["spec_attribution_counts"].values()) == 0


def test_parse_review_attribution_does_not_affect_blocking_or_advisory():
    """回归：两份 findings 完全相同，仅归因值不同 → blocking/advisory 相等（归因不参与 blocking 判定）。"""

    def _make(attribution: str) -> dict:
        return {
            "verdict": "changes-requested",
            "findings": [
                {
                    "id": "F1", "severity": "high", "category": "validation",
                    "title": "x", "file": "a.go", "line_range": "1",
                    "detail": "d", "recommendation": "r", "in_scope": True,
                    "spec_attribution": attribution,
                },
                {
                    "id": "F2", "severity": "medium", "category": "style",
                    "title": "y", "file": "b.go", "line_range": "2",
                    "detail": "d", "recommendation": "r", "in_scope": True,
                    "spec_attribution": attribution,
                },
            ],
        }

    out_a = _review.parse_review(_make("spec-silent"))
    out_b = _review.parse_review(_make("impl-deviation"))
    assert out_a["blocking"] == out_b["blocking"]
    assert out_a["advisory"] == out_b["advisory"]


def test_parse_cli_handler(tmp_path, capsys, make_args):
    review_file = tmp_path / "r.json"
    review_file.write_text(json.dumps(SAMPLE_REVIEW))
    _review.parse(make_args(review_json=str(review_file)))
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["blocking"] == 2
    assert payload["advisory"] == 2


def test_parse_cli_missing_file(tmp_path, capsys, make_args):
    with pytest.raises(SystemExit):
        _review.parse(make_args(review_json=str(tmp_path / "absent.json")))
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["error"] == "file_not_found"


# ============================================================
# merge_review_passes（change review-r0-adversarial-pass D4）
# ============================================================


def _finding(id_, sev, cat, file, line, in_scope=True):
    return {
        "id": id_,
        "severity": sev,
        "category": cat,
        "title": f"t-{id_}",
        "file": file,
        "line_range": line,
        "detail": "...",
        "recommendation": "...",
        "in_scope": in_scope,
        "spec_attribution": "spec-silent",
    }


def test_merge_no_overlap_concatenates_and_renumbers():
    pass1 = {"verdict": "approve", "findings": [_finding("F1", "low", "style", "a.py", "1")]}
    pass2 = {"verdict": "approve", "findings": [_finding("F1", "high", "concurrency", "b.py", "2")]}
    merged, stats = _review.merge_review_passes(pass1, pass2)
    ids = [f["id"] for f in merged["findings"]]
    assert ids == ["F1", "F2"]
    # pass1 全量在前，pass2 去重后剩余在后
    assert merged["findings"][0]["file"] == "a.py"
    assert merged["findings"][1]["file"] == "b.py"
    assert stats["adversarial_blocking_count"] == 1


def test_merge_dedup_exact_triple_keeps_pass1():
    """同一 (file,line_range,category) 三元组：pass2 被丢弃，保留 pass1，总数少 1。"""
    dup1 = _finding("F1", "high", "validation", "a.py", "10-20")
    dup2 = _finding("F9", "critical", "validation", "a.py", "10-20")  # 同键、不同措辞
    pass1 = {"findings": [dup1]}
    pass2 = {"findings": [dup2, _finding("F1", "low", "style", "c.py", "3")]}
    merged, stats = _review.merge_review_passes(pass1, pass2)
    assert len(merged["findings"]) == 2  # dup2 被去重
    # 保留 pass1 版本（severity=high），不是 pass2 的 critical
    kept = next(f for f in merged["findings"] if f["file"] == "a.py")
    assert kept["severity"] == "high"
    # 被去重丢弃的 blocking 不计入 side-channel
    assert stats["adversarial_blocking_count"] == 0


def test_merge_pass2_blocking_promotes_verdict():
    """spec Scenario：pass1 approve 无 findings，pass2 独有 high in_scope → changes-requested。"""
    pass1 = {"verdict": "approve", "findings": []}
    pass2 = {"findings": [_finding("F1", "high", "concurrency", "x.py", "5")]}
    merged, stats = _review.merge_review_passes(pass1, pass2)
    assert merged["verdict"] == "changes-requested"
    assert merged["findings"][0]["id"] == "F1"
    assert stats["adversarial_blocking_count"] == 1


def test_merge_empty_pass2_stub_equivalent_to_pass1_only():
    """降级路径：pass2={"findings":[]} → 等价 pass1-only，verdict 按 pass1 重算。"""
    pass1 = {
        "verdict": "ignored",  # 自报 verdict 必须被忽略
        "findings": [_finding("Fx", "medium", "style", "a.py", "1")],
    }
    merged, stats = _review.merge_review_passes(pass1, {"findings": []})
    assert [f["id"] for f in merged["findings"]] == ["F1"]
    assert merged["findings"][0]["file"] == "a.py"
    assert merged["verdict"] == "passed-with-advisory"  # 有 finding 但非 blocking
    assert stats["adversarial_blocking_count"] == 0


def test_merge_pass1_empty_uses_pass2():
    pass1 = {"findings": []}
    pass2 = {"findings": [_finding("F1", "low", "style", "z.py", "9")]}
    merged, stats = _review.merge_review_passes(pass1, pass2)
    assert len(merged["findings"]) == 1
    assert merged["verdict"] == "passed-with-advisory"
    assert stats["adversarial_blocking_count"] == 0


def test_merge_both_empty_yields_approve():
    merged, stats = _review.merge_review_passes({"findings": []}, {"findings": []})
    assert merged["findings"] == []
    assert merged["verdict"] == "approve"
    assert stats["adversarial_blocking_count"] == 0


def test_merge_out_of_scope_blocking_not_counted():
    """pass2 blocking 但 in_scope=false → verdict 不升级、side-channel 不计。"""
    pass1 = {"findings": []}
    pass2 = {"findings": [_finding("F1", "high", "concurrency", "q.py", "3", in_scope=False)]}
    merged, stats = _review.merge_review_passes(pass1, pass2)
    assert merged["verdict"] == "passed-with-advisory"
    assert stats["adversarial_blocking_count"] == 0


def test_merge_does_not_mutate_inputs():
    f = _finding("F7", "high", "concurrency", "b.py", "2")
    pass1 = {"findings": [f]}
    _review.merge_review_passes(pass1, {"findings": []})
    assert f["id"] == "F7"  # 原对象未被重编号污染


def test_merge_non_list_findings_raises():
    with pytest.raises(ValueError):
        _review.merge_review_passes({"findings": "nope"}, {"findings": []})


# ============================================================
# _finding_key（模块级，供 merge_review_passes 同轮去重复用；
# change review-delta-convergence D2）
# ============================================================


def test_finding_key_module_level_matches_merge_dedup_behavior():
    f = _finding("F1", "high", "validation", "a.py", "10-20")
    assert _review._finding_key(f) == ("a.py", "10-20", "validation")
    # merge_review_passes 内部去重复用同一函数：同键即去重
    pass1 = {"findings": [f]}
    pass2 = {"findings": [_finding("F9", "critical", "validation", "a.py", "10-20")]}
    merged, _ = _review.merge_review_passes(pass1, pass2)
    assert len(merged["findings"]) == 1


# ============================================================
# _is_carry_over_match（区间重叠跨轮匹配；change review-delta-convergence D2）
# ============================================================


def _prior(file="a.py", line_range="10-20", category="validation"):
    return {"file": file, "line_range": line_range, "category": category}


def test_is_carry_over_match_exact_triple():
    assert _review._is_carry_over_match(_prior(), _prior()) is True


def test_is_carry_over_match_overlapping_range_after_drift():
    f = _prior(line_range="15-25")
    assert _review._is_carry_over_match(f, _prior()) is True


def test_is_carry_over_match_non_overlapping_range():
    f = _prior(line_range="80-90")
    assert _review._is_carry_over_match(f, _prior()) is False


def test_is_carry_over_match_different_category():
    f = _prior(category="security")
    assert _review._is_carry_over_match(f, _prior()) is False


def test_is_carry_over_match_different_file():
    f = _prior(file="b.py")
    assert _review._is_carry_over_match(f, _prior()) is False


def test_is_carry_over_match_single_line_within_range():
    f = _prior(line_range="18")
    assert _review._is_carry_over_match(f, _prior(line_range="15-25")) is True


def test_is_carry_over_match_reverse_range_normalized():
    f = _prior(line_range="25-15")
    assert _review._is_carry_over_match(f, _prior()) is True


def test_is_carry_over_match_placeholder_dash_no_exception():
    f = _prior(line_range="-")
    assert _review._is_carry_over_match(f, _prior()) is False


def test_is_carry_over_match_malformed_line_range_no_exception():
    f = _prior(line_range="foo")
    assert _review._is_carry_over_match(f, _prior()) is False


# ============================================================
# _parse_line_range：超长数字端点防御（fix round 1 F2，change review-delta-convergence）
# ============================================================


def test_parse_line_range_overlong_single_digit_returns_none_no_raise():
    """schema 合法（字符串）但位数远超 CPython int() 字符串转换安全上限：
    不应抛 ValueError，必须安全返回 None。"""
    overlong = "9" * 5000
    assert _review._parse_line_range(overlong) is None


def test_parse_line_range_overlong_pair_endpoint_returns_none_no_raise():
    overlong = "9" * 5000
    assert _review._parse_line_range(f"{overlong}-{overlong}") is None


def test_parse_line_range_zero_single_accepted():
    """spec.md 明确 N/M 为非负整数：单行 "0" 必须解析为 (0, 0)，不可判为不可解析
    （fix round 2 F1，change review-delta-convergence）。"""
    assert _review._parse_line_range("0") == (0, 0)


def test_parse_line_range_zero_endpoint_in_pair_accepted():
    """"0-10" 必须解析为 (0, 10)，不可判为不可解析（fix round 2 F1）。"""
    assert _review._parse_line_range("0-10") == (0, 10)


def test_parse_line_range_zero_endpoint_reverse_pair_accepted():
    """"10-0" 归一化为 (0, 10)（fix round 2 F1）。"""
    assert _review._parse_line_range("10-0") == (0, 10)


def test_is_carry_over_match_zero_line_range_matches():
    """回归：零值行区间（"0" / "0-10"）必须参与 carry-over 几何匹配，不可被误判为
    不可解析而回退为 round-diff-new（fix round 2 F1）。"""
    f = _prior(line_range="0")
    assert _review._is_carry_over_match(f, _prior(line_range="0-10")) is True


def test_parse_line_range_max_digits_boundary_accepted():
    """恰好等于位数上限的合理行号仍应正常解析。"""
    n = "9" * _review._LINE_NUMBER_MAX_DIGITS
    assert _review._parse_line_range(n) == (int(n), int(n))


def test_is_carry_over_match_overlong_line_range_no_exception():
    """finding_key 精确扫描以外，跨轮几何匹配路径同样必须对超长数字端点免疫。"""
    overlong = "9" * 5000
    f = _prior(line_range=overlong)
    assert _review._is_carry_over_match(f, _prior()) is False


def test_parse_review_overlong_line_range_does_not_raise():
    """端到端：schema 合法但超长数字行号的 finding 混入 findings 时，
    parse_review 整体不应抛异常（回归 F2 报告的"整个 review phase 被标记失败"故障）。"""
    findings = [
        _finding("F1", "high", "validation", "a.py", "9" * 5000),
        _finding("F2", "high", "validation", "b.py", "42"),
    ]
    result = _review.parse_review({"findings": findings})
    assert result["blocking"] == 2


# ============================================================
# parse_review：round_n / prior_blocking（change review-delta-convergence D2）
# ============================================================


def test_parse_review_default_params_unchanged_derivation():
    """默认参数（不传 round_n/prior_blocking）派生计算方式与改动前一致。"""
    out = _review.parse_review(SAMPLE_REVIEW)
    assert out["blocking"] == 2
    assert out["advisory"] == 2
    assert out["verdict"] == "changes-requested"
    assert out["carryover_unresolved_blocking"] is None
    assert out["finding_origins"] == []


def _delta_finding(id_, sev, cat, file, line, origin, in_scope=True):
    return {
        "id": id_, "severity": sev, "category": cat, "title": f"t-{id_}",
        "file": file, "line_range": line, "detail": "d", "recommendation": "r",
        "in_scope": in_scope, "spec_attribution": "spec-silent",
        "finding_origin": origin,
    }


def test_parse_review_round2_geometric_hit_overrides_self_reported_exact_triple():
    prior = [_delta_finding("P1", "high", "validation", "a.py", "10-20", "round-diff-new")]
    data = {
        "verdict": "changes-requested",
        "findings": [
            _delta_finding("F1", "high", "validation", "a.py", "10-20", "pre-existing-new"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    origin = next(o for o in out["finding_origins"] if o["id"] == "F1")
    assert origin["effective_origin"] == "carry-over-unresolved"
    assert out["carryover_unresolved_blocking"] == 1


def test_parse_review_round2_geometric_hit_overrides_self_reported_overlapping_range():
    prior = [_delta_finding("P1", "high", "validation", "a.py", "10-20", "round-diff-new")]
    data = {
        "verdict": "changes-requested",
        "findings": [
            _delta_finding("F1", "high", "validation", "a.py", "15-25", "pre-existing-new"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    origin = next(o for o in out["finding_origins"] if o["id"] == "F1")
    assert origin["effective_origin"] == "carry-over-unresolved"


def test_parse_review_round2_pre_existing_new_not_hit_excluded_from_blocking():
    prior = [_delta_finding("P1", "high", "validation", "a.py", "10-20", "round-diff-new")]
    data = {
        "verdict": "changes-requested",
        "findings": [
            _delta_finding("F1", "high", "validation", "z.py", "1-2", "pre-existing-new"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    assert out["blocking"] == 0
    assert out["blocking_findings"] == []
    assert out["advisory"] == 1


def test_parse_review_round2_self_reported_carry_over_not_hit_falls_back_no_overlap():
    prior = [_delta_finding("P1", "high", "validation", "a.py", "10-20", "round-diff-new")]
    data = {
        "verdict": "changes-requested",
        "findings": [
            _delta_finding("F1", "critical", "validation", "a.py", "80-90", "carry-over-unresolved"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    origin = next(o for o in out["finding_origins"] if o["id"] == "F1")
    assert origin["effective_origin"] == "round-diff-new"
    assert out["blocking"] == 1  # 仍计入 blocking 候选


def test_parse_review_round2_self_reported_carry_over_not_hit_falls_back_category_change():
    prior = [_delta_finding("P1", "high", "validation", "a.py", "10-20", "round-diff-new")]
    data = {
        "verdict": "changes-requested",
        "findings": [
            _delta_finding("F1", "critical", "security", "a.py", "10-20", "carry-over-unresolved"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    origin = next(o for o in out["finding_origins"] if o["id"] == "F1")
    assert origin["effective_origin"] == "round-diff-new"


def test_parse_review_round2_verdict_recomputed_changes_requested():
    prior: list[dict] = []
    data = {
        "verdict": "approve",  # 自报 verdict 必须被忽略
        "findings": [
            _delta_finding("F1", "critical", "validation", "a.py", "1-2", "round-diff-new"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    assert out["verdict"] == "changes-requested"


def test_parse_review_round2_verdict_recomputed_passed_with_advisory():
    prior: list[dict] = []
    data = {
        "verdict": "changes-requested",  # 自报 verdict 必须被忽略
        "findings": [
            _delta_finding("F1", "high", "validation", "a.py", "1-2", "pre-existing-new"),
        ],
    }
    out = _review.parse_review(data, round_n=2, prior_blocking=prior)
    assert out["verdict"] == "passed-with-advisory"


def test_parse_review_round2_verdict_recomputed_approve():
    out = _review.parse_review({"verdict": "changes-requested", "findings": []}, round_n=2, prior_blocking=[])
    assert out["verdict"] == "approve"


def test_parse_review_round1_or_no_prior_blocking_unchanged_derivation():
    """round_n=1（或 prior_blocking=None）不改变派生计算方式：finding_origin 被忽略，
    verdict 仍取自报值。"""
    data = {
        "verdict": "changes-requested",
        "findings": [
            _delta_finding("F1", "high", "validation", "a.py", "1-2", "pre-existing-new"),
        ],
    }
    out1 = _review.parse_review(data, round_n=1, prior_blocking=[])
    out2 = _review.parse_review(data, round_n=2, prior_blocking=None)
    for out in (out1, out2):
        assert out["blocking"] == 1  # pre-existing-new 忽略，仍计入 blocking（自报 severity/in_scope）
        assert out["verdict"] == "changes-requested"  # 直接取自报值
        assert out["carryover_unresolved_blocking"] is None
