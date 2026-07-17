## Why

agent-spine 当前把 Claude Code 当作唯一原生运行载体：插件清单、命令入口、sub-agent 调度、session 识别和默认评审路由都围绕 Claude Code 建模。虽然 `npc` 已接受 `codex` 作为 coder backend，但 Codex 不能像 Claude Code 一样直接安装插件并完整执行 `/spine-run`、`/spine-spec`、`/spine-analyze`，且 Codex 自己 coding 时缺少强制交给异源 Claude review 的保证。

本 change 为同一套 agent-spine 知识与确定性生命周期增加 Codex 原生运行载体。适配必须是宿主层扩展：共享既有 workflow、state、telemetry 和 gate，不改变 Claude Code 路径及任何与宿主无关的业务逻辑。

## What Changes

- 为 `plugins/agent-spine` 增加 Codex 插件清单和三个原生 skills，分别承载现有 `spine-run`、`spine-spec`、`spine-analyze` 工作流；既有 Claude commands 继续作为规范知识源，不复制一套会漂移的工作流。
- 引入向后兼容的 `runtime_host` run 元数据。旧 run 和普通 `npc init` 仍解释为 `claude`；Codex skill 初始化时显式记录 `codex`。
- 在 Codex runtime 中，把 Codex coder/spec writer 作为宿主内 agent 执行；`npc` 仍负责 phase 生命周期、记录、telemetry、deterministic gates 与路由不变量。
- 增加跨宿主评审约束：当本轮 code 或 spec 由 Codex 生成时，LLM review 必须使用 Claude；相同来源的 Codex review 必须被拒绝。Claude runtime 的既有默认路由不变。
- 使共享 hook/session 探测能够识别 Codex hook payload，同时保持 Claude hook 已有的校验语义。
- 增加安装、权限与验证文档，明确 Codex 需要访问 agent-spine 的外置 worktree 与 task log 目录。

## Capabilities

### New Capabilities

- `codex-native-runtime`: Codex 插件入口、宿主身份、in-session agent 调度、Claude 异源 review、hook/session 兼容和不回归约束。

### Modified Capabilities

无。该能力仅在显式 `runtime_host=codex` 时增加一条宿主适配路径；现有 capability 的 Claude runtime 契约不变。

## Impact

- **插件资产**：`plugins/agent-spine/.codex-plugin/`、`plugins/agent-spine/skills/`、共享 hooks。
- **运行时与 CLI**：`src/npc/paths.py`、`src/npc/init_cmd.py` 及 init CLI 参数；旧 run.json 无需迁移。
- **路由与 pipeline**：coder/spec pipeline 在做异源 review 判定时读取本轮 runtime/generator 身份；Claude runtime 继续沿用现有配置与默认值。
- **测试与文档**：新增 Codex plugin 结构、runtime metadata、routing guard、hook compatibility 测试及 Codex 使用说明。
- **依赖**：不新增 Python 运行时依赖；Codex 与 Claude CLI 仍由使用者环境提供。

## Non-Goals

- 不重写、分叉或改变 `spine-run` / `spine-spec` / `spine-analyze` 的阶段逻辑、质量门、状态机、telemetry 语义。
- 不改变 Claude Code 插件入口、Claude runtime 默认 backend/dispatch/review 行为，也不迁移已有 run。
- 不把 `npc` 扩展成通用 LLM 编排器；Codex/Claude 仍负责智能生成，`npc` 只承担既有确定性职责和路由不变量。
- 不让 Codex 自审 Codex 产物，也不以 prompt 约定替代可测试的路由检查。
- 不自动修改用户全局 Codex/Claude 配置、凭据或权限策略。
