# review-delta-convergence Specification

## Purpose
TBD - created by archiving change review-delta-convergence. Update Purpose after archive.
## Requirements
### Requirement: findings 携带结构化的来源自报字段

`REVIEW_SCHEMA` 的每条 finding MUST 包含必填字段 `finding_origin`，取值为三选一枚举：`carry-over-unresolved`（与上一轮已报告且仍未修复的 blocking finding 是同一个问题）、`round-diff-new`（位置落在当前评审 diff 新引入/修改的代码内）、`pre-existing-new`（位置落在 diff 未修改的既有代码内，是本次新发现的既有问题）。该字段对所有 `round_n` 值（含 round 0、round 1）均为必填；`SPEC_REVIEW_SCHEMA`（spec review）MUST NOT 受本要求影响。

本要求是对所有轮次（含 round 0、round 1）生效的破坏性 schema 变更：本 change 落地前生成、或任何缺该字段的 review JSON，无论其对应轮次，均 MUST 被拒绝。这与「round 0 与 round 1 的判定语义不受影响」Requirement 并不矛盾——后者只约束 `blocking`/`advisory`/`verdict` 的**派生计算方式**，不承诺 review JSON 的结构或 focus 提示文本逐字节不变。

该拒绝规则的作用范围 MUST 明确限定为**当前正在生成的那一轮** review JSON——即引擎为 `round_n` 产出原始 JSON 后、写入 `round-{round_n}.review.json` 之前触发的 `jsonschema.validate(parsed, REVIEW_SCHEMA)` 这一道写入前校验门。它 MUST NOT 被理解为"系统任何时候读取磁盘上任意历史 `round-M.review.json`（`M < round_n`）都必须重新校验其是否含 `finding_origin`"——`parse_review` 是无 schema 校验副作用的纯函数，读取既有磁盘文件（例如为计算 `prior_blocking` 而以默认参数解析 `round-1.review.json`，见「跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果」Requirement）MUST NOT 触发本 Requirement 的拒绝规则，即使该历史文件是本 change 落地前生成、缺 `finding_origin` 字段。这确保了"本 change 落地前已完成 round 1、落地后才跑 round 2"的进行中 run 不会因本 Requirement 而在 round 2 阶段被阻塞或中止（与 design.md Migration Plan 第 2 条的"不对正在进行中的旧 run 产生意外覆盖"目标一致）。

`finding_origin` 的分类还须覆盖无法归属单一明确代码位置的边界场景（删除代码、缺失实现、跨文件交互、finding 同时触及增量与既有代码、`line_range` 为占位符 `"-"` 或无法解析等）。reviewer 自报 `finding_origin` 时 MUST 遵循以下确定性优先级（`round_n >= 2` 语境下，"增量 diff" 指本轮 fix 自身的增量 diff、"既有代码" 指增量 diff 之外的代码）：

1. 若该 finding 所涉及的任一位置（含被删除代码原所在的行号区间、缺失实现所指向的期望落点、跨文件交互中涉及的任一文件）落在增量 diff 范围内，MUST 归类为 `round-diff-new`。
2. 仅当该 finding 所涉及的全部位置均明确落在增量 diff 范围之外时，MUST 归类为 `pre-existing-new`。
3. 若该 finding 没有可归属的单一明确代码位置（如跨越整个模块/设计层面的问题、`line_range` 为占位符 `"-"` 或无法解析、reviewer 确实无法判断该问题是否被本轮增量触及），MUST 保守归类为 `round-diff-new`，MUST NOT 归类为 `pre-existing-new`——宁可多计入 blocking 候选（后续仍受 `severity`/`in_scope` 等既有条件约束），也不允许模糊归属的问题被静默排除出阻塞判定。

`finding_origin` 与既有 `in_scope` 字段回答两个正交问题，MUST 以逻辑 AND 组合参与 blocking 判定，不存在优先级仲裁需求：`in_scope` 表示该位置是否落在本次 change **累计** diff 范围内（既有语义不变）；`finding_origin` 的 `round-diff-new`/`pre-existing-new` 二分（仅 `round_n >= 2` 时参与 blocking 计算）表示该位置是否落在**本轮 fix 自身**的增量 diff 范围内（比累计 diff 更窄）。一条 `in_scope=true` 但有效来源为 `pre-existing-new` 的 finding 是合法组合（表示该问题在本 change 更早轮次引入、本轮 fix 未触碰、reviewer 本轮才新发现）；`in_scope=false` 的 finding 无论 `finding_origin` 取何值都已经因 `in_scope` 本身不满足而不计入 blocking。

#### Scenario: 缺失 finding_origin 的 review JSON 未通过 schema 校验

- **WHEN** 某 finding 的 JSON 对象不含 `finding_origin` 字段
- **THEN** 该 review JSON 未通过 `REVIEW_SCHEMA` 校验

#### Scenario: finding_origin 取值超出三值枚举未通过 schema 校验

- **WHEN** 某 finding 的 `finding_origin` 取值不在 `carry-over-unresolved`/`round-diff-new`/`pre-existing-new` 三者之内
- **THEN** 该 review JSON 未通过 `REVIEW_SCHEMA` 校验

#### Scenario: round 0/1 缺失 finding_origin 同样被拒绝（破坏性变更，无 round 例外）

- **GIVEN** 某 round 0（或 round 1）的 review JSON 是本 change 落地前旧版 producer 生成、不含 `finding_origin` 字段
- **WHEN** 该 JSON 提交 `REVIEW_SCHEMA` 校验
- **THEN** 校验失败，与 `round_n >= 2` 情形规则相同，不存在按 round 豁免的例外

#### Scenario: spec review schema 不受影响

- **WHEN** 检查 `SPEC_REVIEW_SCHEMA` 的 finding 必填字段列表
- **THEN** 其中不含 `finding_origin`

#### Scenario: in_scope=true 与有效来源 pre-existing-new 可以合法并存

- **GIVEN** `round_n = 2`，某 finding 位于本 change 累计 diff 范围内（`in_scope = true`），但不在本轮 fix 的增量 diff 范围内，有效来源为 `pre-existing-new`
- **WHEN** 计算该 finding 是否计入 blocking
- **THEN** 因有效来源为 `pre-existing-new`，该 finding 不计入 blocking，即使 `in_scope = true`；`in_scope` 与 `finding_origin` 之间不需要仲裁优先级

#### Scenario: in_scope=false 时无论 finding_origin 取值如何均不计入 blocking

- **GIVEN** 某 finding `in_scope = false`
- **WHEN** 计算该 finding 是否计入 blocking
- **THEN** 不计入 blocking，结果不受 `finding_origin` 取值影响（既有语义不变）

#### Scenario: 位置部分触及增量 diff（删除代码/跨文件交互）应归类为 round-diff-new

- **GIVEN** 某 finding 描述的是一段被本轮 fix 删除的代码引发的问题（该代码在修复前的行号区间落在本轮 fix 增量 diff 覆盖范围内），或该 finding 描述的是跨两个文件的交互缺陷，其中至少一个文件被本轮 fix 增量 diff 触及
- **WHEN** reviewer 判定该 finding 的 `finding_origin`
- **THEN** MUST 归类为 `round-diff-new`，MUST NOT 归类为 `pre-existing-new`

#### Scenario: 缺失实现类 finding 的期望落点在增量 diff 内应归类为 round-diff-new

- **GIVEN** 某 finding 描述"本应新增但未实现"的逻辑，其期望落点（应新增代码的位置）落在本轮 fix 增量 diff 覆盖的文件/范围内
- **WHEN** reviewer 判定该 finding 的 `finding_origin`
- **THEN** MUST 归类为 `round-diff-new`

#### Scenario: 无法归属单一明确位置或 line_range 为占位符时保守归类为 round-diff-new

- **GIVEN** 某 finding 是跨越整个模块/设计层面的问题，没有可归属的单一明确代码位置，或其 `line_range` 为占位符 `"-"`（或其它无法解析出行区间的取值）
- **WHEN** reviewer 判定该 finding 的 `finding_origin`
- **THEN** MUST 归类为 `round-diff-new`，MUST NOT 归类为 `pre-existing-new`

#### Scenario: 全部位置均明确位于增量 diff 之外时才归类为 pre-existing-new

- **GIVEN** 某 finding 涉及的全部代码位置（含跨文件交互场景下的每一个文件）均明确落在本轮 fix 增量 diff 覆盖范围之外
- **WHEN** reviewer 判定该 finding 的 `finding_origin`
- **THEN** 才 MUST 归类为 `pre-existing-new`

#### Scenario: 本 change 落地前生成的历史 round-1.review.json 仅作 prior_blocking 只读提取时不受本 Requirement 拒绝规则约束

- **GIVEN** 某 run 在本 change 落地前已完成 round 1，其落盘的 `round-1.review.json` 不含 `finding_origin` 字段；本 change 落地后该 run 继续执行 round 2
- **WHEN** round 2 按「跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果」Requirement 对该历史 `round-1.review.json` 执行默认 `parse_review`（不带 `round_n`/`prior_blocking`）以提取 `prior_blocking`
- **THEN** 该提取操作成功完成，不因 `round-1.review.json` 缺 `finding_origin` 字段而被拒绝或中止；本 Requirement 的 schema 拒绝规则仅适用于 round 2 自身正在生成、写入 `round-2.review.json` 前触发的写入前 schema 校验，不适用于对历史文件的只读提取

### Requirement: round≥2 对 finding_origin 做几何交叉核验，几何命中优先于自报

当调用方向 `parse_review` 提供 `round_n >= 2` 与非 `None` 的 `prior_blocking`（上一轮**最终有效** `blocking_findings` 列表，来源见「跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果」Requirement）时，系统 MUST 为每条 finding 计算一个不完全采信自报值的「有效来源」`effective_origin`：

1. 若该 finding 与 `prior_blocking` 中任一条目「同一问题」匹配（`_is_carry_over_match`：`file` 精确相等 AND `category` 精确相等 AND `line_range` 表示的行区间与该条目的行区间存在重叠，即两区间的起止解析为整数后 `max(start1, start2) <= min(end1, end2)`），`effective_origin` MUST 为 `carry-over-unresolved`，无论该 finding 自报的 `finding_origin` 是什么。行区间的重叠判定 MUST NOT 要求 `line_range` 字符串逐字符相等——修复导致的行号小幅漂移（区间整体上移/下移但仍有交集）MUST 仍判定为同一问题。
2. 否则，若该 finding 自报 `finding_origin == "carry-over-unresolved"`，`effective_origin` MUST 回退为 `round-diff-new`。
3. 否则，`effective_origin` MUST 等于自报的 `finding_origin` 值。

`_is_carry_over_match` 的匹配范围 MUST NOT 扩展到 `category` 被两轮之间改写、或行区间因大幅重构完全不重叠的情形——这两种情形下 MUST 按上述第 2/3 条回退处理，是本能力已记录的接受限制（不引入文本相似度等启发式匹配）。

`line_range` 的解析 MUST 覆盖 `REVIEW_SCHEMA` 允许的完整输入域，且 MUST 确定性、MUST NOT 抛出异常：
- 单行整数 `"N"`（视为区间 `[N, N]`）、区间 `"N-M"`（`N`、`M` 均为非负整数，允许在数字与连字符前后含空白，如 `"10 - 20"`）MUST 被解析为对应的整数区间；`N > M` 的反向区间（如 `"25-15"`）MUST 取 `[min(N,M), max(N,M)]` 归一化后再参与重叠判定，MUST NOT 被视为非法。
- 占位符 `"-"`（允许前后空白）、空字符串，或任何无法从中提取出两个整数端点的字符串（如任意自由文本、含非数字字符的畸形格式）MUST 被视为『不可解析』。
- 参与比较的两条 finding（本轮 finding 与 `prior_blocking` 中的条目）之一的 `line_range` 不可解析时，`_is_carry_over_match` MUST 直接返回 `False`（不做区间比较），MUST NOT 抛出异常；此时 `effective_origin` 按上述第 2/3 条自报回退规则处理。仅当两者的 `line_range` 均可解析时才执行区间重叠判定。

当 `round_n < 2` 或 `prior_blocking` 为 `None` 时，系统 MUST NOT 计算或应用 `effective_origin`，`finding_origin` 字段 MUST 被忽略，`parse_review` 对 `blocking`/`advisory`/`verdict`/`blocking_findings` 的**派生计算方式**（`round_n`/`prior_blocking` 参数引入前）MUST 保持不变。

#### Scenario: 几何命中覆盖自报值（三元组完全相等）

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="10-20", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `(file, line_range, category)` 与之完全相同，但自报 `finding_origin = "pre-existing-new"`
- **THEN** 该 finding 的有效来源为 `carry-over-unresolved`

#### Scenario: 行号因修复漂移但区间仍重叠时仍判定为同一问题

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="10-20", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `file="a.py"`、`category="validation"`、`line_range="15-25"`（因修复插入代码导致区间整体下移但与 `10-20` 存在交集 `15-20`），自报 `finding_origin` 为任意值
- **THEN** 该 finding 的有效来源为 `carry-over-unresolved`

#### Scenario: 行区间完全不重叠或 category 被改写时不判定为同一问题

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="10-20", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `file="a.py"`、`line_range="80-90"`（与 `10-20` 无交集）或 `category="security"`（与 `validation` 不同），其余条件相同
- **THEN** `_is_carry_over_match` 判定为不匹配，`effective_origin` 按自报值回退规则计算（自报 `carry-over-unresolved` 则回退为 `round-diff-new`，否则采用自报值），不判定为 `carry-over-unresolved`

#### Scenario: line_range 为占位符 "-" 时不判定为同一问题且不抛异常

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="10-20", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `file="a.py"`、`category="validation"`、`line_range="-"`
- **THEN** `_is_carry_over_match` 判定为不匹配（返回 `False`），不抛出异常；`effective_origin` 按自报值回退规则计算

#### Scenario: line_range 为非法格式时不判定为同一问题且不抛异常

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="10-20", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `file="a.py"`、`category="validation"`、`line_range="foo"`（无法解析出整数端点的畸形格式）
- **THEN** `_is_carry_over_match` 判定为不匹配（返回 `False`），不抛出异常

#### Scenario: 反向区间按端点归一化后参与重叠判定

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="10-20", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `file="a.py"`、`category="validation"`、`line_range="25-15"`（反向区间，归一化后为 `[15, 25]`，与 `[10, 20]` 存在交集 `[15, 20]`）
- **THEN** `_is_carry_over_match` 判定为匹配（返回 `True`）

#### Scenario: 单行 line_range 视为单点区间参与重叠判定

- **GIVEN** `round_n = 2`，`prior_blocking` 含一条 `(file="a.py", line_range="15-25", category="validation")` 的 finding
- **WHEN** 本轮某 finding 的 `file="a.py"`、`category="validation"`、`line_range="18"`（单行，视为区间 `[18, 18]`，落在 `[15, 25]` 内）
- **THEN** `_is_carry_over_match` 判定为匹配（返回 `True`）

#### Scenario: 自报声称遗留但几何核验未命中时回退

- **GIVEN** `round_n = 2`，`prior_blocking` 不含任何与本轮某 finding 匹配的条目
- **WHEN** 该 finding 自报 `finding_origin = "carry-over-unresolved"`
- **THEN** 该 finding 的有效来源为 `round-diff-new`

#### Scenario: round_n 小于 2 时不做几何核验

- **WHEN** 调用 `parse_review` 且 `round_n < 2`（或未提供 `prior_blocking`）
- **THEN** 返回结果与不提供这两个参数时完全一致

### Requirement: 跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果，而非重新默认解析原始 JSON

当 `round_n >= 3` 时，系统为本轮计算提供给 `parse_review` 的 `prior_blocking` 入参 MUST 是上一轮（`round_n - 1`）自身 `parse_review` 调用（含该轮可能发生的 D5 硬收敛覆盖）后得到的最终有效 `blocking_findings` 集合，来源为该轮 `_do_review_phase_exit_and_trend` 持久化在 state phase 记录中的 `effective_blocking_findings` 字段。系统 MUST NOT 通过对上一轮原始 `round-{round_n-1}.review.json` 重新执行不带 `round_n`/`prior_blocking` 参数的默认 `parse_review` 来重建 `prior_blocking`——该默认解析会重新计入已被上一轮判定为 `pre-existing-new` 而降级、或已被上一轮硬收敛覆盖降级的 finding，破坏"`prior_blocking` = 上一轮最终 blocking_findings"的定义。

当 `round_n == 2` 时（上一轮为 round 1，round 1 不适用 delta 计算，没有"最终有效 blocking 集合"与朴素 blocking 集合的区分），系统 MUST 对 `round-1.review.json` 执行默认 `parse_review`（不带 `round_n`/`prior_blocking`）以取得其 `blocking_findings` 作为 `prior_blocking`。

`parse_review` 的默认调用（不带 `round_n`/`prior_blocking`）是一个不做 schema 校验的纯函数，只读取 `severity`/`in_scope`/`file`/`line_range`/`category` 等既有字段（不引用 `finding_origin`），MUST 兼容任意缺失 `finding_origin` 字段的 `round-1.review.json`（包括本 change 落地前生成的历史文件）——「findings 携带结构化的来源自报字段」Requirement 的 schema 拒绝规则只约束"当前正在生成的那一轮"写入前校验，MUST NOT 扩展为对本处只读提取 `prior_blocking` 的历史文件重新做 schema 校验。因此"本 change 落地前已完成 round 1、落地后继续 round 2"的进行中 run，MUST 能正常取得 `prior_blocking` 并继续 round 2 的 delta 计算，不因升级中途而中止或降级。

#### Scenario: round 3 从 round 2 持久化的有效 blocking 集合读取 prior_blocking，而非重新默认解析 round-2.review.json

- **GIVEN** round 2 某 finding（三元组 `T`）在 round 2 自身的 `parse_review(round_n=2, ...)` 调用中被判定有效来源为 `pre-existing-new`，从 `blocking_findings` 降级进入 `advisory`
- **WHEN** round 3 计算本轮的 `prior_blocking`
- **THEN** `prior_blocking` 不包含三元组 `T`（即使 `round-2.review.json` 原始 JSON 中该 finding 自报的 `severity`/`in_scope` 满足朴素 blocking 条件）

#### Scenario: 降级后同一问题在下一轮再次出现不被误判为 carry-over-unresolved

- **GIVEN** round 2 某 finding（三元组 `T`）有效来源为 `pre-existing-new` 被降级为 advisory（因此不在 round 2 持久化的 `effective_blocking_findings` 中）；round 3 reviewer 再次报告同一三元组 `T` 的 finding，自报 `finding_origin = "pre-existing-new"`
- **WHEN** round 3 计算该 finding 的 `effective_origin`
- **THEN** 因 `prior_blocking`（来自 round 2 持久化的有效 blocking 集合）不含 `T`，几何核验未命中，`effective_origin` 采用自报值 `pre-existing-new`，不被误判为 `carry-over-unresolved`；该 finding 仍降级为 advisory，不计入 blocking

#### Scenario: round 2 的 prior_blocking 来自对 round 1 的默认解析

- **GIVEN** `round_n = 2`
- **WHEN** 系统计算本轮 `prior_blocking`
- **THEN** `prior_blocking` 取自对 `round-1.review.json` 执行默认 `parse_review`（不带 `round_n`/`prior_blocking`）得到的 `blocking_findings`

#### Scenario: 升级中途——round 1 完成于本 change 落地前、round 2 在落地后消费其缺 finding_origin 的历史 JSON

- **GIVEN** 某 run 的 round 1 在本 change 落地前已完成并落盘 `round-1.review.json`（不含 `finding_origin` 字段），本 change 落地后该 run 继续执行 round 2
- **WHEN** round 2 计算 `prior_blocking`
- **THEN** 系统对该历史 `round-1.review.json` 执行默认 `parse_review` 成功取得 `blocking_findings` 作为 `prior_blocking`，不因缺 `finding_origin` 字段而拒绝、中止或禁用本轮 delta 计算；round 2 后续按「round≥2 对 finding_origin 做几何交叉核验」Requirement 正常计算 `effective_origin`（round 2 自身产出的 review JSON 仍必须含 `finding_origin`，只有历史 `round-1.review.json` 的只读消费被豁免）

#### Scenario: round≥3 上一轮 effective_blocking_findings 字段缺失时 prior_blocking 取 None、完全禁用几何核验并信任原 verdict

- **GIVEN** `round_n = 3`，state 中 `phases["review-r2"]` 缺失 `effective_blocking_findings` 字段（该 run 早于本能力落地即已在进行，历史 state 无该字段）
- **WHEN** 系统计算本轮 `prior_blocking` 并调用 `parse_review`
- **THEN** `prior_blocking` 取值为 `None`（而非 `[]`）；`parse_review` 因 `prior_blocking is None` 不计算 `effective_origin`，本轮 `blocking`/`advisory`/`verdict`/`blocking_findings` 完全按自报 `severity`/`in_scope` 计算、`verdict` 直接信任引擎自报值（与 `round_n < 2` 时的降级路径一致）；`carryover_unresolved_blocking` 为 `None`，与 `0` 不同，因此也不满足硬收敛覆盖的前置条件（见「round≥3 的硬收敛规则」Requirement）

### Requirement: 存量代码新发现问题不计入 blocking

当 `round_n >= 2` 且提供 `prior_blocking` 时，有效来源为 `pre-existing-new` 的 finding MUST NOT 计入 `blocking`/`blocking_findings`，MUST 计入 `advisory`。`verdict` MUST 在剔除这些 finding 后的 blocking 集合上重新计算：存在至少一条 `severity ∈ {critical, high}` 且 `in_scope == true` 且有效来源不为 `pre-existing-new` 的 finding → `changes-requested`；否则若 findings 非空 → `passed-with-advisory`；否则 → `approve`。该 finding 本身 MUST NOT 从 `round-N.review.json` 落盘内容中被移除或改写。

#### Scenario: pre-existing-new 的 high severity finding 降级为 advisory

- **GIVEN** `round_n = 2`，某 finding `severity="high"`、`in_scope=true`，有效来源为 `pre-existing-new`
- **WHEN** 计算该轮 `blocking`/`advisory`
- **THEN** 该 finding 不出现在 `blocking_findings` 中，`advisory` 计数包含它

#### Scenario: 剔除后无 blocking 时 verdict 为 passed-with-advisory

- **GIVEN** `round_n = 2`，本轮全部 in-scope blocking 候选 finding 的有效来源均为 `pre-existing-new`，findings 非空
- **WHEN** 计算该轮 `verdict`
- **THEN** `verdict = "passed-with-advisory"`，不采信引擎自报的 `verdict` 字段

#### Scenario: carry-over-unresolved 或 round-diff-new 仍计入 blocking

- **GIVEN** `round_n = 2`，某 finding `severity="critical"`、`in_scope=true`，有效来源为 `round-diff-new`
- **WHEN** 计算该轮 `blocking`
- **THEN** 该 finding 出现在 `blocking_findings` 中，`verdict = "changes-requested"`

### Requirement: round 0 与 round 1 的判定语义不受影响

`round_n ∈ {0, 1}` 的 review 执行路径 MUST NOT 触发有效来源计算、`pre-existing-new` 降级或硬收敛覆盖；其 `blocking`/`advisory`/`verdict` 的**计算方式**与 finding_origin 字段引入前一致（仍完全由自报的 `severity`/`in_scope` 决定，`verdict` 仍直接取自引擎自报值）。该一致性约束仅限于 `parse_review` 对 `blocking`/`advisory`/`verdict`/`blocking_findings` 的**派生计算逻辑**，MUST NOT 被理解为 review JSON 的 schema 结构或 focus 提示文本本身逐字节不变——`REVIEW_SCHEMA` 新增的必填字段 `finding_origin`（见「findings 携带结构化的来源自报字段」Requirement）与 focus 模板新增的字段说明文本（见「round≥2 的 focus 模板包含 delta 分类指令」Requirement 关联的 `_output_requirements_block` 变更）对 round 0/1 同样生效，是本能力有意引入的破坏性变更。

#### Scenario: round 0 的 severity/in_scope 判定不变

- **WHEN** `round_n = 0` 的 review 结果被解析
- **THEN** `blocking`/`advisory`/`verdict` 的计算方式与本能力引入前完全一致，不受 `finding_origin` 字段取值影响

#### Scenario: round 1 的 focus 模板不含 delta 规则块

- **WHEN** 渲染 `round_n = 1` 的 review focus 文本
- **THEN** 输出不包含 delta-review 分类规则文案，即使调用方传入了本轮 fix commit

#### Scenario: round 0/1 的 finding_origin 字段说明属于有意的破坏性变更，不违反本 Requirement

- **GIVEN** `round_n = 0` 或 `round_n = 1`
- **WHEN** 渲染其 review focus 文本、或校验其 review JSON 是否含 `finding_origin` 字段
- **THEN** 渲染输出包含 `finding_origin` 字段说明文本、且 JSON 校验要求该字段必填——这不违反本 Requirement，因为本 Requirement 只约束 `blocking`/`advisory`/`verdict` 的计算方式，不约束输出文本或 JSON 结构本身

### Requirement: round≥2 的 focus 模板包含 delta 分类指令

当渲染 `round_n >= 2` 的 review focus 文本时，输出 MUST 始终包含 `finding_origin` 三值分类准则说明（涵盖何时应标注 `carry-over-unresolved`、`round-diff-new`、`pre-existing-new`），不依赖 `round_fix_commit` 是否提供。该分类准则说明 MUST 包含「findings 携带结构化的来源自报字段」Requirement 定义的确定性优先级规则（含删除代码、缺失实现、跨文件交互、无法归属单一明确位置或 `line_range` 为占位符等边界场景的处理：任一位置触及增量 diff 即归 `round-diff-new`；仅全部位置明确在增量 diff 之外才归 `pre-existing-new`；无法判定时保守归 `round-diff-new`），不得只列举三值枚举名称而遗漏该优先级规则。当额外提供了上一轮 fix 阶段的 commit（`round_fix_commit`）时，输出 MUST 额外包含核对本轮 fix 自身引入范围的 git diff 指令（形如 `git --no-pager diff {round_fix_commit}~1..{round_fix_commit}`），区别于既有的累计 diff 指令。当 `round_fix_commit` 未提供（缺省）时，MUST NOT 包含该增量 diff 指令，但分类准则说明 MUST 仍然输出，渲染 MUST 仍然成功产出文本，不抛出异常。

#### Scenario: 提供 round_fix_commit 时包含增量 diff 指令与分类准则

- **WHEN** 渲染 `round_n = 2` 的 focus 文本且提供 `round_fix_commit`
- **THEN** 输出包含形如 `git --no-pager diff <round_fix_commit>~1..<round_fix_commit>` 的指令，且包含 `finding_origin` 三值分类准则文案

#### Scenario: 缺省 round_fix_commit 时分类准则仍输出，仅增量 diff 指令缺位

- **WHEN** 渲染 `round_n = 2` 的 focus 文本且未提供 `round_fix_commit`
- **THEN** 渲染成功产出文本，不抛出异常；输出仍包含 `finding_origin` 三值分类准则文案，只是不包含增量 diff 指令

#### Scenario: 分类准则文案包含边界场景的确定性优先级规则

- **WHEN** 渲染 `round_n >= 2` 的 review focus 文本
- **THEN** 输出的分类准则说明中包含针对删除代码/缺失实现/跨文件交互/无法归属单一位置或 `line_range` 为占位符等场景的判定优先级文案（任一位置触及增量 diff 归 `round-diff-new`；仅全部位置明确在增量 diff 之外才归 `pre-existing-new`；无法判定时保守归 `round-diff-new`），不止是三值枚举名称的罗列

### Requirement: round≥3 的硬收敛规则——连续两轮无遗留未修复 blocking 即确定性把 blocking 覆盖为 0，verdict 按标准规则重算

`round_n >= 3` 的 review 执行 MUST 在完成本轮 `carryover_unresolved_blocking`（有效来源为 `carry-over-unresolved` 且满足 blocking 判定条件的 finding 数）计算后，读取上一轮（`round_n - 1`）持久化在 state 中的 `carryover_unresolved_blocking`。若两者均为 `0`，系统 MUST 确定性地把本轮最终结果覆盖为：`blocking = 0`、`hard_convergence_applied = true`；原本会计入 `blocking_findings` 的 finding MUST 转记入 `advisory` 计数（不丢弃、不从 `round-N.review.json` 中移除）。覆盖后的 `verdict` MUST NOT 被硬编码为固定值，而是在 `blocking = 0` 的前提下按既有的标准规则重新计算：若覆盖后的 `advisory` 计数非空（含本次因覆盖而转记的 finding，或本就存在的其它 advisory finding）→ `verdict = "passed-with-advisory"`；若覆盖后完全没有任何 finding（`advisory == 0` 且 `blocking == 0`）→ `verdict = "approve"`。该规则与 REVIEW_SCHEMA 的既有 verdict 语义、以及本 spec「存量代码新发现问题不计入 blocking」Requirement 的 verdict 计算规则完全一致，MUST NOT 出现 `verdict = "approve"` 与非空 advisory 并存的组合。该覆盖 MUST 应用于写入 state 的 phase 记录、发出的 telemetry 事件、以及函数返回值三者，三者 MUST 保持一致。`round_n < 3`，或上一轮 `carryover_unresolved_blocking` 字段缺失（历史 state），或两者中任一非零，MUST NOT 触发该覆盖，`hard_convergence_applied` MUST 为 `false`。

#### Scenario: 连续两轮零遗留、存在被降级的 round-diff-new blocking 时覆盖为 passed-with-advisory

- **GIVEN** `round_n = 3`，round 2 与 round 3 的 `carryover_unresolved_blocking` 均为 `0`，round 3 本身有一条有效来源为 `round-diff-new` 的 blocking finding
- **WHEN** round 3 的 review 阶段结束
- **THEN** 该轮最终 `blocking = 0`、该 finding 转记入 `advisory`、`verdict = "passed-with-advisory"`、`hard_convergence_applied = true`

#### Scenario: 连续两轮零遗留、覆盖前无任何 blocking 或 advisory finding 时覆盖为 approve

- **GIVEN** `round_n = 3`，round 2 与 round 3 的 `carryover_unresolved_blocking` 均为 `0`，round 3 本身既无 blocking finding 也无其它 advisory finding
- **WHEN** round 3 的 review 阶段结束
- **THEN** 该轮最终 `blocking = 0`、`advisory = 0`、`verdict = "approve"`、`hard_convergence_applied = true`

#### Scenario: 存在遗留时不覆盖

- **GIVEN** `round_n = 3`，round 2 的 `carryover_unresolved_blocking` 为 `2`，round 3 的为 `0`
- **WHEN** round 3 的 review 阶段结束
- **THEN** 不触发覆盖，`hard_convergence_applied = false`，返回值保持未覆盖前的计算结果

#### Scenario: round_n 小于 3 时不适用硬收敛规则

- **GIVEN** `round_n = 2`，本轮 `carryover_unresolved_blocking` 为 `0`
- **WHEN** round 2 的 review 阶段结束
- **THEN** 不触发硬收敛覆盖，无论上一轮数据如何，`hard_convergence_applied = false`

#### Scenario: 硬收敛覆盖不阻断既有 blocking 循环判据

- **GIVEN** round 3 触发硬收敛覆盖（`blocking = 0`）
- **WHEN** 上游读取本轮返回值的 `blocking` 字段作为 review-fix 循环的继续/退出判据
- **THEN** 循环判据在不修改其自身逻辑的前提下判定为"无 blocking，退出循环"

### Requirement: 硬收敛覆盖后不再触发下一轮 fix findings 渲染

当硬收敛覆盖生效（`hard_convergence_applied = true`）时，系统 MUST NOT 渲染 `round-{round_n + 1}.fix.findings.md`（该产物的既有触发条件是最终 `blocking > 0`，覆盖后 `blocking = 0` 天然满足"不触发"，本要求确认该联动效果，不引入额外判断分支）。

#### Scenario: 硬收敛覆盖后不产出下一轮 fix findings 片段

- **GIVEN** round 3 触发硬收敛覆盖
- **WHEN** round 3 的 review 阶段结束
- **THEN** `round-4.fix.findings.md` 不被写出

### Requirement: 每个 delta 轮次落盘 advisory carryover 清单

`round_n >= 2` 的 review 阶段结束时，系统 MUST 写出 `round-{round_n}.advisory-carryover.md`，内容 MUST 包含本轮有效来源为 `pre-existing-new` 的全部 finding；若本轮触发了硬收敛覆盖，MUST 额外包含被覆盖降级的原 blocking finding。`round_n < 2` 的 review 阶段 MUST NOT 产出该文件。该产物是每轮独立快照，MUST NOT 与其它轮次的同名产物合并/去重。

#### Scenario: 存在 pre-existing-new finding 时清单非空

- **GIVEN** `round_n = 2`，本轮有一条有效来源为 `pre-existing-new` 的 finding
- **WHEN** round 2 的 review 阶段结束
- **THEN** `round-2.advisory-carryover.md` 存在，内容包含该 finding 的 id/severity/category/title/file/line_range

#### Scenario: 硬收敛覆盖时清单包含被降级的原 blocking finding

- **GIVEN** round 3 触发硬收敛覆盖，其中一条原本满足 blocking 判定的 finding 被转记为 advisory
- **WHEN** round 3 的 review 阶段结束
- **THEN** `round-3.advisory-carryover.md` 包含该 finding

#### Scenario: round 0/1 不产出该清单

- **WHEN** round 0 或 round 1 的 review 阶段结束
- **THEN** 不产出 `round-0.advisory-carryover.md` 或 `round-1.advisory-carryover.md`

### Requirement: 既有 stale 止损机制不受影响

本能力引入的 `carryover_unresolved_blocking`/`hard_convergence_applied` 判定 MUST NOT 修改 `trend.py` 的 `blocking_trend`/`rounds_since_strict_decrease`/`STALE_THRESHOLD` 的计算规则本身（严格下降清零、否则计数 +1、阈值 3）；`_do_review_phase_exit_and_trend` 写入 `blocking_trend` 时使用的 `blocking` 输入值 MUST 与该轮最终对外返回、写入 state phase 记录、发给 telemetry 的 `blocking` 值保持同一来源（即硬收敛覆盖发生时，`blocking_trend` 追加的是覆盖后的 `0`，与 D5"三者一致"的要求同源，不是覆盖前的原始值另开一份口径）。硬收敛覆盖的触发判定（是否 approve）MUST NOT 读取或依赖 `rounds_since_strict_decrease`/`STALE_THRESHOLD`；`check_stale` 的触发判定 MUST NOT 读取或依赖 `carryover_unresolved_blocking`/`hard_convergence_applied`。

#### Scenario: 硬收敛覆盖后 blocking_trend 追加覆盖后的值

- **GIVEN** 某 run 在 round 3 触发硬收敛覆盖（覆盖后 `blocking = 0`）
- **WHEN** round 3 的 review 阶段结束
- **THEN** 该 run 的 `blocking_trend` 末尾追加的值为 `0`，与该轮对外返回、写入 phase 记录、telemetry 的 `blocking` 值一致

#### Scenario: 硬收敛判定不读取 stale 计数

- **GIVEN** 某 run 在 round 3 的 `rounds_since_strict_decrease` 已达到 `STALE_THRESHOLD`
- **WHEN** 计算 round 3 是否触发硬收敛覆盖
- **THEN** 触发结果仅由 round 2/round 3 的 `carryover_unresolved_blocking` 决定，不受 `rounds_since_strict_decrease` 取值影响

