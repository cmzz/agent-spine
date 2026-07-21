## MODIFIED Requirements

### Requirement: findings 合并去重规则确定性

系统 MUST 按以下规则将两个 pass 各自产出的 `REVIEW_SCHEMA` 兼容 findings 数组合并为一份同样满足 `REVIEW_SCHEMA` 的最终结果：

1. 去重键为 `(file, line_range, category)` 三元组精确字符串匹配；pass2 中与 pass1 去重键相同的 finding MUST 被丢弃，保留 pass1 版本。
2. 合并顺序为 pass1 全量（原相对顺序）后接 pass2 去重后剩余（原相对顺序）；`id` 字段 MUST 按此顺序重新分配为 `F1, F2, ..., Fn`（丢弃引擎自报的原始 `id`）。
3. 合并结果的 `verdict` MUST NOT 直接按"存在至少一条 `severity ∈ {critical, high}` 且 `in_scope == true` 的 finding"这一原始候选条件计算。MUST 改为按合并后 findings 全集**降级后的最终 blocking 集合**重新计算——即先对合并结果应用 `validation-blocking-threshold` capability 定义的两条独立降级 Requirement（「validation 类 finding 缺失触发证据时降级为 advisory」「spec-silent 归因窄化降级为 advisory」），再依据降级后集合判定：存在至少一条未被降级的 blocking 候选 finding → `changes-requested`；该集合为空但 `findings` 非空 → `passed-with-advisory`；`findings` 为空 → `approve`。MUST NOT 直接采信 pass1 或 pass2 自报的 `verdict` 字段。

**Rationale（Round 5 spec 语义评审修订，F3）**：本 Requirement 修订前的第 3 条字面规定"任意 high/critical 且 in_scope finding 即 `changes-requested`"，与 `validation-blocking-threshold` capability 新增的「verdict 必须与降级后的最终 blocking 集合保持一致」Requirement（该 Requirement 明确要求 `merge_review_passes()` 的 verdict 重算基于降级后集合）在同一输入（合并后含被降级 finding 的 findings 全集）上给出相反结论——原 Requirement 说该 finding 触发 `changes-requested`，新 Requirement 说降级后不再是 blocking、verdict 应为 `passed-with-advisory` 或 `approve`。二者是同一份代码（`merge_review_passes()` → `_recompute_verdict()`）的两份互相矛盾的规范来源。经裁决：本 Requirement 第 3 条改为显式引用降级后集合，`review-adversarial-pass` 与 `validation-blocking-threshold` 两个 capability 对同一输入的结论收敛为一致。

#### Scenario: 同一问题被两个 pass 各自报告

- **WHEN** pass1 与 pass2 的 findings 中各有一条 `file`/`line_range`/`category` 三者完全相同的记录
- **THEN** 合并结果只保留 pass1 的那一条，总 findings 数比两份原始之和少 1

#### Scenario: pass2 独有 blocking finding 提升 verdict

- **WHEN** pass1 的 verdict 为 `approve`（无 findings），pass2 有一条 `severity=high` 且 `in_scope=true` 且不满足任何降级条件（`category` 非 `"validation"`、`spec_attribution` 非 `"spec-silent"`）的独有 finding
- **THEN** 合并结果的 `verdict` 为 `changes-requested`，且该 finding 出现在合并结果中并被赋予新 `id`

#### Scenario: pass2 无 findings 时合并结果等价于 pass1-only

- **WHEN** pass2 输入为空 findings 替身 `{"findings": []}`（合并规则只消费 findings 数组，verdict 恒在合并后重算、从不读取任一 pass 的自报值，故替身无需含 verdict 字段，也不违反 `REVIEW_SCHEMA` 对完整 review 产物的 verdict 必填约束——替身不是落盘产物）
- **THEN** 合并结果的 findings 与 `id` 分配和仅有 pass1 时完全一致，`verdict` 由 pass1 的 findings 集合按同一（降级后集合）规则重新计算得出

#### Scenario: pass2 独有 finding 满足候选条件但被降级时不提升 verdict

- **GIVEN** pass1 的 verdict 为 `approve`（无 findings），pass2 有一条独有 finding：`category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence` 缺失（满足原始候选条件，但触发 `validation-blocking-threshold` capability 的举证门槛降级）
- **WHEN** 执行合并
- **THEN** 合并结果的 `verdict` 为 `passed-with-advisory`（不是 `changes-requested`）——该 finding 降级后不构成 blocking，但仍出现在合并后的 findings 数组中并计入 `advisory`

### Requirement: telemetry 透出对抗通道运行状态

`review.round` telemetry 事件 MUST 新增两个字段：`adversarial_pass_ran`（`bool`，任何情况下都 MUST 是 `true` 或 `false`，MUST NOT 为 `None`/缺省）与 `adversarial_blocking_count`（`int | None`）。两字段的取值 MUST 严格按下表五种互斥情形之一确定，不存在表外取值：

| # | 情形 | round_n | adversarial_round0 | pass1 结果 | pass2 结果 | `adversarial_pass_ran` | `adversarial_blocking_count` |
|---|---|---|---|---|---|---|---|
| 1 | 双 pass 成功 | `0` | `true` | 成功 | 成功 | `true` | `int`（`>= 0`，取自合并函数在合并期间、重编号之前统计并随返回值透出的 side-channel 计数：来源于 pass2 且未被去重丢弃的 blocking **候选** finding 数——按原始 `severity ∈ {critical, high} and in_scope == true` 判定，**不感知**「validation 类 finding 缺失触发证据时降级为 advisory」/「spec-silent 归因窄化降级为 advisory」两条降级 Requirement；MUST NOT 从合并后的 `round-0.review.json` 反推——重编号后来源信息已不可辨） |
| 2 | pass2 失败降级 | `0` | `true` | 成功 | 失败（重试耗尽） | `false` | `None` |
| 3 | pass1 失败（整轮失败） | `0` | `true` | 失败（重试耗尽） | 不执行 | `false` | `None` |
| 4 | 对抗通道禁用 | `0` | `false` | 成功或失败 | 不执行 | `false` | `None` |
| 5 | round>=1 | `>= 1` | 任意 | 既有单 pass | 不适用 | `false` | `None` |

即：`adversarial_blocking_count` 当且仅当 `adversarial_pass_ran == true` 时为非 `None` 的 `int`；其余四种情形（含 pass1 失败、对抗通道禁用、round>=1）均是 `adversarial_pass_ran == false` 且 `adversarial_blocking_count is None`——这三者虽然都取值 `false`/`None`，但触发原因不同，调用方可结合 `round_n` 与配置的 `adversarial_round0` 另行区分，telemetry 字段本身不做区分。`review.round` 事件的字段白名单契约（telemetry 结构不变量测试所强制的那份登记表）MUST 同步登记这两个字段，缺失任一都视为契约破坏。

**`adversarial_blocking_count` 的语义裁决（Round 5 spec 语义评审修订，F3）**：本字段名含"blocking"，但其取值 MUST 理解为"pass2 贡献的、按原始候选条件统计的 blocking 候选数"（一个独立于降级判定的可观测性指标），MUST NOT 被理解或消费为"降级后实际计入最终 `blocking_findings`/驱动 `verdict == changes-requested` 的 finding 数"——这两个数值在存在降级发生时可能不相等（例如 pass2 独有一条 `category="validation"` 且 `trigger_evidence` 缺失的 finding：其计入 `adversarial_blocking_count`，但因降级不计入最终 `blocking_findings`，也不驱动 `verdict` 变为 `changes-requested`）。选择保留字段名与"候选层"语义（而非重命名或改为"降级后集合"语义）的理由：(1) 该计数在合并函数内部于降级判定生效之前的阶段（重编号之前）统计，若要求其反映降级后语义，需要合并逻辑先完成降级判定、再回溯统计"来源于 pass2 的有效 blocking finding 数"，属于新增的架构调整，超出本 change"消除矛盾陈述"的范围；(2) 该字段仅用于 telemetry 观测"对抗式 pass 相对 compliance pass 额外发现了多少候选问题"，从未被 `verdict`/`blocking`/`auto-decide` 等任何判定逻辑读取（`rg` 确认 `adversarial_blocking_count` 在 `src/npc/` 内仅出现在 telemetry 事件构造与测试断言中），不存在"名实不符导致误判定"的实际风险，只需在契约文本中显式消歧即可。

#### Scenario: round-0 双 pass 成功时事件含两个新字段

- **WHEN** round-0 双 pass 均成功且合并出至少 1 条来源于 pass2 的 blocking **候选**（原始 `severity`/`in_scope` 判定，不论是否随后被降级）finding
- **THEN** 对应 `review.round` 事件的 `adversarial_pass_ran == true`，`adversarial_blocking_count >= 1`

#### Scenario: pass2 独有的 blocking 候选 finding 被降级时 adversarial_blocking_count 仍计数该候选

- **GIVEN** round-0 双 pass 均成功，pass2 独有一条 `category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence` 缺失的 finding（未被 pass1 去重丢弃）
- **WHEN** 执行合并并 emit `review.round` 事件
- **THEN** `adversarial_blocking_count == 1`（按原始候选条件统计，不感知降级）
- **AND** 该 finding 在合并结果中被降级为 advisory，不计入最终 `blocking_findings`，也不驱动 `verdict == "changes-requested"`——`adversarial_blocking_count` 与最终 `blocking`/`verdict` 判定在此场景下不等价，这是本 Requirement 显式裁决的既有语义，不是缺陷

#### Scenario: pass2 失败降级时事件新字段为 false/None

- **WHEN** round-0 的 pass1 成功、pass2 重试耗尽仍未产出合法 JSON
- **THEN** 对应 `review.round` 事件（`ok == true`）的 `adversarial_pass_ran == false` 且 `adversarial_blocking_count is None`

#### Scenario: pass1 失败（整轮失败）时事件新字段为 false/None

- **WHEN** round-0 的 pass1 重试耗尽仍未产出合法 JSON，round-0 整轮失败
- **THEN** 对应 `review.round` 事件（`ok == false`）仍 MUST 含 `adversarial_pass_ran == false` 且 `adversarial_blocking_count is None`（不是缺省字段，不是 `None`/未定义值）

#### Scenario: `adversarial_round0=false` 时事件新字段为 false/None

- **WHEN** `[review].adversarial_round0 = false` 且 `round_n == 0`，round-0 只执行单一 compliance pass
- **THEN** 对应 `review.round` 事件的 `adversarial_pass_ran == false` 且 `adversarial_blocking_count is None`

#### Scenario: round>=1 事件的新字段为固定 false/None

- **WHEN** `round_n >= 1` 的 review.round 事件被 emit
- **THEN** 事件含 `adversarial_pass_ran == false`（`bool`，不是 `None`）且 `adversarial_blocking_count is None`
