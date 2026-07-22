## Analogs

- `src/npc/init_cmd.py::_scan_spine_worktrees_for_resume`（145-249 行）—— 本次改动的**直接宿主函数**。当前逻辑：遍历 `git worktree list --porcelain` 里 `refs/heads/spine/*` 分支的 worktree，对每个存活目录只调 `resume.find_latest_in_progress(wt_task_log_dir)` / `resume.find_latest_initializing(...)` 判定"有 plan-state 记录即视为悬空候选"，**完全不检查该 plan-state 背后的进程是否还活着**——这正是用户报告的踩踏缺陷根因。`run()`（293-450+ 行）第 2 步在 `not no_worktree and not args.fresh` 时调用它，命中 in-progress 直接 `_io.emit({"needs_resume": True, ...}); return`（322-327 行），把整个悬空 worktree "抢"给当前 `npc init` 调用者——这一步是本次要插入 owner 存活判定的确切位置。

- `src/npc/resume.py::find_latest_in_progress` / `find_latest_initializing` / `find_latest_orphan_skeleton`（28-97 行）—— 三个函数结构完全同构：`glob("*-plan-state.json")` → 逐个 `json.loads` → 按 `status` 字段过滤 → 按 `mtime` 排序取最新。这是仓库里"扫 plan-state.json 按 status 分类"的既定范式，本次给 in-progress 候选加 owner 存活判定，应该沿用同一形态（新增一个 `owner_alive(state_dict_or_path) -> bool` 之类的独立纯函数，而不是散落 if 判断），供 `_scan_spine_worktrees_for_resume` 和 `resume.detect()` / `init_cmd.run()` 步骤 3（`--no-worktree` 路径，364-370 行）共同调用。

- `src/npc/state.py::acquire_state_lock` / `release_state_lock`（29-74 行）—— 仓库里**已有的、且天然崩溃安全的锁机制**：`fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)` 写在 `state.lock`（与 `state_json` 同目录）。flock 的关键性质——持锁进程崩溃/被杀时，OS 会在进程表清理时自动释放该锁，**不需要任何显式清理代码，天生免疫 stale lock 阻塞恢复**的问题。这与用户目标里"锁的写入/清理要幂等且崩溃安全（stale 锁不能阻塞恢复）"的要求高度契合，是比"手写 pid 文件 + 心跳时间戳比对"更简单也更不容易出 bug 的候选方案（细节见 Assumptions/Open Questions）。当前该锁只在 state 读写路径（`update_state` 等）用于**互斥**，尚未被用作"进程是否存活"的探测信号；本次若复用，是把它从"互斥锁"语义扩展为"存活探测"语义的新用法，需要新写测试覆盖。

- `src/npc/clean.py`（250-300 行区域）—— `_scan`（或同名函数）里已有一套"plan-state 状态 → 是否可回收"的分类逻辑：`has_in_progress`（279 行，复用 `resume.find_latest_in_progress`）→ 无条件跳过（保护，不清理）；`orphan` 状态骨架 → 直接列为可回收；`initializing` 骨架 → 结合 `_paths.read_active()` 判断是否仍是 active run。这是本次改动的**姊妹消费点**：clean 目前把"有 in-progress plan-state"等同于"永远受保护，不清理"，与 init 的悬空扫描共享同一个"in-progress ≠ owner 存活"的语义漏洞，但用户目标里未明确要求改 clean（只提到 init/resume 与 `--no-worktree` 路径），需要在 Open Questions 里向用户确认是否顺带修（同类缺陷模式，与 fix 阶段"同类问题一并检查"的要求呼应）。

- `src/npc/session.py::detect_via_hook`（48-77 行）—— 仓库里**已有的"用 mtime 新鲜度代替真正心跳"的先例**：不要求被检测对象主动写心跳字段，而是直接读 CC transcript `.jsonl` 文件的 `st_mtime`，`time.time() - mtime > max_age_seconds`（默认 6h）则判定该 session 记录过期不可信。这与用户目标里"必要时辅以心跳新鲜度"的表述是同一模式的既有实现，可作为"心跳"到底要不要额外写字段、还是复用已有文件 mtime 的参照——`state.lock` 或 `*-plan-state.json` 本身的 mtime 天然会在每次 `update_state()` 写入时刷新，等价于免费心跳。

- `src/npc/paths.py::make_run_ts`（约 186-195 行）—— `os.getpid()` 在仓库里已有先例用于生成不碰撞标识符（run_ts 后缀），是"pid 作为进程身份标识"惯例的既有用法，但**该 pid 是当前 `npc` CLI 子进程的 pid，不是长期存活的宿主进程**（见 Assumptions 第一条对 owner 到底该记谁的 pid 的讨论）。

- `src/npc/init_cmd.py::_mark_initializing_skeleton_orphan`（131-142 行）—— "读 plan-state.json → 改一个字段（`status`）→ 原样写回，失败静默吞掉不阻塞主流程"的既有写字段范式，本次给 plan-state.json 新增 `owner_pid` / `owner_session_id` / `owner_heartbeat_at` 字段时，写入路径应遵循同一"失败不阻塞主流程"的保守惯例。

## Assumptions

- **owner_pid 该记哪个进程的 pid，是本次设计的第一个关键假设**：`npc init` / `npc implement record` / `npc review record` 等都是**每阶段一次性调用的短命子进程**（不是长驻 daemon），若把 `owner_pid` 记成这些一次性调用自身的 pid，check 时该 pid 几乎必然已经退出（哪怕 run 仍在正常进行），会把所有真正活跃的 run 都误判为"owner 已死"。因此假设 `owner_pid` 应该记录**当前 CC 主 session 的宿主进程 pid**（比如 `os.getppid()`，或 shell/CC 进程链上比 `npc` 自身更长命的祖先），并在**每次**该 worktree 下有 npc 子命令被调用时（不止 init）刷新/校验该 pid 是否仍等于当前存活的宿主进程——否则 pid 复用（PID reuse）会导致误判"存活"。
- **flock 可以替代或增强手写 pid+心跳**：假设 owner 存活判定的主实现优先用 `state.py` 现成的 `fcntl.flock`（LOCK_EX | LOCK_NB）机制——sql: 若能对该 worktree 的 `state.lock`（或新引入的 `owner.lock`）拿到独占锁，说明当前没有其他存活进程持有它，即"owner 已死或从未存在"，可以安全接管；若拿不到（`OSError`），说明有别的进程正持有，视为 owner 存活，直接跳过。这一假设的前提是：**owner 进程在整个 run 期间会持续持有该 flock**（不是像 `state.py` 现在那样"拿锁 → 改 state → 立刻释放"的短暂互斥用法），意味着需要新增一个"长驻持锁"的调用点（例如在 spine 主 session 生命周期内、或每次子命令调用时短暂重新验证），这与现有 `state.lock` 的短暂互斥语义不同，可能需要一个独立的 `owner.lock` 文件而非复用 `state.lock` 本身（避免和 state 读写互斥语义混淆）。
- **pid 存活探测用 `os.kill(pid, 0)`**：假设跨进程存活探测走标准 `os.kill(pid, 0)`——`ProcessLookupError` → 已死；`PermissionError` → 进程仍存在（只是权限不足发信号，同机多用户场景），仍判定存活；成功（无异常）→ 存活。假设所有 npc 相关进程都在**同一台主机**运行（`~/task_log` 与 `~/.spine/worktrees` 均为本地路径，无远程/容器隔离场景），pid 命名空间共享，`os.kill` 探测有效——若未来出现跨机/容器场景该假设会失效，但当前仓库无任何迹象支持跨机部署。
- **心跳新鲜度作为 pid 探测失败/不可靠时的兜底，而非独立主判据**：假设心跳字段（`owner_heartbeat_at`，ISO8601）在每次该 worktree 下 npc 子命令被调用时随 `state.py::write_state` 或类似写入路径一并刷新（复用其"原子写"惯例），新鲜度阈值参考 `session.py::detect_via_hook` 的 `max_age_seconds=6*3600` 量级（具体值待定，见 Open Questions）。心跳新鲜度只在 `os.kill` 判定为"存活"但怀疑 pid 复用（比如 pid 存活但心跳明显过期，暗示原进程早已退出、pid 被无关进程复用）时作为二次确认信号，不单独作为"判死"依据（心跳可能因为 run 本身长时间无子命令调用而合理地"不新鲜"，例如用户中途去做别的事）。
- **plan-state.json schema 新增字段是可选、向后兼容的**：假设新增 `owner_pid` / `owner_session_id` / `owner_heartbeat_at` 三个顶层字段写在 `*-plan-state.json`（schema_version 仍为 2，字段新增不破坏兼容），旧版本、缺这些字段的 state 文件在读取时按"无 owner 信息 → 视为孤儿候选，走原有行为"处理（保守，不因为字段缺失而拒绝续跑），不强制 bump `SCHEMA_VERSION`。
- **`--no-worktree` 路径复用同一存活判定函数**：假设 `init_cmd.py` 第 361-370 行（`--no-worktree` 分支）与 `resume.py::detect()`（286-333 行，`find_latest_in_progress` 调用点）都改为调用同一个新增的 `owner_alive(...)` 判定函数，而不是各自维护一份判定逻辑——沿用仓库里"扫描逻辑集中在 `resume.py`，`init_cmd.py`/`clean.py` 只做消费"的既有分层。
- **`--fresh` 语义不变**：假设 `--fresh` 继续代表"无条件不查悬空 worktree、直接新建"（`init_cmd.py` 315 行 `not args.fresh` 已经短路了整个悬空扫描），本次改动不改这一条件分支的触发时机，只改分支内部"候选是否可续跑"的判定逻辑。
- **`clean.py` 的 in-progress 保护逻辑本次不动**：假设本次改动范围严格限定在"续跑扫描误抢占"，不顺带修 `clean.py` 279 行"有 in-progress 就永久保护、不清理"的潜在同类缺陷（owner 已死但 in-progress 状态的 worktree 目前会被 clean 永久跳过、成为真正的僵尸），除非用户在 Open Questions 里明确要求扩大范围。

## Open Questions

- `owner_pid` 具体应该记录哪个进程？是 `npc init` 调用时的 `os.getppid()`（CC 主 session 的直接父 shell），还是需要 CC session 主动通过某个新的 npc 子命令持续"续约"心跳（因为 `os.getppid()` 在某些 CC 启动方式下也可能是短命的 wrapper shell，而非真正长驻到 run 结束的进程）？这会决定实现是"init 时一次性快照 pid"还是"每次子命令调用都刷新 owner_pid"。
- owner 存活判定的主机制二选一（或都要）：(a) 复用 `fcntl.flock` 长驻持锁（需要引入长驻持锁的调用点，可能要求每个 npc 子命令在运行期间持锁，退出时释放）；(b) 纯 pid 探测 + 心跳新鲜度兜底（无需长驻持锁，但心跳新鲜度阈值需要人工拍板，且有 pid 复用误判窗口）。两者工程复杂度和崩溃安全边界不同，需要用户确认优先选哪个作为主判据。
- 心跳新鲜度阈值具体定多少（分钟/小时级）？过短会在用户长时间未触发下一阶段时把活跃 run 误判为死亡进而被抢占；过长则在真正崩溃后仍长期占着悬空 worktree 不能被续跑接管。
- 是否要顺带修复 `clean.py`（279 行 `has_in_progress` 永久保护逻辑）里的同类"in-progress 状态未必意味着 owner 存活"问题，把僵尸 in-progress worktree 也纳入可回收范围？还是严格只改 `init.py`/`resume.py` 涉及的续跑抢占路径，`clean.py` 留待后续 change？


## User Decisions (Interactive)

1. **owner 存活的主判定机制**：选 (b) pid 探测 + 心跳新鲜度兜底。os.kill(pid, 0) 探测存活为主判据，心跳新鲜度兜底覆盖 pid 复用误判与 pid 不可探测场景；不引入 fcntl.flock 长驻持锁（npc 是短命 CLI 进程模型，长驻持锁工程改动大）。
2. **owner_pid 记录哪个进程**：每次 npc 生命周期子命令（init/implement/review/fix/record 等）执行时都刷新 owner_pid + 心跳时间戳，而非 init 一次性快照 getppid。pid 快照即使不完美，持续刷新的心跳保证活跃 run 不被误判。
3. **心跳新鲜度阈值**：24 小时。pid 已死时直接判孤儿、立即可续跑，不受此阈值影响；该阈值只作用于 pid 存活但可能是复用、或 pid 不可探测的兜底场景，用户选择宁可僵尸 worktree 多占一天也不误抢活跃 run。
4. **clean.py 同类问题**：一并修复。clean.py 的 in-progress 永久保护逻辑复用同一个 owner 存活判定：owner 已死的 in-progress worktree 允许回收。同一语义一次落地，避免两套判定漂移。
