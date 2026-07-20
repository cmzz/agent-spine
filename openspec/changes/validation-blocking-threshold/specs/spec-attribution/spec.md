## MODIFIED Requirements

### Requirement: spec 归因不参与 blocking 判定

`parse_review()` 的 `blocking` 计数 MUST 继续仅由 `severity ∈ {critical, high}` 且 `in_scope == true` 决定，这是本 Requirement 的基线规则。`spec_attribution` 取值为 `spec-ambiguous`、`spec-contradicted`、`impl-deviation` 时，其取值 MUST NOT 改变某条 finding 是否计入 blocking——这三个归因值不存在任何例外，完全遵守基线规则。`spec_attribution == "spec-silent"` 时，MUST 遵守 `validation-blocking-threshold` capability「spec-silent 归因窄化降级为 advisory」Requirement 定义的窄化例外：`severity == "critical"` 时不受影响（继续遵守基线规则，计入 blocking）；`severity == "high"` 时降级为 advisory（不计入 blocking）。本 Requirement 不定义该窄化例外的具体判定逻辑，仅声明其存在与适用范围边界，避免与 `validation-blocking-threshold` capability 产生重复或矛盾的规范来源。

#### Scenario: 非 spec-silent 归因值不影响 blocking 计数

- **GIVEN** 两个 review JSON，findings 完全相同（`category` 均非 `"validation"`，避免与 validation 举证门槛降级交叉），仅 `spec_attribution` 分别为 `spec-ambiguous` 与 `impl-deviation`
- **WHEN** 分别调用 `parse_review()`
- **THEN** 两者的 `blocking` 值相等
- **AND** 两者的 `advisory` 值相等

#### Scenario: spec-silent 且 severity=critical 时归因值仍不影响 blocking 计数

- **GIVEN** 两个 review JSON，findings 完全相同（`severity="critical"`，`category` 均非 `"validation"`，避免与 validation 举证门槛降级交叉），仅 `spec_attribution` 分别为 `spec-silent` 与 `impl-deviation`
- **WHEN** 分别调用 `parse_review()`
- **THEN** 两者的 `blocking` 值相等

#### Scenario: spec-silent 且 severity=high 时归因值改变 blocking 计数（窄化例外生效）

- **GIVEN** 两个 review JSON，findings 完全相同（`severity="high"`，`category` 均非 `"validation"`，避免与 validation 举证门槛降级交叉），仅 `spec_attribution` 分别为 `spec-silent` 与 `impl-deviation`
- **WHEN** 分别调用 `parse_review()`
- **THEN** `spec_attribution="spec-silent"` 的一方 `blocking` 值比 `spec_attribution="impl-deviation"` 的一方少 1（该 finding 被降级为 advisory）

### Requirement: 本 change 不引入任何闸门

`spec_attribution` 或 `spec_attributable_blocking_rate` MUST NOT 基于本 capability 自身引入除 `validation-blocking-threshold` capability「spec-silent 归因窄化降级为 advisory」Requirement 明确定义的降级规则之外的任何阻断、阈值、退出码变更或 `auto-decide` 触发条件。该降级规则本身（仅 `spec-silent` 且非 `critical` 触发、结果为"计入 advisory 而非 blocking"）MUST 是 `spec_attribution` 字段唯一被允许影响流程结果的路径；`spec_attribution_counts`/`spec_attributable_blocking_rate` 这两个既有派生/聚合指标 MUST 保持纯观测性质，不驱动任何额外判定。

#### Scenario: 归因率极高时流程不受额外新增阻断影响

- **GIVEN** 两个 review JSON：A 的全部 blocking finding 归因均为 `spec-ambiguous`/`spec-contradicted`、`severity="critical"`（`spec_attributable_blocking_rate == 1.0`，且因 `severity == "critical"` 不触发 `validation-blocking-threshold` capability 定义的任何降级）；B 的 findings 与 A 完全相同，仅将 `spec_attribution` 全部替换为同 `severity` 的 `impl-deviation`（`spec_attributable_blocking_rate == 0`）
- **WHEN** A、B 两个 change 各自走完 review → fix → archive 流程
- **THEN** 二者的 archive 结果完全一致（不受 `spec_attributable_blocking_rate` 取值差异影响）
- **AND** `npc auto-decide` 的可用 trigger 集合在两种情形下均未新增任何项

#### Scenario: spec-silent 降级不属于本 Requirement 禁止的"其它闸门"

- **GIVEN** 某 change 存在 `spec_attribution="spec-silent"`、`severity="high"` 的 finding，按窄化降级规则被计入 advisory
- **WHEN** 核查该 change 的流程是否违反本 Requirement
- **THEN** 该降级是本 Requirement 显式允许的唯一例外，不视为违反，`npc auto-decide` 的可用 trigger 集合仍未新增任何项

### Requirement: 派生 spec 归因分布并向后兼容

`parse_review()` 的返回值 MUST 新增键 `spec_attribution_counts`，其值为映射：四个枚举值各自的 finding 计数，外加键 `unknown` 统计缺失 `spec_attribution` 字段的 finding 数。统计范围 MUST 与最终计入 `blocking`（即 `blocking_findings`）的 finding 集合完全一致——**不是**原始 `severity ∈ {critical, high}` 且 `in_scope == true` 的 blocking 候选集合。任何满足候选条件、但因 `validation-blocking-threshold` capability「validation 类 finding 缺失触发证据时降级为 advisory」或本 capability「spec 归因不参与 blocking 判定」Requirement 定义的 spec-silent 窄化例外而被降级为 advisory 的 finding，MUST NOT 计入 `spec_attribution_counts`（含其 `unknown` 键，即使该 finding 的 `spec_attribution` 字段缺失也不计入 `unknown`）——这是本 Requirement 相对于该字段引入前既有语义的显式修订：既有语义按"blocking 候选集合"统计，本 change 引入降级后改为按"降级后最终 blocking 集合"统计，二者在无降级发生时结果相同、在有降级发生时不再等价。缺失该字段的历史 review.json MUST 被正常解析，MUST NOT 抛异常。

#### Scenario: 历史 review.json 无该字段仍可解析
- **GIVEN** 一个 review JSON，其全部 findings 均不含 `spec_attribution` 键，其中 2 条为 in_scope 的 high（`category` 均非 `"validation"`，避免与 validation 举证门槛降级交叉）
- **WHEN** 调用 `parse_review(data)`
- **THEN** 不抛异常
- **AND** 返回值 `.spec_attribution_counts["unknown"]` 等于 `2`
- **AND** 返回值 `.blocking` 等于 `2`

#### Scenario: 混合归因被正确计数
- **GIVEN** 一个 review JSON，其 in_scope blocking findings 的 `spec_attribution` 依次为 `spec-silent`、`spec-silent`、`impl-deviation`，`severity` 均为 `"critical"`（避免与 spec-silent 非 critical 窄化降级交叉），`category` 均非 `"validation"`（避免与 validation 举证门槛降级交叉）
- **WHEN** 调用 `parse_review(data)`
- **THEN** `.spec_attribution_counts["spec-silent"]` 等于 `2`
- **AND** `.spec_attribution_counts["impl-deviation"]` 等于 `1`
- **AND** `.spec_attribution_counts["unknown"]` 等于 `0`

#### Scenario: advisory finding 不计入归因分布
- **GIVEN** 一个 review JSON，含 1 条 `severity == "low"` 的 finding，其 `spec_attribution == "spec-silent"`，无任何 blocking finding
- **WHEN** 调用 `parse_review(data)`
- **THEN** `.spec_attribution_counts` 的所有值之和为 `0`

#### Scenario: 因 spec-silent 窄化例外被降级的 finding 不计入归因分布

- **GIVEN** 一条 finding：`spec_attribution="spec-silent"`、`severity="high"`、`in_scope=true`（满足 blocking 候选条件，但按窄化例外被降级为 advisory）
- **WHEN** 调用 `parse_review(data)`
- **THEN** `.spec_attribution_counts["spec-silent"]` 等于 `0`（该 finding 未计入，因其已不在最终 blocking 集合内）

#### Scenario: 因 validation 缺证据被降级的 finding 不计入归因分布（不论其归因值）

- **GIVEN** 一条 finding：`category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence` 缺失、`spec_attribution="impl-deviation"`（满足 blocking 候选条件，但按 validation 举证门槛被降级为 advisory）
- **WHEN** 调用 `parse_review(data)`
- **THEN** `.spec_attribution_counts["impl-deviation"]` 等于 `0`（该 finding 因证据缺失降级，不因其归因值非 spec-silent 而计入）
