## Context

`src/npc/review.py::parse_review()` 目前只由 `severity ∈ {critical, high}` 且 `in_scope == true` 决定 `blocking`；`spec_attribution` 字段（见 `openspec/specs/spec-attribution/spec.md`）已经存在但只用于统计 `spec_attribution_counts`，完全不参与 blocking 判定。`src/npc/templates.py::SELFCHECK_RUBRIC_MD` 是 coder 侧唯一的静态自查清单，implement/fix 两处共享；`src/npc/focus.py::_output_requirements_block()` 是 reviewer 侧输出要求文案的单一来源，`STUB_AND_TEST_TAMPERING_BLOCKING`/`SPEC_ATTRIBUTION_ENUM_SEMANTICS` 是该函数内已有的两段"纯 prompt 判据文案，reviewer 自律遵守，npc 侧不做字段级强制校验"的先例。

用户在盘问阶段已就三个关键分歧点拍板（见下方 Pattern Mapping），核心结论：(c) 显式修订 `spec-attribution` capability 的两条既有 Requirement（窄化范围）；(b) 最初拍板方向是"schema 条件必需字段 + npc 侧确定性降级"，但 spec 语义评审 Round 4 发现该方向与"缺失即降级"的实时语义直接矛盾（schema 条件必需会让缺失字段的 review 在到达 `parse_review()` 之前就以 `invalid_review_schema` 重试失败告终），经用户裁决修订为：**`trigger_evidence` 是 schema 可选字段（不进 `required`、不做条件必需），"缺失/空串/占位符即降级"的判定全部确定性落在 `parse_review()`**，原"历史重放兜底降级"分支与实时路径合并为同一条规则；(c) 的降级例外是 `severity == critical` 不降级；本轮就新增降级相关的 telemetry 计数。

## Goals / Non-Goals

**Goals：**

- coder 侧 `SELFCHECK_RUBRIC_MD` 的 `validation` 类目细化为四个具体检查点，帮助 round 0 前置消化常见 validation 类问题。
- `REVIEW_SCHEMA` 新增 `trigger_evidence` 字段，**可选**（不进 `required`、不做 `category == "validation"` 的条件必需）；`parse_review()` 对该字段缺失键/为 `None`/为空字符串/为占位符 `"-"` 的 validation blocking 候选 finding 确定性降级为 advisory——这是 `trigger_evidence` 语义生效的唯一判定入口，Round 4 spec 语义评审裁决修订：不再有 schema 级强制路径与之并存。
- `parse_review()` 对 `spec_attribution == "spec-silent"` 且 `severity != "critical"` 的 blocking 候选 finding 确定性降级为 advisory；`severity == "critical"` 的 spec-silent finding 不降级。
- `openspec/specs/spec-attribution/spec.md` 的「spec 归因不参与 blocking 判定」「派生 spec 归因分布并向后兼容」「本 change 不引入任何闸门」三条 Requirement 被显式修订：前两条分别窄化降级适用范围、改写统计范围为降级后集合，明确承认本 change 定义的这一例外；第三条确认不构成新增闸门；其余语义不变。（Q1 裁决原文只提及两条 Requirement——统计范围矛盾是本 change 后续 spec 语义评审发现并修复的第三处，见「派生 spec 归因分布并向后兼容」Requirement 正文。）
- `parse_review()` 与 `review.round` telemetry 事件新增降级计数，供后续 `spine-analyze` 评估两条策略的实际效果。

**Non-Goals：**

- 不对 `trigger_evidence` 的内容做语义质量判断，只做确定性的"是否为空/占位符"判断。
- 不扩展降级规则到 `spec-ambiguous`/`spec-contradicted`/`impl-deviation`。
- 不改变 `category != "validation"` 的 finding 的 blocking 判定逻辑（`trigger_evidence` 举证门槛仅约束 validation 类；`spec-silent` 非 critical 降级规则与 `category` 无关，跨所有 category 生效，不受本条约束）。
- 不新增失败原因码、退出码或下游 gate；`downgrade_counts` 仅用于可观测性，不驱动任何阻断/阈值/`auto-decide` 触发条件。`REVIEW_SCHEMA` 新增的 `trigger_evidence` 是可选字段（Round 4 裁决：不进 `required`、不做条件必需），因此**不会**新增任何可触发 `invalid_review_schema` 重试-失败路径的 schema 违例条件——该字段缺失与否完全不影响 schema 校验结果，唯一的判定/后果全部发生在 `parse_review()` 内（见 `validation-blocking-threshold/spec.md`「validation 类 finding 携带可选的触发证据字段」Requirement 与 Migration Plan 第 1 条）。
- `verdict` 字段本身的取值枚举（`approve`/`passed-with-advisory`/`changes-requested`）与其在下游（telemetry、gate 判定）的既有消费方式不变；**但**（见 D6）`_recompute_verdict`/`parse_review()` 用于推导 `verdict` 的输入集合 MUST 改为降级后的最终 blocking 集合，而不是原始 `severity`/`in_scope`，以避免 `blocking == 0` 与 `verdict == "changes-requested"` 同时成立的矛盾——`merge_review_passes`/`_recompute_verdict`/`parse_review()` 的**内部推导逻辑**因此必然联动修改，本 change 保持不变的只是三态枚举与外部键名/调用签名这一层"对外契约"。

## Pattern Mapping

> 本段落原样带入 `pattern-interrogation.md` 的 `## Open Questions` 与 `## User Decisions (Interactive)`（该文件含 `## User Decisions (Interactive)` 标题，按契约取该分支）。

### Open Questions

- **(c) 与既有 spec 冲突如何处理**：`openspec/specs/spec-attribution/spec.md` 明确禁止 `spec_attribution` 参与 blocking 判定、禁止本类改动引入任何闸门。本 change 的 (c) 目标与该约束直接矛盾——是否确认本 change 要在 spec delta 里显式 **修订/废止** 该 capability 的这两条 Requirement？若是，修订后的语义边界（例如"仅 spec-silent 降级，spec-ambiguous/spec-contradicted/impl-deviation 不受影响"）需要用户确认。
- **(c) 的降级规则是否有例外**：spec-silent 且 severity=critical 的 finding 是否也一律降级为 advisory，还是仅对 severity=high 生效？降级后 verdict 计算（`_recompute_verdict`）是否需要同步调整语义描述（当前 `changes-requested` 的定义是"至少 1 个 in_scope blocking"，降级后这条定义本身不变，只是 blocking 集合缩小）？
- **(b) 的"可触发的具体输入或调用路径"是否需要 schema 强制**：是否满足于纯 prompt 层面的判据文案（reviewer 自律填写在 `detail`/`recommendation` 里），还是需要在 `schema.REVIEW_SCHEMA` 新增一个针对 `category == "validation"` 的条件必需字段（如 `trigger_evidence`）以便 npc 侧做确定性兜底（例如缺失该字段时自动把 severity 降级）？后者工程量显著更大（需要 JSON Schema 条件校验 + `ensure_schema` 迁移 + `parse_review` 兜底逻辑），需要用户确认优先级。
- **(a) 的自查清单粒度**：是扩写 `SELFCHECK_RUBRIC_MD` 现有 `validation` 一行为四个子要点（边界值/None/类型/外部输入），还是保持单行、只补充措辞？是否需要与 (b) 的 reviewer 判据措辞做一次交叉核对，确认没有违反 `implement-selfcheck-rubric` spec 的「严守生成 ⊥ 验证边界」Requirement（即 coder 侧清单不能泄漏 reviewer 侧"是否附带可触发路径"这类验证方判据）？
- **降级是否需要 telemetry 可观测性**：`spec-attribution` capability 已有 `spec_attributable_blocking_rate` 聚合指标；(c) 引入降级后，是否需要新增一个 telemetry 字段（如"因 spec-silent 被降级的 finding 数"）以便后续评估这条策略的实际效果，还是本轮不做可观测性、留给后续 change？

### User Decisions (Interactive)

#### Q1 (c) 与 spec-attribution capability 的冲突
问题：openspec/specs/spec-attribution/spec.md 规定"spec 归因不参与 blocking 判定、不引入任何闸门"，与 (c) 直接矛盾。
用户裁决：**修订旧 spec，限定范围**。在本 change 的 spec delta 里显式修订该 capability 的这两条 Requirement，将新语义窄化为：仅 `spec-silent` 归因参与降级；`spec-ambiguous` / `spec-contradicted` / `impl-deviation` 一律不受影响，继续遵守原约束。

#### Q2 (b) 证据门槛的强制形态
问题：validation 类 blocking 必须附"可触发的具体输入或调用路径"——纯 prompt 判据还是 schema 强制？
用户原始裁决：**schema 条件必需字段**。REVIEW_SCHEMA 针对 `category == "validation"` 新增条件必需字段（如 trigger_evidence）；缺失该字段时由 npc 侧确定性降级 severity，不依赖 reviewer 自律。与建议 1 change（review-delta-convergence）"npc 侧确定性兜底"的取向保持一致。

> **Round 4 spec 语义评审修订**：上述"schema 条件必需"方向与"缺失即降级"的实时语义直接矛盾——schema 条件必需会使缺失该字段的 review 在到达 `parse_review()` 之前就以 `invalid_review_schema` 重试失败告终，永远不会进入降级分支。经用户就该 blocking finding 裁决：**`trigger_evidence` 改为 schema 可选字段（不进 `required`、不做条件必需）；"缺失/空串/占位符即降级"的全部判定确定性落在 `parse_review()`**，原"历史重放兜底降级"分支与实时路径合并为同一条规则。本节以下 Decisions（D2）与 `specs/validation-blocking-threshold/spec.md` 均已按此修订裁决重写；本条修订同时构成对本 Q2 原选择的正式替代。

#### Q3 (c) 降级的严重度例外
问题：spec-silent 且 severity=critical 的 finding 是否也降级？
用户裁决：**critical 不降级**。spec-silent 且 severity=critical 的 finding 保持 blocking（安全/数据丢失类问题不应因 spec 未覆盖而放行）；仅 high 及以下参与降级。

#### Q4 降级的 telemetry 可观测性
问题：本轮是否新增降级相关指标？
用户裁决：**本轮就加**。新增"因 spec-silent 降级的 finding 数"与"因缺证据降级的 finding 数"的可观测字段，使后续 spine-analyze 能验证本策略的实际效果。

### 交叉约束提醒（源自 Q4 盘问项）
(a) 的 coder 侧自查清单 MUST NOT 泄漏 reviewer 侧判据（如"是否附带可触发路径"），以遵守 implement-selfcheck-rubric spec 的「生成 ⊥ 验证边界」Requirement。

### 落地映射（本 change 如何兑现四条裁决）

- Q1 → 见 Decisions D3：`openspec/specs/spec-attribution/spec.md` 的三条 Requirement（含统计范围改写的「派生 spec 归因分布并向后兼容」，为 spec 语义评审修复项）在本 change 的 spec delta 中以 `## MODIFIED Requirements` 形式重写，新增"仅 spec-silent 参与、其余三值不受影响"的窄化语义与"统计范围随降级收窄"的一致性语义。
- Q2 → 见 Decisions D2（已按 Round 4 修订裁决重写）：`REVIEW_SCHEMA` 新增 `trigger_evidence` **可选**字段（不进 `required`、不做条件必需），`parse_review()` 对缺失键/`None`/空值/占位符统一做确定性降级。
- Q3 → 见 Decisions D4：`parse_review()` 的降级判据显式排除 `severity == "critical"`。
- Q4 → 见 Decisions D5：`parse_review()` 返回值新增 `downgrade_counts`，经 `emit_review_round` 传入 `review.round` telemetry 事件，`EMIT_FIELD_CONTRACT`/`telemetry_schema_v1.json` 同步登记，`npc telemetry agg` 聚合累计计数。

## Decisions

**D1：`SELFCHECK_RUBRIC_MD` 的 `validation` 行细化为四个检查点，保持单一常量、不新增独立段落。**

```
| validation | 边界值（空集合/零值/极值/上下界）是否已校验；None/空值/缺省参数是否显式处理；类型是否符合预期（含隐式转换风险）；外部输入（用户输入、HTTP 请求体、文件内容、环境变量、第三方 API 响应）是否在信任边界处被校验，非法输入是否快速失败并给出明确错误 |
```

四个检查点保持在同一表格行内（逗号/分号分隔的自然语言列举，不拆成四个类目），维持 `implement-selfcheck-rubric` spec 定义的"单一事实源、类目层级清单"结构——不新增第二份并行清单。措辞 MUST NOT 出现"可触发的具体输入或调用路径"/"trigger_evidence"等 (b) 的 reviewer 侧措辞，避免生成 ⊥ 验证边界被打穿（交叉约束提醒）。

备选是仿照 `ATOMIC_ADD_DISCIPLINE_MD` 新增独立强约束段；放弃，因为 pattern-interrogation Assumptions 已确认细节应保持在既有 `SELFCHECK_CATEGORIES`/`SELFCHECK_RUBRIC_MD` 的"类目清单"抽象内，不产生第二份清单。

**D2（Round 4 修订 + Round 5 修订）：`REVIEW_SCHEMA` 为 `trigger_evidence` 新增一个纯可选字段，类型为 `["string", "null"]`；MUST NOT 使用 `allOf`/`if`/`then` 对 `category == "validation"` 做条件必需。字段是否存在、是否为 `null`、是否非空的全部判定确定性落在 `parse_review()`，与 schema 校验结果无关。**

原始设计（schema `allOf`/`if`/`then` 条件必需）在 Round 4 spec 语义评审中被判定为 blocking：条件必需会使缺失 `trigger_evidence` 的 validation finding 在 schema 校验阶段就失败，触发既有 `_execute_review_pass()` 重试机制，重试预算耗尽后以 `invalid_review_schema` 结束整轮 review——该 review **永远不会到达** `parse_review()`，因此"缺失即降级为 advisory"的承诺在实时路径上根本无法兑现，与 proposal/design 反复声明的"确定性降级"语义直接矛盾。经用户就此裁决：改为纯可选字段。

**Round 5 追加修订（F1）**：Round 4 落地时字段类型仍只声明 `"type": "string"`，而降级判据的四个分支之一是显式 `null`。若类型只允许 `string`，显式 `trigger_evidence: null` 的 finding 会在 schema 校验阶段被类型不匹配拒绝，重演 Round 4 同样的"schema 拒绝 vs 确定性降级"矛盾（只是触发值从"缺失"换成了"显式 null"）。经裁决：类型改为 `["string", "null"]`，使 `null` 与缺键、空串、占位符统一只经过 `parse_review()` 的降级判定，不存在 schema 拒绝分支。

`REVIEW_SCHEMA["properties"]["findings"]["items"]` 新增：

- `properties.trigger_evidence`：`{"type": ["string", "null"], "description": "建议描述可复现该问题的具体输入值 / 请求体 / 调用序列 / 参数组合；category == validation 时若缺失、为 null、为空或仅填占位符 \"-\"，该 finding 会被 parse_review() 侧确定性降级为 advisory"}`。
- `additionalProperties` 保持 `false`（既有约束不变），因此该属性必须声明在 `properties` 中才能被任意 finding 携带（含非 validation 类想选填的场景）。
- **不新增 `required`/`allOf`/`if`/`then` 条件规则**：`trigger_evidence` 对所有 `category` 取值都是可选字段，key 可以完全不存在、值可以是 `null` 或任意字符串（含空字符串），schema 校验结果不受该字段影响。
- **不使用** `minLength: 1`：与"不做条件必需"一致，schema 层完全不介入该字段的存在性/非空性判断。

`parse_review()` 是 `trigger_evidence` 语义生效的唯一入口：对 `category == "validation"` 的 blocking 候选 finding，若该字段缺失键、为 `None`、去除首尾空白后为空字符串、或等于占位符 `"-"`，一律确定性降级为 advisory（见 D3）。**不存在**"实时路径 vs 历史重放路径"两套判定分支——四个判定分支（键不存在/`None`/空字符串/占位符）在任意输入（实时生成的 review、历史 `round-N.review.json` 重放、测试直接构造的 dict）上都适用同一条规则，因为 schema 层从不拒绝缺失该字段的 review，缺失键在实时流程中同样可达。

**MUST NOT** 修改 `SPEC_REVIEW_SCHEMA`（无 `category`/`in_scope`/`spec_attribution`/`trigger_evidence` 概念，spec review 不受本 change 影响）。

`src/npc/focus.py::_output_requirements_block()` 新增常量 `VALIDATION_EVIDENCE_REQUIREMENT_MD`（对齐 `SPEC_ATTRIBUTION_ENUM_SEMANTICS`/`STUB_AND_TEST_TAMPERING_BLOCKING` 先例，同一函数内追加一行）：

```
VALIDATION_EVIDENCE_REQUIREMENT_MD = "validation 类 finding 必须在 trigger_evidence 字段写明可复现该问题的具体输入值/请求体/调用序列/参数组合（例如\"传入 limit=-1\"、\"请求体缺 Content-Type 头\"）；trigger_evidence 缺失、为空、或仅填占位符 \"-\" 时，该 finding 会被 npc 侧确定性降级为 advisory，不计入 blocking，即使 severity 为 critical/high。"
```

该文案追加到 `_output_requirements_block()` 现有的字段含义列表之后（`spec_attribution` 说明行之后、`STUB_AND_TEST_TAMPERING_BLOCKING` 之前或之后均可，采用"字段含义列表内追加一行"的既有排版，具体见 tasks.md 实现细节），对 round 0 / round N / 对抗式 pass 三处调用统一生效（`_output_requirements_block()` 是三者共享的单一来源）。

备选是只在 round N（re-review）模板追加，round 0 不追加；放弃，因为 round 0 同样可能产出 validation 类 blocking finding，举证门槛应从第一轮就生效，且 `_output_requirements_block()` 三处统一生效正是既有 `spec_attribution`/`STUB_AND_TEST_TAMPERING_BLOCKING` 两个先例的一致模式。

**D3：`parse_review()` 新增两条独立的降级判据（validation 缺证据 + spec-silent 非 critical），均在"计入 blocking 前"生效，advisory 计数相应增加；`blocking_findings` 排序与既有语义不变。**

`parse_review()` 现有主循环对每条 finding 判断 `sev in BLOCKING_SEVERITIES and in_scope` 决定进入 `blocking_list` 还是 `advisory_count`；本 change 在此基础上新增两个独立的降级谓词：

```python
def _validation_evidence_missing(f: dict) -> bool:
    if f.get("category") != "validation":
        return False
    ev = f.get("trigger_evidence")
    if ev is None:
        return True
    stripped = ev.strip() if isinstance(ev, str) else ""
    return stripped == "" or stripped == "-"


def _spec_silent_non_critical(f: dict) -> bool:
    return f.get("spec_attribution") == "spec-silent" and f.get("severity") != "critical"
```

一条 blocking 候选 finding（`sev in BLOCKING_SEVERITIES and in_scope`）若满足 `_validation_evidence_missing(f) or _spec_silent_non_critical(f)` 中任一条，MUST 从 `blocking_list` 移入 `advisory_count`（即：先按既有条件判断是否为 blocking 候选，候选内再按两条降级谓词做二次过滤）。两条谓词以逻辑 OR 组合（满足任一即降级），互不排斥、互不依赖顺序。

**（Round 6 spec 语义评审修订，F1）**：`_validation_evidence_missing` 第 117 行 `stripped = ev.strip() if isinstance(ev, str) else ""` 对任意非字符串、非 `None` 的 `trigger_evidence`（如数字 `0`、布尔 `false`、列表、字典）一律落入 `else` 分支得到空字符串，从而与缺键/空串/占位符走同一条"证据不足→降级"路径判定为 `True`。这是本 change 对该类型域的**确定性契约**：任意非字符串、非 `null` 的值一律视为"证据不足"，不视为有效证据、也不做拒绝——与 `specs/validation-blocking-threshold/spec.md`「validation 类 finding 缺失触发证据时降级为 advisory」Requirement 新增的第五个判定分支（非字符串非 `null`）严格对齐，两份 artifact 不再矛盾。

`spec_attribution_counts` 的统计范围 MUST 变为"仅统计降级后最终仍计入 `blocking` 的 finding"（即被降级的 finding 不再计入 `spec_attribution_counts`）。既有 `openspec/specs/spec-attribution/spec.md`「派生 spec 归因分布并向后兼容」Requirement 把统计范围字面定义为"与 `blocking` 一致（仅统计 `in_scope == true` 且 `severity ∈ {critical, high}` 的 finding）"——这是**降级前的候选集合**定义；本 change 引入降级后，"blocking 候选集合"与"降级后最终 blocking 集合"不再等价，若不显式修订该 Requirement，会与 `parse_review()` 的实际行为（降级 finding 不再计入 `spec_attribution_counts`）产生矛盾。因此本 change 在 `spec-attribution` capability 的 delta 中新增第三条 `## MODIFIED Requirements`：把该 Requirement 的统计范围定义从"blocking 候选集合"改写为"降级后最终 blocking 集合"，并补充"因窄化例外或 validation 举证门槛被降级的 finding 不计入 `spec_attribution_counts`（含 `unknown` 键）"的显式场景（含 spec-silent 降级、validation 缺证据降级两个方向）。

备选是把两条降级判据做成"改写 finding 的 severity 字段"（如把 `severity` 从 `high` 改写为 `low`）；放弃，因为 `parse_review()` 的既有契约是"不修改/丢弃任何 finding 记录本身"（`round-N.review.json` 落盘内容与引擎原始输出一致），只影响派生的 `blocking`/`advisory` 计算结果——与 `review-delta-convergence` change D3 的"`pre-existing-new` 不修改 finding 记录本身"是同一原则，保持一致更利于未来两个能力共存时的可预测性。

**D4：`severity == "critical"` 的 spec-silent finding 不降级；`_spec_silent_non_critical` 的排除条件是 `severity != "critical"`（等价于对 `high` 生效，`medium`/`low` 本就不是 blocking 候选，不受此谓词实际影响）。**

`BLOCKING_SEVERITIES = {"critical", "high"}`（既有常量不变），故进入降级判定的 finding 的 `severity` 只可能是 `critical` 或 `high` 两者之一。`_spec_silent_non_critical` 的判据 `severity != "critical"` 在此前提下等价于"仅 `severity == high` 触发降级"，与 Q3 裁决"仅 high 及以下参与降级"字面一致（`medium`/`low` 从不进入 blocking 候选池，天然不受影响，不需要额外分支处理）。

**D5：`parse_review()` 返回值新增 `downgrade_counts: {"validation_missing_evidence": int, "spec_silent_non_critical": int}`；两个计数各自独立统计触发对应谓词而被降级的 finding 数（一条 finding 若同时满足两条谓词，两个计数各自 +1，不做互斥去重——用于观测哪条策略实际生效更多，允许重叠计数）。该键新增遵循 `spec_attribution_counts` 的既有传递路径。**

`review.round` telemetry 事件（`src/npc/telemetry.py::emit_review_round`）新增可选参数 `downgrade_counts: dict[str, int] | None = None`（默认 `None`，对齐 `spec_attribution_counts` 参数签名与调用约定），写入事件字典的 `downgrade_counts` 键；`EMIT_FIELD_CONTRACT["review.round"]` 新增 `"downgrade_counts"`；`src/npc/telemetry_schema_v1.json` 的 `review.round` 相关 `properties` 新增 `downgrade_counts`（`type: ["object", "null"]`，`additionalProperties: {"type": "integer", "minimum": 0}`，`description` 说明两个计数键含义，镜像 `spec_attribution_counts` 的既有 schema 条目结构）；`src/npc/pipeline.py::run_review_round` 的两处 `emit_review_round` 调用点（`invalid_review_schema` 失败路径传 `None`，成功路径传 `metrics.get("downgrade_counts")`，镜像既有 `spec_attribution_counts` 两处调用点的传参模式）。

`npc telemetry agg` 的聚合逻辑（`src/npc/telemetry.py` 中处理 `kind == "review.round"` 事件的聚合分支）新增对 `downgrade_counts` 的逐 key 累加（`defaultdict(int)`，镜像既有 `spec_attribution_counts` 的聚合实现：缺该字段的历史事件被忽略、不抛异常、不影响其它字段聚合），输出键沿用 `downgrade_counts`（聚合后的字典，不额外派生比率——本轮 Non-Goals 已声明不引入新阈值/闸门，只做原始计数观测）。

备选是把 `downgrade_counts` 拆成两个独立 telemetry 字段（`downgraded_by_missing_evidence` / `downgraded_by_spec_silent`）；放弃，因为字典形式与 `spec_attribution_counts` 的既有模式（单一字典字段、内部多键）保持结构一致，减少 `EMIT_FIELD_CONTRACT`/schema 新增顶层字段的数量，也便于未来在同一字典内追加新的降级原因而不再动 schema 顶层结构。

**D6：`verdict` 的推导 MUST 统一改为基于降级后的最终 blocking 集合，单 pass（`parse_review()`）与双 pass 合并（`merge_review_passes()` → `_recompute_verdict()`）两条路径共享同一判定逻辑，`parse_review()` 不再透传引擎自报的 `verdict` 值。**

问题根因：D3 引入的两条降级谓词只改变了 `blocking`/`blocking_findings`/`advisory` 计数，但 `verdict` 字段在两条既有路径上都不感知降级——单 pass 路径（`parse_review()` 第 63 行 `"verdict": review_json.get("verdict")`）直接透传引擎自报值（引擎生成 review 时并不知道 npc 侧会做降级判定，其自报 verdict 仍按原始 `severity`/`in_scope` 计算）；双 pass 合并路径（`merge_review_passes()` → `_recompute_verdict(renumbered)`）在合并后的原始 findings 全集上按 `severity`/`in_scope` 重算，同样不感知降级。两条路径都可能在"该轮的全部 blocking 候选恰好都被降级"时产出 `blocking == 0` 但 `verdict == "changes-requested"` 的矛盾结果——而 `verdict` 是 `pipeline.py` 用于日志/gate 展示的关键字段（`run_review_round` 第 965/991 行），矛盾会直接体现在 `npc review` 的输出与 telemetry 中。

修复方案：

- 在 `review.py` 内新增一个模块级 helper（如 `_is_effective_blocking(f)`），逻辑为 `sev in BLOCKING_SEVERITIES and in_scope and not (_validation_evidence_missing(f) or _spec_silent_non_critical(f))`——即"既是候选、又未被任一降级谓词命中"。
- `parse_review()` 主循环改用该 helper 判断一条 finding 是否进入 `blocking_list`（等价于 D3 已描述的"候选内二次过滤"，只是抽成显式命名的谓词，便于 `verdict` 复用同一判定）。
- `parse_review()` 的返回值 `"verdict"` 键改为：`"changes-requested"`（若 `blocking_list` 非空）/`"passed-with-advisory"`（若 `blocking_list` 为空但 `findings` 非空）/`"approve"`（若 `findings` 为空）——**不再**读取 `review_json.get("verdict")`。
- `_recompute_verdict(findings)` 的 `has_blocking` 判定改为对每条 finding 调用 `_is_effective_blocking(f)`，而不是原来的 `f.get("severity") in BLOCKING_SEVERITIES and bool(f.get("in_scope"))`；`merge_review_passes()` 调用点不变（仍是 `_recompute_verdict(renumbered)`），因逻辑改在 `_recompute_verdict` 内部生效。
- `merge_review_passes()` 的 `adversarial_blocking_count`（side-channel 统计，仅用于 telemetry 观测 pass2 独有贡献的 blocking 候选数）保持原有"按原始 severity/in_scope 计数、不感知降级"的既有语义不变——这是一个独立的可观测性统计，不参与 `verdict`/`blocking` 判定，代码层面不属于本 Decision 的修改范围。**但**（Round 5 spec 语义评审修订，F3）该字段命名含"blocking"，若不显式裁决其语义边界，会与 D6 引入的"`verdict`/`blocking` 均基于降级后集合"产生表述矛盾（同一字段名下，一个是候选层数字、一个是降级后数字）。因此本 change 新增 `openspec/specs/review-adversarial-pass/spec.md` 的 MODIFIED Requirements delta，显式裁决 `adversarial_blocking_count` 语义为"pass2 贡献的原始 blocking 候选数，不感知降级、MUST NOT 被消费为最终 blocking 数"，并同步修订该 capability「findings 合并去重规则确定性」Requirement 第 3 条的 `verdict` 重算规则（改为基于降级后集合，与 D6 一致）——详见对应 spec delta 文件与 tasks.md 6.4。

`tests/test_review.py` 既有 `test_parse_review_counts`（第 63-67 行）使用的 `SAMPLE_REVIEW` 中 F1 是 `category="validation"` 且不含 `trigger_evidence` 键，在 D3+D6 落地后会被降级，该用例需要同步更新（`blocking` 从 2 变为 1、`advisory` 从 2 变为 3、`verdict` 需按新推导规则更新为该场景对应的值）——tasks.md 已将其纳入"既有用例集合保持全绿"的回归防护范围，实现阶段需按新语义调整该 fixture 或新增独立 fixture 隔离验证，避免既有测试与新语义冲突却被误判为"未回归"。

## Risks / Trade-offs

- **[trigger_evidence 举证质量不受 npc 校验]** 与 Non-Goals 一致：reviewer 可以填一段看似非空但实际无意义的文本（如"存在边界问题"）规避降级。npc 侧只做"是否为空/占位符"的确定性判断，不做语义质量判断——与既有 `severity`/`in_scope`/`spec_attribution` 的信任模型一致，不是本 change 引入的新风险面。
- **[trigger_evidence 为纯 schema 可选字段，reviewer 完全不写也能通过 schema 校验]** Round 4 修订放弃了 schema 条件必需，意味着 schema 层不再对"reviewer 是否填写该字段"施加任何压力——这个压力完全转移到 `_output_requirements_block()` 的 prompt 文案与 `parse_review()` 的确定性降级结果上（reviewer 若不填，其 validation blocking finding 会被降级为 advisory，间接激励其填写）。这是用户显式裁决的取舍：确定性优先于"强制"，schema 强制曾经制造的"缺失即整轮失败"风险已被消除。
- **[spec-silent 降级可能放行真实 bug]** 若某 validation 类 finding 的根因确实是 spec 未覆盖，但实现本身也存在 bug（不仅是 spec 缺失），severity=high 时会被降级为 advisory，需要人工从 `round-N.review.json` 或后续 advisory 渲染中发现。缓解：finding 本身不丢弃、仍完整落盘，`severity == critical` 的高危场景不受影响，且这是用户显式裁决的窄化范围（仅 spec-silent 参与，仅 high 及以下降级）。
- **[两条降级谓词重叠计数可能导致 `downgrade_counts` 之和大于实际降级 finding 总数]** D5 显式选择"不互斥去重"，若后续需要精确的"总降级 finding 数"指标，需要在聚合层或新的 telemetry 字段中另行定义交集处理逻辑，本 change 不做（超出 Goals 范围，留给后续 change 按需求扩展）。
- **[`parse_review()` 不再透传引擎自报 verdict，行为变化面比表面看起来大]** D6 是本 change 修复 F2 矛盾后新增的行为变化：`parse_review()` 在此之前对任意输入（包括无任何降级发生的场景）都直接信任引擎自报的 `verdict`；D6 落地后一律由 npc 侧重算。理论上，若引擎自报 verdict 与其自身 findings 按 `severity`/`in_scope` 计算的结果本就不一致（引擎计算错误或字段被篡改），旧行为会透传错误值、新行为会纠正为正确值——这是行为改善而非风险，但意味着 `verdict` 字段的"数据来源"从"引擎自报"变为"npc 侧确定性推导"，若后续有代码/文档假设 `verdict` 是引擎自报值（例如期待其能反映引擎自身的置信度差异），需要同步确认不受影响。范围内检索（`rg -n "\.get\(\"verdict\"\)\|\[.verdict.\]"`）确认现有下游消费方只做三态判定，未依赖"是否为引擎自报"这一区分。

## Migration Plan

1. `REVIEW_SCHEMA` 新增 `trigger_evidence` **可选**属性（不含任何 `required`/`allOf`/`if`/`then` 条件规则）会被 `ensure_schema`（内容比对触发重写）自动同步到 `~/task_log/.new-plan-review-schema.json`，无需手工迁移；由于该字段不是必需的，引擎产出缺失该字段的 validation finding **不会**触发 `_execute_review_pass()` 的既有重试-失败机制（`invalid_review_schema`）——该字段的缺失完全不影响 schema 校验结果，一律正常进入 `parse_review()` 由其确定性降级（见「validation 类 finding 携带可选的触发证据字段」Requirement）。
2. 历史 `round-N.review.json`（本 change 落地前生成，不含 `trigger_evidence` 字段）与本 change 落地后新生成、同样缺失该字段的实时 review，在 `parse_review()` 眼中是**同一种输入**、适用**同一条规则**：`parse_review()` 是纯函数，不做 schema 校验，`_validation_evidence_missing` 对"键不存在"（`ev is None → True`）与"新生成但值为空字符串"两个分支一视同仁地判定为证据缺失、确定性降级——不存在"历史重放专属兜底分支"与"实时专属路径"的区分，两者已被 Round 4 裁决合并为同一条规则，因为 schema 层从不拒绝缺失该字段的 review，历史与实时输入在这一点上完全对称。
3. `downgrade_counts` 为新增返回键/telemetry 字段，历史 `review.round` 事件缺该字段时，`npc telemetry agg` 的聚合逻辑 MUST 兼容（键缺失时该事件对聚合结果的贡献为 0，不抛异常），镜像 `spec_attribution_counts` 既有的向后兼容处理。
4. `verdict` 推导来源变更（D6：从"透传引擎自报值"改为"npc 侧基于降级后 blocking 集合重算"）对历史 `round-N.review.json` 文件本身无影响（文件落盘内容不受 `parse_review()` 计算逻辑变化影响）；但对该文件重新调用 `parse_review()`/`npc review parse` 得到的**派生**`verdict` 值可能与该文件落盘时的原始自报值不同，这是预期的行为修正，不需要额外兼容分支。
5. 回滚：移除 D1-D6 增量代码即可；`REVIEW_SCHEMA`/`telemetry_schema_v1.json` 的字段回滚会影响所有后续生成的 review JSON/telemetry 事件（新字段消失），历史已生成的数据不受影响（`ensure_schema` 幂等重写、telemetry 事件不做回填）。

## Open Questions

无。四条关键裁决已在 Pattern Mapping 段落记录并在 Decisions D1-D5 中兑现。
