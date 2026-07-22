# init-worktree Specification

## Purpose
TBD - created by archiving change npc-init-worktree-lifecycle. Update Purpose after archive.
## Requirements
### Requirement: npc init 默认为每个 run 创建独立 worktree

`npc init`（无 `--no-worktree`）MUST 在主 checkout 当前 HEAD 上创建分支 `spine/<run_ts>` 与对应 git worktree（位于 `~/.spine/worktrees/<canonical_proj_key>/<run_ts>/`），并以 worktree 路径作为 `repo_root` 计算本 run 的 `Paths`（从而 state/active.json/index 全部按 worktree 路径隔离）。

#### Scenario: 默认创建 worktree 并按其路径重键

- **WHEN** 在主 checkout 执行 `npc init`
- **THEN** 新建 worktree 与分支 `spine/<run_ts>`
- **AND** 返回 JSON 含 `worktree_root`、`spine_branch`、`canonical_proj_key`
- **AND** `Paths.repo_root` 等于 worktree 路径，`task_log_dir` 按 worktree 路径派生

#### Scenario: --no-worktree 保留就地行为

- **WHEN** 执行 `npc init --no-worktree`
- **THEN** 不创建 worktree，行为与既有就地 init 一致（repo_root = 主 checkout）

#### Scenario: worktree 创建失败不留半残

- **WHEN** worktree 或分支创建失败（分支已存在指向别处 / 磁盘问题）
- **THEN** init 以环境错误（exit 3）报错，不写入半残的 run.json/active.json

### Requirement: run.json 记录 canonical 回指字段

worktree 模式下 `run.json` MUST 持久化 `canonical_repo_root`、`canonical_proj_key`、`base_branch`、`spine_branch`，供 finalize 合并回 main、telemetry 分组使用。`read_run_json` MUST 能还原这些字段。

#### Scenario: 回指字段往返一致

- **WHEN** worktree 模式 init 写出 run.json 后再 `read_run_json`
- **THEN** 还原出的 `canonical_repo_root`/`canonical_proj_key`/`base_branch`/`spine_branch` 与写入一致

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

