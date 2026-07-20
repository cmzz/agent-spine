## 0. 落点确定性枚举（先跑命令，再动手改代码）

以下命令在 `REPO_ROOT` 下逐条执行，命中数与命中行已核对（本轮 write 阶段跑出的实际结果，供后续逐项勾完）：

```bash
grep -n 'choices=\[' src/npc/cli.py
```
命中 15 行；其中 5 行含 `codex` 字面量：79（`--runtime-host`，需加 `kimi`）、248（`review run --engine`，**不加**）、337（`implement run --backend`，需加 `kimi`）、377（`fix run --backend`，需加 `kimi`）、529（`spec review run --engine`，**不加**）。

```bash
grep -n '"claude", "codex"\|NPC_RUNTIME_HOST' src/npc/paths.py
```
命中 4 行（90、322、416、417），其中 2 行是真正的白名单判定，需加入 `"kimi"`：322（`runtime_host_raw not in ("claude", "codex")`）、417（`os.environ.get("NPC_RUNTIME_HOST") in ("claude", "codex")`）；90/416 只是同一字段的读写引用，不含独立白名单逻辑，不需要改。

```bash
grep -n 'SUPPORTED_CODER_BACKENDS\s*=\|"codex": "headless"' src/npc/config.py
```
命中 2 行：`SUPPORTED_CODER_BACKENDS = ("claude", "mimo", "codex")`（加 `"kimi"`）、`DISPATCH_DEFAULTS` 里 `"codex": "headless"`（旁边补 `"kimi": "headless"`）。

```bash
grep -n 'runtime_host == "codex" and backend == "codex"' src/npc/coder.py
```
命中 1 行（87）——泛化为 `runtime_host == backend and backend != "claude"`。

```bash
grep -n 'backend == "codex"' src/npc/coder.py
```
命中 1 行（451，`_run_backend` 的 headless 未实现分支）——扩展为 `backend in ("codex", "kimi")`。

```bash
grep -n 'generator_backend == "codex"' src/npc/pipeline.py
```
命中 1 行（757）——泛化为 `generator_backend in ("codex", "kimi")`。

```bash
grep -n 'runtime_host == "codex"\|explicit_writer != "codex"' src/npc/spec_pipeline.py
```
命中 3 行（179、183、213）+ 1 行（215，`explicit_writer != "codex"`）——四处全部从字面量 `"codex"` 泛化为 `p.runtime_host != "claude"` / `explicit_writer != p.runtime_host` 参数化条件。

```bash
grep -n 'both_codex' src/npc/verify.py
```
命中 2 处判定（`check_routing` 内 276 行、spec 侧同构校验函数内 398 行）——**均不修改**（保留字面同源语义）；但两处紧邻各新增一条独立判定 `kimi_review_not_claude` / `spec_kimi_review_not_claude`（design.md F1 修复段），因为 `both_codex` 只堵"同源"，堵不住"Kimi 生成 + 显式非 Claude engine"这个 F1 指出的漏洞。

```bash
grep -n 'PLUGIN_ROOT:-\${CLAUDE_PLUGIN_ROOT}' plugins/agent-spine/hooks/hooks.json
```
命中 2 行（SessionStart、SubagentStop 各一处）——**本 change 不修改这两行**。design.md "Verified Platform Facts" 第 5 条已用真实 Kimi 0.27.0 二进制核实：Kimi 从不读取 `hooks/hooks.json`（该文件是 Claude/Codex 专属发现约定），扩展它的兜底链对 Kimi 场景是死代码。Kimi 的 hook 改走 `.kimi-plugin/plugin.json` 自带的 `hooks` 数组字段（见下方 3.1a）。

```bash
find plugins/agent-spine/skills -name SKILL.md
```
命中 3 个文件（spine-run/spine-spec/spine-analyze）——各自追加一段 Kimi host adapter 映射表。

```bash
kimi --version && strings -a "$(command -v kimi 2>/dev/null || echo ~/.kimi-code/bin/kimi)" | grep -n 'KIMI_PLUGIN_DIR_PATH\s*=\|HookDefSchema\$1 = object(\|enabledHooks()' 
```
本机 `~/.kimi-code/bin/kimi`（`0.27.0`）上可重跑此命令核实：manifest 路径常量 `KIMI_PLUGIN_DIR_PATH = ".kimi-plugin/plugin.json"`、hook 声明 schema `{event, matcher?, command, timeout?}`、`enabledHooks()` 对每条 hook 注入 `cwd: record.root` 与 `env: {KIMI_CODE_HOME, KIMI_PLUGIN_ROOT: record.root}`——这是 design.md "Verified Platform Facts" 全部结论的可复现验证入口。**版本基线为阻断条件（round-3 F5 修复，见 spec.md 新增 Requirement "Kimi version baseline is fixed and version drift blocks implementation"）**：本 change 只支持 `0.27.0`；任何后续实施者 MUST 先重跑此命令，若报出的版本不是 `0.27.0`，或上述字符串核实结果与 design.md 记录不一致，MUST 停止受影响行为的实施并上报漂移，不得假定新版本行为兼容后静默继续——这不是"建议重跑"，是先决条件。

## 1. Runtime host contract

- [ ] 1.1 补充失败测试：`tests/test_paths.py`（`runtime_host=kimi` 环境变量/run.json 往返）、`tests/test_init_cmd.py`（`--runtime-host kimi` 持久化）、`tests/test_config.py`（`SUPPORTED_CODER_BACKENDS` 含 `kimi`）——对称于既有 `test_codex_runtime_env_roundtrip` / `test_run_json_codex_runtime_roundtrip` / `test_init_codex_runtime_is_persisted`。
- [ ] 1.2 `src/npc/paths.py` 两处白名单（322、417）加入 `"kimi"`；`src/npc/cli.py` `--runtime-host` 的 `choices`（79）加入 `"kimi"`；`src/npc/config.py::SUPPORTED_CODER_BACKENDS` 加入 `"kimi"`，`DISPATCH_DEFAULTS` 补 `"kimi": "headless"`；`implement run` / `fix run` 的 `--backend` choices（337、377）加入 `"kimi"`。
- [ ] 1.3 跑 `uv run pytest tests/test_paths.py tests/test_init_cmd.py tests/test_config.py -v`，确认 Claude/Codex 既有行为仍绿。

## 2. Native generation and review routing

- [ ] 2.1 补充失败测试：`tests/test_coder_dispatch.py`（对称于 `test_codex_runtime_default_is_codex_in_session` 增加 `test_kimi_runtime_default_is_kimi_in_session`，以及显式 headless/backend 覆盖不变的对称用例）、`tests/test_coder_run.py`（对称于 `test_run_implement_codex_not_implemented` 增加 `test_run_implement_kimi_not_implemented`）。
- [ ] 2.2 `src/npc/coder.py::resolve_dispatch` 的 `default_override` 判定从字面量泛化为 `runtime_host == backend and backend != "claude"`；`_run_backend` 的 `if backend == "codex": raise NotImplementedError` 扩展为 `if backend in ("codex", "kimi"): raise NotImplementedError(...)`（消息按实际 `backend` 参数化）。
- [ ] 2.3（round-3 F1 修复措辞校正：这条是固定校验顺序的第 1 步——白名单拒绝，与 2.6 的第 2 步——Kimi 生成者路由拒绝互斥，不冲突，见 spec.md 新增的两步顺序表述）补充失败测试：`tests/test_pipeline.py`（对称于 `test_codex_generated_code_defaults_to_claude_review` 增加 `test_kimi_generated_code_defaults_to_claude_review`；新增 `test_explicit_kimi_review_engine_is_rejected`，直接调用 `run_review_round(..., engine_name="kimi")` 断言抛 `ValueError` 且消息含"未知 review engine"与 `kimi`——这一步在 `generator_backend` 是否为 `kimi` 之前就已经拒绝，不依赖生成者身份）、`tests/test_spec_pipeline.py`（对称于 `test_codex_runtime_spec_review_defaults_to_claude` 增加 `test_kimi_runtime_spec_review_defaults_to_claude`、`test_kimi_runtime_rejects_explicit_non_kimi_spec_writer`、`test_kimi_runtime_explicit_kimi_spec_writer_has_no_violation`；新增 `test_explicit_kimi_spec_review_engine_is_rejected` 对称覆盖 `spec_review_run(..., engine_name="kimi")`）。
- [ ] 2.4 `src/npc/pipeline.py:757` 的 `default_engine` 判定从 `generator_backend == "codex"` 泛化为 `generator_backend in ("codex", "kimi")`（不含 `mimo`）。
- [ ] 2.5 `src/npc/spec_pipeline.py` 四处（179、183、213、215）从字面量 `"codex"` 泛化为 `p.runtime_host != "claude"` / `explicit_writer != p.runtime_host` 参数化条件，`spec_writer_host_mismatch` violation 消息保持"路由错误可观察"的既有措辞风格，仅替换宿主名变量。
- [ ] 2.6（F1 修复，新判定不是既有代码泛化；round-3 F1 修复措辞校正：这是固定校验顺序的第 2 步，只在 2.3 的白名单校验放过某个取值之后才会被求值——实践中该取值只可能是 `codex`，因为 `kimi` 已经在 2.3 那一步被拒绝、永远不会带着 `review.engine == "kimi"` 走到这里；下面的 `review.engine != "claude"` 判定式在正常可达路径里等价于 `review.engine == "codex"`，不会与 2.3 的"未知 engine"分类产生歧义）补充失败测试：`tests/test_verify.py` 新增 `test_check_routing_rejects_explicit_codex_review_of_kimi_generated_code`（`coder_backend_override="kimi"`、`review.engine="codex"` → 断言 violations 含新规则 `kimi_review_not_claude`）与 spec 侧对称的 `test_check_spec_routing_rejects_explicit_codex_review_of_kimi_written_spec`；`tests/test_pipeline.py` 新增 `test_explicit_codex_review_of_kimi_generated_code_is_rejected`（走 `run_review_round(..., engine_name="codex")`，phase record 的 `generator_backend="kimi"`，断言返回 routing-violation 而不是执行 codex review）；`tests/test_spec_pipeline.py` 对称新增 `test_explicit_codex_spec_review_of_kimi_written_spec_is_rejected`。`src/npc/verify.py::check_routing` 与 spec 侧同构函数各新增一条独立判定：`kimi_review_not_claude = effective_backend == "kimi" and review.engine != "claude"`／`spec_kimi_review_not_claude`，命中即追加 violation（`rule` 用这个新名字，不复用 `gen_not_orthogonal`——语义不同，不是"同源"而是"来源为 Kimi 时非 Claude engine 一律拒绝"）。

- [ ] 2.7（round-3 F3 修复，回归测试，不新增 `src/npc/pipeline.py` 任何新分支）补充失败测试，证明 `record_implement`/`record_fix` 现有的确定性拒绝路径与 `runtime_host`/生成者身份无关、对 Kimi 同样生效，且拒绝态下 phase 不完成、review 不启动：
  - `tests/test_pipeline.py` 新增 `test_record_implement_kimi_backend_missing_result_line_blocked`（`generator_backend="kimi"` 起始的 phase，`record_implement` 收到空/无 `RESULT:` 行文本，断言返回 `error="result-line-missing"`、`ok=False`，且未调用 `run_review_round`）、`test_record_implement_kimi_backend_commit_not_found_blocked`（对称于既有 `commit-not-found`/`commit-not-on-run-branch` 用例，只是 phase 由 `backend="kimi"` 起始）、`test_record_implement_kimi_backend_rerun_tests_failed_blocked`（对称于既有 `test_record_implement_rerun_fail_overrides_self_report`，`generator_backend="kimi"`）；`tests/test_coder_run.py`/`test_pipeline.py` 对称补 `record_fix` 三个用例。
  - 本条不新增运行时代码——`record_implement`/`record_fix` 从不读取 `runtime_host` 或 `generator_backend` 来决定是否校验 RESULT/commit/tests，既有分支对任意 backend 结构性统一生效；新增的是显式断言这条硬闸对 Kimi in-session 路径可达，防止将来误以为 Kimi 绕过了它（对应 spec.md 新增 Scenario "Missing or malformed Kimi RESULT..." / "An unresolvable or off-branch commit..." / "Failing tests reported by Kimi..."）。
  - `tests/test_spec_pipeline.py` 对称新增 `test_spec_write_record_kimi_writer_out_of_scope_changes_blocked` 与 `test_spec_fix_record_kimi_writer_unexpected_commit_blocked`，覆盖既有 `_scope_guard_violation` 的 `out_of_scope_changes`/`unexpected_commit` 分支对 Kimi 生成的 spec writer phase 同样生效（对应 spec.md 新增 Scenario "Out-of-scope changes or an unexpected commit from a Kimi-dispatched spec writer..."）。
- [ ] 2.8（round-2 F4 修复，缺失场景补测，不是新增运行时代码）补充失败测试，验证"Kimi 作为生成者、默认路由到 Claude review、但 Claude 不可用或执行失败"时既有的 `dependency_missing` / `<engine>-exec-failed` 结构化错误路径可达，且不会静默降级为 Codex/Kimi 自审：
  - `tests/test_pipeline.py` 新增 `test_kimi_generated_code_review_dependency_missing_does_not_fallback`（`generator_backend="kimi"`，monkeypatch `_find_claude_bin` 抛出既有的依赖缺失异常，走 CLI 层入口断言产出 `dependency_missing`、`exit_code=4`，且从未调用任何 codex/kimi review 执行函数）与 `test_kimi_generated_code_review_claude_exec_failed_does_not_fallback`（对称于既有 `test_run_review_round_claude_fails_then_retry_fails`，固定 `engine_name="claude"`、phase 的 `generator_backend="kimi"`，monkeypatch `_claude_exec` 失败，断言 `result["ok"] is False`、`result["error"] == "claude-exec-failed"`、`result["engine"] == "claude"`，且未触发任何 codex/kimi 路径）。
  - `tests/test_spec_pipeline.py` 对称新增 `test_kimi_written_spec_review_dependency_missing_does_not_fallback` 与 `test_kimi_written_spec_review_claude_exec_failed_does_not_fallback`，覆盖 `spec_review_run` 走到既有 `dependency_missing`（`src/npc/spec_pipeline.py:1054/1391`）与 `claude-exec-failed`（对称于既有 `{"ok": False, "error": "claude-exec-failed"}` 用例）两条路径，phase 的 spec writer 为 `kimi`。
  - 本条不新增任何 `src/npc/*.py` 运行时代码——`_find_claude_bin` 抛出、`dependency_missing`、`<engine>-exec-failed` 均是既有通用错误处理，只是此前从未有测试从"生成者是 Kimi"这一具体触发路径断言过它们可达且不被绕过（design.md Risks "[Claude CLI 不可用或执行失败，round-2 F4 修复]"）。
- [ ] 2.10（round-3 F2 修复，缺失场景补测）补充失败测试：`tests/test_spec_pipeline.py` 新增 `test_kimi_runtime_unconfigured_spec_writer_is_kimi_in_session`——Kimi runtime 且未配置 `[spec_writer]` 时，调用 `spec_write_run`（及对称的 `spec_fix_run`）断言解析出的 writer 生成身份为 `kimi`、返回 `deferred=true` 的 in-session 分发请求（对应 spec.md 新增 Scenario "Unconfigured Kimi spec writer resolves to Kimi in-session"）。
- [ ] 2.9 跑 `uv run pytest tests/test_coder_dispatch.py tests/test_coder_run.py tests/test_pipeline.py tests/test_spec_pipeline.py tests/test_verify.py tests/test_spec_routing.py -v`，确认 Claude/Codex/MiMo 既有路由行为逐项不变，且新增 F1（round-1 routing gap）、F4（round-2 Claude 不可用隔离）与 2.7（round-3 F3 确定性 record 拒绝闸）回归测试全绿。

## 3. Kimi plugin surface

- [ ] 3.1 新增 `plugins/agent-spine/.kimi-plugin/plugin.json`，顶层字段参照 `.codex-plugin/plugin.json`（`"skills": "./skills/"`，`interface.displayName/shortDescription/longDescription/developerName`；`interface.capabilities`/`category`/`defaultPrompt` 等 Codex 专属子字段 Kimi 会静默忽略，可选择性省略，不是必须字段级对齐——见 design.md "Verified Platform Facts" 第 2 条），名称/描述替换为 Kimi 专属文案。
- [ ] 3.1a（F2/F4 修复，新增字段）在同一 `.kimi-plugin/plugin.json` 里新增 `"hooks"` 数组字段（Kimi manifest 自带的 hook 声明机制，`{event, matcher?, command, timeout?}`，`.strict()` schema，不接受 Claude/Codex 的分组结构）：
  ```json
  "hooks": [
    { "event": "SessionStart", "command": "bash \"$KIMI_PLUGIN_ROOT/hooks/index-session.sh\" --runtime-host kimi", "timeout": 10 },
    { "event": "SubagentStop", "matcher": "coder", "command": "bash \"$KIMI_PLUGIN_ROOT/hooks/verify-subagent-result.sh\"", "timeout": 15 }
  ]
  ```
  复用现有 `plugins/agent-spine/hooks/index-session.sh` 与 `verify-subagent-result.sh` 两个物理脚本（不新增脚本文件）；`$KIMI_PLUGIN_ROOT` 由 Kimi 运行时自动注入到该 hook 的执行环境（`enabledHooks()` 已验证会这样做），不需要 hooks.json 那套 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 兜底链。**不要**同时修改 `plugins/agent-spine/hooks/hooks.json`——那是 Claude/Codex 专属发现路径，Kimi 从不读取（design.md D5）。**matcher 必须是 `"coder"` 不是 `"spine-coder"`（round-2 F2 修复）**：design.md Verified Platform Facts 第 9 条已用 `strings -a` 核实 `"coder"` 是 Kimi `Agent` 工具未显式传 `subagent_type` 时的内置默认 profile 名，也是 SubagentStop 事件 `matcherValue` 的实际取值；`"spine-coder"` 在 Kimi 侧不对应任何真实 profile，用它做 matcher 会让该 hook 在 Kimi 下永远不被触发。
- [ ] 3.2（round-2 F1/F2 修复）在现有 `plugins/agent-spine/skills/{spine-run,spine-spec,spine-analyze}/SKILL.md` 三个文件内完成两处改动：
  - **F1 — 宿主选择前言**：在既有编号列表（"1. Read.../2. Follow.../3. Apply only..."）末尾新增第 4 条,原样写入 design.md D1 段落给出的英文选择规则文本（"This file may contain host-adapter mapping tables for more than one host...MUST NOT read, follow, or otherwise apply any mapping table headed with a different host's name...")；同时把现有 `## Host mappings` 下的 Codex 段落标题改名为 `### Codex host adapter mapping`。
  - **F2 — Kimi 映射表措辞**：在 `### Codex host adapter mapping` 之后新增并列的 `### Kimi host adapter mapping` 三级标题段落（不删除不改写 Codex 段落）：`npc init --runtime-host kimi`；把 Claude `Agent` spawn 映射为"调用 `Agent` 工具时不显式传 `subagent_type`（或显式传 `subagent_type="coder"`，Kimi 内置默认 profile），传入与 Codex 版本相同的 `.spawn_prompt` + `.prompt_file` 契约"——**不写** `Agent subagent_type=spine-coder`（design.md Verified Platform Facts 第 9 条已核实 Kimi 无此 profile）；`TodoWrite`→Kimi todo；`AskUserQuestion`→Kimi 用户输入；`backend=kimi` 时强制 `--engine claude`。
- [ ] 3.3 新增 `tests/test_kimi_plugin.py`，断言项对称于 `tests/test_codex_plugin.py`，并新增 F1 边界测试：
  - `.kimi-plugin/plugin.json` 存在、`skills == "./skills/"`、`hooks` 数组含 `event=SessionStart` 与 `event=SubagentStop` 两条且 `command` 字面含 `--runtime-host kimi` / `matcher == "coder"`（**不是** `"spine-coder"`，round-2 F2 修复）。
  - 三个 SKILL.md 均含 `../../commands/{name}.md` 引用；文中含选择规则第 4 条的字面文本（`MUST NOT read, follow, or otherwise apply any mapping table headed with a different host's name` 子串存在）；`--runtime-host kimi` 与 `--engine claude` 字面出现于 run/spec skill 正文。
  - **F1 边界测试（新增）**：对每个 SKILL.md，按 `### Codex host adapter mapping` 与下一个 `###` 标题（或文件尾）切出 Codex 区间字符串，按 `### Kimi host adapter mapping` 切出 Kimi 区间字符串；断言 Codex 区间不含子串 `--runtime-host kimi`，Kimi 区间不含子串 `--runtime-host codex`，且 Kimi 区间不含子串 `subagent_type=spine-coder` / `subagent_type=\"spine-coder\"`。
  - **round-3 F2 边界测试（新增，对应 spec.md 新增 Scenario "Workflow-fidelity directives are identical across host adapters"）**：对每个 SKILL.md，取整份文件文本，分别减去（挖空）其 Codex 区间与 Kimi 区间（复用上一条已切出的边界），得到"host-mapping 之外的公共文本"；断言该公共文本里编号列表的 1/2/3 条（"Read .../Follow every phase.../Apply only the host mappings below...if this file and the canonical workflow differ, the canonical workflow wins"）与结尾"Keep all `npc` state, record, telemetry, gate, archive, and finalization calls exactly as defined by the canonical workflow"这句字面存在且不因宿主而改写；这把"Kimi 与 Codex 执行相同 canonical workflow"从"引用同一个文件"这一弱断言，升级为"工作流忠实性指令逐字相同、只有 host-mapping 表不同"这一可 grep 复核的边界断言。
  - `marketplace.json` 无需改动（复用同一条目，见 design.md Assumptions）。
- [ ] 3.4（F4 修复：真实验证，不是"无工具则记录未验证"；round-3 F5 修复：明确此为阻断条件而非"重新核实后继续"）`.kimi-plugin/plugin.json` 的 manifest 路径、字段集、`skills` 目录发现约定、`hooks` 数组 schema、`${KIMI_PLUGIN_ROOT}` 注入行为均已在 design.md "Verified Platform Facts" 一节通过对本机已安装的真实 `~/.kimi-code/bin/kimi`（`0.27.0`）二进制做 `strings -a` 检索验证（可重跑任务 0 里列出的验证命令复核）；这不是猜测,也不是"官方文档转述",是对实际将加载该插件的二进制的直接检查。本 change 的支持基线固定为 `0.27.0`（见 spec.md 新增 Requirement "Kimi version baseline is fixed and version drift blocks implementation"）：若实施时本机 Kimi 版本已升级、`strings` 命中结果与 design.md 记录不一致，这是**阻断条件**——任务执行者 MUST 停止受影响行为的实施并上报漂移，不得先假定新版本兼容再继续实施；仅当另开后续 change 重新核实并同步更新 design.md 的"Verified Platform Facts"编号条目与受影响的 Requirement/Scenario 之后，才可在该新版本基线上恢复实施。本条不再允许"无校验工具可用时仅记录未验证"这一逃生舱口,因为验证工具（真实二进制）在本机确认可用。

## 4. Hook and session compatibility

- [ ] 4.1 补充失败测试：`tests/test_kimi_plugin.py`（对称于 `test_session_start_hook_indexes_codex_common_payload`，新增 Kimi payload 索引用例：payload 只含 `{source, session_id, cwd}`——不含 `transcript_path`，因为 design.md 已核实 Kimi SessionStart 结构性地永远不带该字段——断言 `index-session.sh` 仍写入一行缓存记录，`transcript_path` 字段为空字符串；另新增显式 `--runtime-host kimi` CLI 参数场景，断言写入的记录里 `runtime_host == "kimi"`）；`tests/test_session.py` 新增：(a) `detect_via_hook` 对 `transcript_path` 为空字符串的缓存条目返回 `None`（与无条目同一分支）；(b) 公共入口 `session.detect_session`，在 mtime 未命中且 hook 只有该部分条目时返回 `("-", "-", "unknown")`，不报错、不误判为命中；(c) 断言 `detect_via_hook` 的实现不调用 `detect_via_mtime`（避免 F3 指出的"hook 内部自行回退 mtime"这种职责混淆重新引入）。
- [ ] 4.1b（round-3 F3 修复，回归测试，不新增运行时代码）`tests/test_subagent_stop_hook.py` 新增 `test_kimi_payload_without_last_assistant_message_released`，对称于既有 `test_codex_payload_without_last_assistant_message_released`：构造仅含 `{session_id, cwd}`（不含 `last_assistant_message`）的 Kimi 形态 SubagentStop payload，断言 `verify-subagent-result.sh` exit 0 放行（fail-open）；测试注释显式说明放行不代表结果被信任——真正的拒绝闸是 2.7 新增的 `record_implement`/`record_fix`/`spec_write_record`/`spec_fix_record` 回归测试，二者合起来才是 spec.md 新增 Scenario "Hook fail-open never substitutes for the deterministic record gate" 的完整覆盖。
- [ ] 4.2 `plugins/agent-spine/hooks/index-session.sh`：新增对 `--runtime-host <value>` 位置参数的解析（`$1`/`$2`，或用 `getopt`；只有 Kimi 的 manifest hook 声明会传，Claude/Codex 的 `hooks/hooks.json` 调用不受影响）——写入优先级：显式 CLI 参数 > 既有 `source` 字符串猜测（`"codex"` 分支不变）> `data.get("runtime_host")` payload 直通 > 缺省 `None`；同时把第 18 行的必需字段收窄为 `cwd`/`session_id`（原来的三字段 `all(...)` 校验会让 Kimi payload 整条记录被外层 `except Exception: pass` 吞掉，必须先修这个才有"部分索引"可言），`transcript_path` 缺失时写入 `""`。**不修改** `plugins/agent-spine/hooks/hooks.json`（design.md D5：Kimi 不读这个文件）。`src/npc/session.py::detect_via_hook` 保持现状的 `if not sid or not tx: return None` 判断（这一行本身已经正确，是它上游的 payload 曾经被吞掉；修完 index-session.sh 后这行会被真正走到），不新增 mtime 调用、不新增数据结构。
- [ ] 4.3 跑 `uv run pytest tests/test_kimi_plugin.py tests/test_codex_plugin.py tests/test_subagent_stop_hook.py tests/test_session.py -v`，确认 Kimi/Codex/Claude 三种 payload 形状均按预期通过或按预期 fail-open，且部分索引降级路径的新增用例全绿。

## 5. Documentation and regression

- [ ] 5.1 在 `docs/usage.md` 现有 Codex 段落（层 2）之后追加 Kimi 对称段落：说明 Kimi 无 shell 级插件安装命令、通过 Kimi 自身插件管理机制启用本地/git 插件源、需授予与 Codex 相同的两个外置目录权限、Kimi 作为生成者时 LLM review 强制由 Claude 执行。
- [ ] 5.2 跑 `openspec validate add-kimi-native-runtime --type change --strict`，完成本清单全部勾选项。
- [ ] 5.3 跑本 change 涉及的目标测试文件（1.3/2.9/4.3 已列），随后跑 `uv run pytest -q` 全量回归。
- [ ] 5.4 确认 worktree 只含本 change 预期内改动（`git status --porcelain` 只涉及 `plugins/agent-spine/.kimi-plugin/`、`plugins/agent-spine/skills/*/SKILL.md`、`plugins/agent-spine/hooks/*`、`src/npc/*.py`、`tests/test_kimi_plugin.py` 及既有测试文件的追加断言、`docs/usage.md`、`openspec/changes/add-kimi-native-runtime/**`），原始 checkout 不受影响。
