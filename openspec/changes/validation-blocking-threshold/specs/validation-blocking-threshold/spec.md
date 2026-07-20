## ADDED Requirements

### Requirement: validation 类 finding 携带条件必需的触发证据字段

`REVIEW_SCHEMA` 的每条 finding MUST 声明可选属性 `trigger_evidence`（string）。当某条 finding 的 `category == "validation"` 时，该 finding MUST 包含 `trigger_evidence` 键（`allOf`/`if`/`then` 条件必需）；`category != "validation"` 的 finding MUST NOT 被要求包含该字段。该字段的 schema 级校验 MUST 仅保证键存在，MUST NOT 施加非空长度约束（如 `minLength`）——字段是否存在由 schema 保证，字段值是否为空/占位符由 `parse_review()` 在派生计算阶段处理（见「validation 类 finding 缺失触发证据时降级为 advisory」Requirement）。

本 Requirement 定义的 schema 级"键必须存在"约束 MUST 通过引擎产出环节既有的 `invalid_review_schema` 校验-重试机制生效（`src/npc/pipeline.py::_execute_review_pass()` 对 `jsonschema.validate(parsed, REVIEW_SCHEMA)` 失败的既有处理：本轮重试，重试预算耗尽后以 `invalid_review_schema` 失败原因结束该 review round）——这是 `REVIEW_SCHEMA` 现有其它必填字段（如 `verdict`/`findings`/finding 必填属性）校验失败时已经复用的同一条既有失败路径，本 Requirement MUST NOT 引入新的失败原因码或新的阻断类型，仅新增一种触发该既有路径的 schema 违例条件。因此，任何**当前经 `REVIEW_SCHEMA` 校验通过**的 review（无论单 pass 或对抗式双 pass）中，`category == "validation"` 的 finding 的 `trigger_evidence` 键 MUST 已经存在且其值 MUST 为字符串类型（不为 `null`、不缺失）——"键缺失"或"值为 `null`"这两种状态在该场景下不可达；「validation 类 finding 缺失触发证据时降级为 advisory」Requirement 中针对这两种状态定义的降级分支，其覆盖范围仅限于绕开本 Requirement schema 校验的输入（本 change 生效前生成的历史 `round-N.review.json` 经 `npc review parse` 重新解析、或测试/其它调用方直接构造 dict 调用 `parse_review()`），详见该 Requirement 正文的范围说明。

#### Scenario: category 为 validation 且缺失 trigger_evidence 未通过 schema 校验

- **GIVEN** 一条 finding 的 `category == "validation"`，其 JSON 对象不含 `trigger_evidence` 键
- **WHEN** 用 `REVIEW_SCHEMA` 校验该 finding
- **THEN** 校验失败

#### Scenario: 引擎持续产出缺失 trigger_evidence 的 validation finding 时的流程结果

- **GIVEN** 某轮 review，引擎在全部重试次数内产出的 JSON 均含至少一条 `category == "validation"` 且缺失 `trigger_evidence` 键的 finding
- **WHEN** `_execute_review_pass()` 对每次产出执行 `jsonschema.validate(parsed, REVIEW_SCHEMA)`
- **THEN** 每次校验均失败，触发既有重试；重试预算耗尽后，该 review round 以既有 `invalid_review_schema` 失败原因结束（与 `verdict`/`findings` 等其它必填字段校验失败时完全相同的既有失败路径，不新增失败原因码）
- **AND** 该轮不会到达 `parse_review()`，也就不会命中「validation 类 finding 缺失触发证据时降级为 advisory」Requirement 的降级分支

#### Scenario: category 为 validation 且 trigger_evidence 为空字符串仍通过 schema 校验

- **GIVEN** 一条 finding 的 `category == "validation"`，其 `trigger_evidence` 取值为 `""`
- **WHEN** 用 `REVIEW_SCHEMA` 校验该 finding
- **THEN** 校验通过（schema 层不做非空判断）

#### Scenario: category 非 validation 时不要求 trigger_evidence

- **GIVEN** 一条 finding 的 `category == "security"`，其 JSON 对象不含 `trigger_evidence` 键
- **WHEN** 用 `REVIEW_SCHEMA` 校验该 finding
- **THEN** 校验通过

#### Scenario: spec review schema 不受影响

- **WHEN** 检查 `SPEC_REVIEW_SCHEMA` 的 finding 必填/可选字段与顶层条件规则
- **THEN** 其中不含 `trigger_evidence` 属性，也不含针对 `category` 的 `allOf`/`if`/`then` 条件规则

### Requirement: validation 类 finding 缺失触发证据时降级为 advisory

`parse_review()` 对每条满足既有 blocking 候选条件（`severity ∈ {critical, high}` 且 `in_scope == true`）且 `category == "validation"` 的 finding，MUST 额外判断其 `trigger_evidence` 字段是否满足以下任一"缺失"条件：字段不存在、取值为 `null`、取值为字符串且去除首尾空白后为空字符串、或去除首尾空白后等于占位符 `"-"`。满足任一缺失条件时，该 finding MUST NOT 计入 `blocking`/`blocking_findings`，MUST 计入 `advisory` 计数；该判定 MUST NOT 受 `severity` 取值影响（`critical` 与 `high` 同样适用，与「spec-silent 归因窄化降级为 advisory」Requirement 的 `severity == critical` 例外相互独立，不共享豁免条件）。`trigger_evidence` 非空且不等于占位符 `"-"` 时，MUST NOT 因本 Requirement 而降级。`parse_review()` MUST NOT 修改或丢弃 finding 记录本身（`round-N.review.json` 落盘内容不受影响）。

`parse_review()` 是纯函数，不做 schema 校验，因此本 Requirement 定义的四个判定分支（键不存在 / `null` / 空字符串 / 占位符）在**任意输入**上均一体适用，不因输入来源而分叉逻辑。但结合「validation 类 finding 携带条件必需的触发证据字段」Requirement 的既有约束，"键不存在"与"取值为 `null`"这两个分支在**当前经 `REVIEW_SCHEMA` 校验通过的实时 review 流程**中永远不会被触发（schema 已保证该场景下 `trigger_evidence` 键存在且类型为 string）；这两个分支实际可达的输入仅为：本 change 生效前生成、不含该字段的历史 `round-N.review.json`（经 `npc review parse` 重新解析）、或测试 / 其它调用方绕开 schema 直接构造 dict 调用 `parse_review()`。"空字符串"与"占位符 `-`"两个分支在实时 schema 校验通过的流程与历史文件重放中均可达（schema 不拒绝空字符串，见「validation 类 finding 携带条件必需的触发证据字段」Requirement 的对应 Scenario）。

#### Scenario: trigger_evidence 缺失键时降级（历史文件重放 / 直接调用场景）

- **GIVEN** 一条 finding：`category="validation"`、`severity="high"`、`in_scope=true`，JSON 对象不含 `trigger_evidence` 键（例如本 change 生效前生成的历史 `round-N.review.json`，或测试直接构造的 dict）
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 不出现在 `blocking_findings` 中，计入 `advisory`
- **AND** 该场景 MUST NOT 出现在当前经 `REVIEW_SCHEMA` 校验通过的实时 review 流程中（见「validation 类 finding 携带条件必需的触发证据字段」Requirement）

#### Scenario: trigger_evidence 为空字符串或占位符时降级

- **GIVEN** 一条 finding：`category="validation"`、`severity="high"`、`in_scope=true`，`trigger_evidence` 分别取值 `""` 与 `"-"`（两个独立场景）
- **WHEN** 调用 `parse_review()`
- **THEN** 两种取值下该 finding 均不计入 `blocking_findings`，计入 `advisory`

#### Scenario: trigger_evidence 非空且非占位符时不降级

- **GIVEN** 一条 finding：`category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence="传入 limit=-1 触发下标越界"`
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 正常计入 `blocking_findings`

#### Scenario: severity 为 critical 时同样受举证门槛约束

- **GIVEN** 一条 finding：`category="validation"`、`severity="critical"`、`in_scope=true`，`trigger_evidence` 缺失
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 仍降级为 advisory，不因 `severity == "critical"` 而豁免

#### Scenario: 非 validation 类 finding 不受本 Requirement 约束

- **GIVEN** 一条 finding：`category="security"`、`severity="high"`、`in_scope=true`，不含 `trigger_evidence` 字段
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 是否计入 blocking 不受本 Requirement 影响，仍按既有 `severity`/`in_scope` 条件判定

### Requirement: spec-silent 归因窄化降级为 advisory

`parse_review()` 对每条满足既有 blocking 候选条件（`severity ∈ {critical, high}` 且 `in_scope == true`）且 `spec_attribution == "spec-silent"` 且 `severity != "critical"` 的 finding，MUST 将其从 `blocking`/`blocking_findings` 移入 `advisory` 计数。`severity == "critical"` 的 `spec-silent` finding MUST NOT 被本 Requirement 降级，继续计入 blocking。`spec_attribution` 取值为 `spec-ambiguous`/`spec-contradicted`/`impl-deviation` 的 finding MUST NOT 受本 Requirement 影响，继续遵守 `openspec/specs/spec-attribution/spec.md`「spec 归因不参与 blocking 判定」Requirement 的既有约束（该 Requirement 已被本 change 修订为窄化版本，见对应 spec delta）。

#### Scenario: spec-silent 且 severity=high 时降级

- **GIVEN** 一条 finding：`spec_attribution="spec-silent"`、`severity="high"`、`in_scope=true`、`category` 非 `"validation"`
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 不计入 `blocking_findings`，计入 `advisory`

#### Scenario: spec-silent 且 severity=critical 时不降级

- **GIVEN** 一条 finding：`spec_attribution="spec-silent"`、`severity="critical"`、`in_scope=true`
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 正常计入 `blocking_findings`

#### Scenario: 其余三个归因值不触发本 Requirement 的降级

- **GIVEN** 三条 finding，分别 `spec_attribution` 为 `spec-ambiguous`、`spec-contradicted`、`impl-deviation`，其余字段均满足 blocking 候选条件（`severity="high"`、`in_scope=true`）
- **WHEN** 调用 `parse_review()`
- **THEN** 三条 finding 均正常计入 `blocking_findings`，不因本 Requirement 降级

### Requirement: 两条降级判据独立叠加，互不排斥

一条 finding 若同时满足「validation 类 finding 缺失触发证据时降级为 advisory」与「spec-silent 归因窄化降级为 advisory」两条 Requirement 的降级条件，MUST 仅被计入 `advisory` 一次（不重复计数），但两条判据各自的降级归因 MUST 被独立记录（见「降级计数供可观测性」Requirement）。

#### Scenario: 同时满足两条降级条件时仅计入一次 advisory

- **GIVEN** 一条 finding：`category="validation"`、`trigger_evidence` 缺失、`spec_attribution="spec-silent"`、`severity="high"`、`in_scope=true`
- **WHEN** 调用 `parse_review()`
- **THEN** 该 finding 不计入 `blocking_findings`，`advisory` 计数因该 finding 恰好增加 `1`（不重复计数）

### Requirement: 降级计数供可观测性

`parse_review()` 的返回值 MUST 新增键 `downgrade_counts`，其值为映射，至少含 `validation_missing_evidence`（因缺失触发证据被降级的 finding 数）与 `spec_silent_non_critical`（因 spec-silent 非 critical 归因被降级的 finding 数）两个键，值均为非负整数。同一条 finding 若同时触发两条降级判据，两个计数键 MUST 各自独立 `+1`（不做互斥去重）。`review.round` telemetry 事件 MUST 携带 `downgrade_counts` 字段，且该字段 MUST 出现在 `telemetry.EMIT_FIELD_CONTRACT["review.round"]` 与 `telemetry_schema_v1.json` 中。`npc telemetry agg` MUST 对该字段做逐 key 累加聚合；历史事件缺该字段时 MUST 被忽略、不抛异常、不影响其它字段聚合。本 Requirement 引入的计数 MUST NOT 驱动任何阻断、阈值、退出码变更或 `auto-decide` 触发条件。

#### Scenario: downgrade_counts 分别统计两类降级原因

- **GIVEN** 一轮 review 中一条 finding 因缺失 `trigger_evidence` 降级、另一条 finding 因 spec-silent 非 critical 降级
- **WHEN** 调用 `parse_review()`
- **THEN** 返回值 `downgrade_counts["validation_missing_evidence"] == 1` 且 `downgrade_counts["spec_silent_non_critical"] == 1`

#### Scenario: 同时触发两条判据的 finding 使两个计数键各自增加

- **GIVEN** 一条 finding 同时满足 validation 缺证据与 spec-silent 非 critical 两条降级条件
- **WHEN** 调用 `parse_review()`
- **THEN** `downgrade_counts["validation_missing_evidence"]` 与 `downgrade_counts["spec_silent_non_critical"]` 均因该 finding 各自增加 `1`

#### Scenario: emit 的字段集合含 downgrade_counts

- **GIVEN** 一轮 review 完成并 emit `review.round` 事件
- **WHEN** 捕获实际 emit 的事件字典
- **THEN** `downgrade_counts` 在其键集合中

#### Scenario: 聚合兼容历史事件缺该字段

- **GIVEN** telemetry 中混有不含 `downgrade_counts` 键的历史 `review.round` 事件
- **WHEN** 执行 `npc telemetry agg`
- **THEN** 命令 exit code 为 `0`，不含该键的事件被忽略，不计入聚合值

#### Scenario: 本 Requirement 不引入任何闸门

- **GIVEN** 某 change 的 `downgrade_counts` 取任意值（含极高比例降级）
- **WHEN** 该 change 走完 review → fix → archive 流程
- **THEN** 其流程结果不受 `downgrade_counts` 取值影响，`npc auto-decide` 的可用 trigger 集合未新增任何项

### Requirement: verdict 必须与降级后的最终 blocking 集合保持一致

`parse_review()` 返回值中的 `verdict` 键 MUST NOT 直接透传输入 review JSON 顶层自报的 `verdict` 值；MUST 由 `parse_review()` 基于降级后的最终 `blocking_findings` 集合（即已应用「validation 类 finding 缺失触发证据时降级为 advisory」与「spec-silent 归因窄化降级为 advisory」两条 Requirement 之后的集合）重新推导，推导规则与既有 `verdict` 三态语义一致：`blocking_findings` 非空 → `"changes-requested"`；`blocking_findings` 为空但 `findings` 非空 → `"passed-with-advisory"`；`findings` 为空 → `"approve"`。`merge_review_passes()` 内部用于合并后重算 `verdict` 的既有逻辑（`_recompute_verdict`）MUST 同步改为基于同一降级后集合判定，MUST NOT 仅依据原始 `severity ∈ {critical, high} and in_scope == true`（不含降级判定）。本 Requirement 不改变 `verdict` 字段本身的取值枚举（仍为 `approve`/`passed-with-advisory`/`changes-requested` 三态）与其在下游（telemetry、gate 判定）的既有消费方式，只改变其推导所依据的输入集合。

#### Scenario: 单 pass 中唯一 finding 被降级后 verdict 不再是 changes-requested

- **GIVEN** 一轮（非对抗式）review，`findings` 仅含一条 `category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence=""` 的 finding，顶层自报 `verdict="changes-requested"`
- **WHEN** 调用 `parse_review()`
- **THEN** 返回值 `blocking == 0`、`advisory == 1`
- **AND** 返回值 `verdict == "passed-with-advisory"`（不采信引擎自报的 `"changes-requested"`）

#### Scenario: 双 pass 合并后 verdict 基于降级后集合重算

- **GIVEN** pass1 的 `findings` 仅含一条 `spec_attribution="spec-silent"`、`severity="high"`、`in_scope=true` 的 finding，pass2 的 `findings` 为空
- **WHEN** 调用 `merge_review_passes(pass1, pass2)`
- **THEN** 合并结果的 `verdict == "passed-with-advisory"`（该 finding 因 spec-silent 非 critical 被降级，不构成 blocking）

#### Scenario: 全部 blocking 候选均被降级时 verdict 不为 changes-requested

- **GIVEN** 一轮 review 的 `findings` 含两条 finding：一条因 `trigger_evidence` 缺失被降级、另一条因 `spec_attribution="spec-silent"` 且 `severity="high"` 被降级，二者均无其它 blocking 候选
- **WHEN** 调用 `parse_review()`
- **THEN** 返回值 `blocking == 0`
- **AND** 返回值 `verdict == "passed-with-advisory"`（`findings` 非空，故不是 `"approve"`；无剩余 blocking，故不是 `"changes-requested"`）

#### Scenario: 无任何 finding 时 verdict 仍为 approve（既有语义回归）

- **GIVEN** 一轮 review 的 `findings` 为空数组
- **WHEN** 调用 `parse_review()`
- **THEN** 返回值 `verdict == "approve"`
