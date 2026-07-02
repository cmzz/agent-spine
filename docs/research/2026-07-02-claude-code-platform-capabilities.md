# Claude Code 平台机制盘点报告（2026-07，v2.1.198）

> 调研日期：2026-07-02。盘点 Claude Code 当前版本提供的、可以让 plugin 形态自主编码 harness（agent-spine）「更硬、更稳、更省 context」的平台机制。信息来自官方文档（changelog + code.claude.com），非推测。
> 同期姊妹篇：[Anthropic harness 最佳实践提炼](./2026-07-02-anthropic-harness-best-practices.md)

---

## 一、Hooks 系统（钩子强制约束）

**是什么**：在 Claude Code 执行生命周期的关键点注册自定义命令/HTTP/MCP 工具/Prompt，拦截和转换代理行为。

**对 harness 的具体用法**：

| Hook 事件 | 触发时机 | 能力 | harness 用法 |
|---------|--------|------|----------|
| **PreToolUse** | Tool 执行前 | 阻止 (exit 2)、转换参数、强制提示 | 拦截越权写文件、阻止 `rm -rf .`、`git push --force` |
| **PostToolUse** | Tool 成功后 | 注入上下文、验证结果、自动修复 | 强制跑测试失败则阻止后续、校验 commit message 格式 |
| **Stop** | Turn 结束（主 session） | 注入反馈、验证回复 | 检查是否残留 console.log、验证 PR 已创建 |
| **SubagentStop** | Subagent 完成 | 验证 subagent 结果、强制继续或回滚 | **核心**：阻止 subagent 自声明完成，强制提交证明（test results、git log） |
| **SessionStart** | Session 启动 | 加载配置、设环境变量、重载 skills | 初始化 worktree 权限、检查依赖就绪 |
| **PermissionRequest** | 权限对话出现 | 自动批准/拒绝 | harness 里少用（auto mode 更稳健） |
| **MessageDisplay** (v2.1.180+) | 输出文本前 | 转换/隐藏输出 | 清理 subagent 内部对话、只暴露最终结果 |

**在 plugin 里打包 hooks**：

```text
plugin-root/
├── .claude-plugin/plugin.json
└── hooks/
    └── hooks.json    # 与 settings.json 中 hooks 字段格式一致
```

```json
{
  "hooks": {
    "SubagentStop": [
      {
        "matcher": "Agent",
        "hooks": [
          { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/verify-subagent-commit.sh", "timeout": 10 }
        ]
      }
    ]
  }
}
```

**注意事项 & 坑**：

- exit code 2 是**硬阻止**（中断 tool 调用），其他非 0 是**警告**（继续执行）
- stdin/stdout 必须是纯 JSON，任何日志输出会污染 JSON parser
- PreToolUse 里拒绝 tool 调用时，permission rules 的 deny 规则**优先级更高**（hook 无法覆盖）
- SubagentStop 没有直接的 "rerun" 能力；重试需通过 hook 返回 `additionalContext` 给主 session，由主 session 再显式调用 subagent
- async hooks 适合长时运行（如上传日志），不阻塞 turn 完成

## 二、Custom Subagents 能力边界

**是什么**：专业化 AI 代理，独立 context window，工具受限，可并行。

**核心配置**（SDK/CLI 两种方式）：

```python
AgentDefinition(
    description="...",           # Claude 决策是否调用的依据
    prompt="...",                # 系统提示（决定行为）
    tools=["Read", "Bash"],     # 白名单（omit = 继承全部工具）
    disallowedTools=["Edit"],   # 黑名单（优先级高于 tools）
    model="opus",               # 模型覆盖（"inherit" = 继承主 session）
    maxTurns=20,                # 最多交互轮数
    background=False,           # 后台运行标志（v2.1.175+）
    permissionMode="acceptEdits" # 不支持 bypassPermissions
)
```

**对 harness 的用法**：

1. **工具白名单隔离**（成本 + 安全）：test-runner 只给 Read/Bash/Grep 且 prompt 声明不许改码；code-reviewer 只读（disallow Edit/Write/Bash）
2. **Model 路由（成本优化）**：轻量任务 `model: haiku`，复杂决策 `model: opus`
3. **返回值契约（最关键）**：
   - Subagent 返回的是**最后一条 assistant message**（不是 tool result）
   - 返回体含 `agentId` 可用来 resume
   - subagent 失败（tool 被阻止、max turns 到达）时返回 error message，主 session 需检查
   - **无法**从 SDK 拿到 subagent 全部 tool calls（只有最后 message）；要审计全轨迹须 hook 监听 `parent_tool_use_id`，或 subagent 自己把 audit log 写文件
4. **Context 隔离保证**：不继承主 session 对话历史；**继承** CLAUDE.md、工具定义、指定 skills、MCP servers；信息只通过 Agent tool 的 prompt string 传入
5. **嵌套 subagents**（v2.1.172+）：subagent 可 spawn 自己的 subagent，最深 5 层（需给它 Agent tool）

**注意事项 & 坑**：

- `maxTurns` 到达后强制停止，返回当前状态（不自动 retry）
- `model: "inherit"` 时用主 session 模型
- Windows 上 subagent prompt >8191 字符会失败
- subagent 配置里不支持 `bypassPermissions`；所有 subagent 继承主 session 的 permission mode

## 三、长时运行 & 后台任务支持

| 特性 | 场景 | 限制 | harness 用法 |
|------|------|------|----------|
| Subagents | 专业子任务 | 单次 turn 内（主线程调度） | 主 harness 按顺序 spawn、等待完成 |
| Background subagents (v2.1.175+) | 非阻塞后台任务 | 需 SDK；CLI 有限制 | 主线程继续，subagent 后台跑 |
| Workflows (TS SDK v0.3.149+) | 批量编排（10-100 agents） | 脚本编排，不在对话中 | 脱离 session context，更便宜 |
| Monitor tool | 实时流事件 | Bash 输出每行回调 | 后台 tail 日志，实时反馈 |
| Session resume | 中断恢复 | 需保存 session ID | harness 检查点，恢复后继续 |

**Context 压缩（compaction）行为**：

1. 触发：context 使用 >80% 时自动尝试；压缩前询问（可被 hook 阻止）；单个 tool output 过大导致频繁 thrash 时会放弃并报错
2. 策略（按顺序）：清空旧 tool outputs（保留最近几个）→ 总结对话历史（早期详细指令会丢失）→ 清除过期 skills 定义
3. **compaction 后存活**：`CLAUDE.md` + `MEMORY.md` 永不丢失；`.claude/settings.json` 权限规则保留；subagent 独立 context 不受影响；⚠️ 早期对话里注入的约束可能被压缩掉 → **应该用 deny rules 硬化**
4. 最佳实践：在 CLAUDE.md 里写 "Compact Instructions" 一节，固化 harness 不变量（compaction 后仍在）

## 四、Headless / SDK 模式 vs 交互式 Session

| 维度 | Claude Code CLI（交互式） | Agent SDK（headless） |
|-----|-------|-------|
| 使用场景 | 开发者手工引导 | 自动化脚本 / CI |
| Context 管理 | 自动压缩 + 人工查看 | 完全程序化（settingSources） |
| Hooks | settings.json 配置 | 代码注册 async callback，更灵活 |
| Model 选择 | 交互切换 | 每个 query() 可指定 |
| 权限审批 | 人工切换 | 代码设 permissionMode |
| Session 持久化 | 本地 JSONL（可 resume） | 代码里显式 resume |
| 错误恢复 | 人工中断 + 重新提示 | 异常抛出，显式重试逻辑 |

**关键决策点**：主 harness 交互式（人驾驭）→ CLI + plugin slash command；自主子任务（无人干预）→ Agent SDK query() 或 Workflow；后台长时监听 → Monitor tool。

## 五、权限系统（--auto 档最小权限集）

体系：permission rules（allow/ask/deny）→ permission modes（default/acceptEdits/plan/auto/dontAsk/bypassPermissions）→ managed settings（组织级，不可覆盖）。

`--auto` 档最小权限集示例（`.claude/settings.json`）：

```json
{
  "permissions": {
    "defaultMode": "auto",
    "allow": [
      "Read", "Glob", "Grep",
      "Edit(src/**)", "Write(src/**)",
      "Bash(git status)", "Bash(git commit -m *)", "Bash(npm test)",
      "Agent(*)"
    ],
    "deny": [
      "Bash(curl | bash)",
      "Bash(git push --force *)",
      "Bash(git reset --hard)",
      "Edit(.env)", "Edit(.claude/**)", "Edit(.git/**)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "filesystem": { "denyRead": ["/Users/*/.ssh/**"] }
  }
}
```

**Auto mode 分类器**（v2.1.83+）：默认允许本地文件读写、npm install（有 lock file）、git status/log；默认阻止 curl|bash、force push、production deploy、IAM 改动。

**坑**：`dontAsk` 只执行 allow rules（适合 CI）；`bypassPermissions` 不能在 root/sudo 下跑；deny 规则从不例外（`deny: ["Bash(rm *)"]` 会阻止一切 rm，即使有 allow）。

## 六、Plugin 系统（版本、加载、更新）

```text
plugin-root/
├── .claude-plugin/plugin.json   # 元数据 + 版本
├── skills/<name>/SKILL.md
├── agents/<name>.md
├── hooks/hooks.json
├── .mcp.json
└── settings.json
```

- **版本管理**：plugin.json `version`（semver，用户只在版本变更时升级）；omit version 时每个 commit 即新版本；marketplace nightly 同步（24h 延迟）
- **加载与 reload**：`/reload-plugins` 重扫本地 plugin；`--plugin-dir ./path` 测试时优先级最高；`enabledPlugins` 控制启停
- **skills 自动发现**（v2.1.176+）：`.claude/skills/<name>/` 目录自动当 plugin 加载，无需 plugin.json——适合项目私有 harness 打包
- **坑**：plugin 的 hooks/settings 在启用时全量加载，改了要 `/reload-plugins`；plugin name 全局唯一

## 七、新特性速查（v2.1.180 – v2.1.198）

| 版本 | 特性 | 对 harness 的价值 |
|------|------|----------|
| v2.1.198 | Background Agent Notifications（Notification hook + agent_completed/agent_needs_input） | 订阅 subagent 完成事件，无需轮询 |
| v2.1.198 | Auto-commit/push in background agents | 后台 agent 自动提交 |
| v2.1.195 | `Tool(param:value)` 权限规则（如 `Agent(model:opus)`） | 细粒度控制 subagent 模型成本 |
| v2.1.180 | MessageDisplay hook | 清理中间对话，只暴露最终结果 |
| v2.1.176 | `.claude/skills/` 自动发现 | 项目私有 harness skills 免打包 |
| v2.1.172 | Nested subagents（最深 5 层）；`maxTurns` 限制 | 递归分解；防 subagent 无限循环 |
| v2.1.168 | Extended thinking inheritance in subagents | subagent 继承 ext thinking 配置 |
| v2.1.152+ | SubagentStop hook 可访问 background_tasks / session_crons | hook 可检测后台任务状态 |

## 八、最值得引入的 Top 5（按 ROI 排序）

1. **SubagentStop hook + 强制结果验证**：唯一能硬阻止 subagent 自声明完成的机制；~100 行 hook 脚本消除大量 silent failure
2. **Subagent 工具白名单 + model 路由**：在 agent 定义层收紧权限与成本，而非靠 prompt
3. **Auto mode + deny rules 硬化**：deny 是硬政策，compaction 后仍有效；加 3-5 条 deny 即可真正无人值守
4. **Plugin 打包 hooks 统一管理**：harness 的 hooks 版本化、可共享、可独立测试
5. **CLAUDE.md Compact Instructions + Monitor 后台日志**：不变量在 compaction 后存活 + 实时可观测

## 总结表

| 机制 | 关键能力 | 成熟度 | 优先级 |
|------|--------|------|----------|
| Hooks | 拦截、阻止、强制验证 | 生产级 | 必须 |
| Subagents + 工具白名单 | context 隔离、成本路由 | 生产级 | 必须 |
| Plugin 系统 | 版本管理、团队共享 | 生产级 | 强烈推荐 |
| Agent SDK | 无人脚本化、批量运行 | 生产级 | 强烈推荐 |
| Auto Mode | 消除权限提示 | 研究预览 | 中等 |
| Monitor Tool | 实时日志流 | 稳定 | 中等 |
| Extended Thinking 继承 | subagent 深度推理 | 新特性 | 可选 |
| Nested Subagents | 递归分解 | 新特性 | 可选 |
