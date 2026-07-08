"""Review JSON 解析：从 codex --output-schema 输出派生关键指标。

输入：codex review 写出的 round-N.review.json（已通过 schema 校验）
输出：JSON 单行，含 verdict / blocking / advisory / categories / blocking_findings /
spec_attribution_counts
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import _io


BLOCKING_SEVERITIES = {"critical", "high"}

# spec_attribution 四值枚举（与 schema.REVIEW_SCHEMA 的 spec_attribution.enum 同源）。
SPEC_ATTRIBUTION_VALUES = (
    "spec-silent",
    "spec-ambiguous",
    "spec-contradicted",
    "impl-deviation",
)


def parse_review(review_json: dict) -> dict:
    """从 review JSON 派生指标。纯函数。"""
    findings = review_json.get("findings") or []
    if not isinstance(findings, list):
        raise ValueError("review.findings 必须是数组")

    blocking_list: list[dict] = []
    advisory_count = 0
    categories: list[str] = []
    seen_cats: set[str] = set()
    # spec_attribution_counts：仅统计 in_scope 且 severity ∈ BLOCKING_SEVERITIES 的 finding
    # （统计范围与 blocking 一致）。缺失该字段（历史 review.json）计入 unknown，不抛异常。
    spec_attribution_counts: dict[str, int] = {v: 0 for v in SPEC_ATTRIBUTION_VALUES}
    spec_attribution_counts["unknown"] = 0

    for f in findings:
        sev = f.get("severity")
        in_scope = bool(f.get("in_scope"))
        cat = f.get("category")
        if cat and cat not in seen_cats:
            seen_cats.add(cat)
            categories.append(cat)
        if sev in BLOCKING_SEVERITIES and in_scope:
            blocking_list.append(f)
            attribution = f.get("spec_attribution")
            if attribution in SPEC_ATTRIBUTION_VALUES:
                spec_attribution_counts[attribution] += 1
            else:
                spec_attribution_counts["unknown"] += 1
        else:
            advisory_count += 1

    blocking_list.sort(key=lambda x: x.get("id", ""))
    return {
        "verdict": review_json.get("verdict"),
        "blocking": len(blocking_list),
        "advisory": advisory_count,
        "categories": categories,
        "blocking_findings": blocking_list,
        "spec_attribution_counts": spec_attribution_counts,
    }


def parse(args: argparse.Namespace) -> None:
    """review parse <review.json>。"""
    path = Path(args.review_json)
    if not path.exists():
        _io.emit_error("file_not_found", f"review JSON 不存在：{path}", exit_code=3)
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _io.emit_error("invalid_json", f"review JSON 解析失败：{e}", exit_code=1)
        return

    try:
        result = parse_review(data)
    except ValueError as e:
        _io.emit_error("invalid_schema", str(e), exit_code=1)
        return

    _io.emit(result)
