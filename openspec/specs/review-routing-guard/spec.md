# review-routing-guard Specification

## Purpose
TBD - created by archiving change wire-verify-routing. Update Purpose after archive.
## Requirements
### Requirement: review 执行前强制路由校验

`run_review_round` MUST 在执行任何 review 引擎调用前运行 `verify.check_routing`；存在任一 violation 时 MUST 以单行 JSON `emit_error`（含 violation 详情）拒绝执行 review 并 exit 1，MUST NOT 静默降级或继续。生成⊥验证（不变量 1）与「review 永不路由 MiMo」（不变量 4）由此在主回路代码层强制。

#### Scenario: review 引擎含 mimo 被拒绝

- **WHEN** 配置把 review 引擎/bin/model 指向 mimo，调用 `npc review run --seq N --round 0`
- **THEN** review 不执行，stdout 单行 JSON `ok=false`、`error="routing-violation"`、含具体 violation，exit 1

#### Scenario: review 与 coder 同源被拒绝

- **WHEN** review 引擎与 coder 后端解析为同源（自己评自己）
- **THEN** `npc review run` 拒绝执行并返回 routing-violation 详情，供主 session 报人

#### Scenario: 合法路由正常执行

- **WHEN** coder=claude 或 mimo、review=codex/Claude（不同源、不含 mimo）
- **THEN** `check_routing` 无 violation，review 按原契约执行并返回 blocking/stale 字段

### Requirement: review 引擎的 backend-aware 确定性选择

系统 MUST 提供单一确定性解析逻辑，按以下优先级为每次 review 选择引擎：显式引擎 override > 生成源 backend-aware 默认 > 配置引擎。无显式 override 时：生成源为 codex 或 kimi 时 MUST 选择 claude；生成源为 claude 且配置引擎与生成源同源（同为 claude 且执行身份相同）时 MUST 自动选择 codex；生成源为 claude 且配置引擎不同源时 MUST 使用配置引擎；生成源为 mimo 时 MUST 使用配置引擎。review pipeline 与 spec pipeline MUST 共用同一解析逻辑，MUST NOT 各自维护内联硬编码分支。

#### Scenario: codex/kimi 生成源默认路由 claude（既有行为收敛）

- **WHEN** 未提供显式引擎 override，且被评物的生成源为 codex 或 kimi
- **THEN** 选择的 review 引擎为 claude

#### Scenario: claude 生成源配置同源时自动路由 codex

- **WHEN** 未提供显式引擎 override，生成源为 claude，且配置引擎解析后与生成源同源
- **THEN** 选择的 review 引擎为 codex
- **AND** 不产生 routing-violation，review 正常执行

#### Scenario: claude 生成源配置不同源时使用配置引擎

- **WHEN** 未提供显式引擎 override，生成源为 claude，且配置引擎与生成源不同源
- **THEN** 选择的 review 引擎为配置引擎

#### Scenario: mimo 生成源使用配置引擎

- **WHEN** 未提供显式引擎 override，且生成源为 mimo
- **THEN** 选择的 review 引擎为配置引擎（其合法性仍由既有路由校验保证）

#### Scenario: 显式 override 优先且仍受校验

- **WHEN** 提供显式引擎 override
- **THEN** 选择结果为该 override
- **AND** 该选择仍经既有执行前路由校验，违规则拒绝执行且不静默重路由

#### Scenario: 双侧 pipeline 选择结果一致

- **GIVEN** 相同的生成源、配置与 override 输入
- **WHEN** 分别经 review pipeline 与 spec pipeline 解析 review 引擎
- **THEN** 两侧选择结果一致，且均来自同一解析逻辑

### Requirement: 文档与 CLI 帮助描述 backend-aware 默认行为

review 相关 CLI 帮助文本、入口 docstring 与插件编排规则 MUST 描述 backend-aware 默认选择行为（含 codex/kimi → claude 与 claude 同源 → codex 的自动选路），MUST NOT 继续描述「仅从配置读取默认引擎」的旧行为。插件编排规则 MUST 说明自动选路已内置，编排者显式传 `--engine claude` 仍合法但非必需。

#### Scenario: CLI 帮助与代码行为一致

- **WHEN** 阅读 review 命令的引擎参数帮助文本与入口 docstring
- **THEN** 其描述的默认解析行为与确定性选择的实际行为一致

#### Scenario: 插件编排规则与代码行为一致

- **WHEN** 阅读插件中 host adapter 的 review 路由规则
- **THEN** 其说明自动选路由解析逻辑内置完成，且不与实际行为矛盾

