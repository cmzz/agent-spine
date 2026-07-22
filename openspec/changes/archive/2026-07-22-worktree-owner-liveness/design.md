## Context

`src/npc/init_cmd.py::_scan_spine_worktrees_for_resume`（145-249 行）遍历 `spine/*` worktree，对每个存活目录只调用 `resume.find_latest_in_progress(wt_task_log_dir)` / `resume.find_latest_initializing(...)` 判定"有 plan-state 记录即视为悬空候选"，完全不检查该 plan-state 背后的进程是否还活着。`run()`（293-450+ 行）第 2 步在 `not no_worktree and not args.fresh` 时调用它，命中 in-progress 直接 `_io.emit({"needs_resume": True, ...}); return`，把整个悬空 worktree "抢"给当前 `npc init` 调用者。`--no-worktree` 路径（步骤 3，364-370 行）与 `npc clean`（`clean.py` 279-281 行 `has_in_progress` 门槛）存在同一语义漏洞。

仓库里已有的可复用先例：`src/npc/state.py::write_state()` 是几乎所有生命周期子命令（`state init-run`/`add-change`/`set-progress`/`phase enter|exit|rotate`/`set-parallel-fields`/`finalize`）共享的唯一落盘出口；`session.py::detect_via_hook` 已有"用文件 mtime 新鲜度代替显式心跳"的先例；`init_cmd.py::_mark_initializing_skeleton_orphan` 已有"读 plan-state.json → 改字段 → 原样写回、失败静默不阻塞"的保守写入惯例。

用户在盘问阶段已就四个关键问题拍板（见下方 Pattern Mapping），核心结论：(1) 主判定机制选纯 pid 探测（`os.kill(pid, 0)`）+ 心跳新鲜度兜底，不引入 `fcntl.flock` 长驻持锁；(2) `owner_pid` 不是 init 时一次性快照，而是每次生命周期子命令执行都刷新；(3) 心跳新鲜度阈值 24 小时；(4) `npc clean` 的同类缺陷一并修复，复用同一个 `owner_alive` 判定。

Review round 2 修订（实测证据驱动）：原裁决"pid 确认死亡时直接判孤儿、不受阈值影响"的前提在真实部署中不成立——`os.getppid()` 记录的常是每条命令独立的短命包装 shell（Bash 工具的 `zsh -c`），命令结束后数秒内即死。据此修订为 **pid 探测只能确认存活、不能确认死亡**：`ProcessLookupError` 一律退化为心跳判定，判死完全由心跳过期决定；同时新增 `npc init --takeover` 显式接管旗标（与 `--fresh` 互斥），覆盖"真崩溃但心跳尚未过期、用户要求立即恢复"的场景。

## Goals / Non-Goals

**Goals：**

- 新增 `src/npc/owner.py`，提供写入侧 `capture_owner_fields()` 与判定侧 `owner_alive(state: dict) -> bool` 两个纯函数，作为 owner 存活语义的单一事实源。
- `*-plan-state.json`（含 `initializing` 骨架与正式 STATE_JSON）新增 `owner_pid` / `owner_session_id` / `owner_heartbeat_at` 三个可选顶层字段，写入路径向后兼容（旧文件缺字段时判定行为退化为"无 owner 信息 → 视为孤儿候选，走原有行为"）。
- `_scan_spine_worktrees_for_resume` 对 in-progress 与 initializing 两类候选均先做 `owner_alive()` 判定，owner 存活的 worktree 一律跳过（不进候选池）。
- `init_cmd.py` 步骤 3（`--no-worktree`）与 `resume.py::detect()` 复用同一个 `owner_alive()` 判定。
- `clean.py` 的 `has_in_progress` 保护门槛改为"in-progress 且 owner 存活才保护"，owner 已死的 in-progress worktree 落入既有 age-gate（`plan_cleanup`）二次判定。
- 崩溃安全：不引入需要显式清理的锁文件；`owner_pid`/`owner_session_id`/`owner_heartbeat_at` 与 state 的其余字段共享同一次原子替换写（骨架落盘出口改为复用 `write_state()` 内既有的 `_atomic_write_text(...)`，不再直接调用 `_skeleton_path.write_text(...)`），不是独立的写入调用，因此不存在"其余字段写成功、唯独 owner 字段写失败"的部分失败态；该写调用本身若失败（`OSError` 等）会照既有行为向上抛出、中断当次生命周期子命令，与"owner 字段写入失败静默跳过"无关——这与 `_mark_initializing_skeleton_orphan`（读→改→写回、失败静默）是两个不同的写入路径：后者是本 change 之外、用于回填孤儿标记的次要读改写操作，不适用于骨架/`write_state()` 的主写入路径，此处不再援引它作为 owner 字段写入的失败语义先例。

**Non-Goals：**

- 不引入 `fcntl.flock` 长驻持锁（用户已否决）。
- 不改变 `--fresh` 的默认值、触发条件或语义。
- 不改变 `resume.py::compute_resume()` 的 phase 级断点推断算法。
- 不处理跨机 / 容器场景的 pid 命名空间隔离（假设所有 npc 进程运行在同一台主机）。
- 不对 `owner_session_id` 做存活判定用途，只落盘供人工诊断。

## Pattern Mapping

> 本段落原样带入 `pattern-interrogation.md` 的 `## Open Questions` 与 `## User Decisions (Interactive)`（该文件含 `## User Decisions (Interactive)` 标题，按契约取该分支）。

### Open Questions

- `owner_pid` 具体应该记录哪个进程？是 `npc init` 调用时的 `os.getppid()`（CC 主 session 的直接父 shell），还是需要 CC session 主动通过某个新的 npc 子命令持续"续约"心跳（因为 `os.getppid()` 在某些 CC 启动方式下也可能是短命的 wrapper shell，而非真正长驻到 run 结束的进程）？这会决定实现是"init 时一次性快照 pid"还是"每次子命令调用都刷新 owner_pid"。
- owner 存活判定的主机制二选一（或都要）：(a) 复用 `fcntl.flock` 长驻持锁（需要引入长驻持锁的调用点，可能要求每个 npc 子命令在运行期间持锁，退出时释放）；(b) 纯 pid 探测 + 心跳新鲜度兜底（无需长驻持锁，但心跳新鲜度阈值需要人工拍板，且有 pid 复用误判窗口）。两者工程复杂度和崩溃安全边界不同，需要用户确认优先选哪个作为主判据。
- 心跳新鲜度阈值具体定多少（分钟/小时级）？过短会在用户长时间未触发下一阶段时把活跃 run 误判为死亡进而被抢占；过长则在真正崩溃后仍长期占着悬空 worktree 不能被续跑接管。
- 是否要顺带修复 `clean.py`（279 行 `has_in_progress` 永久保护逻辑）里的同类"in-progress 状态未必意味着 owner 存活"问题，把僵尸 in-progress worktree 也纳入可回收范围？还是严格只改 `init.py`/`resume.py` 涉及的续跑抢占路径，`clean.py` 留待后续 change？

### User Decisions (Interactive)

1. **owner 存活的主判定机制**：选 (b) pid 探测 + 心跳新鲜度兜底。os.kill(pid, 0) 探测存活为主判据，心跳新鲜度兜底覆盖 pid 复用误判与 pid 不可探测场景；不引入 fcntl.flock 长驻持锁（npc 是短命 CLI 进程模型，长驻持锁工程改动大）。
2. **owner_pid 记录哪个进程**：每次 npc 生命周期子命令（init/implement/review/fix/record 等）执行时都刷新 owner_pid + 心跳时间戳，而非 init 一次性快照 getppid。pid 快照即使不完美，持续刷新的心跳保证活跃 run 不被误判。
3. **心跳新鲜度阈值**：24 小时。pid 已死时直接判孤儿、立即可续跑，不受此阈值影响；该阈值只作用于 pid 存活但可能是复用、或 pid 不可探测的兜底场景，用户选择宁可僵尸 worktree 多占一天也不误抢活跃 run。
4. **clean.py 同类问题**：一并修复。clean.py 的 in-progress 永久保护逻辑复用同一个 owner 存活判定：owner 已死的 in-progress worktree 允许回收。同一语义一次落地，避免两套判定漂移。

> **Review round 2 修订说明**：第 3 条中"pid 已死时直接判孤儿、立即可续跑"的前提被实测推翻（owner_pid 常是短命包装 shell，见 Context 末段），已修订为 pid 探测只能确认存活、判死完全由心跳过期决定；立即恢复通道改由 `npc init --takeover` 承担。上文保留原始裁决记录不改写。

## Decisions

**D1：新增 `src/npc/owner.py`，作为 owner 存活语义的单一事实源；写入侧与判定侧各一个纯函数。**

```python
OWNER_HEARTBEAT_STALENESS_SECONDS = 24 * 60 * 60  # Decision 3：24 小时


def capture_owner_fields(*, now_iso=None) -> dict:
    """写入侧：当前调用方（npc 子命令进程）的 owner 快照。

    owner_pid 取 os.getppid()（Decision 2：调用 npc 的父进程——即触发本次
    子命令的 CC 主 session / shell），每次调用返回最新值，不做缓存。
    """
    return {
        "owner_pid": os.getppid(),
        "owner_heartbeat_at": now_iso or _io.now_iso(),
    }


def owner_alive(state: dict, *, now_ts: float | None = None) -> bool:
    """判定侧：给定 plan-state dict（骨架或正式 STATE_JSON），判断其 owner 是否存活。

    算法（Decision 1/3）：
      1. owner_pid 缺失（仅发生在本 change 落地前生成的旧 schema 文件——owner
         字段与其余 state 字段共享同一次原子写，不存在"其余字段写成功、
         唯独 owner_pid 写失败"的部分失败态，该写调用整体失败会直接向上
         抛出并中断当次子命令，不会留下缺 owner_pid 的新 state 文件）→
         退化为仅心跳判定；心跳也缺失 → 视为无 owner 信息，判定为不存活
         （向后兼容：走原有"无信息即孤儿候选"行为，只覆盖旧 schema 文件）。
      2. owner_pid 存在 → os.kill(pid, 0) 探测（只能确认存活、不能确认死亡）：
         - PermissionError → 进程存在（仅权限不足发信号）→ 存活分支，继续走 3。
         - 无异常（kill 成功）→ pid 存在 → 存活分支，继续走 3。
         - ProcessLookupError / 其它 OSError（如 pid<=0 非法值）→ pid 无法确认
           存活，退化为仅心跳判定。实测（review round 2）：npc 经 Bash 工具的
           zsh -c 调用时，os.getppid() 记录的包装 shell 在命令结束后数秒内即死，
           若 pid 死亡即判死，活跃 run 在任意两次子命令之间都会被并发 init
           抢走——原始缺陷原样复现。
      3. pid 判定为"存在"后，用心跳新鲜度做二次确认（防 pid 复用）：
         - owner_heartbeat_at 缺失 → 信任 pid 存活判定（避免心跳字段尚未写入时的误杀）。
         - owner_heartbeat_at 在 OWNER_HEARTBEAT_STALENESS_SECONDS（24h）内 → 存活。
         - 否则（心跳明显过期，暗示原进程早已退出、pid 被无关进程复用）→ 不存活。
    """
```

备选是把"pid 存在但心跳过期"也判定为存活（完全信任 pid 探测，心跳只做诊断展示）；放弃，因为这与 Decision 3 的显式裁决矛盾——用户要求心跳新鲜度作为 pid 复用误判的二次确认信号，不是纯展示字段。

**D2：owner 字段写入接入两个既有落盘出口，不新增独立写入调用点。**

- `init_cmd.py` 的 `initializing` 骨架字典（`_skeleton`，run() 步骤 4，385-394 行）新增 `owner_pid`/`owner_heartbeat_at`（用 `owner.capture_owner_fields()`），`owner_session_id` 先置 `None`（此时 session 探测尚未执行，步骤 9 才发生）。骨架落盘机制同步升级（round-4 评审 F1 修复）：原 `_skeleton_path.write_text(...)`（394-398 行，无原子替换语义）改为调用 `state.py::_atomic_write_text(_skeleton_path, json.dumps(_skeleton, ensure_ascii=False, indent=2) + "\n")`（`init_cmd.py` 需从 `state.py` 导入该函数，或将其提升为跨模块共享的落盘工具函数）——tmp 文件写入完成后 `os.replace` 整体替换目标路径，与 `write_state()` 的正式 STATE_JSON 落盘共享同一原子写语义。写入时机与既有骨架落盘时机完全一致、不改变：骨架落盘在 `_git_ops.add_worktree(...)`（400-407 行）**之前**执行——即骨架先于 worktree 本身落盘。这一时序覆盖了从"骨架写入"到"init-run 完成"之间的整个窗口，其中就包含用户报告的最危险窗口："worktree 已建但 init-run 未执行"的崩溃间隙（该窗口被完整包含在"骨架已存在"的区间内，因为骨架写入早于 worktree 创建）。
- 时序统一口径（proposal / spec / tasks 均以此为准）：骨架落盘 → `git worktree add` → provision → …… → `state init-run`。任何提及"建 worktree 后落盘骨架"的表述均为笔误，应订正为"建 worktree 前落盘骨架"。
- `src/npc/state.py::write_state()`（107-117 行）在 `state["last_updated_at"] = _io.now_iso()` 之后统一追加 `state.update(_owner.capture_owner_fields())` 与 `state["owner_session_id"] = (state.get("cc_session") or {}).get("session_id")`——`write_state()` 是 `init_run`/`update_state`（进而 `add_change`/`set_progress`/`phase_enter`/`phase_exit`/`phase_rotate`/`set_parallel_fields`）/`finalize` 的唯一落盘出口，这一处修改即覆盖"每次生命周期子命令执行都刷新 owner_pid + 心跳"（Decision 2），无需逐一修改每个 CLI handler。
- 不新增独立的"owner 续约"子命令：`write_state()` 的调用频率（几乎每个 phase 转换都会触发）已经满足 Decision 3 的"24 小时新鲜度"粒度，不需要更高频的显式心跳机制。

备选是新增一个 `npc state touch-owner` 之类的独立心跳子命令，要求 CC 主 session 定期主动调用；放弃，因为该方案需要修改 spine-run 编排层去插入额外调用点，而 `write_state()` 已经是天然高频的既有落盘路径，复用它零新增调用面。

**D3：`_scan_spine_worktrees_for_resume` 对两类候选（in-progress / initializing）均在"进入候选池之前"插入 owner 存活判定。**

现有逻辑（`init_cmd.py` 198-215 行）：

```python
state_file = resume.find_latest_in_progress(wt_task_log_dir)
if state_file is not None:
    ...
    in_progress_candidates.append((mtime, wt_path))
    continue

init_file = resume.find_latest_initializing(wt_task_log_dir)
if init_file is not None:
    ...
    initializing_candidates.append((mtime, wt_path))
```

修改为：在 `in_progress_candidates.append(...)` 与 `initializing_candidates.append(...)` 之前，各自读取对应 state/骨架 JSON（读取失败——`OSError`/`json.JSONDecodeError`——按"无法判定，保守视为不存活"处理，允许进入候选池，与既有"缺信息即孤儿候选"的宽松向后兼容语义一致），调用 `_owner.owner_alive(data)`；若为 `True`（owner 存活）则 `continue`（不进候选池，视为他人活跃 run，扫描器继续检查下一个 worktree；若两类候选均不满足，`_scan_spine_worktrees_for_resume` 最终返回 `(False, None, False)`，`run()` 步骤 4 会为当前调用者新建独立 worktree）；若为 `False` 才追加进候选池。

`_mark_initializing_skeleton_orphan`（worktree 缺失/残破分支，180-190 行）与「反向扫描」孤儿标记（217-238 行）不受影响——这两处处理的是"worktree 物理缺失"场景，与 owner 是否存活无关（worktree 都不在了，owner 是否存活已不重要）。

**D4：`--no-worktree` 路径（`init_cmd.py` 步骤 3，364-370 行）与 `resume.py::detect()`（286-333 行）复用同一个 `owner_alive()` 判定。**

`init_cmd.py` 步骤 3 修改为：

```python
if not args.fresh and no_worktree:
    if task_log_dir_for_resume.is_dir():
        candidate = resume.find_latest_in_progress(task_log_dir_for_resume)
        if candidate is not None:
            try:
                candidate_state = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                candidate_state = {}
            if not _owner.owner_alive(candidate_state):
                resume_state_json = candidate
                needs_resume = True
            # owner 存活 → resume_state_json 保持 None，needs_resume 保持 False，
            # 步骤 5 走"新生成 run_ts"分支，等价于"未发现候选"
```

`--no-worktree` 模式无法像 worktree 模式那样"新建独立 worktree 隔离"（`repo_root` 固定为 canonical checkout），owner 存活时的正确行为是"当作未发现可续跑候选"，落到步骤 5 的 `else` 分支生成全新 `run_ts`，与"确实没有 in-progress 记录"完全同构，不需要新增分支。

`resume.py::detect()`（`npc resume detect` CLI，供人工/工具诊断用）同样在 `find_latest_in_progress` 命中后先做 `owner_alive()` 判定；owner 存活时返回 `{"needs_resume": False, "state_json": None, "message": "找到 in-progress 记录，但 owner 仍存活（他人 run），不建议接管"}`，区别于"没有找到 in-progress 旧 run"的原始消息，便于人工诊断分辨两种"needs_resume=False"的成因。

**D5：`clean.py` 的 `has_in_progress` 门槛（279-281 行）改为"in-progress 且 owner 存活才保护"；owner 已死时不再 `continue`，落入既有 age-gate 二次判定。**

```python
state_file = _resume.find_latest_in_progress(wt_task_log_dir)
if state_file is not None:
    try:
        candidate_state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        candidate_state = {}
    if _owner.owner_alive(candidate_state):
        in_progress_wts.append(entry)
        continue
    # owner 已死：不再无条件保护，落入下方 orphan 骨架 / initializing 骨架 /
    # 第二道门（task_log run 的 age-gate plan_cleanup）判定链路，
    # 与"无 in-progress 记录"的 worktree 走同一套保守回收判定。
```

选择"落入既有 age-gate 二次判定"而非"owner 已死立即列为孤儿直接回收"：与 Decision 4 "允许回收"的字面要求一致，但保留 `clean.py` 既有的"必须同时满足 keep_days 保留窗口"这一保守护栏——避免一个进程刚崩溃几分钟、`npc clean` 恰好在此时运行，就把仍在 keep_days 保留期内的 run 立即物理删除（`git worktree remove` 是破坏性操作，无法撤销，比"跳过续跑候选"更需要保守）。这与 `clean.py` 模块 docstring 声明的"可清理判定（保守，三条件全满足才删）"一致，不为 owner 已死单独开一条绕过 age-gate 的快速通道。

备选是 owner 已死立即等价于 orphan（跳过 age-gate，直接进 `orphans` 列表）；放弃，因为这会让"进程崩溃"与"用户主动清理陈旧 run"两种场景共享同一个立即删除路径，而前者可能是用户希望稍后手动 `npc init` 续跑的场景（`_scan_spine_worktrees_for_resume` 此时会把它识别为可续跑候选并接管）——若 `clean` 先一步把 worktree 物理删除，会与"owner 已死即可续跑"的核心目标（D3）冲突：worktree 都被删了就无法续跑。落入 age-gate 二次判定，使"最近才崩溃的 run"继续可被后续 `npc init` 发现并续跑，只有真正陈旧（超过 keep_days）且 owner 已死的僵尸才会被 `clean` 回收。

## Risks / Trade-offs

- **[`owner_pid = os.getppid()` 未必是"长驻到 run 结束"的稳定进程]** pattern-interrogation Open Questions 已指出该风险：CC 某些启动方式下父进程可能是短命 wrapper shell。Decision 2 的取舍是接受这一不完美，靠"每次生命周期子命令都刷新 pid + 心跳"稀释单次快照不准的影响——只要 owner 在 24 小时内至少触发过一次子命令调用，心跳就会保持新鲜，即使某一次快照的 pid 恰好在下一刻退出也不影响后续判定（下一次子命令调用会写入新的、当时仍存活的 pid）。真正的风险窗口收窄为"心跳新鲜但夹在两次子命令调用之间 pid 恰好死亡且被无关进程复用"，概率低且已被 24 小时阈值兜底。
- **[心跳阈值 24 小时可能让真崩溃的悬空 worktree 多占一天]** 用户已在 Decision 3 显式接受这一取舍（"宁可僵尸 worktree 多占一天也不误抢活跃 run"）。Review round 2 后判死完全由心跳过期决定（pid 死亡不再是快速判死信号），该窗口成为常态；缓解：需要立即恢复时用 `npc init --takeover` 显式接管，不必等心跳过期。
- **[`os.kill(pid, 0)` 假设同机部署]** Non-Goals 已声明不处理跨机/容器场景；若未来引入远程 worktree 执行，本设计需要重新评估。
- **[`clean.py` 的 age-gate 二次判定意味着 owner 已死的 in-progress worktree 不会立即被清理]** 这是 D5 的有意设计（避免与 D3 的续跑接管路径冲突），不是遗漏——真正陈旧的僵尸最终仍会被回收，只是不会比一个"正常完成后陈旧"的 run 更快被清理。

## Migration Plan

1. `owner_pid`/`owner_session_id`/`owner_heartbeat_at` 是新增顶层字段，`plan-state.json` 的 `schema_version` 仍为 2（字段新增、向后兼容，不 bump 版本）。
2. 历史（本 change 落地前生成、不含三字段的）plan-state 文件：`owner_alive()` 对 `owner_pid` 与 `owner_heartbeat_at` 均缺失的输入返回 `False`（无 owner 信息 → 视为不存活/孤儿候选），与该文件在旧代码下"直接进候选池"的行为等价——不会因为字段缺失而拒绝历史悬空 worktree 被续跑接管，只是不再无条件信任，而是走同一套"无信息即孤儿"判定，行为上向后兼容。
3. 首次调用任一写入路径（`init` 建 worktree 骨架，或该 worktree 下任意生命周期子命令触发 `write_state()`）后，字段自动补齐，后续判定即拥有完整 owner 信息。
4. 回滚：移除 D1-D5 增量代码即可；`plan-state.json` 里已写入的三个新字段对旧代码（不认识这三个字段的历史版本）无影响（JSON 额外字段不影响旧代码的字段读取逻辑）。

## Open Questions

无。四条关键裁决已在 Pattern Mapping 段落记录并在 Decisions D1-D5 中兑现。
