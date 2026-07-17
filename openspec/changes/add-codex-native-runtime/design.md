## Context

agent-spine 已有稳定的 Claude Code 插件层和宿主无关的 `npc` 确定性层。缺口不在 workflow 本身，而在 Codex 没有原生可发现的 plugin/skill 入口，也没有把“当前 in-session 生成者是谁”带进 run 路由判定。结果是 Codex 只能被当作一个未完成的 headless backend，无法承载完整主 session；若直接复用默认 review 配置，还可能形成 Codex 生成、Codex review。

Codex plugin 使用 `.codex-plugin/plugin.json`、`skills/*/SKILL.md` 和默认发现的 `hooks/hooks.json`。Codex 与 Claude Code 都能向 hook command 传递 session/cwd/transcript 等公共字段，但 sub-agent stop payload 并非逐字段一致。设计必须在共享插件目录里兼容两种宿主，同时不改变 Claude commands 的工作流文本和默认行为。

## Goals / Non-Goals

**Goals:**

- 同一插件目录可被 Claude Code 与 Codex 原生发现。
- Codex skills 复用现有三份 command workflow，并只做宿主 primitive 映射。
- run 持久化宿主身份；旧 run 和普通 init 保持 Claude 语义。
- Codex runtime 的默认 in-session coder/spec writer 是 Codex；其 LLM review 强制路由到 Claude。
- 路由约束由 Python 代码和测试保证，不只写在 prompt 中。
- Codex SessionStart 能复用现有 session cache；共享 SubagentStop hook 不因 payload 差异误阻断。

**Non-Goals:**

- 不改写 Claude commands、state machine、gate、telemetry 或 archive 逻辑。
- 不实现 Codex headless coder；Codex 原生路径使用宿主内 agent。
- 不自动写用户全局配置或放宽 Codex sandbox。
- 不把 Codex skill 做成第二份独立 workflow 真相源。

## Decisions

**D1：同一 plugin root，双 manifest，workflow 单一真相源。**

在现有插件根增加 `.codex-plugin/plugin.json` 与 `skills/spine-{run,spec,analyze}/SKILL.md`。Codex skills 必须先完整读取对应 `commands/spine-*.md`，再应用一张固定的宿主映射表：`npc init` 增加 Codex runtime 标记；Claude `Agent` 映射为 Codex sub-agent；`TodoWrite` 映射为 plan；交互问答映射为 Codex 的用户输入能力。原 command 文件不修改，避免 Claude 行为回归和两套流程漂移。

备选是复制三份 command 正文进 skills；放弃，因为后续任何 gate/fix-loop 修改都必须双写，无法满足“只扩展运行载体”。

**D2：run.json 增加向后兼容的 `runtime_host`，默认值恒为 `claude`。**

`npc init --runtime-host codex` 把 `runtime_host=codex` 写入 run metadata 和 init payload。CLI 不传时、环境变量兼容路径以及旧 run.json 缺字段时均解析为 `claude`。字段只描述主 session 运行载体，不替代 coder/reviewer backend 配置。

备选是依赖 `CODEX_*` 环境变量自动猜测；放弃，因为环境变量不是稳定契约，且 headless Codex reviewer 也可能让 Claude runtime 进程带有相关变量。

**D3：Codex runtime 只改变未显式配置的 in-session 默认。**

coder backend 解析仍保持 CLI override > phase config > global config；只有全部未设置时，默认 backend 从固定 Claude 改为当前 runtime host。dispatch 仍保持 CLI > phase config > global config；只有全部未设置且 `runtime_host=codex`、backend=codex 时使用 `in-session`。因此 Claude runtime 的解析结果逐项不变，显式 MiMo/headless 配置也不受影响。Codex headless coder 的现有未实现状态保持不变。

spec writer 恒为 in-session；未显式配置时，其生成身份取 runtime host。Codex skill 只调度当前 Codex sub-agent，不伪装成 Claude writer。

**D4：实际生成身份进入 phase/spec routing，Codex 生成时 review 默认强制为 Claude。**

code coder 进入 implement/fix phase 时记录 `generator_backend`，phase exit 保留该字段。review round 从对应 implement/fix phase 读取实际生成身份；旧 state 缺字段时回退到原配置解析。spec 没有 code state phase，因此由 `spec_writer.backend` 显式值或 `runtime_host` 解析其生成身份。

若实际生成身份为 Codex：未传 `--engine` 时选择 Claude，不采用历史默认 Codex；显式 `--engine codex` 仍由同源路由守卫拒绝。其他生成 backend 继续使用既有 review 配置和默认。路由校验函数接受“本次实际生成身份”覆盖值，但 `npc verify routing` 无运行上下文时保持原有配置级输出。

备选是只在 skill 文本里要求 `--engine claude`；放弃，因为用户或后续 skill 版本漏参就能绕过不变量。备选是所有 Codex runtime 都无条件使用 Claude review；放弃，因为 Codex 作为宿主运行显式 MiMo/Claude coder 时并不等于 Codex 生成，约束应绑定产物来源。

**D5：共享 SessionStart hook 只写兼容索引，SubagentStop 对缺字段 fail-open。**

新增一个只消费公共字段的 SessionStart command，把 session/cwd/transcript 追加到现有 by-cwd cache。Claude session 仍优先走现有 mtime 探测，因此该旁路不会改变其正常选择；Codex 可走 hook cache。现有 SubagentStop 校验仅在 payload 明确提供 `last_assistant_message` 时执行内容校验；Codex payload 缺该字段时放行，最终 RESULT 仍由 `npc ... record` 的确定性 schema、commit 和 test gate 校验。

**D6：权限通过文档和启动参数声明，不写机器专属配置。**

Codex 安装说明要求为 `~/.spine/worktrees` 与 `~/task_log` 提供 scoped write access（例如启动时 `--add-dir`）。插件不修改 `~/.codex/config.toml`，也不把绝对路径写进仓库。

## Risks / Trade-offs

- **[Codex sub-agent API 随宿主版本变化]** → skills 只依赖“启动独立 sub-agent 并传 prompt”这一抽象，不把内部工具名写进 `npc`；插件 manifest/skill 用官方 validator 校验。
- **[共享 hook 影响两个宿主]** → SessionStart 仅追加 cache、检测失败退出 0；Claude 仍优先 mtime。SubagentStop 只对已知完整 payload 保持原硬校验。
- **[旧 state 没有 generator backend]** → review 回退到既有 config 解析，历史行为不变；新 coder phase 均写入真实 backend。
- **[Claude CLI 不可用]** → Codex 生成后的 review 返回现有 dependency-missing/exec-failed 结构，不降级为 Codex 自审。
- **[显式 Codex headless 配置]** → 本 change 不实现该路径；只有 Codex 原生 runtime 的未配置默认走 in-session，已有明确错误保持原样。

## Migration Plan

1. 发布包含双 manifest/skills 与 runtime metadata 的插件版本。
2. 旧安装继续通过 `.claude-plugin` 工作；旧 run.json 自动按 `runtime_host=claude` 读取。
3. Codex 用户从 Git 仓库安装/启用 plugin，并按文档授予两个外置目录权限。
4. 回滚时移除 Codex manifest/skills/hooks 增量即可；新增 run.json 字段会被旧版本当作未知字段忽略。

## Open Questions

无。本 change 刻意不覆盖 Codex headless coder；若未来需要，应以独立 capability 实现和验证。
