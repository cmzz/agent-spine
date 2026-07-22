## Why

`npc review run` 的 backend-aware 默认引擎选择（codex/kimi 生成源 → claude review）目前以硬编码内联分支散落在两处（review pipeline 与 spec pipeline），无单一确定性 resolver；claude 生成源在配置引擎同源时只会被路由校验拒绝，没有任何自动选路；且 CLI help、docstring 与插件编排规则仍描述旧的「仅配置默认」行为，与代码现状脱节。

## What Changes

- 新增单一确定性 review 引擎 resolver：显式 override > 生成源 backend-aware 默认 > 配置引擎，供 review pipeline 与 spec pipeline 共用，替换两处内联分支。
- 补齐 claude 生成源的自动选路：无显式 override 且配置引擎与生成源同源时，review 自动路由到 codex，而不是仅以 routing-violation 拒绝。
- 显式 override 语义不变：override 永远优先，且仍经路由校验，违规即拒绝，绝不静默重路由。
- 文档对齐：CLI `--engine` help、review 入口 docstring、插件编排规则更新为 backend-aware 默认行为。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `review-routing-guard`: 从「仅执行前路由校验（拒绝）」扩展为「确定性选择 + 校验」——新增 backend-aware 默认选择、claude 生成源自动路由 codex、单一 resolver 共用、override 优先级与校验不变等需求。

## Impact

- 代码：`src/npc/` 中 review 引擎解析（pipeline、spec pipeline）与新增/复用 verify 模块的 resolver 纯函数。
- 文档：`src/npc/cli.py` `--engine` help、`run_review_round` docstring、`plugins/agent-spine/` 下 spine-run 编排规则（各 host adapter mapping）。
- 测试：resolver 纯函数单测 + pipeline/spec pipeline 的 claude 生成源自动选路回归测试。
- 行为兼容：codex/kimi 生成源的现有默认（→ claude）不变；`check_routing` 的 violation 规则、`rule` 字符串与退出码不变。

## Non-Goals

- 不修改 `check_routing` 的任何 violation 规则、触发条件、`rule` 字符串或 `detail` 语义。
- 不修改 `generator_backend` 的记录机制与 legacy phase 的 config 回退语义。
- 不引入新的 review 引擎或 coder 后端。
- 不改变显式 override 被拒时的错误形态（仍 routing-violation，exit 1）。
