# 推荐用法：CLI + plugin + CLAUDE.md 三层配置

`npc` 单独可用，但要发挥它作为**自主 harness 底座**的最大价值，需 **CLI + plugin + CLAUDE.md 三层一起配**。本文给出可直接照做的完整步骤。

---

## 层 1：装 `npc` CLI（机器级，所有 Claude Code / Codex session 共享）

`npc` 内置在本仓库（`src/npc`），直接从仓库根安装：

```bash
uv tool install --force --from . npc              # 从仓库根（内置 src/npc）装 CLI
npc --version          # 应输出当前版本（见 pyproject.toml）
```

首次在某工程内 `npc init` 时会自举 `~/task_log/.new-plan-review-schema.json` 与 `~/.local/bin/portable-timeout`。

外部依赖：`git`（必需）、`openspec`（archive + 目标拆解）、`codex`（默认 review 引擎）、`jq`（推荐）。

---

## 层 2：装 harness plugin（用户级，所有 project 共享）

```text
# 在 Claude Code 中：
/plugin marketplace add winewei/agent-spine
/plugin install agent-spine@agent-spine
```

装完得到 5 个能力：commands `/spine-run`、`/spine-spec`、`/spine-analyze` + agents `spine-coder`、`spine-spec-writer`。

> CLI 与 plugin 版本应保持一致；升级 CLI（`uv tool upgrade npc`，tool 名是 npc）后建议同步 `/plugin update agent-spine@agent-spine`。

Codex 使用同一个 plugin root 的原生 manifest/skills：

```bash
codex plugin marketplace add /absolute/path/to/agent-spine
codex plugin add agent-spine@agent-spine
codex --add-dir "$HOME/.spine/worktrees" --add-dir "$HOME/task_log"
```

对应入口为 `$agent-spine:spine-run`、`$agent-spine:spine-spec`、`$agent-spine:spine-analyze`。Codex 作为生成者时，代码与 spec 的 LLM review 强制由 Claude 执行；缺少 Claude CLI 时流程停止，不同源降级。

Kimi Code（`0.27.0`）也复用同一个 plugin root 的原生 manifest/skills（`.kimi-plugin/plugin.json`），但 Kimi 0.27.0 **没有** `codex plugin add` 那种 shell 级插件安装命令——需要通过 Kimi Code 自身的插件管理机制（会话内 `/plugins` 命令）启用本地/git 插件源，并授予与 Codex 相同的两个外置目录访问权限：

```text
# 在 Kimi Code 会话内，用 /plugins 启用本地插件源（Kimi 无对应 shell 命令）：
/plugins
# 按 Kimi 的插件管理界面添加本地路径 /absolute/path/to/agent-spine
```

```bash
# Kimi 进程仍需能写这两个外置目录（与 Codex 相同）：
kimi --add-dir "$HOME/.spine/worktrees" --add-dir "$HOME/task_log"
```

Kimi 作为生成者时，代码与 spec 的 LLM review 同样强制由 Claude 执行（`npc init --runtime-host kimi`）；缺少 Claude CLI 或 Claude review 执行失败时流程停止，不会静默降级为 Codex/Kimi 自审。插件本身不会自动修改用户全局 Kimi 配置或凭据。

---

## 层 3：CLAUDE.md 片段（项目级，让主 session 知道何时该用 harness）

把下面这段粘到目标工程的 `CLAUDE.md`（或 `~/.claude/CLAUDE.md` 全局）：

```markdown
## 自主 harness（agent-spine）

当用户要"实现一批 openspec change"、"把某目标自主跑完"、"长时无人值守地 plan→implement→review→archive"时，
用 `/spine-run`，不要手工逐步操作：

- `/spine-run <目标>` —— 自由目标，harness 自动拆解成 change 再跑（交互档）
- `/spine-run <change名…>` —— 已有 openspec change，直接跑
- `/spine-run <…> --auto` —— 全自主档，fire-and-forget

规则：
- 主 session 只调度与决策；实现/修复一律 spawn `spine-coder` subagent。
- 确定性动作（状态/事件/模板/review/archive）一律走 `npc` 子命令，看一行 JSON 做分支。
- 不在 context 里搬运 prompt 模板 / review.json / summary.md 原文。
- 跑过几个 run 后，用 `/spine-analyze` 读跨 run 指标迭代 harness 自身。
```

---

## 端到端：第一次跑

```text
# 在一个带 openspec/ 的 git 工程内
/spine-run 给认证模块加请求限流和审计日志 --auto
```

harness 会：

1. `npc init` 落 run.json + active.json，检测是否需续跑。
2. 把目标拆成若干 openspec change（如 `add-rate-limit`、`add-audit-log`），排 plan_order。
3. 逐个 change：spawn `spine-coder` 实现 → `npc review run` 多轮 codex review → 有 blocking 就 spawn coder 修 → 干净后 `npc archive run`。
4. 决策点（review 卡死 / archive 失败）：auto 档由 `npc auto-decide` 判定，交互档问你。
5. 收尾：`finalize` + `summary render` + `index append`，汇报结果与轨迹路径。

全程轨迹在 `~/task_log/<PROJ_KEY>/`，跨 run 指标在 `~/task_log/_telemetry/`。

---

## 续跑

中断后再次 `/spine-run`（同工程）会自动检测 `needs_resume` 并从断点（next_seq / next_phase）接着跑，不会重复已 archived 的 change。

## 切 review 引擎到 claude（或自定义后端）

见仓库根 [README — Review 引擎配置](../README.md#review-引擎配置)。常见：用 `.npc/config.toml` 把 `engine` 切到 `claude`，`bin` + `extra_args` 路由到经 `--settings` 配置的 qwen / deepseek 后端。
