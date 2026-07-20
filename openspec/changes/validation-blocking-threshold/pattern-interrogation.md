# Pattern Interrogation — validation-blocking-threshold

## Analogs

- **(a) coder 侧 validation 自查清单** — `src/npc/templates.py::SELFCHECK_RUBRIC_MD`（单一事实源常量，第 43-60 行）已经是「静态通用自检类目清单」，其中 `validation` 一行现文案为「所有外部入参 / 边界值是否已校验；非法输入是否快速失败并给出明确错误」。该常量被 `render_implementer`（第 116 行起，第 164 行注入）与 `render_fixer`（第 248 行起，第 340 行注入）同时引用，两处 prompt 共享同一份文案——这正是 (a) 要求的「固定清单」的既有落点形态。对应的 spec 能力是 `openspec/specs/implement-selfcheck-rubric/spec.md`（由 change `reduce-review-fix-cost` 归档），其 Requirement「implement/fix prompt 注入静态通用自检 checklist」与「严守生成 ⊥ 验证边界，不注入 per-change review 判据」明确约束了这类清单的写法：只能是 change-无关的通用类目，不能引用当次 review focus 或 reviewer 判据文案。
- **独立强约束段的先例** — `ATOMIC_ADD_DISCIPLINE_MD`（`templates.py:70-90`）展示了「新增一段独立的 Markdown 强约束常量，供 implement/fix 两处 prompt 共享」的既有模式；若 (a) 要求的 validation 清单需要比现有单行更细（边界值/None/类型/外部输入 4 个子项），可参照此形态新增专属常量，或直接扩写 `SELFCHECK_RUBRIC_MD` 中 `validation` 一行的文案粒度——两条路径仓库里都有先例。
- **(b) reviewer focus 侧的 blocking 判据文案** — `src/npc/focus.py::STUB_AND_TEST_TAMPERING_BLOCKING`（第 193 行）+ `_output_requirements_block()`（第 196-222 行）是「reviewer 侧纯 prompt 级判据，不由 npc 确定性代码校验，只靠 reviewer 自己在生成的 JSON 里遵守」的既有形态：现在的「反 stub / 反删测判据」一句话文案被注入 round-0 / round-N / adversarial 三种 focus 模板，要求 reviewer 在给 severity 定级时遵循特定启发式。(b) 要求「validation 类 blocking 必须附带可触发的具体输入或调用路径，否则降级为 advisory」在结构上与此完全同构：都是加一段"判据文案"到 `_output_requirements_block()` 或独立注入 `_round_0_template` / `_round_n_template` / `_adversarial_round_0_template`，靠 reviewer 自律填写，npc 侧不做字段级强制校验（因为 `schema.REVIEW_SCHEMA` 的 finding 目前只有自由文本的 `detail`/`recommendation`，没有结构化的"触发证据"字段）。
- **(c) spec-silent 归因降级为 advisory 的最近似落点** — `src/npc/review.py::parse_review()`（第 29-69 行），当前 blocking 判定逻辑是 `sev in BLOCKING_SEVERITIES and in_scope`（第 51 行），`spec_attribution` 字段目前**只用于统计**（`spec_attribution_counts`），完全不参与 blocking/advisory 的二分。这正是 (c) 要求"spec-silent 归因的 finding 默认降级为 advisory"的确定性实现落点：需要在 `parse_review()`（以及配套的 `_recompute_verdict()`，`review.py:72-86`，供 `merge_review_passes` 复用）里把分类条件从 `sev in BLOCKING_SEVERITIES and in_scope` 扩展为额外排除 `spec_attribution == "spec-silent"`（或更宽的语义）。
- **与 (c) 直接冲突的既有 spec 硬约束** — `openspec/specs/spec-attribution/spec.md` 中已归档的 Requirement「spec 归因不参与 blocking 判定」明文写道：`parse_review()` 的 `blocking` 计数 MUST 继续仅由 `severity ∈ {critical, high}` 且 `in_scope == true` 决定，**`spec_attribution` 的任何取值 MUST NOT 改变某条 finding 是否计入 blocking**；另有 Requirement「本 change 不引入任何闸门」明文禁止"基于 `spec_attribution` 或 `spec_attributable_blocking_rate` 引入任何阻断、阈值、退出码变更"。这是仓库里**已确权的反向约束**，(c) 的目标与它字面冲突，必须在 design.md 里显式声明本 change 是否修订/取代该 Requirement（openspec 允许 change 修改既有 capability 的 Requirement，但必须显式建模为 delta，不能默默绕过）。
- **`categories_seen` / streak 升级机制的类比** — `src/npc/templates.py::_render_escalation_section`（第 203-247 行）+ `category_streaks` / `recurred_categories` 参数展示了"某个 category 连续出现 → 触发更强约束"的既有确定性状态机形态（来自 change `fix-prompt-exhaustive-sweep`），对应 spec `openspec/specs/coder-category-streak-sweep/spec.md`。虽然本 change 的 (c) 是"降级"而非"升级"，但两者都属于"用 finding 的 category/attribution 字段驱动确定性分类逻辑"的同一族模式，值得在 design 里对照，避免与 streak 升级逻辑产生优先级冲突（例如某 finding 既是 spec-silent 又是连续复现的 category，两条规则谁优先）。
- **schema 契约演进先例** — `src/npc/schema.py::REVIEW_SCHEMA` + `ensure_schema()`（`schema.py:160-180`）是"新增/修改 finding 必需字段"的既有事实源；`spec_attribution` 字段本身就是通过这条路径加入 schema 的（见 `openspec/specs/spec-attribution/spec.md`）。若 (b) 决定用结构化字段（而非纯 prompt 判据）表达"可触发的具体输入或调用路径"，此文件是唯一落点，需同步跑 `ensure_schema` 幂等测试（参照 `tests/test_schema.py`）。

## Assumptions

- 本次 change 的语义锚点是 prompt 里"用户原始目标"原文，`docs/optimization-proposals/2026-07-20.md` 在本 worktree 中不存在（只在另一 checkout 存在未提交草稿），故不作为必读输入，假设原文本身已完整表达意图，不需要额外读取该文档来补全语义。
- (a) 的"固定 validation 自查清单"假设应落在既有 `SELFCHECK_RUBRIC_MD` 常量内（扩写 `validation` 一行为更细粒度的边界值/None/类型/外部输入四点），而不是另起一段独立的 Markdown 块——理由是 `implement-selfcheck-rubric` spec 已把"静态通用自检类目清单"定义为单一事实源、implement/fix 共享的整体结构，新增细节应保持在同一常量内以维持"类目清单"这一既有抽象，而非产生第二份并行清单；若后续 design 阶段判断需要独立成段，会在 design.md 显式说明偏离理由。
- (b) 假设采用"纯 prompt 判据文案"路线（类比 `STUB_AND_TEST_TAMPERING_BLOCKING`），不新增 schema 结构化字段——因为"可触发的具体输入或调用路径"本质上是自然语言证据，塞进现有 `detail` 字段即可表达，无需新增 required 属性；npc 侧不做字段级确定性校验，只能在 prompt 文案层面要求，实际执行力依赖 reviewer（Codex）自身遵守。
- (c) 假设"降级为 advisory"必须实现在 `review.py::parse_review()`（及 `_recompute_verdict()`），且**必须**在 design.md 中显式声明这是对 `openspec/specs/spec-attribution/spec.md` 两条既有 Requirement（"spec 归因不参与 blocking 判定"、"本 change 不引入任何闸门"）的修订/取代，而不是静默新增一条并行逻辑——否则会产生两份互相矛盾的已归档 spec 文本，`repo-spec-lint` 类校验或人工评审会发现矛盾。
- 假设"默认降级"允许存在例外覆盖机制（如 severity == critical 时即使 spec-silent 也不降级，或反之无例外、一律降级），具体阈值/例外规则本身是需要用户拍板的设计决策，本轮盘问不预设答案，留给 Open Questions。
- 假设 (a)(b)(c) 三部分虽然分别改动 `templates.py` / `focus.py` / `review.py` 三个文件，但仍算作**一个** openspec change（`validation-blocking-threshold`），因为三者共享同一个上游动机（validation 类 blocking 治理）且用户目标描述里是作为一体提出的，不拆分为多个 change。
- 假设本 change 需要更新的测试文件对应为 `tests/test_templates.py`（(a)）、`tests/test_focus.py`（(b)）、`tests/test_review.py`（(c)，可能还需碰 `tests/test_reduce_review_fix_cost.py` 或新建 `tests/test_validation_blocking_threshold.py`），具体归档到哪个文件留给 write 轮 tasks.md 决定。

## Open Questions

- **(c) 与既有 spec 冲突如何处理**：`openspec/specs/spec-attribution/spec.md` 明确禁止 `spec_attribution` 参与 blocking 判定、禁止本类改动引入任何闸门。本 change 的 (c) 目标与该约束直接矛盾——是否确认本 change 要在 spec delta 里显式 **修订/废止** 该 capability 的这两条 Requirement？若是，修订后的语义边界（例如"仅 spec-silent 降级，spec-ambiguous/spec-contradicted/impl-deviation 不受影响"）需要用户确认。
- **(c) 的降级规则是否有例外**：spec-silent 且 severity=critical 的 finding 是否也一律降级为 advisory，还是仅对 severity=high 生效？降级后 verdict 计算（`_recompute_verdict`）是否需要同步调整语义描述（当前 `changes-requested` 的定义是"至少 1 个 in_scope blocking"，降级后这条定义本身不变，只是 blocking 集合缩小）？
- **(b) 的"可触发的具体输入或调用路径"是否需要 schema 强制**：是否满足于纯 prompt 层面的判据文案（reviewer 自律填写在 `detail`/`recommendation` 里），还是需要在 `schema.REVIEW_SCHEMA` 新增一个针对 `category == "validation"` 的条件必需字段（如 `trigger_evidence`）以便 npc 侧做确定性兜底（例如缺失该字段时自动把 severity 降级）？后者工程量显著更大（需要 JSON Schema 条件校验 + `ensure_schema` 迁移 + `parse_review` 兜底逻辑），需要用户确认优先级。
- **(a) 的自查清单粒度**：是扩写 `SELFCHECK_RUBRIC_MD` 现有 `validation` 一行为四个子要点（边界值/None/类型/外部输入），还是保持单行、只补充措辞？是否需要与 (b) 的 reviewer 判据措辞做一次交叉核对，确认没有违反 `implement-selfcheck-rubric` spec 的「严守生成 ⊥ 验证边界」Requirement（即 coder 侧清单不能泄漏 reviewer 侧"是否附带可触发路径"这类验证方判据）？
- **降级是否需要 telemetry 可观测性**：`spec-attribution` capability 已有 `spec_attributable_blocking_rate` 聚合指标；(c) 引入降级后，是否需要新增一个 telemetry 字段（如"因 spec-silent 被降级的 finding 数"）以便后续评估这条策略的实际效果，还是本轮不做可观测性、留给后续 change？


## User Decisions (Interactive)

### Q1 (c) 与 spec-attribution capability 的冲突
问题：openspec/specs/spec-attribution/spec.md 规定"spec 归因不参与 blocking 判定、不引入任何闸门"，与 (c) 直接矛盾。
用户裁决：**修订旧 spec，限定范围**。在本 change 的 spec delta 里显式修订该 capability 的这两条 Requirement，将新语义窄化为：仅 `spec-silent` 归因参与降级；`spec-ambiguous` / `spec-contradicted` / `impl-deviation` 一律不受影响，继续遵守原约束。

### Q2 (b) 证据门槛的强制形态
问题：validation 类 blocking 必须附"可触发的具体输入或调用路径"——纯 prompt 判据还是 schema 强制？
用户裁决：**schema 条件必需字段**。REVIEW_SCHEMA 针对 `category == "validation"` 新增条件必需字段（如 trigger_evidence）；缺失该字段时由 npc 侧确定性降级 severity，不依赖 reviewer 自律。与建议 1 change（review-delta-convergence）"npc 侧确定性兜底"的取向保持一致。

### Q3 (c) 降级的严重度例外
问题：spec-silent 且 severity=critical 的 finding 是否也降级？
用户裁决：**critical 不降级**。spec-silent 且 severity=critical 的 finding 保持 blocking（安全/数据丢失类问题不应因 spec 未覆盖而放行）；仅 high 及以下参与降级。

### Q4 降级的 telemetry 可观测性
问题：本轮是否新增降级相关指标？
用户裁决：**本轮就加**。新增"因 spec-silent 降级的 finding 数"与"因缺证据降级的 finding 数"的可观测字段，使后续 spine-analyze 能验证本策略的实际效果。

### 交叉约束提醒（源自 Q4 盘问项）
(a) 的 coder 侧自查清单 MUST NOT 泄漏 reviewer 侧判据（如"是否附带可触发路径"），以遵守 implement-selfcheck-rubric spec 的「生成 ⊥ 验证边界」Requirement。
