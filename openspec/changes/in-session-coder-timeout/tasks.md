## 1. skill 接线

- [ ] 1.1 spine-run.md 3a：deferred=true 时 spawn 前 `npc agent timeout-budget --seq N --phase implement` 取预算，注明主 session 以预算监督 Task
- [ ] 1.2 spine-run.md 3b：fix 分支同样接入
- [ ] 1.3 超时路径：`npc agent record-timeout` 记账 → 预算未耗尽重派 / 耗尽 `npc auto-decide --trigger agent-timeout-exhausted`
- [ ] 1.4 Guardrails 增补：in-session spawn 必须带 timeout 预算

## 2. npc 侧核对与最小补齐

- [ ] 2.1 核对 timeout-budget/record-timeout 返回字段（剩余预算、exhausted 标志）足以支撑上述分支；不足则最小补齐
- [ ] 2.2 exhausted 状态与 auto-decide `agent-timeout-exhausted` trigger 的衔接核对

## 3. 测试

- [ ] 3.1 状态链用例：budget→record-timeout（×N）→exhausted 标志翻转
- [ ] 3.2 exhausted 后 auto-decide 返回 skip（现有语义回归）
- [ ] 3.3 守卫测试：spine-run.md 含 timeout-budget 调用（skill 契约不回退）
- [ ] 3.4 `pytest` 全绿
