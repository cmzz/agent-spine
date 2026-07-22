## 0. 落点清单（确定性枚举）

以下命令在仓库根（`/Users/ethan/.spine/worktrees/-Users-ethan-Workspace-agent-spine/2026-07-21-2300-54c37b0`）执行，枚举本 change 需要改动/新增测试覆盖的全部调用点：

```
$ rg -n "find_latest_in_progress\(" --type py
```
匹配 7 处：`src/npc/resume.py:28`（定义）、`src/npc/resume.py:312`（`detect()` 内调用）、`src/npc/init_cmd.py:199`（`_scan_spine_worktrees_for_resume` 内 in-progress 候选）、`src/npc/init_cmd.py:369`（`--no-worktree` 续跑探测）、`src/npc/clean.py:279`（`has_in_progress` 门槛）、`tests/test_resume.py`（2 处，既有用例）。
本 change 需要改动的调用点：`init_cmd.py:199`（D3，加 owner_alive 门槛）、`init_cmd.py:369`（D4，加 owner_alive 门槛）、`resume.py:312`（D4，`detect()` 加 owner_alive 门槛）、`clean.py:279`（D5，has_in_progress 语义改写）；`resume.py:28` 定义本身不变（只改调用方）；`tests/test_resume.py` 既有 2 处用例 MUST 保持通过（不依赖 owner 字段），并新增 owner 相关用例。

```
$ rg -n "find_latest_initializing\(" --type py
```
匹配 12 处：`src/npc/resume.py:49`（定义）、`src/npc/init_cmd.py`（4 处：187/209/225/337，孤儿标记与 initializing 候选/恢复读取）、`src/npc/clean.py:296`（initializing 孤儿检测）、`tests/test_init_crash_recovery.py`（6 处既有用例）。
本 change 只改 `init_cmd.py:209`（D3，initializing 候选加 owner_alive 门槛）；`init_cmd.py:187/225/337`、`clean.py:296` 处理的是"worktree 物理缺失"或"骨架恢复读取"场景，与 owner 存活无关，MUST 不改动；`tests/test_init_crash_recovery.py` 既有 6 处用例 MUST 保持通过（零回归）。

```
$ rg -n "write_state\(" --type py
```
匹配 43 处：`src/npc/state.py`（4 处：107 定义、136/142 内部调用、439/645 `init_run`/`finalize` 直接调用）、`tests/test_*.py`（39 处，跨 `test_git_chain.py`/`test_lessons.py`/`test_spec_report.py`/`test_state.py`/`test_summary.py`/`test_ff_merge_teardown.py`/`test_telemetry_decision_finalize.py`/`test_parallel_state.py`）。
本 change 只改 `state.py:107` 函数体本身（D2，新增 owner 三字段刷新逻辑）；`state.py:136/142/439/645` 四处既有调用点因函数签名不变（仍是 `write_state(state_json, state_md, state)`）MUST 无需改动；测试侧 39 处既有调用 MUST 因签名不变而保持通过（新增字段是**追加**到 state dict，不影响既有断言除非测试对 state dict 做全字段严格比对——需逐个复核，见任务 3.4）；`tests/test_state.py` 新增用例覆盖 owner 字段刷新本身。

```
$ rg -n "has_in_progress" --type py
```
匹配 2 处：`clean.py:279`（赋值）、`clean.py:280`（`if` 判断），均在 `scan_worktrees_for_cleanup` 同一函数内。
本 change 改写这两行（D5），无其它调用点。

```
$ rg -n "_scan_spine_worktrees_for_resume" --type py
```
匹配 2 处：`init_cmd.py:145`（定义）、`init_cmd.py:316`（`run()` 内唯一调用）。
本 change 改函数体内部逻辑（D3），调用点 316 行签名/返回值形状不变，无需改动。

```
$ rg -n "_atomic_write_text|_skeleton_path\.write_text" --type py
```
匹配：`state.py:99`（`_atomic_write_text` 定义，tmp + `os.replace`）、`state.py:114/116`（`write_state()` 内两处调用）、`init_cmd.py:395`（骨架落盘现状 `_skeleton_path.write_text(...)`，无原子替换语义）。
round-4 评审 F1 修复：`init_cmd.py:395` 改为调用 `state.py::_atomic_write_text(...)`（跨模块导入，或将其提升为共享工具函数），与 `write_state()` 落盘出口共享同一原子替换写机制；`state.py:99/114/116` 不变。

## 1. `src/npc/owner.py`：owner 存活判定核心模块（新建）

- [x] 1.1 新增失败测试 `tests/test_owner.py`：`capture_owner_fields()` 返回含 `owner_pid`（等于当前进程 `os.getppid()`，测试内用 `monkeypatch` 固定值）与 `owner_heartbeat_at`（ISO8601 字符串）两键
- [x] 1.2 新增失败测试：`owner_alive({})`（无任何 owner 字段）→ `False`（无信息即孤儿候选，向后兼容旧 schema）
- [x] 1.3 新增失败测试：`owner_alive({"owner_pid": <当前测试进程自身 pid>})`（pid 确定存活，`os.kill(pid, 0)` 不抛异常）且无心跳字段 → `True`（信任 pid，心跳缺失不判死）
- [x] 1.4 新增失败测试：`owner_alive({"owner_pid": <一个确定不存在的 pid，如通过 fork+立即回收或极大值探测获取>})` → `False`（`ProcessLookupError` 立即判死，不受心跳阈值影响）
- [x] 1.5 新增失败测试：`owner_pid` 存活 + `owner_heartbeat_at` 为 25 小时前的 ISO 时间戳 → `False`（心跳过期，疑似 pid 复用）
- [x] 1.6 新增失败测试：`owner_pid` 存活 + `owner_heartbeat_at` 为 1 小时前 → `True`（心跳新鲜）
- [x] 1.7 新增失败测试：`owner_alive` 对 `os.kill` 抛 `PermissionError` 的场景（用 `monkeypatch` 注入）→ 视为存在，走心跳二次确认分支（同 1.5/1.6 逻辑）
- [x] 1.8 新增失败测试：`owner_pid` 为非法值（如字符串、负数触发 `OSError` 而非 `ProcessLookupError`）→ 退化为仅心跳判定（心跳缺失则 `False`，心跳新鲜则 `True`）
- [x] 1.9 落地 `src/npc/owner.py`：`OWNER_HEARTBEAT_STALENESS_SECONDS` 常量、`capture_owner_fields()`、`owner_alive()`（design.md D1）
- [x] 1.10 运行 `tests/test_owner.py` 全量确认通过

## 2. `src/npc/state.py`：`write_state()` 统一刷新 owner 字段（D2）

- [x] 2.1 新增失败测试（`tests/test_state.py`）：调用 `write_state(state_json, state_md, {...无 owner 字段...})` 后，重新读回的 state JSON 含 `owner_pid`/`owner_heartbeat_at`/`owner_session_id` 三键
- [x] 2.2 新增失败测试：state 含 `cc_session={"session_id": "sess-123", ...}` 时，`write_state()` 后 `owner_session_id == "sess-123"`
- [x] 2.3 新增失败测试：state 不含 `cc_session`（或为 `None`）时，`write_state()` 后 `owner_session_id` 为 `None`（不抛异常）
- [x] 2.4 新增失败测试：连续两次 `write_state()` 调用（间隔可控），第二次 `owner_heartbeat_at` 晚于第一次（刷新语义回归防护）
- [x] 2.5 落地 `state.py::write_state()` 内接入 `owner.capture_owner_fields()` + `owner_session_id` 派生逻辑（design.md D2）
- [x] 2.6 逐一复核 `write_state` 现有 39 处测试调用点（任务 0 已枚举）：对做全字段严格 dict 比对的用例（如直接 `assert data == {...}` 而非取子集字段断言）补齐新增的三个 owner 键或改为子集断言，避免误判为回归
- [x] 2.7 运行 `tests/test_state.py` 全量以及受影响的 `tests/test_git_chain.py`/`tests/test_lessons.py`/`tests/test_spec_report.py`/`tests/test_summary.py`/`tests/test_ff_merge_teardown.py`/`tests/test_telemetry_decision_finalize.py`/`tests/test_parallel_state.py`，确认零回归

## 3. `src/npc/init_cmd.py`：`initializing` 骨架写入 owner 字段（D2）+ 悬空扫描门槛（D3）+ `--no-worktree` 门槛（D4）

- [x] 3.1 新增失败测试（`tests/test_init_cmd.py`）：`npc init` 在建新 worktree **前**落盘的 `initializing` 骨架文件（`_skeleton_path`，写入时机早于 `_git_ops.add_worktree(...)` 调用，见 design.md D2）含 `owner_pid`（非 `None`）与 `owner_heartbeat_at`；`owner_session_id` 为 `None`（session 探测发生在骨架写入之后）
- [x] 3.1a 新增失败测试（round-4 评审 F1 修复）：骨架落盘改用 `_atomic_write_text(...)` 后，骨架文件写入过程 MUST 经由临时文件 + `os.replace`（`monkeypatch` 观测 `os.replace` 被调用一次，或断言目标路径写入前无残留 `.tmp` 文件遗留在正常路径）
- [x] 3.1b 新增失败测试：`monkeypatch` 让骨架落盘的底层写入（`_atomic_write_text` 内部 `os.replace` 或 tmp 文件写入）抛出 `OSError` → 断言异常向上抛出、中断 `run()`，且目标骨架路径要么不存在、要么仍是写入前的旧内容（不得出现"内容被截断/缺 owner 字段"的半态文件），呼应 spec.md「落盘失败时不产生缺 owner 字段的半态新文件」Scenario
- [x] 3.2 新增失败测试：`_scan_spine_worktrees_for_resume` 面对一个 in-progress candidate，其 `owner_pid` 为当前测试进程自身 pid（存活）→ 该 worktree 不进候选池，函数返回 `(False, None, False)`
- [x] 3.3 新增失败测试：同上但 `owner_pid` 为确定不存在的 pid（已死）→ 候选池命中，函数返回 `(True, <wt_path>, False)`（既有行为）
- [x] 3.4 新增失败测试：`_scan_spine_worktrees_for_resume` 面对一个 initializing candidate，owner 存活 → 不进候选池；owner 已死 → 进候选池（同 3.2/3.3 但覆盖 initializing 分支）
- [x] 3.5 新增失败测试：in-progress state 文件缺失/损坏（`json.JSONDecodeError`）时，owner 判定保守退化为"允许进候选池"（与既有"读取失败不阻断"惯例一致）
- [x] 3.6 新增失败测试（并发场景集成测试）：两个连续调用 `run(args)`（模拟两个并发 `npc init`）——第一次建 worktree A（owner 为当前测试进程存活 pid），第二次调用 MUST NOT 返回 `needs_resume=True` 指向 A，而是新建独立 worktree B
- [x] 3.7 新增失败测试：`--no-worktree` 路径（`task_log_dir_for_resume` 下有 in-progress state，owner 存活）→ `run()` 输出 `needs_resume=False`，且生成全新 `run_ts`（不复用旧 state 的 run_ts）
- [x] 3.8 新增失败测试：`--no-worktree` 路径，owner 已死 → `needs_resume=True`，复用旧 run_ts（既有行为回归防护）
- [x] 3.9 落地 `init_cmd.py` 骨架字典新增 owner 字段，并把骨架落盘由 `_skeleton_path.write_text(...)` 改为复用 `state.py::_atomic_write_text(...)`（design.md D2，round-4 评审 F1 修复：原子替换写，失败不留半态）
- [x] 3.10 落地 `_scan_spine_worktrees_for_resume` 的 in-progress/initializing 两处门槛（design.md D3）
- [x] 3.11 落地 `run()` 步骤 3 `--no-worktree` 门槛（design.md D4）
- [x] 3.12 运行 `tests/test_init_cmd.py` 全量确认通过（既有用例零回归 + 新增用例全绿）

## 4. `src/npc/resume.py`：`detect()` 接入 owner 存活判定（D4）

- [x] 4.1 新增失败测试（`tests/test_resume.py`）：`detect()` 面对 owner 存活的 in-progress state → 输出 `needs_resume=False`，`message` 字段区分于"没有找到 in-progress 旧 run"（含"owner"或等价字样，供人工诊断分辨两种成因）
- [x] 4.2 新增失败测试：`detect()` 面对 owner 已死的 in-progress state → 行为不变（`needs_resume=True`，`state_json` 指向该文件，既有行为回归防护）
- [x] 4.3 落地 `resume.py::detect()` 接入 `owner.owner_alive()`（design.md D4）
- [x] 4.4 运行 `tests/test_resume.py` 全量确认通过

## 5. `src/npc/clean.py`：`has_in_progress` 门槛改写（D5）

- [x] 5.1 新增失败测试（`tests/test_clean.py`）：某 worktree 有 in-progress state 且 owner 存活 → 落入 `in_progress_wts`（既有保护行为回归防护）
- [x] 5.2 新增失败测试：某 worktree 有 in-progress state 但 owner 已死，且对应 task_log run **未过** `keep_days` 保留窗口 → 不进 `orphans`（也不进 `in_progress_wts`——因 age-gate 未满足，保守跳过；断言其不出现在两个返回列表中，或按 `plan_cleanup` 语义归为 too-recent，视实现落地时的返回结构决定，落笔时在 summary.md 中记录最终断言形态）
- [x] 5.3 新增失败测试：某 worktree 有 in-progress state 但 owner 已死，且对应 task_log run **已过** `keep_days` 保留窗口 → 进 `orphans`（可回收）
- [x] 5.4 落地 `clean.py::scan_worktrees_for_cleanup` 的 `has_in_progress` 门槛改写（design.md D5）
- [x] 5.5 运行 `tests/test_clean.py` 全量确认通过（既有用例零回归 + 新增用例全绿）

## 6. spec delta：`worktree-owner-liveness`（新能力） + `init-worktree`（修订） + `clean-worktree`（修订）

- [x] 6.1 撰写 `openspec/changes/worktree-owner-liveness/specs/worktree-owner-liveness/spec.md`（`## ADDED Requirements`）：owner 存活信息落盘（字段与刷新时机）、owner 存活判定算法（pid 探测 + 心跳兜底）、`--no-worktree` 路径接入 owner 判定，三条 Requirement 及各自 Scenario
- [x] 6.2 撰写 `openspec/changes/worktree-owner-liveness/specs/init-worktree/spec.md`（`## MODIFIED Requirements`）：「续跑探测扫描悬空 spine worktree」Requirement 修订，新增 owner 存活门槛描述与对应 Scenario（owner 存活时不续跑）
- [x] 6.3 撰写 `openspec/changes/worktree-owner-liveness/specs/clean-worktree/spec.md`（`## MODIFIED Requirements`）：「npc clean 清理孤儿 spine worktree」Requirement 修订，`in-progress` 保护门槛改为"owner 存活才保护"，新增 Scenario（owner 已死的 in-progress worktree 纳入 age-gate 判定）
- [x] 6.4 运行 `openspec validate worktree-owner-liveness --type change --strict`，确认新增/修订 capability 均被正确识别、无重复/矛盾 Requirement 校验错误

## 7. 收尾

- [x] 7.1 运行 `openspec validate worktree-owner-liveness --type change --strict`，修复全部报错直至通过
- [x] 7.2 运行 `uv run pytest tests/test_owner.py tests/test_state.py tests/test_init_cmd.py tests/test_resume.py tests/test_clean.py -v`，确认全绿
- [x] 7.3 运行 `uv run pytest -q` 全量测试，确认零回归
- [x] 7.4 确认改动范围仅限 `src/npc/owner.py`（新建）/ `src/npc/state.py` / `src/npc/init_cmd.py` / `src/npc/resume.py` / `src/npc/clean.py` 与对应 `tests/test_*.py`，未触及 `src/npc/git_ops.py` / `src/npc/session.py` / `src/npc/paths.py`（`git status`/`git diff --stat` 自检）
