## ADDED Requirements

### Requirement: 显式指定 review engine 不受生成后端一刀切禁令限制

当调用方显式指定 review engine（CLI `--engine` 覆盖，或 `[review].engine`/`[spec_review].engine` 的显式 TOML 配置）时，`run_review_round` 与 spec 侧同构入口 MUST 允许对任意受支持生成后端（`claude`/`codex`/`kimi`/`mimo`）产出的、且生成阶段本身未违反任何结构性不变量的合法产物，指定任意受支持的 review engine（`codex`/`claude`），MUST NOT 仅因"生成者是某个特定后端"这一单一维度就无条件拒绝该显式指定。仍对显式指定生效的约束是既有结构性不变量：生成⊥验证正交（`gen_not_orthogonal`/`spec_gen_not_orthogonal`，自己不评自己）、MiMo 仅限执行（`mimo_exec_only`/`spec_mimo_exec_only`）；这些判定范围与触发条件不因本 Requirement 而改变。此外，MiMo 仅限 headless 执行（`mimo_in_session`/`spec_mimo_in_session`）是作用于**生成阶段本身**的独立结构性约束（判定 `spec_writer`/对应 coder phase 的分发方式是否 in-session），与"验证方是否显式指定"无关；MiMo 生成方以 in-session 方式产出的产物本身已违反该约束，不因验证方显式指定了任意合法 review engine 而被本 Requirement 豁免或放行。

#### Scenario: 显式指定对 kimi 生成产物的 codex review 被放行
- **GIVEN** 最近一次 implement/fix 产物由 `kimi` 生成
- **WHEN** 显式请求 `--engine codex` 执行 review
- **THEN** review 正常执行，不产生 routing-violation

#### Scenario: 显式指定对 kimi 写的 spec 的 codex review 被放行
- **GIVEN** 某 spec 由 `kimi` 生成身份写成
- **WHEN** 显式请求 `--engine codex` 执行 spec review
- **THEN** spec review 正常执行，不产生 spec routing-violation

#### Scenario: 显式指定仍受生成⊥验证正交约束
- **GIVEN** `coder.effective_backend == "codex"` 且最近一次产物由 `codex` 生成
- **WHEN** 显式请求 `--engine codex` 执行 review（同源自评）
- **THEN** review 不执行，返回 `rule == "gen_not_orthogonal"` 的 routing-violation

#### Scenario: 显式指定仍受 MiMo 仅限执行约束
- **GIVEN** 任意生成后端产出的产物
- **WHEN** 显式请求的 review engine/`claude_model`/`claude_bin` 含子串 `mimo`
- **THEN** review 不执行，返回 `rule == "mimo_exec_only"` 的 routing-violation

#### Scenario: MiMo in-session 生成的 spec 即便显式指定 codex review 仍被拒绝
- **GIVEN** 某 spec 由 `spec_writer.effective_backend == "mimo"` 以 in-session 方式生成（`spec_mimo_in_session` 已在生成阶段命中）
- **WHEN** 显式请求 `--engine codex` 执行该 spec 的 review
- **THEN** `check_routing`/spec 侧同构入口仍返回 `rule == "spec_mimo_in_session"` 的 routing-violation
- **AND** 本 Requirement（显式指定 review engine 放行）不豁免、不覆盖这条判定——该约束作用于生成阶段本身，与验证方的显式指定无关

### Requirement: 未显式配置 review engine 时按生成身份感知默认路由

当调用方未显式指定 review engine（CLI 未覆盖且 `[review].engine`/`[spec_review].engine` 未配置）时，系统 MUST 按生成方（`coder.effective_backend`/`spec_writer.effective_backend`）解析出的有效身份选择默认 review engine：生成方为 `codex` 时默认路由到 `claude`；生成方为其它受支持后端（`claude`/`kimi`/`mimo`）时默认路由到 `codex`。此默认解析规则 MUST 对 code review（`run_review_round`）与 spec review（spec 侧同构入口）同构应用，两处 MUST NOT 使用不一致的判定条件或分支形态。

#### Scenario: codex 生成默认路由到 claude review（既有行为，本 Requirement 显式记录其契约）
- **GIVEN** 最近一次 implement/fix 产物由 `codex` 生成，未显式指定 review engine
- **WHEN** 调用 `run_review_round`
- **THEN** 实际执行的 review engine 为 `claude`

#### Scenario: claude 生成默认路由到 codex review
- **GIVEN** 最近一次 implement/fix 产物由 `claude` 生成，未显式指定 review engine
- **WHEN** 调用 `run_review_round`
- **THEN** 实际执行的 review engine 为 `codex`

#### Scenario: mimo 生成默认路由到 codex review
- **GIVEN** 最近一次 implement/fix 产物由 `mimo` 生成，未显式指定 review engine
- **WHEN** 调用 `run_review_round`
- **THEN** 实际执行的 review engine 为 `codex`

#### Scenario: kimi 生成默认路由到 codex review
- **GIVEN** 最近一次 implement/fix 产物由 `kimi` 生成，未显式指定 review engine
- **WHEN** 调用 `run_review_round`
- **THEN** 实际执行的 review engine 为 `codex`

#### Scenario: spec 侧默认路由与 code 侧同构
- **GIVEN** 某 spec 的 `spec_writer.effective_backend` 分别取 `codex`/`claude`/`kimi`/`mimo`，未显式指定 spec review engine
- **WHEN** 调用 spec 侧同构入口解析默认 spec review engine
- **THEN** `spec_writer.effective_backend == "codex"` 时解析为 `claude`，其余三种取值均解析为 `codex`，与 code 侧的判定条件形态一致（不各写一套判断条件）

### Requirement: code 侧 review.engine 有效性与 None 语义

`review.engine` 的类型 MUST 为 `str | None`，`None` 表示未显式配置该值（等待按生成身份感知解析出的 `effective_engine(generator_backend)` 填充具体值）；`None` 本身 MUST 被视为合法的"未配置"状态，MUST NOT 被当作待校验的越界取值。`check_routing` 对 `review.engine` 的有效性校验（`rule == "engine_unsupported"`）MUST 遵循与 `spec_review.engine`/`spec_engine_unsupported`（本 change 同一 capability 内 `spec-routing-invariant` delta 定义）对称的语义：`review.engine is None` MUST NOT 产出 `engine_unsupported` violation；`review.engine` 为非 `None` 但不属于 `SUPPORTED_ENGINES` 的字符串时 MUST 产出 `rule == "engine_unsupported"` 的 violation，`detail` MUST 含越界的实际取值。

此校验规则 MUST 对两类调用路径同时生效、无差别应用（`check_routing` 本身不区分调用方是否已完成 effective 解析）：

- **`run_review_round` 路径**：调用 `check_routing` 前 MUST 先通过 `review.effective_engine(generator_backend)` 解析出具体 engine 字符串，并写回 `effective_cfg.review.engine`（`dataclasses.replace`）后再传入 `check_routing`；该路径下 `check_routing` 收到的 `review.engine` 恒为具体字符串，本 Requirement 的 `None` 分支不会被触发，但 `check_routing` 本身的判定逻辑 MUST NOT 依赖调用方是否已完成此解析——即判定逻辑对 `None` 的处理是无条件的，不是"因为调用方保证不传 None 所以不用管"。
- **`npc verify routing`（`src/npc/verify.py` 内直接对原始 `cfg` 调用 `check_routing(cfg)` 的路径，不经过 `effective_engine` 解析）**：`.npc/config.toml` 未显式配置 `[review].engine` 时，`cfg.review.engine` 为 `None`，调用 `check_routing(cfg)` MUST NOT 因此产出 `engine_unsupported` violation。

#### Scenario: 未配置 [review].engine 时直接调用 check_routing 不触发 engine_unsupported
- **GIVEN** `.npc/config.toml` 中不存在 `[review]` 段或该段内无 `engine` key（`cfg.review.engine` 为 `None`）
- **WHEN** 调用 `check_routing(cfg)`（未经 `effective_engine` 解析的原始 cfg，对应 `npc verify routing` 的调用路径）
- **THEN** violations 中不存在 `rule == "engine_unsupported"` 的项

#### Scenario: 非法 review.engine（显式非 None 越界值）仍被拒绝
- **GIVEN** `review.engine` 取值为 `"bard"`（非 `None`，且不在 `SUPPORTED_ENGINES` 内）
- **WHEN** 调用 `check_routing(cfg)`
- **THEN** violations 中存在一项 `rule == "engine_unsupported"`
- **AND** 该项 `detail` 含子串 `bard`

#### Scenario: run_review_round 路径下 check_routing 恒收到已解析的具体 engine
- **GIVEN** `.npc/config.toml` 未显式配置 `[review].engine`，最近一次产物由任意受支持后端生成
- **WHEN** 调用 `run_review_round`（未显式传 `--engine`）
- **THEN** `run_review_round` 内部传给 `check_routing` 的 `effective_cfg.review.engine` 为具体字符串（`review.effective_engine(generator_backend)` 的解析结果），不为 `None`
- **AND** 不因"未配置"这一状态本身产出 `engine_unsupported` violation
