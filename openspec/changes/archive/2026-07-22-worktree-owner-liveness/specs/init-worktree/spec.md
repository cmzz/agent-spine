## MODIFIED Requirements

### Requirement: 续跑探测扫描悬空 spine worktree

`npc init` 在创建新 worktree 之前 MUST 扫描既有 `spine/*` worktree（`git worktree list --porcelain`），若某 worktree 的 task_log 存在 in-progress state，MUST 先对该 state 做 owner 存活判定（见 `worktree-owner-liveness` capability 的「owner 存活判定——pid 探测只能确认存活，判死由心跳新鲜度决定」Requirement）：owner 仍存活时 MUST NOT 将其视为悬空候选（视为他人活跃 run，继续正常创建新 worktree）；只有 owner 已死的 in-progress state 才报 `needs_resume=true` 并指向该 `worktree_root`，不创建新 worktree。initializing 中间态（worktree 已建但 `init-run` 未执行）候选同样先过 owner 存活判定，owner 存活时不视为可复用的崩溃恢复候选。

#### Scenario: 命中悬空 in-progress worktree 且 owner 已死则续跑

- **WHEN** 存在一个 `spine/*` worktree 且其 task_log 有 in-progress state，且该 state 的 owner 已死
- **AND** 在主 checkout 执行 `npc init`
- **THEN** 返回 `needs_resume=true` 且 `worktree_root` 指向该悬空 worktree
- **AND** 不创建新的 worktree/分支

#### Scenario: 命中 in-progress worktree 但 owner 仍存活则不续跑

- **WHEN** 存在一个 `spine/*` worktree 且其 task_log 有 in-progress state，且该 state 的 owner 仍存活（另一并发 `npc init` 正在跑该 run）
- **AND** 在主 checkout 执行 `npc init`
- **THEN** 该 worktree 不被视为悬空候选，`needs_resume` 不指向它
- **AND** 正常创建一个独立的新 worktree（`needs_resume=false` 或指向其它真正悬空的候选）

#### Scenario: 无悬空 run 则正常新建

- **WHEN** 不存在带 in-progress state 的 `spine/*` worktree
- **THEN** 正常创建新 worktree 并 `needs_resume=false`

#### Scenario: 命中 initializing 候选但 owner 仍存活则不接管

- **WHEN** 存在一个 `spine/*` worktree 处于 initializing 中间态（worktree 已建但 `init-run` 未执行），且该骨架 state 的 owner 仍存活（另一并发 `npc init` 正在初始化该 worktree）
- **AND** 在主 checkout 执行 `npc init`
- **THEN** 该 initializing worktree 不被视为可复用的崩溃恢复候选
- **AND** 正常创建一个独立的新 worktree（`needs_resume=false` 或指向其它真正悬空的候选）

#### Scenario: 命中 initializing 候选且 owner 已死则按崩溃恢复候选续跑

- **WHEN** 存在一个 `spine/*` worktree 处于 initializing 中间态（worktree 已建但 `init-run` 未执行），且该骨架 state 的 owner 已死
- **AND** 在主 checkout 执行 `npc init`
- **THEN** 该 worktree 被视为崩溃恢复候选，返回 `needs_resume=true` 且 `worktree_root` 指向该 worktree
- **AND** 不创建新的 worktree/分支

## ADDED Requirements

### Requirement: `npc init --takeover` 显式接管 owner 判定仍存活的候选

`npc init` MUST 提供 `--takeover` 旗标：悬空扫描与 `--no-worktree` 续跑探测在该旗标下 MUST 跳过 owner 存活门槛，把 owner 判定仍存活的 in-progress / initializing 候选照常纳入续跑候选池（用于崩溃后心跳尚未过期、用户确认原 session 已死时的手动恢复通道）。`--takeover` 与 `--fresh` MUST 互斥（前者抢占既有 run，后者无视既有 run，同时给出无意义）。`--takeover` MUST NOT 豁免孤儿标记的 owner 存活门槛——接管是续跑语义，不是把他人活跃骨架判残骸的许可。

#### Scenario: --takeover 接管 owner 存活的 in-progress worktree

- **WHEN** 存在一个 `spine/*` worktree 且其 task_log 有 in-progress state，其 owner 判定为存活
- **AND** 在主 checkout 执行 `npc init --takeover`
- **THEN** 返回 `needs_resume=true` 且 `worktree_root` 指向该 worktree（显式接管）

#### Scenario: --takeover 与 --fresh 互斥

- **WHEN** 执行 `npc init --fresh --takeover`
- **THEN** 参数解析失败退出（exit code 2），不执行任何扫描或写入

#### Scenario: --takeover 不豁免孤儿标记门槛

- **WHEN** 存在一份 worktree 缺失、但骨架 owner 判定存活的 initializing 记录
- **AND** 执行 `npc init --takeover`
- **THEN** 该骨架 MUST NOT 被标记为 `orphan`（status 保持 `initializing`）
