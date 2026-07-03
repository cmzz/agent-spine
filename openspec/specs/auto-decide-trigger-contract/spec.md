# auto-decide-trigger-contract Specification

## Purpose
TBD - created by archiving change fix-auto-decide-trigger-contract. Update Purpose after archive.
## Requirements
### Requirement: skill 侧 trigger 词表与代码词表一致

`spine-run.md` 中出现的所有 `npc auto-decide --trigger` 候选值 MUST 是 `auto_decide.VALID_TRIGGERS` 的子集，并由守卫测试机器强制。`_decide` MUST 对 `VALID_TRIGGERS` 中每个 trigger 都有可达分支（含 archive 失败场景）。

#### Scenario: 主 session 照 skill 字面调用不再崩

- **WHEN** 主 session 按 spine-run.md 3d 示范的任一 trigger 值调用 `npc auto-decide`
- **THEN** 返回 `ok=true` 与合法 `action`，不出现 `invalid_trigger` exit 2

#### Scenario: 守卫测试拦截词表漂移

- **WHEN** 有人改 spine-run.md 引入一个不在 `VALID_TRIGGERS` 中的 `--trigger` 候选值
- **THEN** 守卫测试失败，明确指出漂移的值与合法集

#### Scenario: archive 失败有合法决策入口

- **WHEN** `npc archive run` 失败，主 session 以 `--trigger archive-failed` 调用 auto-decide
- **THEN** 首次返回 `action=continue-retry`（记 retry 计数），同一 seq 再次触发返回 `action=skip` 且 `set_status=skipped-auto`

