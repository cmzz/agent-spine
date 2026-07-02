# Anthropic 官方 agent harness 工程实践提炼报告

> 调研日期：2026-07-02。面向"本地自主编码 harness：主 session 编排 + subagent 执行 + CLI 底座 + 独立 review 闸门"（agent-spine）的作者。全部内容基于实时抓取原文，非训练记忆。
> 同期姊妹篇：[Claude Code 平台机制盘点](./2026-07-02-claude-code-platform-capabilities.md)

---

## 1. Building effective agents

URL: https://www.anthropic.com/engineering/building-effective-agents

- **先问是不是需要 agent**：能用预定义代码路径（workflow）解决的就不要用自主 agent。Orchestrator-workers 只在"子任务无法预先枚举"时才值得（多文件代码修改被点名为典型场景）——对应本地 harness：调度逻辑尽量写成确定性代码，只把真正开放的部分交给 LLM。
- **Evaluator-optimizer 循环**：一个 LLM 生成、另一个 LLM 按明确标准评估并回灌反馈，适用于"有清晰评估标准 + 迭代可量化改进"的任务——这正是独立 review 闸门的理论出处。
- **自主 agent 的代价**：成本高、错误会复合，必须"沙盒测试 + 护栏（guardrails）"，并在设计上保持透明——显式展示 agent 的规划步骤。
- **ACI（Agent-Computer Interface）与 HCI 同等重要**：工具文档要写到"给 junior developer 看"的详细度，含示例、边界情况、输入格式；用 Poka-yoke 设计让错误更难发生——SWE-bench 实例：相对路径导致错误，改为强制绝对路径后问题彻底消失。
- **三原则**：Simplicity（最小复杂度起步）、Transparency（暴露规划）、精心设计的 ACI。
- 编码 agent 之所以有效，是因为"输出可验证 + 迭代反馈 + 客观质量度量"——harness 要主动构造这三样，而不是指望模型。

## 2. How we built our multi-agent research system

URL: https://www.anthropic.com/engineering/built-multi-agent-research-system

- **Token 用量解释 80% 的性能方差**（工具调用次数 + 模型选择占 15%）；多 agent 用 ~15 倍于 chat 的 token，只对高价值、可重度并行、超单 context window 的任务划算——本地 harness 应对每个 change 做"复杂度→资源"路由。
- **显式教 orchestrator 委派**：每个 subagent 任务必须带明确目标、输出格式、工具使用指引、任务边界，否则子 agent 重复劳动或漏做。**按复杂度显式规则化投入**：简单查询 1 agent / 3-10 次工具调用；复杂任务才 10+ subagent 分工。
- **工具描述本身是杠杆**：改进工具描述使任务完成时间降低 40%；给 agent 明确启发式（先审视所有可用工具、匹配意图、偏好专用工具）。
- **评估方法**：LLM-as-judge 用单一 prompt 输出 0-1 分 + pass/fail 比多个专用评审器更一致；**~20 个代表性用例的小样本 eval 足以看出改动方向**，不必等大规模评测；对多轮改状态的 agent 做**端状态评估**（只看最终状态，允许替代路径）。
- **生产可靠性**：agent 是有状态长任务，错误不能从头重跑 → 需要从错误点恢复的 checkpoint；全面 tracing 才能诊断"为什么失败"；**rainbow deployment**（新旧版本并行、流量渐移）避免打断在跑的长任务——本地对应：改 harness prompt/契约时不要热改在跑的 run。
- **同步等待 subagent 是吞吐瓶颈但简化协调**；异步化要付出结果协调、状态一致性、跨 agent 错误传播的复杂度——先同步，量大再异步。
- 接近 context 上限时：总结工作阶段 → 存外部 memory → spawn 新 subagent 续跑，保持连续性。

## 3. Effective context engineering for AI agents

URL: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

- **Context 是有限的 attention budget**："context rot"——token 越多准确率越降（n² attention 的结构性约束）。harness 的第一设计变量就是每个角色的 context 预算。
- **System prompt 找"right altitude"**：既不要脆弱的硬编码 if-else，也不要含糊假设共享语境；用分节结构（`<background_information>`、`<instructions>`、tool guidance）。
- **Just-in-time 检索**：只在 context 里保留轻量标识符（文件路径、查询），用工具按需加载，而非预灌数据。
- **长任务三件套**：Compaction（压缩历史，保留架构决策与未解决问题、丢弃冗余输出）、**Structured note-taking**（agent 维护外部 memory/todo 文件，跨 context reset 持久）、**Sub-agent 架构**（专职 agent 干重活，只回传浓缩摘要给协调者）。
- 少而精的 canonical few-shot 示例优于穷举边界情况。

## 4. Writing effective tools for agents

URL: https://www.anthropic.com/engineering/writing-tools-for-agents

- **工具不是越多越好**：合并工作流级工具（`schedule_event` 内部处理查可用性；`search_logs` 只返回相关行而非 `read_logs` 全量）减少 context 消耗与策略混乱。
- **返回有意义的信号**：丢弃 UUID/MIME 等低信号字段；提供 `response_format: concise|detailed` 让 agent 选详略（实测 72 vs 206 tokens）。
- **Token 效率**：分页、过滤、截断 + 合理默认（Claude Code 默认工具响应上限 25k tokens）；截断时**明确告诉 agent 下一步怎么改进查询**；错误信息要给可执行建议而非错误码。
- **工具描述是最高性价比优化点**：像给新员工写说明；参数命名消歧（`user_id` 而非 `user`）；namespacing（`asana_projects_search`）帮助选对工具。
- **评估驱动迭代**：用真实多步任务（数十次工具调用）做 eval，把失败 transcript 喂给 Claude 让它重写工具描述——Claude 优化后的工具超过手写版本。

## 5. Building agents with the Claude Agent SDK

URL: https://claude.com/blog/building-agents-with-the-claude-agent-sdk

- **核心循环**：gather context → take action → **verify work** → repeat。verify 是循环的一等公民，不是收尾装饰。
- **Agentic search 优先于 semantic search**：用 grep/tail 等 bash 动态拉取比向量检索更透明、准确、易维护；只有速度成为瓶颈才加语义检索。
- **Subagent 的两个用途**：并行执行 + context 隔离（只把相关结论带回 orchestrator）。
- **Action 分层**：自定义 tools（高频核心动作，占据显要 context 位置）→ bash/脚本（通用胶水）→ 代码生成（复杂可复用的精确操作）→ MCP（标准化集成）。
- **三种 verify 手段按鲁棒性排序**：rules-based（lint 式，指出哪条规则为何失败——最鲁棒）> visual feedback（截图/渲染）> LLM-as-judge（模糊标准可用但最弱、有延迟）。
- Compaction 由 SDK 自动处理长任务的 context 增长。

## 6. Claude Code 官方文档：subagents / hooks / headless

URLs: https://code.claude.com/docs/en/sub-agents 、https://code.claude.com/docs/en/hooks-guide 、https://code.claude.com/docs/en/headless

- **Subagent 使用判据**："当一个旁支任务会用搜索结果/日志/文件内容淹没主对话，且之后不会再引用时"就该 subagent 化；反复 spawn 同类 worker 就该固化成定义。`description` 字段决定委派时机，要写清楚。
- **Subagent 是约束边界**：独立 context window + 独立 system prompt + `tools`/`disallowedTools` 白名单 + 独立权限 + `model`（廉价模型控成本）+ `maxTurns`/`effort`/`background`/`isolation`（worktree）都可按 agent 声明。
- **Hooks = 确定性护栏**：官方定性为"deterministic control——保证某些动作一定发生，而非依赖 LLM 选择去做"。exit 2 + stderr = 阻断并把原因回灌给 Claude；多 hook 并行时**最严格决定获胜**（deny > defer > ask > allow）；deny 规则永远压过 hook 的 allow。典型闸门：PreToolUse 拦保护文件/危险命令、PostToolUse 强制格式化、Stop/SubagentStop 收尾校验；判断型闸门可用 prompt-based / agent-based hooks。
- **Headless（`claude -p`）**：CI/脚本推荐 `--bare`（不读本机 hooks/MCP/CLAUDE.md，保证跨机器可复现）；`--output-format json`（含 session_id、`total_cost_usd`）+ `--json-schema` 拿结构化结果；`--allowedTools` 用前缀规则精确放权（`Bash(git diff *)` 注意空格）；`--resume <session_id>` 续会话（按项目目录 + worktree 范围查找）；stream-json 的 `system/api_retry` 事件可做重试可观测。

## 7. Effective harnesses for long-running agents

URL: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

- **四大失败模式**：过早宣布完成、把环境留在坏状态、一次批处理过多代码、验证不足——harness 的每个组件都应对位到一个失败模式。
- **两阶段架构**：Initializer agent（首个 session 专用 prompt）产出 `init.sh`（一键起 dev server）、`claude-progress.txt`（工作日志）、初始 git commit、**200+ 条结构化 JSON feature list（全部初始为 failing）**；Coding agent 每个 session 固定仪式：`pwd` 确认目录 → 读 git log + progress 文件 → 选最高优先级未完成项 → 起服务跑基础 e2e 冒烟 → **只实现一个 feature** → commit + 更新进度。
- **JSON 而非 Markdown 存 feature list**：模型更不容易不当篡改/覆盖 JSON；只允许改 `passes` 字段；用强禁令措辞（"不可接受移除或编辑测试/清单项"）。
- **Git commit 即 checkpoint**：描述性提交信息让模型可回滚坏代码、恢复工作状态。
- **Model self-report 不可信**：Claude 倾向于只凭代码或单测就标记完成——必须显式强制真实端到端验证（浏览器自动化走用户路径）。
- Feature 描述要写到步骤级（"点击'新聊天'→验证新会话创建→检查侧边栏"），让验证可执行。

## 8. Harness design for long-running application development

URL: https://www.anthropic.com/engineering/harness-design-long-running-apps

- **三 agent 分工**：Planner（把 1-4 句需求扩成完整 spec，管野心不管实现细节——细节错误会级联）、Generator（迭代实现 + 交接前自评 + git 可回滚）、Evaluator（独立验证）。
- **核心发现（review 闸门的最强论据）**："让 agent 评估自己产出时，它倾向于自信地夸赞——即使在人看来质量明显平庸。" 所以 evaluator 必须是独立 agent、独立 context。
- **Evaluator 主动验证而非静态审查**：用 Playwright 像用户一样点击真实运行的应用、截图、测 API 与数据库状态，把评估锚定在**可观察行为**上；明确评分标准 + 硬阈值（任一项低于线即 sprint 失败）。早期 evaluator 会"说服自己问题不大"，需 prompt 强制怀疑态度与边界测试。
- **Artifact 交接**：agent 间通过文件（sprint contract：generator 先提"要建什么+怎么验证"，evaluator 先审提案；progress 文件跨 session 传状态）而非共享对话。
- **Harness 应随模型进步做减法**："harness 里每个组件都编码了一个'模型自己做不到'的假设"——要定期测试脚手架是否仍然承重，否则变成技术债（Opus 4.5 需要显式 context reset 对抗"context anxiety"，Opus 4.6 已可连续多小时 + 自动 compaction）。
- **成本判断**：evaluator QA 让总成本涨 20 倍（$200），只在"任务处于 generator 独立能力边缘"时才划算。

## 9. Scaling managed agents: decoupling the brain from the hands

URL: https://www.anthropic.com/engineering/managed-agents

- **三层解耦**：Brain（模型+harness 循环）/ Hands（沙箱执行环境）/ Session（不可变事件日志）。耦合设计的问题：容器挂 = 会话全丢；凭证与生成代码同沙箱是弱安全边界。
- **Session 日志独立于 context window 存储**：harness 通过 `getEvents()` 灵活重建上下文（切片、回溯、缓存优化）；harness 崩溃无需持久状态，`wake(sessionId)` 从最后事件恢复。
- **沙箱是牲畜不是宠物**：沙箱故障被 harness 捕获为工具调用错误，交给 Claude 决定重试。
- 对老化脚手架的再次警告：旧模型的"context anxiety"处理逻辑在新模型下已是死代码。

---

## 对照清单：harness 设计准则

来源缩写：BEA=building effective agents，MAR=multi-agent research，CE=context engineering，WT=writing tools，SDK=Agent SDK blog，SUB/HK/HL=Claude Code docs（subagents/hooks/headless），LRA=long-running agents，HD=harness design apps，MA=managed agents

1. 能写成确定性代码的编排逻辑不要交给 LLM；从最简单方案起步，复杂度必须证明自己值回票价。[BEA]
2. 核心循环固定为 gather context → act → verify → repeat，verify 是一等公民。[SDK]
3. 永远不信 agent 对自己工作的自报——review/verify 必须由独立 context 的独立 agent 或确定性检查完成。[HD, LRA]
4. Verify 手段按鲁棒性优先：确定性规则检查 > 可观察行为验证（跑起来点/截图/查库） > LLM-as-judge。[SDK, HD]
5. 硬性护栏用 hooks（PreToolUse 拦截 + exit 2 回灌原因），不用 prompt 恳求；最严格决定获胜。[HK]
6. 每个 subagent 任务必须带：明确目标、输出格式、工具指引、任务边界。[MAR]
7. 按任务复杂度显式规则化资源投入（agent 数、工具调用预算、模型档位）；token 用量解释 80% 性能方差。[MAR]
8. Subagent 的价值 = 并行 + context 隔离：脏活在隔离窗口做，只回传浓缩结论。[SDK, SUB, CE]
9. 用 tools/disallowedTools/model/maxTurns/isolation 在 agent 定义层收紧权限与成本，而非靠 prompt。[SUB]
10. 每 session 一个 feature：小步实现、详细验证、commit、更新进度、干净收尾。[LRA]
11. 状态放外部 artifact（JSON feature list、progress 文件、git log），不放对话；机器可解析的 JSON 比 Markdown 抗篡改，且只允许改状态字段。[LRA, HD, CE]
12. Git commit 即 checkpoint：描述性信息，支持回滚与从错误点恢复，绝不从头重跑。[LRA, MAR]
13. Session 开始有固定仪式：确认目录 → 读进度/git log → 冒烟验证环境未坏 → 再动手。[LRA]
14. Feature/验收标准写到可执行步骤级，让 evaluator 可以照做。[LRA, HD]
15. Evaluator 用硬阈值评分（任一项不达标即失败），prompt 强制怀疑态度，防"说服自己问题不大"。[HD]
16. Context 是 attention budget：just-in-time 用工具按需取，不预灌；长任务靠 compaction + 外部笔记 + subagent 三件套。[CE]
17. 工具求少求整合：工作流级工具替代原子 API 堆叠；返回去噪（砍 UUID 类低信号字段）、分页截断带"下一步怎么查"的指引。[WT]
18. 工具描述当"给新员工的文档"写，是最高性价比优化点（实测 -40% 任务时长）；路径等参数用防呆设计（如强制绝对路径）。[WT, MAR, BEA]
19. CLI 底座用 `claude -p --bare` + `--output-format json`/`--json-schema` + 前缀式 `--allowedTools`，保证可复现、可解析、可控权限；用 session_id resume 续跑。[HL]
20. 用 ~20 个代表性任务的小 eval 快速迭代 harness；对改状态的 agent 做端状态评估，允许替代路径。[MAR]
21. 全程 tracing/telemetry：记录决策模式与工具调用结构，否则无法诊断失败。[MAR]
22. 改 harness 契约时不打断在跑的长任务（rainbow 式新旧并行渐移）。[MAR]
23. 执行环境当牲畜：沙箱/worktree 可丢弃可重建，故障降级为工具错误交模型重试；事件日志与执行环境解耦存储。[MA]
24. 先同步编排（简单、易协调），并行度成为瓶颈再异步化，并预算好异步的协调/一致性成本。[MAR]
25. 定期给 harness 做减法：每个脚手架组件都是"模型做不到 X"的假设，模型升级后要重测该假设是否仍承重。[HD, MA]
