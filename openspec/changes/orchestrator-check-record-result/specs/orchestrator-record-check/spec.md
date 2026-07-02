## ADDED Requirements

### Requirement: 主循环必须检查 record 返回值并对失败转决策点

spine-run 主循环在每次 `npc implement record` / `npc fix record` 后 MUST 读取返回 JSON 的 `.ok` 与 `.status` 做分支：`.ok=false` 或 `.status=needs-user-decision` 时 MUST 立即进入 3d 决策点，MUST NOT 继续后续 review/archive。deferred=true 时 `implement/fix run` 的 `.ok` MUST NOT 被当作 coder 执行成功的依据。

#### Scenario: fix record 失败不再被静默吞掉

- **WHEN** spine-coder 的 RESULT 行不合法或标记失败，`npc fix record` 返回 `.ok=false`（progress 置 needs-user-decision）
- **THEN** 主循环立即转 3d 决策点（auto 档 `--trigger fixer-failed`），不发起下一轮 `npc review run`
- **AND** 该 change 不会在同一循环内被 archive 覆盖成 archived

#### Scenario: implement record 失败转决策点

- **WHEN** `npc implement record` 返回 `.ok=false` 或 `.status=needs-user-decision`
- **THEN** 主循环跳过 3b review，直接进 3d（auto 档 `--trigger implementer-failed`；交互档问用户）

#### Scenario: record 成功才继续正常流

- **WHEN** `npc implement record` / `npc fix record` 返回 `.ok=true` 且 status 非 needs-user-decision
- **THEN** 主循环按原契约继续（implement 后进 review round0；fix 后进下一轮 review）
