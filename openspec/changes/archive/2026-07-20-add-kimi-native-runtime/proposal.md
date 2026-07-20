## Why

agent-spine 现已有两个原生运行载体：Claude Code（唯一完整实现）与 Codex（`add-codex-native-runtime`，插件清单 + host-adapter skills + `runtime_host=codex` 路由）。Kimi Code 0.27.0 声称提供与 Claude 同款的 `Agent(subagent_type=...)` / `AskUserQuestion` / todo 工具集，理论上可以比 Codex 更接近"近恒等"地承载 agent-spine 工作流，但目前没有任何 Kimi 原生入口——Kimi 用户只能把 Kimi 当作未完成的 headless coder backend，无法承载完整主 session，也没有跨宿主 review 隔离保证。

本 change 为同一套 agent-spine 知识与确定性生命周期增加 Kimi 原生运行载体，严格镜像 `add-codex-native-runtime` 已验证的四层结构（插件清单、host-adapter skills、npc 路由扩展、hook/session 兼容），只在 Kimi 与 Codex 行为确有差异的地方分叉（sub-agent 映射粒度、宿主标识传参机制、显式同源 review 的可达性）。

## What Changes

- 为 `plugins/agent-spine` 增加第三份插件清单 `.kimi-plugin/plugin.json`，`skills` 字段与 Codex manifest 一样指向共享的 `./skills/`目录；不新建 Kimi 专属 skills 子目录——现有 `skills/spine-{run,spec,analyze}/SKILL.md` 三个文件各自扩展出一段独立的 "Kimi host adapter" 映射表，与既有 "Codex host adapter" 映射表并存于同一文件，两套映射均可被对应宿主的 skill 加载机制读取。
- 引入 `runtime_host=kimi` 取值：CLI `npc init --runtime-host kimi`、run.json 持久化、环境变量兼容路径均把 `kimi` 加入既有 `claude`/`codex` 白名单；旧 run 与未显式指定的 init 继续解释为 `claude`，Codex 行为逐项不变。
- 扩展 `SUPPORTED_CODER_BACKENDS` 加入 `kimi`；把 coder dispatch 的"未配置默认 in-session"判定从字面量 `runtime_host == "codex" and backend == "codex"` 泛化为参数化条件（`runtime_host == backend and backend != "claude"`），同一段代码同时覆盖 Codex 与 Kimi，不复制分支。
- 把"生成者非 Claude 时 review 默认强制 Claude"的判定从 `generator_backend == "codex"` 泛化为 `generator_backend in ("codex", "kimi")`；`spec_writer_host_mismatch` 判定从字面量 `runtime_host == "codex"` 泛化为 `runtime_host != "claude"`，同一份代码同时覆盖 Codex 与 Kimi。
- `review.engine`（`SUPPORTED_ENGINES`）保持恒为 `("codex", "claude")` 二值不扩展；新增回归测试显式断言 `--engine kimi` 报"未知 review engine"而非被静默接受，把这一结构性保证纳入回归面。**新增**（fix round 1，round-3 F1 修复措辞校正）：校验固定分两步、按序执行，二者结果不会冲突——(1) 先按 `SUPPORTED_ENGINES` 白名单拒绝任意不在集合内的取值为"未知 review engine"，`kimi` 从不在这个集合里，因此 `--engine kimi` 永远在这一步被拒绝，无论 generator 是不是 Kimi；(2) 只有通过白名单的取值（实践中只剩 `codex`，因为 `claude` 从不构成违规）才进入 `check_routing` 与 spec 侧同构函数各新增的一条独立判定：Kimi 生成的产物显式请求该受支持的非 Claude engine（即 `--engine codex`）算路由违规而拒绝执行——不是"同源才拒绝"（`both_codex` 那种），因为 `kimi` 从不出现在 `review.engine` 取值里，"同源"判定对它结构性不可达，必须单独按 generator 身份判定，否则"MUST 路由到 Claude"会被显式 `--engine codex` 绕过。这两步的判定范围互斥（第一步拦掉 `kimi`，第二步只处理通过白名单后剩下的 `codex`），因此不存在"同一输入同时满足两种分类"的矛盾。
- Kimi 的 hook 通过 `.kimi-plugin/plugin.json` 自带的 `"hooks"` 数组字段声明（`{event, matcher?, command, timeout?}`，manifest-embedded，Kimi 运行时自动注入 `${KIMI_PLUGIN_ROOT}`/`${KIMI_CODE_HOME}`），SessionStart 条目直接携带显式 `--runtime-host kimi`；复用现有 `hooks/index-session.sh`/`verify-subagent-result.sh` 两个物理脚本，但**不改动** `plugins/agent-spine/hooks/hooks.json`（那是 Claude/Codex 专属的目录发现约定，经对本机真实 Kimi 0.27.0 二进制核实，Kimi 从不读取这个文件，扩展它的 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 兜底链对 Kimi 无效）。`index-session.sh` 新增对显式 `--runtime-host` 参数的解析（优先级最高），`source` 字符串猜测保留为 Codex 向后兼容回退。
- `index-session.sh` 的必需字段从 `{cwd, session_id, transcript_path}` 收窄为 `{cwd, session_id}`（经核实 Kimi 的 SessionStart payload 结构性地永远不带 `transcript_path`，原三字段校验会让整条记录被静默吞掉）；`transcript_path` 缺失时写入空字符串。`detect_via_hook` 对该类"部分索引"条目返回 `None`（与无条目同一分支，不新增数据结构、不在内部调用 mtime 探测）——覆盖 Kimi SessionStart payload 缺 `transcript_path` 的降级路径,同时保持 `detect_session` 既有的"先 mtime 后 hook"调用顺序不变。
- 增加 Kimi 安装、权限与验证文档（追加在现有 Codex 段落之后，不新起一节），明确 Kimi 0.27.0 无 shell 级插件安装命令，用户需通过 Kimi 自身的插件管理机制启用本地/git 插件源，并授予与 Codex 相同的两个外置目录访问权限。
- **版本基线策略**（round-3 F5 修复，不再推迟到实施时决定）：本 change 的支持基线固定为 Kimi Code `0.27.0`，不做版本区间或兼容矩阵；`design.md` "Verified Platform Facts" 记录的 manifest/hook schema、默认 sub-agent profile 名等结论均以对该版本二进制的 `strings -a` 直接核实为依据。若实施时本机 Kimi 版本或上述核实结果发生漂移，这是**阻断条件**——实施者 MUST 停止受影响行为的实施并上报，不得假定新版本兼容后静默继续；恢复实施只能靠还原 `0.27.0` 二进制，或另开一个后续 change 重新核实并同步更新受影响的 Requirement/Scenario/`design.md` 事实（见 `specs/kimi-native-runtime/spec.md` 新增 Requirement "Kimi version baseline is fixed and version drift blocks implementation"）。

## Capabilities

### New Capabilities

- `kimi-native-runtime`: Kimi 插件入口、宿主身份、in-session agent 调度、Claude 异源 review、hook/session 兼容和不回归约束。

### Modified Capabilities

- `coder-dispatch`: 「in-session 分发绝不与廉价层同源」的 premium 后端白名单从 claude/codex 扩为 claude/codex/kimi（mimo 恒 headless 的约束不变）。除此之外，该能力仅在显式 `runtime_host=kimi` 时增加一条宿主适配路径；现有 `codex-native-runtime` 与 Claude runtime 契约不变。

## Impact

- **插件资产**：`plugins/agent-spine/.kimi-plugin/`（新增，含自带的 `hooks` 数组字段）、`plugins/agent-spine/skills/*/SKILL.md`（扩展映射表）、`plugins/agent-spine/hooks/index-session.sh`（新增显式 `--runtime-host` 解析 + 放宽必需字段）。**不改动** `plugins/agent-spine/hooks/hooks.json`（Kimi 从不读取，见 design.md D5）。
- **运行时与 CLI**：`src/npc/config.py`、`src/npc/paths.py`、`src/npc/cli.py`、`src/npc/coder.py`。
- **路由与 pipeline**：`src/npc/pipeline.py`、`src/npc/spec_pipeline.py`、`src/npc/verify.py`（`both_codex` 判定本身不需要新增 `both_kimi`——见 design.md D4 说明；但需要新增一条独立的 `kimi_review_not_claude`／`spec_kimi_review_not_claude` 判定，堵住"Kimi 生成 + 显式非 Claude engine"绕过路由的漏洞，见 design.md F1 修复段与 fix round 1）。
- **session 探测**：`src/npc/session.py`（`detect_via_hook` 对部分索引条目返回 `None` 的既有分支保持不变；行为改变的根因在 `index-session.sh` 的字段校验放宽，而不在 `session.py` 本身）。
- **测试与文档**：新增 `tests/test_kimi_plugin.py`，并在既有 `test_config.py` / `test_coder_dispatch.py` / `test_paths.py` / `test_init_cmd.py` / `test_pipeline.py` / `test_spec_pipeline.py` / `test_verify.py` / `test_session.py` / `test_cli` 相关测试文件里补充 Kimi 对称断言；`docs/usage.md` 追加 Kimi 段落。
- **依赖**：不新增 Python 运行时依赖；Kimi Code CLI 仍由使用者环境提供。

## Non-Goals

- 不重写、分叉或改变 `spine-run` / `spine-spec` / `spine-analyze` 的阶段逻辑、质量门、状态机、telemetry 语义。
- 不改变 Claude Code 或 Codex 插件入口、默认 backend/dispatch/review 行为，也不迁移已有 run。
- 不把 `npc` 扩展成通用 LLM 编排器；Kimi/Codex/Claude 仍负责智能生成，`npc` 只承担既有确定性职责和路由不变量。
- 不让 Kimi 自审 Kimi 产物，也不以 prompt 约定替代可测试的路由检查。
- 不实现 Kimi headless coder；Kimi 原生路径使用宿主内 agent，与 Codex 现状一致。
- 不把 `kimi` 加入 `SUPPORTED_ENGINES`（review engine 恒为 codex/claude 二选一）。
- 不支持 Kimi `0.27.0` 之外的版本，也不构建多版本兼容矩阵；版本或已核实行为漂移按 spec.md 新增 Requirement 阻断实施，不做静默适配（round-3 F5 修复）。
- 不改造 qlj hub 或任何跨仓库插件注册机制（Kimi 0.27.0 无对应 shell 命令，属于另一仓库范围）。
- 不自动修改用户全局 Kimi/Codex/Claude 配置、凭据或权限策略。
