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


def _recompute_verdict(findings: list[dict]) -> str:
    """按 REVIEW_SCHEMA verdict 语义在 findings 全集上重算 verdict。纯函数。

    存在 in_scope blocking → changes-requested；否则非空 → passed-with-advisory；
    否则 approve。
    """
    has_blocking = any(
        f.get("severity") in BLOCKING_SEVERITIES and bool(f.get("in_scope"))
        for f in findings
    )
    if has_blocking:
        return "changes-requested"
    if findings:
        return "passed-with-advisory"
    return "approve"


def merge_review_passes(pass1: dict, pass2: dict) -> tuple[dict, dict]:
    """合并两个 review pass 的 findings（compliance pass1 + adversarial pass2）。纯函数。

    见 change review-r0-adversarial-pass D4：
    1. 去重键 ``(file, line_range, category)`` 精确匹配；pass2 中与 pass1 同键的
       finding 被丢弃（pass1 优先）。
    2. 合并顺序：pass1 全量（原序）→ pass2 去重后剩余（原序）。
    3. 按最终顺序重新分配 ``id`` 为 ``F1..Fn``（丢弃引擎自报的原始 id）。
    4. ``verdict`` 在合并后 findings 全集上按 REVIEW_SCHEMA 语义重算，
       不采信任一 pass 自报的 verdict。
    5. 返回 ``(merged, stats)``；``stats["adversarial_blocking_count"]`` 是来源于
       pass2、未被去重丢弃、且 ``severity ∈ BLOCKING_SEVERITIES and in_scope`` 的
       finding 数（在重编号之前、来源尚可区分时统计的 side-channel）。

    ``pass2`` 允许为空 findings 替身 ``{"findings": []}``（pass2 失败降级路径），
    此时等价于仅用 pass1，``adversarial_blocking_count`` 计为 0。
    """
    p1_findings = pass1.get("findings") or []
    p2_findings = pass2.get("findings") or []
    if not isinstance(p1_findings, list) or not isinstance(p2_findings, list):
        raise ValueError("review.findings 必须是数组")

    def _key(f: dict) -> tuple:
        return (f.get("file"), f.get("line_range"), f.get("category"))

    pass1_keys = {_key(f) for f in p1_findings}

    merged: list[dict] = list(p1_findings)
    adversarial_blocking_count = 0
    for f in p2_findings:
        if _key(f) in pass1_keys:
            continue
        merged.append(f)
        if f.get("severity") in BLOCKING_SEVERITIES and bool(f.get("in_scope")):
            adversarial_blocking_count += 1

    # 重新编号（immutable：构造新 dict，不改原对象）
    renumbered = [{**f, "id": f"F{i}"} for i, f in enumerate(merged, start=1)]

    merged_review = {
        "verdict": _recompute_verdict(renumbered),
        "findings": renumbered,
    }
    stats = {"adversarial_blocking_count": adversarial_blocking_count}
    return merged_review, stats


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
