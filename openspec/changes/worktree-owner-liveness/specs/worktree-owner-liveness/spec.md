## ADDED Requirements

### Requirement: plan-state 持久化 owner 存活信息

`*-plan-state.json`（含 `npc init` 建 worktree 前落盘的 `initializing` 骨架，以及 `state init-run` 之后的正式 STATE_JSON）MUST 携带三个可选顶层字段：`owner_pid`（int，最近一次触发该 run 生命周期子命令的父进程 pid，即 `os.getppid()`——触发本次子命令调用的 CC 主 session / shell 进程，而非 npc 子进程自身的 pid）、`owner_session_id`（string 或 null，对应 CC 主 session 的 session_id）、`owner_heartbeat_at`（ISO8601 字符串，最近一次字段刷新时间）。这三个字段 MUST 在**每次**该 run 的生命周期子命令（`init`/`state init-run`/`state add-change`/`state set-progress`/`phase enter|exit|rotate`/`state set-parallel-fields`/`state finalize` 等）落盘 state 时被刷新为调用当时的值，而非仅在 `npc init` 时写入一次。

这三个字段与该次落盘的其余 state 内容 MUST 合入同一个 dict、共享同一次原子替换写入（落盘出口 MUST 采用"先写临时文件、再整体替换目标文件"的原子落盘语义，覆盖骨架与正式 STATE_JSON 两类落盘出口），不得拆成独立的写入调用；因此不存在"其余字段写入成功、唯独 owner 字段写入失败"的部分失败态——该次落盘调用整体失败 MUST 照落盘出口既有的错误处理方式向上抛出并中断当次子命令，MUST NOT 静默吞掉异常后留下一份缺 owner 字段的"新"落盘文件，也 MUST NOT 留下一份不完整（半写）的临时或目标文件。据此，"缺 owner 字段"这一状态 MUST 只出现在本 change 落地前生成的历史 plan-state 文件上；这类历史文件 MUST 被视为"无 owner 信息"，不因字段缺失而拒绝续跑判定。

#### Scenario: init 建 worktree 时骨架含 owner_pid 与心跳

- **WHEN** `npc init` 在建 worktree 前落盘 `initializing` 骨架
- **THEN** 骨架文件含 `owner_pid`（当前调用进程的父进程 pid）与 `owner_heartbeat_at`（当前时间）
- **AND** `owner_session_id` 允许为 `null`（session 探测发生在骨架写入之后）

#### Scenario: 每次生命周期子命令写 state 都刷新心跳

- **WHEN** 同一 run 内连续两次触发生命周期子命令（如两次 `phase enter`）
- **THEN** 第二次落盘后的 `owner_heartbeat_at` 晚于第一次
- **AND** `owner_pid` 更新为第二次调用时的父进程 pid（`os.getppid()`）

#### Scenario: 缺 owner 字段的历史 plan-state 向后兼容

- **WHEN** 读取一份本 change 落地前生成、不含 `owner_pid`/`owner_session_id`/`owner_heartbeat_at` 的 plan-state 文件
- **THEN** 该文件在存活判定中被视为"无 owner 信息"，不因字段缺失而报错或拒绝处理

#### Scenario: 落盘失败时不产生缺 owner 字段的半态新文件

- **WHEN** 某次生命周期子命令落盘 state 时底层原子替换写入调用（骨架落盘出口或 `write_state()` 落盘出口，二者均须为原子替换写）失败（如 `OSError`）
- **THEN** 该次落盘调用整体失败并向上抛出异常、中断当次子命令
- **AND** MUST NOT 静默吞掉该异常后留下一份包含其余字段但缺 owner 字段的"新"落盘文件

### Requirement: owner 存活判定——pid 探测只能确认存活，判死由心跳新鲜度决定

给定一份 plan-state（骨架或正式 STATE_JSON）的 owner 字段，判定其 owner 是否存活 MUST 遵循以下确定性算法。核心原则：**pid 探测只能作为存活的证据、不得作为死亡的证据**——`owner_pid` 记录的是触发子命令的父进程，在真实部署（CC 经 shell 包装调用 npc）中该父进程常是每条命令独立的短命包装 shell，命令结束后数秒内即退出；若把 pid 死亡当作 owner 死亡，活跃 run 在任意两次生命周期子命令之间都会被并发 session 误判为孤儿，原始并发踩踏缺陷将原样复现。
1. `owner_pid` 缺失时退化为仅心跳判定：`owner_heartbeat_at` 也缺失 → 判定为不存活；否则按第 3 步的心跳新鲜度判定。
2. `owner_pid` 存在时，MUST 用 `os.kill(pid, 0)` 探测：探测成功（进程存在）或因权限不足无法探测（`PermissionError`）→ 判定为"pid 存活"，继续第 3 步二次确认；进程不存在（`ProcessLookupError`）、非法 pid 值或其它探测异常 → pid 无法确认存活，MUST 退化为仅心跳判定（同第 1 步），MUST NOT 仅凭 pid 不存在就判定 owner 不存活。
3. "pid 存活"分支的二次确认：`owner_heartbeat_at` 缺失 → 信任 pid 判定，视为存活；心跳时间在 24 小时（`OWNER_HEARTBEAT_STALENESS_SECONDS`）以内 → 存活；心跳已超过 24 小时 → 判定为不存活（视为 pid 复用，原进程已退出）。

#### Scenario: pid 已死但心跳新鲜判定为存活（短命包装 shell 场景）

- **WHEN** plan-state 的 `owner_pid` 对应的进程已不存在（如短命包装 shell 已退出），但 `owner_heartbeat_at` 在 24 小时以内
- **THEN** owner 存活判定返回存活（活跃 run 不得因包装 shell 退出而被并发 session 接管）

#### Scenario: pid 已死且心跳过期或缺失判定为不存活

- **WHEN** plan-state 的 `owner_pid` 对应的进程已不存在，且 `owner_heartbeat_at` 超过 24 小时未刷新（或缺失）
- **THEN** owner 存活判定返回不存活（真崩溃：心跳停止刷新，过期即可被接管）

#### Scenario: pid 存活且心跳新鲜判定为存活

- **WHEN** plan-state 的 `owner_pid` 对应进程存在，且 `owner_heartbeat_at` 在 24 小时以内
- **THEN** owner 存活判定返回存活

#### Scenario: pid 存活但心跳过期判定为不存活（疑似 pid 复用）

- **WHEN** plan-state 的 `owner_pid` 对应进程存在，但 `owner_heartbeat_at` 超过 24 小时未刷新
- **THEN** owner 存活判定返回不存活

#### Scenario: 无任何 owner 信息判定为不存活（向后兼容）

- **WHEN** plan-state 不含 `owner_pid` 也不含 `owner_heartbeat_at`
- **THEN** owner 存活判定返回不存活（视为孤儿候选，不阻断历史文件被续跑接管）

### Requirement: `--no-worktree` 续跑探测同样受 owner 存活门槛约束

`npc init --no-worktree` 的续跑探测（扫描 canonical task_log 下的 in-progress state）与 `npc resume detect` MUST 在命中 in-progress state 后先做 owner 存活判定；owner 仍存活时 MUST NOT 将该 state 视为可续跑候选。

#### Scenario: --no-worktree 遇到 owner 存活的 in-progress state 不续跑

- **WHEN** 执行 `npc init --no-worktree`，canonical task_log 下存在一份 owner 仍存活的 in-progress plan-state
- **THEN** `needs_resume` 为 `false`
- **AND** 生成全新 `run_ts`，不复用该 state 的 run_ts

#### Scenario: --no-worktree 遇到 owner 已死的 in-progress state 正常续跑

- **WHEN** 执行 `npc init --no-worktree`，canonical task_log 下存在一份 owner 已死的 in-progress plan-state
- **THEN** `needs_resume` 为 `true`
- **AND** 复用该 state 的 run_ts（既有行为不变）

#### Scenario: npc resume detect 区分"无候选"与"owner 存活不建议接管"

- **WHEN** 执行 `npc resume detect`，找到的最新 in-progress state 的 owner 仍存活
- **THEN** 输出 `needs_resume=false`，且诊断消息区别于"没有找到 in-progress 旧 run"的默认消息
