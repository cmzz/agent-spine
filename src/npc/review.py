"""Review JSON 解析：从 codex --output-schema 输出派生关键指标。

输入：codex review 写出的 round-N.review.json（已通过 schema 校验）
输出：JSON 单行，含 verdict / blocking / advisory / categories / blocking_findings /
spec_attribution_counts
"""

from __future__ import annotations

import argparse
import json
import re
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

# finding_origin 三值枚举（与 schema.REVIEW_SCHEMA 的 finding_origin.enum 同源）。
# 见 change review-delta-convergence D1。
FINDING_ORIGIN_VALUES = (
    "carry-over-unresolved",
    "round-diff-new",
    "pre-existing-new",
)

_LINE_RANGE_SINGLE_RE = re.compile(r"^\d+$")
_LINE_RANGE_PAIR_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def _finding_key(f: dict) -> tuple:
    """``(file, line_range, category)`` 精确三元组，供 ``merge_review_passes`` 同轮去重使用。

    只服务于同一轮内跨 pass 的精确匹配（逐字符相等）；跨轮 carry-over 匹配见
    :func:`_is_carry_over_match`（区间重叠），二者用途不同、互不替代（见 change
    review-delta-convergence D2）。
    """
    return (f.get("file"), f.get("line_range"), f.get("category"))


def _parse_line_range(line_range: Any) -> tuple[int, int] | None:
    """把 ``line_range`` 解析为整数区间 ``(start, end)``；不可解析返回 ``None``，不抛异常。

    可解析：单行 ``"N"``（视为 ``[N, N]``）、区间 ``"N-M"``（允许数字与连字符前后空白，
    ``N > M`` 时归一化为 ``[min, max]``）。
    不可解析：占位符 ``"-"``、空字符串、任意无法提取出两个整数端点的字符串。
    """
    if not isinstance(line_range, str):
        return None
    s = line_range.strip()
    if not s:
        return None
    if _LINE_RANGE_SINGLE_RE.match(s):
        n = int(s)
        return (n, n)
    m = _LINE_RANGE_PAIR_RE.match(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b))
    return None


def _is_carry_over_match(finding: dict, prior_finding: dict) -> bool:
    """判定 ``finding`` 与 ``prior_finding`` 是否是「同一问题」的跨轮 carry-over 匹配。

    判据（见 change review-delta-convergence D2、spec.md「round≥2 对 finding_origin
    做几何交叉核验」Requirement）：``file``/``category`` 精确匹配 AND ``line_range``
    解析出的整数区间存在重叠。任一 ``line_range`` 不可解析时直接返回 ``False``，
    不抛异常、不做区间比较。
    """
    if finding.get("file") != prior_finding.get("file"):
        return False
    if finding.get("category") != prior_finding.get("category"):
        return False
    r1 = _parse_line_range(finding.get("line_range"))
    r2 = _parse_line_range(prior_finding.get("line_range"))
    if r1 is None or r2 is None:
        return False
    return max(r1[0], r2[0]) <= min(r1[1], r2[1])


def parse_review(
    review_json: dict,
    *,
    round_n: int = 0,
    prior_blocking: list[dict] | None = None,
) -> dict:
    """从 review JSON 派生指标。纯函数。

    ``round_n >= 2`` 且提供非 ``None`` 的 ``prior_blocking``（上一轮最终有效
    ``blocking_findings``）时，对每条 finding 计算「有效来源」``effective_origin``
    （几何命中优先于自报值，见 change review-delta-convergence D2），有效来源为
    ``pre-existing-new`` 的 finding 不计入 blocking，``verdict`` 在调整后的集合上
    重新计算，不采信自报 ``verdict``。

    ``round_n < 2`` 或 ``prior_blocking`` 为 ``None``：``finding_origin`` 字段被
    忽略，``blocking``/``advisory``/``verdict``/``blocking_findings`` 的派生计算
    方式与本参数引入前完全一致（``carryover_unresolved_blocking`` 为 ``None``，
    ``finding_origins`` 为空列表）。
    """
    findings = review_json.get("findings") or []
    if not isinstance(findings, list):
        raise ValueError("review.findings 必须是数组")

    delta_active = round_n >= 2 and prior_blocking is not None

    blocking_list: list[dict] = []
    advisory_count = 0
    categories: list[str] = []
    seen_cats: set[str] = set()
    # spec_attribution_counts：仅统计 in_scope 且 severity ∈ BLOCKING_SEVERITIES 的 finding
    # （统计范围与 blocking 一致）。缺失该字段（历史 review.json）计入 unknown，不抛异常。
    spec_attribution_counts: dict[str, int] = {v: 0 for v in SPEC_ATTRIBUTION_VALUES}
    spec_attribution_counts["unknown"] = 0
    finding_origins: list[dict] = []
    carryover_unresolved_blocking: int | None = 0 if delta_active else None

    for f in findings:
        sev = f.get("severity")
        in_scope = bool(f.get("in_scope"))
        cat = f.get("category")
        if cat and cat not in seen_cats:
            seen_cats.add(cat)
            categories.append(cat)

        effective_origin: str | None = None
        if delta_active:
            reported_origin = f.get("finding_origin")
            hit = any(_is_carry_over_match(f, g) for g in prior_blocking)
            if hit:
                effective_origin = "carry-over-unresolved"
            elif reported_origin == "carry-over-unresolved":
                # 自报声称遗留但几何核验未命中：保守回退，仍计入 blocking 候选。
                effective_origin = "round-diff-new"
            elif reported_origin in ("round-diff-new", "pre-existing-new"):
                effective_origin = reported_origin
            else:
                # 自报字段缺失/非法枚举（防御性分支，schema 已强制必填合法枚举）。
                effective_origin = "round-diff-new"
            finding_origins.append({"id": f.get("id"), "effective_origin": effective_origin})

        is_blocking_candidate = sev in BLOCKING_SEVERITIES and in_scope
        if delta_active and effective_origin == "pre-existing-new":
            is_blocking_candidate = False

        if is_blocking_candidate:
            blocking_list.append(f)
            attribution = f.get("spec_attribution")
            if attribution in SPEC_ATTRIBUTION_VALUES:
                spec_attribution_counts[attribution] += 1
            else:
                spec_attribution_counts["unknown"] += 1
            if delta_active and effective_origin == "carry-over-unresolved":
                carryover_unresolved_blocking = (carryover_unresolved_blocking or 0) + 1
        else:
            advisory_count += 1

    blocking_list.sort(key=lambda x: x.get("id", ""))

    if delta_active:
        if blocking_list:
            verdict = "changes-requested"
        elif advisory_count > 0:
            verdict = "passed-with-advisory"
        else:
            verdict = "approve"
    else:
        verdict = review_json.get("verdict")

    return {
        "verdict": verdict,
        "blocking": len(blocking_list),
        "advisory": advisory_count,
        "categories": categories,
        "blocking_findings": blocking_list,
        "spec_attribution_counts": spec_attribution_counts,
        "carryover_unresolved_blocking": carryover_unresolved_blocking,
        "finding_origins": finding_origins,
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

    pass1_keys = {_finding_key(f) for f in p1_findings}

    merged: list[dict] = list(p1_findings)
    adversarial_blocking_count = 0
    for f in p2_findings:
        if _finding_key(f) in pass1_keys:
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
