## MODIFIED Requirements

### Requirement: spec 侧路由配置与安全默认值

配置层 MUST 提供 `[spec_writer]` 与 `[spec_review]` 两个段。`spec_writer` MUST 暴露与 `coder` 同构的 `backend` 及其 `effective_backend` 解析语义；`spec_review` MUST 暴露原始配置字段 `engine`（`str | None`，`None` 表示未显式配置该值）与按生成身份感知解析出的 `effective_engine(spec_writer_backend)`：`engine` 非 `None` 时原样返回该显式值；`engine` 为 `None` 时，`spec_writer_backend == "codex"` 解析为 `"claude"`，其余受支持后端（`"claude"`/`"kimi"`/`"mimo"`）解析为 `"codex"`。当 `.npc/config.toml` 未声明 `[spec_writer]`/`[spec_review]` 两段时，系统 MUST 解析为 `spec_writer.effective_backend == "claude"`、`spec_review.engine is None`、`spec_review.effective_engine("claude") == "codex"`，且 MUST NOT 产生任何 violation。

#### Scenario: 未配置时取安全默认值且零 violation
- **GIVEN** `.npc/config.toml` 中不存在 `[spec_writer]` 与 `[spec_review]` 段
- **WHEN** 加载配置并调用 `check_routing(cfg)`
- **THEN** `cfg.spec_writer.effective_backend` 等于 `"claude"`
- **AND** `cfg.spec_review.engine` 为 `None`
- **AND** `cfg.spec_review.effective_engine(cfg.spec_writer.effective_backend)` 等于 `"codex"`
- **AND** 返回的 violations 列表中不含任何 `rule` 以 `spec_` 开头的项

#### Scenario: 显式配置被正确解析
- **GIVEN** `.npc/config.toml` 含 `[spec_writer] backend = "mimo"` 与 `[spec_review] engine = "codex"`
- **WHEN** 加载配置
- **THEN** `cfg.spec_writer.effective_backend` 等于 `"mimo"`
- **AND** `cfg.spec_review.engine` 等于 `"codex"`（非 `None`，显式配置值原样保留）
- **AND** `cfg.spec_review.effective_engine(cfg.spec_writer.effective_backend)` 等于 `"codex"`（与显式配置值一致，因为显式值优先于按生成身份的默认值）

#### Scenario: 未显式配置时按 spec_writer 生成身份解析默认引擎
- **GIVEN** `.npc/config.toml` 声明 `[spec_writer] backend = "kimi"` 但未声明 `[spec_review]` 段（`cfg.spec_review.engine` 为 `None`）
- **WHEN** 调用 `cfg.spec_review.effective_engine(cfg.spec_writer.effective_backend)`
- **THEN** 返回 `"codex"`（生成方非 `codex` 时的默认值，与 `spec_writer.effective_backend == "claude"` 或 `"mimo"` 时的默认结果相同）

#### Scenario: codex 生成方默认解析为 claude 审查
- **GIVEN** `.npc/config.toml` 声明 `[spec_writer] backend = "codex"` 但未声明 `[spec_review]` 段
- **WHEN** 调用 `cfg.spec_review.effective_engine(cfg.spec_writer.effective_backend)`
- **THEN** 返回 `"claude"`

### Requirement: spec 侧后端有效性

`check_routing` MUST 校验 `spec_writer.effective_backend` 属于既有的受支持 coder 后端集合，越界 MUST 产出 `rule == "spec_backend_unsupported"` 的 violation，`detail` MUST 含越界的实际取值。对 `spec_review.engine`，校验对象 MUST 是该字段的**显式非 `None` 取值**：`spec_review.engine is None`（未显式配置）MUST NOT 产出任何 `spec_engine_unsupported` violation（`None` 是合法的"未配置"状态，不是待校验的取值集合成员）；`spec_review.engine` 为非 `None` 但不属于既有受支持 engine 集合的字符串时，MUST 产出 `rule == "spec_engine_unsupported"` 的 violation，`detail` MUST 含越界的实际取值。此校验 MUST NOT 检查 `effective_engine(...)` 的解析结果——`effective_engine` 折叠了默认值解析逻辑，其返回值恒为受支持集合成员，不需要也不应重复校验。

#### Scenario: 非法 spec_writer.backend 被拒
- **GIVEN** `spec_writer.backend` 取值为 `"gpt-9"`（不在受支持后端集合内）
- **WHEN** 调用 `check_routing(cfg)`
- **THEN** violations 中存在一项 `rule == "spec_backend_unsupported"`
- **AND** 该项 `detail` 含子串 `gpt-9`

#### Scenario: spec_review.engine 为 None 时不产出 spec_engine_unsupported
- **GIVEN** `spec_review.engine` 为 `None`（未显式配置）
- **WHEN** 调用 `check_routing(cfg)`
- **THEN** violations 中不存在 `rule == "spec_engine_unsupported"` 的项

#### Scenario: 非法 spec_review.engine（显式非 None 越界值）被拒
- **GIVEN** `spec_review.engine` 取值为 `"bard"`（非 `None`，且不在受支持 engine 集合内）
- **WHEN** 调用 `check_routing(cfg)`
- **THEN** violations 中存在一项 `rule == "spec_engine_unsupported"`
- **AND** 该项 `detail` 含子串 `bard`
