## Why

`npc telemetry hotspots` 显示 code review 是全仓库成本最高的阶段族：`review-r0`..`review-r4` 常年占据 hotspot 榜首，且 `blocking` 计数并不总是单调下降——`round_n >= 1` 的 focus 模板（`src/npc/focus.py::_round_n_template`）虽然已经注入 Already-Fixed History 并要求 reviewer「验证上轮 findings 是否被真正修复」，但没有约束 reviewer 只能对上轮遗留问题 + 本轮 fix diff 新引入问题判 blocking：reviewer 仍可在**存量代码**（既不是上轮遗留、也不是本轮 fix 改动）里随意挑出新问题判 blocking，导致 review-fix 循环因为"每轮都在打不同的地鼠"而反复拉长，而现有 `trend.py` 的 stale 机制只在 blocking 总数连续 3 轮不降时兜底止损，无法在健康收敛（旧问题清零、只是不断有轻微新发现）时提前放行。

本 change 让 `round_n >= 2` 的 review 进入 delta-review 模式：reviewer 必须显式标注每条 finding 相对本轮改动范围的来源，npc 侧对该自报做几何交叉核验并据此重算 blocking/verdict，把"存量代码新发现"强制降级为 advisory（不阻塞、随 archive 记录），并在连续两轮都没有"上轮遗留未修复"blocking 时由 npc 侧确定性把该轮 `blocking` 覆盖为 `0`（原属 blocking 的 finding 转记为 advisory，`verdict` 按既有"blocking=0 时 advisory 非空则 passed-with-advisory、否则 approve"的标准规则重新计算，不强制固定为 approve），提前结束循环。

## What Changes

- `src/npc/schema.py::REVIEW_SCHEMA` 的 finding 新增必填字段 `finding_origin`（三值枚举：`carry-over-unresolved` / `round-diff-new` / `pre-existing-new`），由 reviewer 结构化自报该 finding 相对本轮改动范围的来源；`SPEC_REVIEW_SCHEMA`（spec review）不变。该字段对 round 0/1 也必填——这是有意的破坏性 schema 变更（旧版/缺字段的 review JSON 将无法通过校验），round 0/1 唯一保持不变的是**派生的** `blocking`/`advisory`/`verdict` 计算语义，不是 JSON 结构或 prompt 输出内容本身（见 Non-Goals 与 design.md Migration Plan）。
- `src/npc/review.py::parse_review` 新增可选参数 `round_n` / `prior_blocking`：`round_n >= 2` 且提供 `prior_blocking` 时，对每条 finding 用 `file` + `category` 精确匹配、`line_range` 区间重叠匹配（而非要求三元组逐字符完全相等，以容忍修复导致的行号漂移）与上一轮**持久化的有效** blocking 集合做几何交叉核验，得到 npc 侧「有效来源」（与自报值不一致时，几何命中优先）；`pre-existing-new`（有效来源）的 finding 一律不计入 blocking，`verdict`/`blocking`/`advisory`/`blocking_findings` 在此调整后的集合上重新计算；`round_n < 2` 或未提供 `prior_blocking` 时行为与现状完全一致。
- `src/npc/focus.py::_round_n_template` 为 `round_n >= 2` 追加两部分内容，二者条件独立：(a) delta-review 分类准则说明（carry-over 判定优先、pre-existing-new 不计 blocking 的分类准则，以及 `in_scope`/`finding_origin` 是两个正交问题——前者看累计 diff、后者在 round≥2 语境下看本轮增量 diff——的说明），只要 `round_n >= 2` 就始终追加，不依赖 `round_fix_commit` 是否提供；(b) 本轮增量 diff 指令，仅当额外提供 `round_fix_commit` 时才追加（缺省时只是少一条辅助指令，分类准则说明仍然输出）。`_output_requirements_block` 补充 `finding_origin` 字段语义，对所有轮次统一生效——round 0/1 的模板输出文本因此新增一行字段说明（不是"不改变现有输出"，而是"不改变现有输出所驱动的 blocking/advisory/verdict 计算语义"）。
- `src/npc/pipeline.py::run_review_round` 在 `round_n == 2` 时读取上一轮 `round-1.review.json`、用**默认参数**（无 `round_n`/`prior_blocking`）的 `parse_review` 取其 `blocking_findings` 作为 `prior_blocking`（round 1 无 delta 概念，其 blocking 就是朴素语义）；在 `round_n >= 3` 时改为读取 state 中 `review-r{round_n-1}` 阶段 persist 的 `effective_blocking_findings`（该轮 `parse_review` 调用后得到的**最终有效** blocking 集合，已含该轮自身的 delta 降级与可能的硬收敛降级）作为 `prior_blocking`——MUST NOT 对上一轮原始 `round-{round_n-1}.review.json` 重新执行默认 `parse_review`，否则会把已被上一轮判定为 `pre-existing-new` 或已被硬收敛降级的 finding 错误地重新纳入 `prior_blocking`。`round_n >= 3` 时另读取 `carryover_unresolved_blocking`：若本轮与上一轮的该计数均为 0，npc 侧确定性覆盖本轮返回值为 `blocking=0`（原属 blocking 的 finding 转记为 advisory），`verdict` 按标准规则（advisory 非空 → passed-with-advisory；否则 → approve）重新计算，供 `plugins/agent-spine/commands/spine-run.md` 既有的 `while [ .blocking -gt 0 ]` 循环判据直接生效，不需要改动该 shell 循环本身。
- `src/npc/pipeline.py::_do_review_phase_exit_and_trend` 在 `review-rN` 的 state phase 记录中新增 `carryover_unresolved_blocking` / `hard_convergence_applied` / `effective_blocking_findings` 三个字段，供下一轮读取。
- 每个 `round_n >= 2` 的 review 轮次新增产物 `round-{round_n}.advisory-carryover.md`：汇总本轮被降级/覆盖为 advisory 的 finding（含硬收敛覆盖掉的原 blocking finding），供 archive 后人工回顾。
- 同步补齐 `tests/test_review.py` / `tests/test_focus.py` / `tests/test_pipeline.py` / `tests/test_schema.py` 对应测试。

## Capabilities

### New Capabilities

- `review-delta-convergence`：round≥2 delta-review 分类与收敛判定——`finding_origin` 自报字段与 npc 侧几何核验、存量新发现降级 advisory、连续两轮无遗留 blocking 的硬收敛覆盖、advisory carryover 持久化产物。

### Modified Capabilities

- `review-adversarial-pass`：不修改其行为，但其复用的 `merge_review_passes` 内部去重键函数与本 change 新增的模块级 `_finding_key`（精确三元组，供 `merge_review_passes` 既有的同轮去重场景使用，语义不变）共享同一实现；跨轮 carry-over 匹配是另一个新增函数 `_is_carry_over_match`（`file`/`category` 精确匹配 + `line_range` 区间重叠），二者用途不同、互不替代（仅内部重构，不改变 round-0 双 pass 合并的既有契约）。

## Impact

- **评审执行链路**：`src/npc/review.py`（`parse_review` 签名扩展、新增 `_finding_key`/`_is_carry_over_match`/`FINDING_ORIGIN_VALUES`）、`src/npc/schema.py`（`REVIEW_SCHEMA.finding_origin`）、`src/npc/focus.py`（`_round_n_template` delta 规则块、`_output_requirements_block` 字段说明，round 0/1 模板输出因此变化）、`src/npc/pipeline.py`（`run_review_round` 跨轮读取 + 硬收敛覆盖、`_do_review_phase_exit_and_trend` 新增 state 字段、`_render_focus` 传递本轮增量 diff commit）。
- **state 结构**：`progress[].phases["review-rN"]` 新增 `carryover_unresolved_blocking` / `hard_convergence_applied` / `effective_blocking_findings` 字段（向后兼容，历史轮次缺该字段按 `None`/`False`/`None` 处理——`effective_blocking_findings` 缺失时传给 `parse_review` 的 `prior_blocking` 为 `None` 而非 `[]`，等价于 `round_n < 2` 的降级路径，完全禁用几何核验、信任原 verdict；`[]` 会走满足几何核验条件但无历史 blocking 可匹配的不同分支，二者语义不同，详见 design.md D5/Migration Plan 与 spec.md「跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果」Requirement）。
- **新增产物**：`round-{N}.advisory-carryover.md`（`N >= 2`）。
- **测试**：`tests/test_review.py`（`parse_review` delta 参数、`_finding_key` 复用、`_is_carry_over_match` 区间重叠场景）、`tests/test_focus.py`（round≥2 模板新增内容、round 0/1 不回归其派生计算语义但接受输出文本新增字段说明）、`tests/test_pipeline.py`（跨轮读取来源分 round==2/round>=3 两态、硬收敛覆盖三态：未达标/达标/round<3 不适用）、`tests/test_schema.py`（`finding_origin` 枚举与 required 校验，含 round 0/1 缺字段应拒绝的回归用例）。
- **不涉及**：`SPEC_REVIEW_SCHEMA`、`src/npc/spec_pipeline.py`、`trend.py` 既有 stale 机制、`src/npc/fixer.py`（其按 severity 过滤逻辑天然兼容降级后的 finding，无需改动）。

## Non-Goals

- 不改变 `trend.py` 的 `STALE_THRESHOLD` / `rounds_since_strict_decrease` 既有兜底止损语义，两套收敛判据并存、互不替代。
- 不改变 round 0 / round 1 **派生的** blocking 判定语义（round 1 仍是"上一轮全部 findings 均可判 blocking"的既有全量语义，计算方式不变），delta 分类只从 round 2 起生效；但 REVIEW_SCHEMA 新增必填字段 `finding_origin` 与 focus 模板新增的字段说明文本对 round 0/1 同样生效——这是 schema/prompt 输出层面的有意破坏性变更，不属于本条 Non-Goal 承诺范围（不是"round 0/1 JSON/prompt 输出逐字节不变"）。
- 不新增独立的跨轮 advisory 累积 ledger 文件格式规范；`round-{N}.advisory-carryover.md` 只是每轮各自的静态 markdown 快照，不做跨轮汇总/去重。
- 不改动 spec review（`SPEC_REVIEW_SCHEMA` / `spec_pipeline.py`）的判定逻辑。
- 不改变硬收敛覆盖之外的 verdict 计算路径——round 0/1 的 `verdict` 字段仍按现状直接信任引擎自报值，不引入本 change 之外的确定性重算。
- 不对 `round-diff-new`/`pre-existing-new` 的自报值做几何核验（仅 `carry-over-unresolved` 子集通过 `_is_carry_over_match` 与上一轮有效 blocking 集合核验）——与既有 `severity`/`in_scope` 自报信任模型一致，是已记录的接受风险（见 design.md Risks），不是本 change 的隐藏行为。
