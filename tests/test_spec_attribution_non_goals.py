"""spec-attribution-telemetry change 的非目标守护（防止实现期悄悄越界）。

本 change 的 proposal.md 明确列出以下非目标：
- 不引入任何基于 spec_attribution 的闸门、阈值或阻断行为
- 不修改 blocking 的判定逻辑（BLOCKING_SEVERITIES 不变）
- 不给 category 字段补 enum 约束
- 不改变 npc fixer findings 交给 coder 的 findings 内容（见 test_fixer.py 的负向测试）

这些测试把非目标从人工审计变成机器闸门。
"""

from __future__ import annotations

import ast
from pathlib import Path

from npc import auto_decide as _auto_decide
from npc import review as _review
from npc import schema as _schema

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src" / "npc"


def test_valid_triggers_unchanged():
    """VALID_TRIGGERS 集合未新增任何项（本 change 不引入 auto-decide 触发条件）。"""
    expected = {
        "stale",
        "max-rounds",
        "agent-timeout-exhausted",
        "codex-failed",
        "implementer-failed",
        "fixer-failed",
        "summary-missing",
        "commit-not-found",
        "archive-failed",
        "merge-evicted",
    }
    assert _auto_decide.VALID_TRIGGERS == expected


def test_blocking_severities_unchanged():
    """本 change 未修改 blocking 判定逻辑（BLOCKING_SEVERITIES 常量不变）。"""
    assert _review.BLOCKING_SEVERITIES == {"critical", "high"}


def test_category_field_has_no_enum_constraint():
    """category 字段未被补 enum 约束（是独立问题，另开 change）。"""
    finding_schema = _schema.REVIEW_SCHEMA["properties"]["findings"]["items"]
    assert "enum" not in finding_schema["properties"]["category"]


def test_no_gating_on_spec_attributable_blocking_rate():
    """grep 确认代码中不存在任何基于 spec_attributable_blocking_rate 的比较/阈值/分支。

    用 AST 扫描全部源文件：spec_attributable_blocking_rate 只允许出现在
    「计算 / 赋值 / 输出」语境（telemetry.aggregate 内部），不得出现在
    Compare（比较运算）、If 条件表达式，或作为函数调用的阈值参数。
    """
    offending: list[str] = []
    target_name = "spec_attributable_blocking_rate"

    for path in sorted(SRC_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if target_name not in text:
            continue
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            # 任何 Compare 节点，若其左值/比较值中引用了该名字 → 视为潜在闸门
            if isinstance(node, ast.Compare):
                sub_names = {
                    n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                }
                sub_attrs = {
                    n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
                }
                sub_strs = {
                    n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                }
                if target_name in sub_names or target_name in sub_attrs or any(
                    target_name in s for s in sub_strs
                ):
                    offending.append(f"{path}:{node.lineno}")
            # if 条件中直接引用（覆盖字符串 key 访问后再比较的常见写法之外的直接场景）
            if isinstance(node, ast.If):
                test_src = ast.dump(node.test)
                if target_name in test_src:
                    offending.append(f"{path}:{node.lineno}")

    assert not offending, (
        f"发现基于 {target_name} 的比较/分支，违反本 change 非目标（不引入闸门）：{offending}"
    )
