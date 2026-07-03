"""守卫测试：skill 侧（spine-run.md）示范的 ``npc auto-decide --trigger`` 候选值
必须是 ``auto_decide.VALID_TRIGGERS`` 的子集。

fix-auto-decide-trigger-contract：审计 B1 指出 spine-run.md 曾用
``implement-failed|review-stale|archive-failed`` 这类未在代码侧注册的词，
主 session 照字面调用必崩（``invalid_trigger`` exit 2）。这条测试把
skill↔代码词表一致性从人工审计变成机器闸门：任何人改 spine-run.md 引入
不在 ``VALID_TRIGGERS`` 中的候选值，测试立刻失败并报出漂移的值。
"""

from __future__ import annotations

import re
from pathlib import Path

from npc import auto_decide as _auto_decide

REPO_ROOT = Path(__file__).resolve().parents[1]
SPINE_RUN_MD = REPO_ROOT / "plugins" / "agent-spine" / "commands" / "spine-run.md"

# 匹配 `--trigger <a|b|c>`、`--trigger a`、`--trigger <a>` 等形态，
# 抓取 `--trigger` 后紧跟的候选值片段（尖括号内或裸词）。
_TRIGGER_ARG_RE = re.compile(r"--trigger[ =]<([^>]+)>")
_TRIGGER_BARE_RE = re.compile(r"--trigger[ =]([A-Za-z][A-Za-z0-9_-]*)")

# `spine-run.md` 用一张 markdown 表把场景映射到真实 trigger 值（每行
# `| 场景描述 | \`trigger-value\` |`）。表头含 "`--trigger` 值"。
_TRIGGER_TABLE_HEADER_RE = re.compile(r"\|[^\n]*`--trigger`\s*值[^\n]*\|")
_TRIGGER_TABLE_ROW_RE = re.compile(r"\|[^|\n]*\|\s*`([a-z][a-z0-9_-]*)`\s*\|")


def _extract_trigger_candidates(text: str) -> set[str]:
    candidates: set[str] = set()

    # `--trigger <a|b|c>` 形态：拆枚举
    for group in _TRIGGER_ARG_RE.findall(text):
        # 形如 "上表对应值" 这种非枚举占位符不是真实 trigger 候选，跳过
        if "|" not in group and not re.fullmatch(r"[A-Za-z0-9_-]+", group):
            continue
        for value in group.split("|"):
            value = value.strip()
            if re.fullmatch(r"[A-Za-z0-9_-]+", value):
                candidates.add(value)

    # `--trigger a` / `--trigger a-b` 裸词形态（不含尖括号）
    text_without_angle = _TRIGGER_ARG_RE.sub("", text)
    for value in _TRIGGER_BARE_RE.findall(text_without_angle):
        candidates.add(value)

    # 场景映射表：表头之后到下一个空表头行前的所有行，抓第二列的反引号值
    header_match = _TRIGGER_TABLE_HEADER_RE.search(text)
    if header_match:
        table_start = header_match.end()
        # 表格在下一个空行或代码块围栏（```）处结束
        table_end_match = re.search(r"\n\s*\n|```", text[table_start:])
        table_end = (
            table_start + table_end_match.start() if table_end_match else len(text)
        )
        table_block = text[table_start:table_end]
        for value in _TRIGGER_TABLE_ROW_RE.findall(table_block):
            candidates.add(value)

    return candidates


def test_spine_run_md_trigger_values_are_valid():
    assert SPINE_RUN_MD.exists(), f"spine-run.md 不存在：{SPINE_RUN_MD}"
    text = SPINE_RUN_MD.read_text(encoding="utf-8")

    candidates = _extract_trigger_candidates(text)
    assert candidates, "spine-run.md 中未解析到任何 --trigger 候选值，检查正则或文件内容是否变化"

    drifted = candidates - _auto_decide.VALID_TRIGGERS
    assert not drifted, (
        f"spine-run.md 中出现不在 VALID_TRIGGERS 中的 --trigger 候选值：{sorted(drifted)}；"
        f"合法集：{sorted(_auto_decide.VALID_TRIGGERS)}"
    )


def test_extract_trigger_candidates_parses_enum_form():
    sample = "npc auto-decide --trigger <implementer-failed|stale|archive-failed> --seq $SEQ"
    assert _extract_trigger_candidates(sample) == {
        "implementer-failed",
        "stale",
        "archive-failed",
    }


def test_extract_trigger_candidates_rejects_placeholder_only_text():
    sample = "npc auto-decide --trigger <上表对应值> --seq $SEQ"
    assert _extract_trigger_candidates(sample) == set()


def test_extract_trigger_candidates_parses_scenario_table():
    sample = (
        "| 触发场景 | `--trigger` 值 |\n"
        "|---|---|\n"
        "| 3a implement 失败 | `implementer-failed` |\n"
        "| 3c archive 失败 | `archive-failed` |\n"
        "\n"
        "```bash\n"
        "npc auto-decide --trigger <上表对应值> --seq $SEQ\n"
        "```\n"
    )
    assert _extract_trigger_candidates(sample) == {
        "implementer-failed",
        "archive-failed",
    }
