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
