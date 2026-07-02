## ADDED Requirements

### Requirement: auto-decide 决策与 finalize 结果必须进入 telemetry

`npc auto-decide` 每次决策 MUST emit 一条 telemetry 事件（trigger/action/reason/seq/change_id/applied）；`npc state finalize` MUST emit 一条 run 级事件（status/merged_back/worktree_removed 等）。telemetry 写入失败 MUST NOT 阻塞主流程或污染 stdout JSON。

#### Scenario: auto-decide 决策可被 /spine-analyze 统计

- **WHEN** auto 档触发 `npc auto-decide --trigger stale --seq 2` 并返回 action=skip
- **THEN** `_telemetry` 中新增一条 kind=`auto_decide.decision` 事件，含 trigger=stale、action=skip、seq=2、change_id
- **AND** stdout 决策 JSON 契约不变

#### Scenario: finalize 结果进入指标流

- **WHEN** `npc state finalize` 完成（无论 merged_back 真假）
- **THEN** `_telemetry` 中新增一条 kind=`run.finalize` 事件，含顶层 status、merged_back、worktree_removed

#### Scenario: telemetry 不可写不阻塞

- **WHEN** telemetry 目录不可写
- **THEN** auto-decide 与 finalize 仍按原契约返回单行 JSON 与 exit code
