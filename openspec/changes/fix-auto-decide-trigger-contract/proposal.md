## Why

审计 B1（严重）：`plugins/agent-spine/commands/spine-run.md:184` 的 3d 决策点示范 `npc auto-decide --trigger <implement-failed|review-stale|archive-failed>`，但 `src/npc/auto_decide.py:22-31` 的 `VALID_TRIGGERS = {stale, max-rounds, agent-timeout-exhausted, codex-failed, implementer-failed, fixer-failed, summary-missing, commit-not-found}`——三个示范值**无一命中**（`implement-failed`≠`implementer-failed`、`review-stale`≠`stale`、`archive-failed` 不存在且 `_decide` 无 archive 失败分支）。主 session 照 skill 字面调用必然 `emit_error("invalid_trigger", exit_code=2)`（auto_decide.py:134-140），auto 档每个决策点都会崩。单测只用正确词表（tests/test_v11_features.py:271），全绿掩盖了 skill 侧的错。这违反不变量 2（结构化契约是唯一真相——skill 与代码两侧契约漂移即真相分裂）。

## What Changes

- 修正 `spine-run.md` 3d 决策点的 trigger 示范词表为 `auto_decide.py` 的真实词表，并按触发场景标注映射（implement 失败→`implementer-failed`、fix 失败→`fixer-failed`、review 卡死→`stale`/`max-rounds`、archive 失败→新增 trigger）。
- `auto_decide.py` 的 `_decide` 增加 `archive-failed` trigger 分支（进 `VALID_TRIGGERS`），语义：archive 失败一次给 retry、再失败 skip（复用软失败 RETRY_TRIGGERS 语义），使 3c 失败路径有合法决策入口。
- 新增守卫测试：解析 `spine-run.md` 全文中出现的所有 `--trigger` 候选值，断言 ⊆ `VALID_TRIGGERS`——skill↔代码词表一致性从此有机器闸门。

## Capabilities

### New Capabilities

- `auto-decide-trigger-contract`: skill 侧 trigger 词表与 `auto_decide.VALID_TRIGGERS` 的一致性契约，含 archive-failed 分支与守卫测试。

### Modified Capabilities

## Impact

- `plugins/agent-spine/commands/spine-run.md`（3d 决策点词表修正 + 场景映射）
- `src/npc/auto_decide.py`（`VALID_TRIGGERS` + `_decide` 增 archive-failed 分支）
- `tests/`（skill↔代码词表守卫测试 + archive-failed 分支单测）
