# agent-spine Harness 设计与实现审计报告

> 审计日期：2026-07-02（npc/plugin v1.3.0）。审计范围：`plugins/agent-spine/`（spine-run / spine-coder / spine-analyze 契约）+ `src/npc/`（33 个模块）+ `docs/` + `tests/`（33 个测试文件，约 11.5K 行）。
> B1（trigger 词表不一致）与 B3（verify routing 未接主回路）已由主 session 二次核实属实。
> 姊妹篇：[Anthropic 最佳实践](./2026-07-02-anthropic-harness-best-practices.md) · [平台能力盘点](./2026-07-02-claude-code-platform-capabilities.md)

---

## A. 架构地图：数据流与交接契约

```
用户 /spine-run [目标|change 名|空] [--auto]
   │
   ▼
主 session（编排者，Claude，premium 决策层）
   │  只读「一行 JSON 关键字段」做分支，不读模板/summary/review 原文
   │
   ├─ Step0 前置门：npc --version / git / openspec / codex（spine-run.md:47-52）
   ├─ Step1 npc init [--auto]  ──► 一行 JSON：{run_ts, needs_resume, worktree_root, spine_branch, ...}（init_cmd.py:341-369）
   │        · worktree 模式：~/.spine/worktrees/<proj_key>/<run_ts>，分支 spine/<run_ts>
   │        · needs_resume=true 早退（init_cmd.py:196-203）
   ├─ Step2 排 plan_order ──► npc state init-run --plan-order '[...]'（state.py:299）
   │
   └─ Step3 主循环（每个 SEQ）：
        3a implement: IMPL=npc implement run --seq  ──► 按 .deferred 分发
             · deferred=true（in-session/claude）：npc 渲染 prompt 返回 spawn_prompt（coder.py:409-434）
                  → 主 session Task(spine-coder) → 收 RESULT 行 → npc implement record --result
             · deferred=false（headless/mimo）：npc 内部 spawn→抽 RESULT→record（coder.py:468-505）
        3b review-fix 循环：R=npc review run --round0（pipeline.py:490）
             while blocking>0 && stale==false && N<20：npc fix run → [spawn spine-coder] → npc fix record → npc review run
        3c archive: npc archive run（precheck→openspec validate→archive→git commit，pipeline.py:744）
        3d 决策点（auto）：npc auto-decide --trigger ... → action∈{continue-retry,skip,force-archive,abort}
   ▼
Step4 收尾：npc state finalize（判顶层 status + worktree ff-only 合回+拆树，state.py:502）
        → npc summary render → npc index append
```

**三个交接点的契约格式**：

1. **npc → 主 session**：单行紧凑 JSON 到 stdout（`_io.emit`，_io.py:15-18），人类信息走 stderr。关键字段：`ok` / `deferred` / `spawn_prompt` / `blocking` / `stale` / `action` / `merged_back`。
2. **coder → 主 session**：末尾一行 `RESULT: key=value ...`（spine-coder.md:44-59）。implement / fix / 失败三套 schema。
3. **prompt 文件渲染**：npc 把完整契约落盘（`implement.prompt.md` / `round-N.fix.prompt.md`，coder.py:235-293），spawn_prompt 只放 ~150 token 薄引导语 + 绝对路径；coder 第一步 Read 该文件。

---

## B. 脆弱点清单（按严重度排序）

### B1 —【严重】auto-decide 的 trigger 词表与 skill 完全对不上，auto 档决策点必然崩

`spine-run.md:184` 写 `npc auto-decide --trigger <implement-failed|review-stale|archive-failed>`，但 `auto_decide.py:22-31` 的 `VALID_TRIGGERS = {stale, max-rounds, agent-timeout-exhausted, codex-failed, implementer-failed, fixer-failed, summary-missing, commit-not-found}`。三个示范值**无一命中**（`implement-failed`≠`implementer-failed`、`review-stale`≠`stale`、`archive-failed` 不存在，`_decide` 也没有 archive 失败分支）。LLM 照 skill 字面调用 → `emit_error("invalid_trigger", exit_code=2)`（auto_decide.py:134-140）——auto 档每个决策点都会失败。单测用的是正确词表（tests/test_v11_features.py:271），全绿掩盖了 skill 侧的错。

### B2 —【严重】主循环不检查 record 结果，in-session 下 coder 失败被静默吞掉

`IMPL.ok`（spine-run.md:122）在 in-session 分支恒为 true（coder.py:424-434，只代表 prompt 渲染成功）。真正判定 coder 成败的 `npc implement record` / `npc fix record` 的返回值 skill **从不检查**（spine-run.md:133/160）。`record_fix` 失败时把 progress 置 `needs-user-decision`（pipeline.py:1067-1122），但循环无视、继续 review；若后续某轮恰好 blocking==0 → archive 把状态覆盖成 archived（pipeline.py:874），人工闸门被抹掉（并发 B17）。

### B3 —【严重/与不变量矛盾】生成⊥验证 + MiMo 只许执行，运行时并未强制

`principles.md:47` 声称「由 `npc verify routing` 在代码层强制」，但 `check_routing`（verify.py:183）只在独立子命令里被调用（verify.py:294）；`run_review_round`（pipeline.py:490）和 `run_implement/run_fix`（coder.py:358/535）都不调用；spine-run.md 全文也从不执行它。运行时唯一内联守卫是 `_reject_mimo_in_session`（coder.py:54-65）。「review 与 coder 同源」零阻拦——宪法级不变量实际是 opt-in 且未接主回路。

### B4 —【高】tests=pass 裸信；已建好的复跑笼子 `npc verify tests` 从未接线

`record_implement/record_fix` 只信 RESULT 的 `tests` 字段（pipeline.py:974/1080），从不复跑。`verify.py:123-171` 整套 `run_tests`（真实复跑、shlex 防注入、探测 pytest/npm/make）已造好但从未被 pipeline 或 skill 调用。（对应 docs/optimization-proposals/2026-06-22.md 提案 1 + principles.md roadmap——笼子已造好，只差接线。）

### B5 —【高】archive 存在裸 traceback / 无结构化 JSON 的失败路径

`run_archive` 两处 `subprocess.run(..., check=True)`：`git add openspec/`（pipeline.py:831）与 `_git_head`（pipeline.py:737/854）。`cli_archive_run` 只捕获 FileNotFoundError/ValueError（pipeline.py:1202-1207）。`git add` 失败（index.lock、权限、pre-commit hook）→ 裸 traceback、exit 1、stdout 无 JSON → 主 session `jq -r '.ok'` 读空串。违反不变量 2。

### B6 —【高】in-session coder 无 wall-clock timeout，可无限挂起

`timeout` 只传给 headless 子进程（coder.py:346）；in-session 分支（coder.py:383-384）返回 deferred 后，主 session 的 Task 调用无任何超时。`agent timeout-budget / record-timeout`（cli.py:525-555）机制存在但 skill 从不使用 → auto-decide 的 `agent-timeout-exhausted` trigger 在默认流程不可达。默认路径（claude in-session）是唯一没有时间笼子的。

### B7 —【高】崩溃窗口：worktree 创建后、state init-run 前 crash → worktree 泄漏且无法续跑

`npc init` 先建 worktree + 分支 + run.json/active.json（init_cmd.py:223-271），Step2 才落 plan state（state.py:299）。其间崩溃 → `*-plan-state.json` 不存在 → 续跑扫描（init_cmd.py:159，resume.py:28-46）找不到 in-progress → 判定非续跑 → 再建一个 worktree，旧的孤立。`clean.py` 不回收 worktree。

### B8 —【中】detached HEAD → base_branch="" → spine 分支永远合不回，且无告警

`_get_current_branch` detached 时返回 `""`（init_cmd.py:126）；finalize 只判 None（state.py:564），空串通过；`merge_ff_only` `git checkout ""` 失败（git_ops.py:108-116）→ 分支保留待人处理。功能安全但 init 阶段不检测不警告，用户到 run 结束才发现。

### B9 —【中】review run 自身失败在循环里没有分支

while 条件直接读 `.blocking`/`.stale`（spine-run.md:147-149），从不检查 `R.ok`。review 失败（codex-exec-failed，pipeline.py:593-630，返回体无 blocking）时 `jq` 得 `null` → bash 整数比较错误 → 行为未定义。`codex-failed` trigger 存在却无触发点。

### B10 —【中】auto-decide 决策空间与 skill 广告的四个 action 不闭合

skill 声称 action∈{continue-retry, skip, force-archive, abort}（spine-run.md:185-187），但 `_decide`（auto_decide.py:45-122）永不返回 `abort`——遇系统性阻塞只会一路 skip，没有「及时止损整体退出」。

### B11 —【中】force-archive 二次失败无兜底 → finalize 卡死

force-archive 只 `npc archive run` 一次（spine-run.md:187）；再失败则状态停非终态 → `npc state finalize` `emit_error("incomplete")`（state.py:543-548）；3d 对「force-archive 又失败」无二次决策 → 潜在悬挂。

### B12 —【低】RESULT 解析：notes 里的 `word=` 会污染键

`_parse_result_line` 用 `re.split(r"\s+(?=[a-zA-Z_]+=)", rest)`（pipeline.py:926）。`notes=调大 timeout=30 后通过` 会把 `timeout` 抽成新 key 甚至覆盖真实字段。notes 无「吃到行尾」处理。

### B13 —【低】coder backend=codex + dispatch=in-session 静默降级为 Claude

headless codex 明确 NotImplementedError（coder.py:351），但 in-session 分支（coder.py:383）不检查 codex，直接渲染 prompt 让主 session spawn spine-coder → 「配置 codex 却 in-session」静默用 Claude 执行，telemetry `backend=codex` 是假标签。

### B14 —【低】telemetry 完整性缺口

- auto-decide 完全不 emit telemetry：skip/force-archive/trigger 频次对 /spine-analyze 不可见——恰是「harness 在哪卡住」的最高价值信号
- finalize / ff-merge 结果不 emit（state.py:502-616）：run 级成败、合回失败率进不了指标流
- in-session 崩在 phase enter 与 record 之间时，phase 永远停 in-progress，无 phase.exit

### B15 —【低】版本漂移无运行时兼容门

Step0 只判 npc 存在（spine-run.md:48），不比对版本。plugin markdown 与 npc CLI 经不同渠道安装，三处版本号靠人工同步。旧 npc 缺子命令/字段时只会 argparse exit 2 或缺字段静默。

### B16 —【低】多个确定性笼子造好却未接入主回路

`npc plan check`（apply 前 artifact 齐全门）、`npc spec analyze`（spec↔tasks 漂移门）、`npc git branch-for / ensure-clean`（cli.py:416-420）——spine-run.md 全文均不调用。Step2B 用裸 `openspec new change`（spine-run.md:94）而非 `npc plan new-change`。

### B17 —【低】archived 覆盖 needs-user-decision，弱化人工闸门

`run_archive` 成功后无条件置 `status=archived`（pipeline.py:874），不检查之前是否 needs-user-decision。

---

## C. 测试与验证缺口

确定性底座覆盖扎实（ff_merge、resume、state、git_ops、coder_dispatch、review、pipeline、verify 均有）。缺口集中在**契约层与集成层**：

1. 无「skill 词表 ↔ 代码词表」一致性测试（B1 本可被一个守卫测试拦下：解析 spine-run.md 里的 `--trigger` 候选值 ∈ VALID_TRIGGERS；同理断言 skill 里出现的 npc 子命令/字段名真实存在）
2. 无全循环集成测试：deferred→record-fail→转 3d 的编排路径（B2）无任何 harness-level 冒烟
3. archive 未捕获异常无测试（B5）：无用例覆盖 `git add` 抛错时 CLI 是否仍 emit JSON
4. verify routing / verify tests 的「接线」无测试：只测了函数本身，没有断言被 review/record 路径调用（B3/B4）
5. 崩溃恢复边界无测试：B7、B8、in-session phase 悬挂
6. review 循环病态收敛无测试：blocking 振荡（3→2→3→2）只靠 N<20 兜底

## D. 与 4 条核心不变量的矛盾/执行不到位

- **不变量 1（生成⊥验证）**：声称代码层强制，实为 opt-in 且未接主回路（B3）
- **不变量 2（结构化契约唯一真相）**：archive 有裸 traceback 路径（B5）；tests=pass 采信 coder 自报（B4）；主 session 不检查 record 返回（B2）
- **不变量 3（笼子 ∝ 1/人在回路）**：笼子造而不用（B4/B16）与 auto 档关键失败路径缺笼（B6/B9/B11）并存——auto 档是「去掉人」的档，恰恰应该更硬，实际最软
- **不变量 4（廉价层只许执行）**：内联守卫只挡 mimo+in-session；codex+in-session 静默降级 Claude 打假标签（B13）；auto-decide 不进 telemetry 使越界不可事后审计（B14）

## 优先修复建议（按性价比）

1. **B1**：改 spine-run.md:184 trigger 示范值为真实词表（或加别名映射 + archive-failed 分支）；加 skill↔代码词表一致性测试
2. **B2**：主循环必须检查 `npc implement/fix record` 的 `.ok`，失败即转 3d
3. **B5**：`run_archive` 的 `git add`/`_git_head` 包 try/except 转 emit_error，堵死裸 traceback
4. **B3/B4**：把 `verify routing`（review 前）与 `verify tests`（record 时）接进主回路——接线成本极低，收益是两条宪法级不变量从「声明」变「执行」
5. **B6/B9/B11**：补齐 auto 档三个失败路径的确定性处理（in-session 超时、review-run 失败、force-archive 二次失败）
