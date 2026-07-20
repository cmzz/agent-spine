## MODIFIED Requirements

### Requirement: in-session 分发绝不与廉价层同源

`npc verify routing` MUST 保证 in-session 分发只用于 premium 后端（claude/codex/kimi），mimo 后端 MUST 始终 headless；任何把 mimo 与 in-session 绑定的配置即 violation。

#### Scenario: mimo + in-session 判为 violation

- **WHEN** 配置使 mimo 后端的某 phase 解析出 `in-session`
- **THEN** `npc verify routing` 报告 violation（非零退出 / `ok=false`）

#### Scenario: kimi 后端的 in-session 分发不构成 violation

- **WHEN** Kimi runtime 下未显式配置 dispatch 且某 phase 的 backend 解析为 `kimi`、dispatch 解析为 `in-session`
- **THEN** `npc verify routing` 不报告 in-session 相关 violation（kimi 属 premium 后端白名单）
