## Why

`src/npc/init_cmd.py::_scan_spine_worktrees_for_resume` 把「某 `spine/*` worktree 的 task_log 里存在 `status=in-progress` 的 plan-state」直接等同于「该 worktree 悬空、可安全续跑接管」。这一等价关系在单 session 场景下成立，但在**同一仓库下并发运行多个 `npc init`**（多个 CC 主 session 各自跑一个 spine run）时会踩踏：`in-progress` 只反映"某次 run 尚未跑完"，不反映"跑它的进程是否还活着"。今天已两次实际发生：一个主 session 的 `npc init` 把另一个仍在正常推进的主 session 的 worktree 当悬空 run 抢走（`needs_resume=true` 指向别人的 `worktree_root`），用户被迫用 `--fresh` 规避——但 `--fresh` 无条件跳过悬空扫描，若设为默认会同时废掉"进程真崩溃后自动续跑"这条恢复通道，不可接受。

根因是悬空扫描判据里缺一层**owner 存活判定**：`in-progress` 状态本身不携带任何"谁在跑、还活不活着"的信息。`--no-worktree` 路径（`find_latest_in_progress` 直接决定 `needs_resume`）与 `npc clean` 的"有 in-progress 就永久保护"逻辑存在同一语义漏洞（前者同样会误抢，后者会让 owner 已死的 in-progress worktree 永久占用、变成真僵尸，永远等不到清理）。

## What Changes

- **owner 存活信息落盘**：`*-plan-state.json`（plan-state / STATE_JSON）新增三个顶层字段 `owner_pid` / `owner_session_id` / `owner_heartbeat_at`。写入时机覆盖两处：(1) `npc init` 在建 worktree 前落盘的 `initializing` 骨架（`init_cmd.py` 的 `_skeleton` 字典）；(2) `src/npc/state.py::write_state()`——这是 `state init-run` / `add-change` / `set-progress` / `phase enter|exit|rotate` / `set-parallel-fields` / `finalize` 等**几乎所有生命周期子命令**共享的唯一落盘出口，在此处统一刷新三个字段，覆盖"每次 npc 生命周期子命令执行都刷新 owner_pid + 心跳"的要求，无需逐一改造每个 CLI handler。
- **新增 owner 存活判定模块** `src/npc/owner.py`：`capture_owner_fields()`（写入侧，供 `state.py`/`init_cmd.py` 复用同一份"`os.getppid()` 父进程 pid + 心跳时间戳"快照逻辑；`owner_pid` 记录的是触发本次子命令调用的父进程——CC 主 session / shell，而非 npc 子进程自身）与 `owner_alive(state: dict) -> bool`（判定侧，`os.kill(pid, 0)` 探测为主判据 + 24 小时心跳新鲜度为兜底，详见 design.md）。
- **悬空扫描接入 owner 存活判定**：`_scan_spine_worktrees_for_resume` 对 in-progress 与 initializing 两类候选均先做 `owner_alive()` 判定——owner 仍存活的 worktree 一律跳过（不进候选池，`npc init` 直接新建自己的 worktree）；只有 owner 已死的候选才计入可续跑池。
- **`--no-worktree` 路径同样接入**：`init_cmd.py` 步骤 3（`no_worktree` 分支）与 `resume.py::detect()` 复用同一个 `owner_alive()` 判定，owner 存活的 in-progress state 不再被当作续跑候选。
- **`npc clean` 同步治理同类缺陷**（用户在 pattern-interrogation 阶段裁决一并修复）：`clean.py` 的"有 in-progress 就永久保护、不清理"判定改为"owner 存活才保护"；owner 已死的 in-progress worktree 落入既有的 age-gate（`plan_cleanup`/`keep_days`）二次判定，而不是无条件跳过，避免误删仍在保留窗口内的近期崩溃 run。
- **`--fresh` 语义不变**：继续代表"无条件跳过悬空扫描、直接新建"，本 change 不改其触发时机，只改扫描内部候选判定逻辑。
- **骨架写入机制升级为原子替换写**：`init_cmd.py` 的 `initializing` 骨架落盘目前用 `_skeleton_path.write_text(...)`（无 tmp + `os.replace` 语义），与本 change 要求的"骨架与 owner 字段共享同一次原子写、失败不留半态"的可观察语义冲突（round-4 评审 F1）。本 change 把骨架写入改为复用 `state.py::_atomic_write_text(...)`（tmp 文件写入完成后 `os.replace` 整体替换目标文件）同一落盘机制，不再直接调用 `Path.write_text(...)`。
- **崩溃安全 / 幂等**：`owner_pid`/`owner_session_id`/`owner_heartbeat_at` 不走独立写入调用，而是与 state 其余字段合并进同一份 dict、共享同一次原子替换写（骨架落盘出口与 `write_state()` 落盘出口均采用 tmp + `os.replace` 语义）；因此不存在"其余字段写成功、唯独 owner 字段写失败"的部分失败态——该次写调用整体失败会照 `write_state()`/骨架写入既有行为向上抛出、中断当次生命周期子命令，不会静默产生一份缺 owner 字段的"新" state 文件，也不会留下半写的临时/目标文件（`_mark_initializing_skeleton_orphan` 的"读→改→写回、失败静默"惯例是另一条独立于本 change 的次要读改写路径，用于回填孤儿标记，不适用于骨架/`write_state()` 的主写入路径，不作为 owner 字段写入失败语义的先例）。不引入新锁机制，`owner_pid` 存活探测本身天然对"stale 记录"免疫——owner 进程崩溃后 pid 立即变为不可探测，不存在需要显式清理的锁文件。
- 补齐并发场景测试：owner 存活/已死两种候选的悬空扫描行为、`--no-worktree` 路径行为、`npc clean` 的 owner 存活门槛行为、`write_state`/`init` 骨架字段写入的幂等性。

## Capabilities

### New Capabilities

- `worktree-owner-liveness`：owner 存活信息的落盘（写入侧字段与刷新时机）、判定算法（`owner_alive`）、以及该判定在 `--no-worktree` 续跑探测路径上的接入。

### Modified Capabilities

- `init-worktree`：「续跑探测扫描悬空 spine worktree」Requirement 修订——命中 in-progress 候选前 MUST 先做 owner 存活判定，owner 存活则不视为悬空、继续正常新建。
- `clean-worktree`：「npc clean 清理孤儿 spine worktree」Requirement 修订——"in-progress 即保留"改为"in-progress 且 owner 存活才保留"；owner 已死的 in-progress worktree 落入既有 age-gate 判定链路，而非无条件保留。

## Impact

- **owner 存活核心逻辑**：新增 `src/npc/owner.py`（`capture_owner_fields`/`owner_alive`/`OWNER_HEARTBEAT_STALENESS_SECONDS`）。
- **写入侧**：`src/npc/state.py::write_state()`（统一刷新 owner 三字段）、`src/npc/init_cmd.py`（`initializing` 骨架字典新增字段，且骨架落盘由 `write_text(...)` 改为复用 `state.py::_atomic_write_text(...)` 的原子替换写机制）。
- **判定侧接入**：`src/npc/init_cmd.py::_scan_spine_worktrees_for_resume`（in-progress + initializing 两类候选门槛）、`src/npc/init_cmd.py::run()` 步骤 3（`--no-worktree` 续跑探测）、`src/npc/resume.py::detect()`（`npc resume detect` CLI 复用同一判定）、`src/npc/clean.py::scan_worktrees_for_cleanup`（`has_in_progress` 门槛改写）。
- **测试**：`tests/test_owner.py`（新建，覆盖 `owner_alive`/`capture_owner_fields`）、`tests/test_init_cmd.py`、`tests/test_resume.py`、`tests/test_clean.py`、`tests/test_state.py`（`write_state` 字段刷新回归）。
- **spec 归档**：新增 `worktree-owner-liveness` capability；修订 `openspec/specs/init-worktree/spec.md`、`openspec/specs/clean-worktree/spec.md` 各一条既有 Requirement。
- **不涉及**：`--fresh` 的触发条件本身、`resume.py::compute_resume`（断点推断逻辑不变）、`git_ops.py`（worktree 创建/删除机制不变）、`session.py`（session_id 探测逻辑不变，仅复用其已探测结果写入 `owner_session_id`）。

## Non-Goals

- 不引入 `fcntl.flock` 长驻持锁机制（pattern-interrogation 阶段用户已明确否决，npc 是短命 CLI 进程模型，长驻持锁工程改动大）。
- 不改变 `--fresh` 的默认值或触发条件；`--fresh` 依旧是用户手动逃生口，不做成默认行为。
- 不改变 `resume.py::compute_resume()` 的断点推断算法（phase 级续跑定位逻辑不受影响，本 change 只影响"是否进入续跑候选池"这一前置门槛）。
- 不处理跨机 / 容器场景的 pid 命名空间隔离问题（`os.kill` 探测假设所有 npc 进程运行在同一台主机，仓库当前无迹象支持跨机部署）。
- 不对 `owner_session_id` 做除记录外的额外校验或用途扩展（不用它做存活判定，仅作诊断信息落盘）。
