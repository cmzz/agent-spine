## ADDED Requirements

### Requirement: in-session coder spawn 必须受 wall-clock 超时预算约束

spine-run 在 deferred=true 分支 spawn spine-coder 前 MUST 通过 `npc agent timeout-budget` 获取本次预算并以之监督执行；超时 MUST 调用 `npc agent record-timeout` 记账并转决策点；预算耗尽 MUST 以 `--trigger agent-timeout-exhausted` 调用 auto-decide。in-session 路径 MUST NOT 无限等待 coder。

#### Scenario: coder 超时被记账并重派

- **WHEN** in-session spine-coder 执行超出 timeout-budget 给出的预算且预算未耗尽
- **THEN** 主 session 调用 `npc agent record-timeout` 记账，回到对应阶段重派 coder

#### Scenario: 预算耗尽转 auto-decide

- **WHEN** 同一 seq/phase 的超时记账使预算耗尽
- **THEN** auto 档调用 `npc auto-decide --trigger agent-timeout-exhausted`，按返回 action（skip，status=skipped-auto）处理
- **AND** `agent-timeout-exhausted` trigger 在默认流程可达

#### Scenario: 正常完成不受影响

- **WHEN** coder 在预算内返回合法 RESULT 行
- **THEN** 流程按原契约 record 装订，预算状态不阻塞后续阶段
