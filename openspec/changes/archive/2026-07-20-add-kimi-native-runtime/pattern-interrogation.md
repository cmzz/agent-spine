## Analogs

本 change 的语义锚点明确要求"镜像 add-codex-native-runtime 的四层结构"。逐层核对仓库内既有实现：

### 1. 双 manifest + 复用 hook 脚本层

- `plugins/agent-spine/.codex-plugin/plugin.json` —— Codex 原生 manifest，`"skills": "./skills/"` 指回共享 skills 目录，无独立 `hooks` 路径字段（依赖 hooks 自动发现约定）。`.kimi-plugin/plugin.json` 应同构：新增第三份 manifest，`skills` 字段指向同一 `./skills/` 目录，不新建 kimi 专属 skills 子目录。
- `plugins/agent-spine/.claude-plugin/plugin.json` —— Claude manifest 对照组，字段集与 Codex manifest 不完全相同（多 `keywords`，少 `interface.capabilities`），说明各宿主 manifest 允许字段差异，只需各自满足官方 schema。
- `plugins/agent-spine/hooks/hooks.json` 第 8/20 行：`"command": "bash ${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/hooks/index-session.sh"`（及 `verify-subagent-result.sh`）—— 现有 provider-neutral 兜底链已经是 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 两级；Kimi 侧按用户目标要接入 `${KIMI_PLUGIN_ROOT}`，需要扩展为三级兜底链（如 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${KIMI_PLUGIN_ROOT}}}`），而不是新写一份 hooks.json。
- `plugins/agent-spine/hooks/index-session.sh` 第 32 行：`"runtime_host": "codex" if "codex" in str(data.get("source", "")).lower() else data.get("runtime_host")` —— SessionStart hook 已经按 payload `source` 字段猜测 `codex`；泛化到 Kimi 需要同一处加一条 `"kimi" in source` 分支（或改成更通用的宿主标记探测），否则 Kimi session 索引会落回 `data.get("runtime_host")`（可能为 None）。
- `plugins/agent-spine/hooks/verify-subagent-result.sh` 第 20-38 行：SubagentStop 校验已经对"payload 缺 `last_assistant_message`"做 fail-open（`exit 0`），这正是用户目标里"SubagentStop 在 Kimi 不可块（仅观察）"要求的既有机制——**不需要为 Kimi 新写分支**，只要 Kimi 的 stop payload 确实缺该字段（或经同一 fail-open 判定）即可复用。

### 2. host-adapter skills 层

- `plugins/agent-spine/skills/spine-run/SKILL.md`：三步结构（1. 完整读 `../../commands/spine-run.md` 2. 遵循其全部 phase/gate/RESULT schema 3. 只应用宿主映射表）。映射表覆盖：`npc init --runtime-host codex`、Claude `Agent`→Codex sub-agent（含 `.spawn_prompt`/`.prompt_file` 契约）、`TodoWrite`→Codex plan、`AskUserQuestion`→Codex 用户输入、`backend=codex` 时强制 `--engine claude`。Kimi 版三个 skill 应逐条镜像这张表，把 `--runtime-host codex` 换成 `--runtime-host kimi`。
- `plugins/agent-spine/skills/spine-spec/SKILL.md`：同构映射表，多了"Codex MUST NOT 自审 spec"一句强调。
- `plugins/agent-spine/skills/spine-analyze/SKILL.md`：只读工作流，映射表最简（无 review 路由分支，因为 analyze 不生成受 review 约束的产物）。
- `plugins/agent-spine/commands/spine-run.md` 第 271/395 行：`Agent subagent_type=spine-coder prompt="$SPAWN_PROMPT" timeout=$TIMEOUT_SEC` —— 这是 Claude 侧调用形态的唯一真相源；Codex skill 因为没有同名工具，需要把它翻译成"启动隔离 sub-agent 并传 prompt"的抽象描述（design.md D1 备选分析：拒绝复制 command 正文，只做映射表）。若 Kimi 真的原生支持 `Agent(subagent_type=...)` 同名工具（用户目标原文断言），Kimi skill 的映射粒度可以比 Codex skill 更细——直接写 `Agent subagent_type=spine-coder ...` 而不是泛化描述，这是与 Codex 模式的一个**关键差异点**，不是照抄。

### 3. npc 运行时/路由扩展层

- `src/npc/config.py` 第 35-37 行：`SUPPORTED_ENGINES = ("codex", "claude")`、`SUPPORTED_CODER_BACKENDS = ("claude", "mimo", "codex")`、`DISPATCH_DEFAULTS = {"claude": "in-session", "mimo": "headless", "codex": "headless"}`——三张表是 backend/engine 校验与默认 dispatch 的唯一真相源。加 Kimi 只需在 `SUPPORTED_CODER_BACKENDS` 与 `DISPATCH_DEFAULTS` 追加 `"kimi"`，**不**追加进 `SUPPORTED_ENGINES`（review engine 恒 codex/claude 二选一，Kimi 从不是 review 执行者）。
- `src/npc/paths.py` 第 75 行 `runtime_host: str = "claude"`；第 321-323 行 `runtime_host_raw = data.get("runtime_host", "claude"); if runtime_host_raw not in ("claude", "codex"): runtime_host_raw = "claude"`；第 416-418 行环境变量兼容路径同一白名单。三处都是 hardcode 的二元 tuple，加 Kimi 需要在三处同时把 `"kimi"` 补进白名单（同一模式三次出现，写代码时要一次搜全，否则会出现"CLI 能传但 run.json 读回来降级成 claude"的漂移）。
- `src/npc/cli.py` 第 77-82 行：`p_init.add_argument("--runtime-host", choices=["claude", "codex"], default="claude", ...)`——CLI 层第四处白名单，同样要加 `"kimi"`。
- `src/npc/coder.py` `resolve_dispatch`（第 69-91 行）：`default_override = "in-session" if runtime_host == "codex" and backend == "codex" else None`——这是"未配置默认 in-session 复用 default_override"的确切落点；泛化成 Kimi 需要把条件从字面量 `"codex"` 改成"runtime_host 与 backend 相等且不是 claude"这种参数化判定，否则会出现 Codex/Kimi 各写一遍相同逻辑的重复分支。同文件 `resolve_backend`（第 94-115 行）`return cfg.coder.backend_for_phase(phase) or runtime_host` 已经是完全通用实现，*不需要改*——因为它直接回退到 `runtime_host` 字符串本身，Kimi 会自动获得正确的未配置默认值。
- `src/npc/pipeline.py` 第 748-757 行：`generator_backend = phase_record.get("generator_backend") or ...`；`default_engine = "claude" if generator_backend == "codex" else review_cfg.engine`——这是"Codex 生成强制 Claude review"的实际落点，泛化需要把 `== "codex"` 改成 `in ("codex", "kimi")`（或更通用的"非 claude 的 in-session/未来宿主生成"判定）。
- `src/npc/verify.py` `check_routing`（第 214-283 行）：`both_codex = effective_backend == "codex" and review.engine == "codex"`（第 276 行）是"同源守卫拒绝显式 --engine codex"的判定点。**关键差异**：Kimi 从未进入 `SUPPORTED_ENGINES`，所以 `review.engine == "kimi"` 在正常路径下不可达（CLI/pipeline 层的 `engine_name not in ("codex", "claude")` 校验会先行拒绝）——意味着"显式同源 Kimi review 被拒绝"这条 codex 侧对应场景，对 Kimi 可能是**结构性不可达**而不是需要新增运行时判定的场景，需要在 Assumptions/Open Questions 里挑明。
- `src/npc/spec_pipeline.py` `_effective_spec_routing`（第 163-195 行）与 `_spec_routing_violations`（第 198-230 行）：`writer_backend = "codex" if p.runtime_host == "codex" else cfg.spec_writer.effective_backend`；`spec_writer_host_mismatch` 判定 `p.runtime_host == "codex" and explicit_writer is not None and explicit_writer != "codex"`（第 212-216 行）——这正是用户目标"spec_writer_host_mismatch 泛化为 runtime_host 与显式 writer 不符即拒"的确切落点。泛化写法应类似 `p.runtime_host != "claude" and explicit_writer is not None and explicit_writer != p.runtime_host`，同一份代码同时覆盖 codex 与 kimi，不是复制一份 kimi 专属分支。

### 4. 测试与文档层

- `tests/test_codex_plugin.py`：`test_codex_manifest_and_native_skills_exist`（manifest 字段 + skill 引用 canonical command 断言）、`test_codex_coding_skills_require_claude_review`（断言 skill 正文含 `--runtime-host codex` 与 `--engine claude`）、`test_session_start_hook_indexes_codex_common_payload` / `test_session_start_hook_indexes_symlinked_cwd_under_both_keys`（hook 索引行为）。Kimi 侧应新增结构对称的 `tests/test_kimi_plugin.py`，断言项一一对应（manifest 存在、skill 引用 canonical command、`--runtime-host kimi` + `--engine claude` 字面出现、SessionStart 索引行为）。
- `docs/usage.md` 第 34/42 行已有 Codex 原生入口的两行说明（"Codex 使用同一个 plugin root 的原生 manifest/skills""Codex 作为生成者时…LLM review 强制由 Claude 执行"）；Kimi 应在同一段落追加对称描述，而不是另起一节。
- `openspec/changes/add-codex-native-runtime/{proposal,design,tasks}.md` 与 `specs/codex-native-runtime/spec.md`：六个 Decision（D1-D6）、五组 Requirement/Scenario 是本 change 后续 write 轮最直接的结构模板——Requirement 命名、Scenario 覆盖面（unconfigured/explicit/legacy/host-mismatch 四态）都应逐条对照复用，只替换宿主名与本 change 特有的两个待验证降级路径（transcript_path、subagent_type profile）。

## Assumptions

- Kimi Code 0.27.0 的插件发现机制与 Codex 同构：存在一个 `.kimi-plugin/plugin.json` 及其自身的 `skills` 字段发现约定，且复用同一份 `plugins/agent-spine/skills/*/SKILL.md` 目录（不新建 kimi 专属 skills 子目录），符合用户目标原文。
- Kimi 原生提供与 Claude `Task(subagent_type=spine-coder)` 语义等价的 `Agent(subagent_type=...)` 工具，因此 Kimi host-adapter skill 的映射粒度可以比 Codex skill 更"近恒等"（直接引用同一 subagent_type 名字），而不需要 Codex skill 那种"启动隔离 sub-agent"的抽象层措辞。
- Kimi 提供与 Claude `AskUserQuestion` 及 `TodoWrite` 语义等价的用户问答与 todo/plan 工具，映射表可以逐条对照 Codex skill 的映射表（问答→Kimi 用户输入机制，todo→Kimi plan 更新），且在 `--auto` 模式下同样保留"禁止询问用户"的既有约束。
- 插件 hooks 的宿主 root 环境变量约定是 `${KIMI_PLUGIN_ROOT}`（与 `${CLAUDE_PLUGIN_ROOT}` 同构命名），需要追加进 `plugins/agent-spine/hooks/hooks.json` 现有的 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 两级兜底链，扩展为三级。此假设来自用户目标原文，本次盘问未独立核实 Kimi 官方文档；write 轮落盘前应尽量用可及渠道（如 context7/官方文档）交叉核实一次变量名，核实不到则在 design.md 的 Risks/Trade-offs 里显式标注"未验证的第三方约定"。
- `review.engine`（`SUPPORTED_ENGINES`）保持恒为 `("codex", "claude")` 二值，不因新增 Kimi runtime host 而扩展——Kimi 只作为 `runtime_host` / `coder`/`spec_writer` backend 的第三个取值，从不作为 review 执行者，这与"Kimi 生成强制 Claude review、同源拒绝"的约束是一致的（拒绝逻辑落在 generator_backend 判定上，不落在 review engine 白名单扩展上）。
- Kimi 0.27.0 没有 shell 级插件安装命令（用户目标原文明确排除 qlj hub 改造）；因此本 change 的文档层只需描述"如何在 Kimi 内启用本地/git 插件源"，不涉及类似 `codex plugin` CLI 子命令的自动化步骤，也不涉及跨仓库的 hub 注册改造。
- `.agents/plugins/marketplace.json` 不需要新增条目——现有单条目 `{"name": "agent-spine", "source": {"path": "./plugins/agent-spine"}}` 已经同时服务 Claude 与 Codex 两套 manifest（各宿主按自己的发现约定在同一路径下找自己的 manifest 文件名），Kimi 应同样复用这一条目而不新增。

## Open Questions

- Kimi SubagentStop（或等价 stop 事件）payload 是否包含 `transcript_path` 字段？若包含，`hooks/index-session.sh` 的 SessionStart 索引路径可以直接复用现有 by-cwd cache 写入逻辑；若不包含，`npc` 侧的 session 探测（`src/npc/session.py::detect_via_hook`）在 Kimi runtime 下应该走什么降级路径——是完全跳过 hook cache 只靠 mtime 探测，还是需要一种"部分索引"（无 transcript_path 但仍记录 session_id/cwd）的中间态？
- Kimi 的 `Agent(subagent_type=...)` 工具是否允许插件/skill 声明自定义 subagent_type 配置文件（类似 Claude `agents/spine-coder.md` 的 frontmatter 注册机制），还是只能调度 Kimi 内置的通用 sub-agent 类型？若只能用内置类型，Kimi skill 的"近恒等映射"实际上要退化为"用默认 coder sub-agent + `.prompt_file` 契约驱动其行为"，这与 Codex skill 当前采用的抽象层措辞趋同，需要在 design.md 里明确两种情况各自的 SKILL.md 措辞与测试断言差异。
- `check_routing`（`src/npc/verify.py`）里"显式同源 review 被拒绝"这条针对 Codex 的判定（`both_codex`）依赖 `review.engine == "codex"` 可达；由于 Kimi 从不进入 `SUPPORTED_ENGINES`，对应的 "Explicit same-source review is rejected" 场景（对照 codex spec 的同名 Scenario）在 Kimi 侧是否应该：(a) 直接不写这条 Scenario（因为 CLI/pipeline 层的 engine 白名单校验已经结构性拒绝，属于既有行为的自然推论，不需要新测试）；还是 (b) 仍然显式写一条 Scenario + 一个防御性测试，断言"传 `--engine kimi` 时报 `未知 review engine` 而不是被静默接受"，把这个结构性保证也纳入回归面？
- `plugins/agent-spine/hooks/index-session.sh` 第 32 行按 `data.get("source")` 字符串猜测 `"codex"`；Kimi 的 SessionStart payload 里对应字段的取值约定是什么（是否也叫 `source`，取值是否含 `"kimi"` 子串）？还是应该改成更通用的机制——例如让各宿主的 hooks.json 条目显式传一个 `runtime_host` 环境变量或 CLI 参数给 `index-session.sh`，不再靠猜测字符串？


## User Decisions (Interactive)

以下为交互档用户对 4 条开放问题的裁决：

1. **transcript_path 缺失时的 session 探测降级路径** → 采用**部分索引中间态**：SessionStart hook 仍写入 session_id/cwd（transcript_path 缺省为空），`detect_via_hook` 对空 transcript_path 条目跳过、自然回落 mtime 探测——索引数据不丢，实现改动最小。
2. **Kimi 不支持插件自定义 subagent_type profile 时的 SKILL.md 措辞** → 采用**抽象层措辞**，与 Codex skill 同构：只依赖'启动隔离 sub-agent 并传 prompt'这一抽象，用默认 coder sub-agent + .prompt_file 契约；若 Kimi 将来支持自定义 profile 属自然增强，SKILL.md 不用改。
3. **'显式 --engine kimi 被拒'** → **写 Scenario + 防御性测试**：显式断言 --engine kimi 报'未知 review engine'而非被静默接受，把结构性保证纳入回归面，防止将来有人把 kimi 加进 SUPPORTED_ENGINES 时漏掉同源守卫。
4. **index-session.sh 的宿主标识机制** → **显式传参、泛化**：各宿主 hooks 声明里给 index-session.sh 传显式参数（如 --runtime-host kimi 或环境变量），不再猜 source 字符串；codex 的猜测逻辑保留为向后兼容回退。
