## Why

`spec_attribution_counts` 的历史遥测显示 validation 类 blocking finding 占比长期偏高，但相当一部分要么（1）coder 在 round 0 前完全没做边界值/None/类型/外部输入的自查——本可在生成侧提前消化；要么（2）reviewer 判 blocking 时并未给出"具体在什么输入/调用路径下会触发"，导致 fix 循环花在验证"这条 finding 到底能不能复现"上；要么（3）根因是 spec 本身未覆盖该行为（`spec_attribution == "spec-silent"`），本该由 spec 补条款，却被当成实现 bug 反复走 fix 循环。三者共同拉长了 review-fix 循环长度、推高了 `review-rN`/`fix-rN` 的 token 成本。

本 change 做三件对称的事：coder 侧前置消化（(a)）、reviewer 侧提高 validation blocking 的举证门槛（(b)）、npc 侧对 spec-silent 归因做窄化降级（(c)）——三者共享同一个上游动机，作为一个 change 落地。

## What Changes

- **(a) coder 自查清单细化**：`src/npc/templates.py::SELFCHECK_RUBRIC_MD` 的 `validation` 行从单句文案细化为四个具体检查点（边界值、None/空值、类型、外部输入来源），继续保持在同一常量内（implement/fix 共享），不新增独立段落、不引用 reviewer 侧判据措辞。
- **(b) validation 类 blocking 的举证门槛**：`src/npc/schema.py::REVIEW_SCHEMA` 的 finding 新增可选字段 `trigger_evidence`（string），当 `category == "validation"` 时通过 `if/then` 条件必需（MUST 出现该字段的 key，但值是否非空由 npc 侧而非 schema 判断）；`src/npc/focus.py::_output_requirements_block()` 新增文案说明该字段的用途与"缺失/空值会被 npc 侧确定性降级"的后果；`src/npc/review.py::parse_review()` 对 `category == "validation"` 的 blocking 候选 finding，若 `trigger_evidence` 缺失、为 `None`、去除首尾空白后为空字符串或等于占位符 `"-"`，则降级为 advisory（不计入 `blocking`/`blocking_findings`）。
- **(c) spec-silent 归因窄化降级**：`parse_review()` 对 blocking 候选 finding，若 `spec_attribution == "spec-silent"` 且 `severity != "critical"`，降级为 advisory；`severity == "critical"` 的 spec-silent finding 保持 blocking。本条修订 `openspec/specs/spec-attribution/spec.md` 的「spec 归因不参与 blocking 判定」「派生 spec 归因分布并向后兼容」「本 change 不引入任何闸门」**三条** Requirement：前者把降级规则显式限定在 `spec-silent` 且非 critical 这一窄化子集（`spec-ambiguous`/`spec-contradicted`/`impl-deviation` 不受影响、继续遵守原约束）；中者把 `spec_attribution_counts` 的统计范围从"blocking 候选集合"改写为"降级后最终 blocking 集合"（被降级的 finding 不再计入该统计，含 `unknown` 键）；后者确认该降级规则不构成新增闸门。
- **verdict 一致性修复**：`parse_review()` 与 `merge_review_passes()`/`_recompute_verdict()` 的 `verdict` 推导统一改为基于降级后的最终 blocking 集合（不再是原始 `severity`/`in_scope`），`parse_review()` 不再透传引擎自报的 `verdict` 值——避免"该轮全部 blocking 候选均被降级"时出现 `blocking == 0` 但 `verdict == "changes-requested"` 的矛盾。
- **可观测性**：`parse_review()` 返回值新增 `downgrade_counts`（`{"validation_missing_evidence": int, "spec_silent_non_critical": int}`），供后续评估两条降级策略的实际效果；`review.round` telemetry 事件新增字段 `downgrade_counts`（对齐 `spec_attribution_counts` 的既有传递路径：`pipeline.py::run_review_round` → `telemetry.py::emit_review_round` → `EMIT_FIELD_CONTRACT["review.round"]` → `telemetry_schema_v1.json`），`npc telemetry agg` 聚合输出各降级原因的累计计数。
- 同步补齐 `tests/test_templates.py`（或 `tests/test_reduce_review_fix_cost.py`，视既有归档惯例）、`tests/test_focus.py`、`tests/test_schema.py`、`tests/test_review.py`（含 `verdict` 推导来源变更、`merge_review_passes` verdict 一致性用例）、`tests/test_structural_invariants.py`（`EMIT_FIELD_CONTRACT` 字段集合断言）、`tests/test_spec_attribution_agg.py`（或新建同级测试）对应用例。

## Capabilities

### New Capabilities

- `validation-blocking-threshold`：validation 类 blocking 的双向治理——reviewer 侧举证门槛（`trigger_evidence` 条件必需字段 + npc 侧缺失降级）、spec-silent 归因窄化降级（非 critical 降级为 advisory）、降级可观测性计数。

### Modified Capabilities

- `implement-selfcheck-rubric`：`SELFCHECK_RUBRIC_MD` 的 `validation` 类目自查要点细化为四个具体检查点。
- `spec-attribution`：「spec 归因不参与 blocking 判定」「派生 spec 归因分布并向后兼容」「本 change 不引入任何闸门」三条 Requirement 修订——前者窄化，为 `validation-blocking-threshold` 能力定义的 spec-silent 非 critical 降级规则让出显式例外；中者把统计范围改写为"降级后最终 blocking 集合"；后者确认该例外不构成新增闸门。其余归因值与既有闸门约束不变。

## Impact

- **实现 prompt 渲染**：`src/npc/templates.py`（`SELFCHECK_RUBRIC_MD` 常量文案）。
- **review 举证与降级判定**：`src/npc/schema.py`（`REVIEW_SCHEMA.trigger_evidence` 条件必需）、`src/npc/focus.py`（`_output_requirements_block()` 新增举证要求文案）、`src/npc/review.py`（`parse_review()` 新增两条降级判据、`downgrade_counts` 返回值、`verdict` 改为基于降级后集合重算而非透传引擎自报值；`merge_review_passes()`/`_recompute_verdict()` 同步改为基于降级后集合判定 `verdict`）。
- **可观测性**：`src/npc/telemetry.py`（`emit_review_round` 新增 `downgrade_counts` 参数、`EMIT_FIELD_CONTRACT["review.round"]` 新增字段、`agg` 聚合逻辑）、`src/npc/telemetry_schema_v1.json`（新增 `downgrade_counts` 属性）、`src/npc/pipeline.py`（`run_review_round` 两处 `emit_review_round` 调用点传参）。
- **spec 归档**：修订 `openspec/specs/spec-attribution/spec.md` 两条既有 Requirement（作为本 change 的 MODIFIED Requirements delta）。
- **测试**：`tests/test_templates.py` 或 `tests/test_reduce_review_fix_cost.py`、`tests/test_focus.py`、`tests/test_schema.py`、`tests/test_review.py`、`tests/test_pipeline.py`、`tests/test_telemetry*.py`（聚合）、`tests/test_structural_invariants.py`。
- **不涉及**：`SPEC_REVIEW_SCHEMA`、`src/npc/spec_pipeline.py`、`src/npc/fixer.py`（其"仅渲染 blocking_findings"逻辑天然兼容降级后的 finding，无需改动）、`trend.py`。

## Non-Goals

- 不对 `trigger_evidence` 的内容做语义质量判断（例如"这段描述是否真的可复现"）——npc 侧只做确定性的"是否为空/占位符"判断，语义可信度仍依赖 reviewer 自律，与既有 `severity`/`in_scope` 信任模型一致。
- 不扩展窄化降级规则到 `spec-ambiguous`/`spec-contradicted`/`impl-deviation` 三值；`spec-attribution` capability 对这三值的既有约束（不参与 blocking 判定）保持不变。
- 不改变 `category != "validation"` 的 finding 的 blocking 判定逻辑（`trigger_evidence` 举证门槛仅约束 validation 类）。
- 不引入新的 `auto-decide` 触发条件或退出码变更；`downgrade_counts` 仅用于可观测性，不驱动任何阻断/阈值判定。
- 不改变 round 0/N 模板既有的其它审查重点顺序与内容，仅在 `_output_requirements_block()` 追加一段举证要求文案。
