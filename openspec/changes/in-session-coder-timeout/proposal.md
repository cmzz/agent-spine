## Why

审计 B6（高）：`timeout` 只传给 headless 子进程（src/npc/coder.py:346）；in-session 分支（coder.py:383-384）返回 deferred 后，主 session 的 Task spawn 无任何超时——默认路径（claude in-session）是唯一没有时间笼子的执行路径，coder 可无限挂起。现有 `npc agent timeout-budget / record-timeout` 机制（src/npc/cli.py:525-555）已造好但 skill 从不使用，导致 auto-decide 的 `agent-timeout-exhausted` trigger（auto_decide.py:26）在默认流程不可达。不变量 3：--auto 是「去掉人」的档，恰恰应该更硬——补上这道已造好的时间笼子。

## What Changes

- `spine-run.md` 3a/3b 的 deferred=true 分支：spawn spine-coder **前**调用 `npc agent timeout-budget --seq N --phase implement|fix` 取本次预算；主 session 以该预算监督 Task 执行（超预算即视为超时）。
- 超时后调用 `npc agent record-timeout` 记账，随后转 3d 决策点：预算未耗尽 → 重派（continue-retry 语义）；预算耗尽 → `npc auto-decide --trigger agent-timeout-exhausted`（现返回 skip），使该 trigger 可达。
- Guardrails 补一条：in-session coder spawn 必须带 timeout 预算，绝不无限等待。
- 纯 skill 契约接线为主；如 timeout-budget/record-timeout 返回字段不足以支撑该流程，做最小补齐并补测试。

## Capabilities

### New Capabilities

- `coder-timeout-budget`: in-session coder 的 wall-clock 超时预算契约——spawn 前取预算、超时记账、预算耗尽转 auto-decide。

### Modified Capabilities

## Impact

- `plugins/agent-spine/commands/spine-run.md`（3a/3b spawn 前取预算 + 超时处理 + Guardrails）
- `src/npc/cli.py` / `src/npc/agent_budget.py`（如返回字段需最小补齐）
- `tests/`（timeout-budget→record-timeout→exhausted 的状态链用例）
