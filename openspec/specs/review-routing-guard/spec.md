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

