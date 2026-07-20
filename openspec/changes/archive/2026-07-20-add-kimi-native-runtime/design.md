## Context

`add-codex-native-runtime` 已经建立并验证了"共享插件目录承载多个原生宿主"的四层结构：双 manifest、host-adapter skills、`runtime_host` 路由元数据、共享 provider-neutral hook。本 change 复用这套已验证结构，为 Kimi Code 增加第三个原生运行载体。

与 Codex 不同的两点前提，来自用户原始目标与本轮 pattern interrogation（见 `pattern-interrogation.md`）：

1. Kimi 声称原生提供与 Claude 语义等价的 `Agent(subagent_type=...)` / `AskUserQuestion` / todo 工具（Codex 没有同名工具，只能靠抽象层措辞映射）。这让 Kimi skill 的映射粒度理论上可以比 Codex skill 更"近恒等"——但 Kimi 是否允许插件声明自定义 `subagent_type` profile 未经验证，是本次的 Open Question #2（已由用户裁决为：仍采用与 Codex 相同的抽象层措辞，见下方 Pattern Mapping）。
2. Kimi 0.27.0 没有 shell 级插件安装命令（不同于 `codex plugin marketplace add`），文档层不能照抄 Codex 的安装步骤。

设计目标：新增 Kimi 路径必须是纯粹的宿主层扩展，且尽可能与 Codex 共享同一段泛化代码，而不是新增一份平行分支——两个宿主的路由判定应该收敛到同一个参数化条件（`runtime_host` 与 `backend` 的关系），只有 skill 文本、hook 传参方式、文档三处允许因为宿主 primitive 差异而分叉。

## Verified Platform Facts (Kimi Code 0.27.0)

本轮 fix 针对 F4（"核心 Kimi 原生发现契约被延迟到实施时验证"），在本机 `~/.kimi-code/bin/kimi`（`kimi --version` → `0.27.0`）上做了直接验证：对该 Mach-O 二进制跑 `strings -a` 并搜索 manifest/hook/skill 相关的 schema 常量与函数体（zod schema 定义、`readHooks`/`resolveSkillsField`/`parseManifest` 等函数源码片段），这是确定性、可重复的技术（同一二进制、同一命令，任何人可重跑复核），不是猜测或官方文档转述。核心结论，逐条替换此前 pattern-interrogation Assumptions 里"未验证的第三方约定"的状态：

1. **manifest 路径**：Kimi 同时支持根级 `kimi.plugin.json`（`kimi-plugin-root`，优先）与目录级 `.kimi-plugin/plugin.json`（`kimi-plugin-dir`，两者都存在时目录级被 shadow）。D1 采用的 `.kimi-plugin/plugin.json` 是受支持的合法约定——**已验证，非假设**。
2. **manifest 字段集**：实际 zod 解析出的字段是 `name`（必填，须匹配 `/^[a-z0-9][a-z0-9_-]{0,63}$/`，`agent-spine` 合规）、`version`/`description`/`keywords`/`homepage`/`license`/`author`/`skills`/`sessionStart`/`mcpServers`/`hooks`/`commands`/`interface`（仅读 `displayName`/`shortDescription`/`longDescription`/`developerName`/`websiteURL` 五个子字段）/`skillInstructions`。`.codex-plugin/plugin.json` 里的 `interface.capabilities`/`interface.category`/`interface.defaultPrompt` 不在这五个子字段内——Kimi 会静默忽略，不报错也不产生 diagnostic（`recordUnsupportedRuntimeFields` 只检查顶层字段，不检查 `interface` 内部），因此"字段集同构"在 Kimi 侧是"允许多余字段、按需只读它认的那五个"，不是逐字段等价。
3. **`skills` 字段**：路径需以 `"./"` 开头、必须解析到一个目录；Kimi 的 skill 发现约定与 Claude/Codex 相同——扫描目录找 `SKILL.md`（`isDirectorySkill`/`directorySkills` 逻辑与 Claude 侧同名概念一致）。`"./skills/"` 复用同一目录——**已验证，非假设**。
4. **`${KIMI_PLUGIN_ROOT}` 环境变量**：确认存在，且由 Kimi 自身在执行任意 plugin-manifest 声明的 hook 时自动注入（`enabledHooks()`：对每条 `manifest.hooks` 追加 `cwd: record.root, env: {KIMI_CODE_HOME, KIMI_PLUGIN_ROOT: record.root}`）——**已验证，非假设**；不需要用户或本插件自己想办法传这个变量，Kimi 运行时保证会给。
5. **关键修正（推翻此前假设）：Kimi 的 hook 不是通过独立的 `hooks/hooks.json` 文件发现的**。`enabledHooks()` 只读 `record.manifest.hooks`——即 hook 必须作为 `.kimi-plugin/plugin.json` 自身的 `"hooks"` 数组字段声明，每条形状固定为 `{event, matcher?, command, timeout?}`（zod `.strict()`，不接受 Claude/Codex 那种 `{"hooks": {"SessionStart": [{"hooks": [{"type": "command", ...}]}]}}` 分组结构，也没有 per-hook 的 `env` 字段可声明——env 由 Kimi 统一注入,不可覆盖)。这意味着"扩展 `plugins/agent-spine/hooks/hooks.json` 的 `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 两级兜底链为三级、纳入 `${KIMI_PLUGIN_ROOT}`"这条此前的计划是**基于错误前提的死代码**——Kimi 从不读这个文件，扩展它的兜底链对 Kimi 场景没有任何效果。D5 已按此修正重写。
6. **`SessionStart`/`SubagentStop` 事件名与 payload 形状**：`HOOK_EVENT_TYPES` 枚举确认含 `"SessionStart"`/`"SubagentStop"`（与既有 `hooks.json` 用的事件名字面量相同，无需改名）。但 payload 内容与假设不同——`triggerSessionStart(source)` 只传 `{source}`（外加公共 `session_id`/`cwd`），**从不携带 transcript 相关字段**；`triggerSubagentStop(parent, profileName, result)` 传 `{agent_name: profileName, response: result片段}`（`camelToSnake` 转换后），**不含 `last_assistant_message`**。前者证实 pattern-interrogation Open Question #1 的顾虑是必然发生（不是"可能发生"）：Kimi 的 SessionStart payload 结构性地永远没有 `transcript_path`，"部分索引"降级路径对 Kimi 是常态而非边缘情况。后者证实 spec.md"Kimi stop payload omits Claude message field" Scenario 的假设成立——**均已验证**。
7. **`Agent(subagent_type=...)` 自定义 profile（Open Question #2）**：manifest 字段列表里没有 `agents`/`subagents`/`profiles` 之类的字段，sub-agent profile 由 `DEFAULT_AGENT_PROFILES`（代码内建、`loadAgentProfilesFromSources` 加载）决定，插件无法注册自定义 `subagent_type`。**结论确定**：用户裁决 #2（抽象层措辞，与 Codex skill 同构）是唯一可行路径，不是权宜之计——已验证，非假设。
8. **无 shell 级插件安装命令、但有 `/plugins` 会话内命令**：`kimi --help` 顶层不含任何 `plugin` 子命令；`/plugins: manage plugins` 作为会话内命令字符串存在于二进制里。与 D6"通过 Kimi 自身插件管理机制启用本地/git 插件源"的描述一致——**已验证，非假设**。

9. **`Agent` 工具的实际 `subagent_type` 取值与内置 profile 集合（round-2 F2 复核）**：对同一二进制继续 `strings -a` 检索确认：`DEFAULT_AGENT_PROFILES` 只从 `profile/default/{agent,coder,explore,plan}.yaml` 四个内建文件加载（`loadAgentProfilesFromSources(["agent.yaml","coder.yaml","explore.yaml","plan.yaml"].map(...))`），不存在名为 `spine-coder` 的内建 profile，也没有任何插件声明式注册路径（复核并强化第 7 条结论）。`Agent` 工具调度子代理时,若调用方未显式传 `subagent_type`,运行时取默认值 `"coder"`（`let profileName = args.subagent_type?.length ? args.subagent_type : "coder"`；swarm 路径的同义常量是 `DEFAULT_SUBAGENT_TYPE$1 = "coder"`）；`triggerSubagentStop(parent, profileName, result)` 把这个 `profileName` 原样写进 SubagentStop 事件的 `matcherValue`/`agentName`（`agent_name: profileName`）。**结论**：Kimi 侧唯一可确定性匹配的 sub-agent 标识字符串是 `"coder"`，不是 `"spine-coder"`（那是 Claude 专属 `agents/spine-coder.md` 的注册名，Kimi 从不存在同名 profile）；`.kimi-plugin/plugin.json` 自带的 `SubagentStop` hook 声明的 `matcher` 字段必须写 `"coder"`，否则该 hook 在 Kimi 下永远不会被触发——Kimi 按 `matcherValue` 精确匹配才调用对应 command，不是 Claude/Codex 那种"宽松触发 + 脚本内部按 payload 字段 fail-open"的语义,写错 matcher 意味着整条 hook 静默失效而非降级——已验证，非假设。

以上 9 条中，1/3/4/6/7/8/9 直接消解了 pattern-interrogation 里标记为"未验证的第三方约定"的假设；2/5 是新发现的、此前设计未预料到的修正点，已同步进 D1/D5 与 tasks.md；9 是本轮（round 2）针对 F2 finding 新增的复核项,直接推翻了 D1 段落此前"直接写 `Agent subagent_type=spine-coder`"的措辞，并纠正 D5 hooks matcher 示例（下方已同步重写）。

## Goals / Non-Goals

**Goals:**

- 同一插件目录可被 Claude Code、Codex、Kimi 三种宿主原生发现。
- Kimi skills 复用现有三份 command workflow，并只做宿主 primitive 映射；不新建 Kimi 专属 skills 子目录。
- run 持久化宿主身份支持 `kimi`；旧 run 和普通 init 保持 Claude 语义，Codex 语义逐项不变。
- Kimi runtime 的默认 in-session coder/spec writer 是 Kimi；其 LLM review 强制路由到 Claude。
- 路由约束（"生成者非 Claude 时默认 Claude review""同源拒绝""spec writer 宿主不匹配拒绝"）由同一段参数化 Python 代码同时覆盖 Codex 与 Kimi，不复制分支。
- `review.engine` 白名单不因 Kimi 扩展；显式 `--engine kimi` 必须报错而不是被静默接受，并有回归测试覆盖这条结构性保证。
- Kimi SessionStart 能复用现有 session cache；共享 SubagentStop hook 不因 payload 差异误阻断 Kimi sub-agent。

**Non-Goals:**

- 不改写 Claude commands、state machine、gate、telemetry 或 archive 逻辑。
- 不实现 Kimi headless coder；Kimi 原生路径使用宿主内 agent，与 Codex 现状一致。
- 不自动写用户全局配置，也不改造 qlj hub 或任何跨仓库插件注册机制。
- 不把 Kimi skill 做成第二份独立 workflow 真相源，也不把 Codex skill 现有文本改写成不兼容的新结构。

## Decisions

**D1：同一 plugin root，三重 manifest，同一份 skill 文件内并存两套 host-adapter 映射表。**

在现有插件根增加 `.kimi-plugin/plugin.json`，顶层字段与 `.codex-plugin/plugin.json` 尽量对齐（`"skills": "./skills/"`、`interface.displayName/shortDescription/longDescription/developerName`），只替换名称/描述里的宿主标识。按"Verified Platform Facts"第 2 条，Kimi 只读 `interface` 下的五个子字段，`capabilities`/`category`/`defaultPrompt` 等 Codex 专属子字段可以原样保留在文件里（Kimi 静默忽略，不产生 diagnostic），不需要为了"字段集同构"删掉它们，也不需要额外为 Kimi 补一套等价子字段。**新增**：`.kimi-plugin/plugin.json` 还需声明自己的 `"hooks"` 数组字段（D5 展开），这是 Kimi 侧 hook 发现的唯一入口，Codex/Claude manifest 不需要对应字段。

现有 `skills/spine-{run,spec,analyze}/SKILL.md` 三个文件**不复制成 Kimi 专属子目录**，而是在原文件内新增一段独立的"Kimi host adapter"映射表，与既有"Codex host adapter"映射表并列（各自独立小节，标题分别标注宿主名）。两个宿主的 manifest 都指向同一份物理文件；`tests/test_codex_plugin.py` 现有的子串断言（如 `--runtime-host codex` 在文件中出现）不受影响，因为新增的 Kimi 段落是追加内容，不删除或改写既有 Codex 段落。

Kimi 映射表与 Codex 版本共享同一套"启动隔离 sub-agent 并传 prompt + `.prompt_file` 契约驱动其行为"的抽象层措辞（用户裁决 #2 的直接结果），只替换 `--runtime-host codex` → `--runtime-host kimi`。**不写** `Agent subagent_type=spine-coder`（round-2 F2 修复：此前措辞在"抽象层措辞"结论已定的前提下仍保留了字面 `subagent_type=spine-coder` 提法，自相矛盾，且 `spine-coder` 在 Kimi 侧不是任何合法取值）——按 Verified Platform Facts 第 9 条，Kimi 没有 `spine-coder` 这个内建或可注册的 profile，唯一可确定性匹配的默认子代理标识是内建 `"coder"` profile；Kimi 映射表改为显式指出"调用 `Agent` 工具时不传 `subagent_type`（或显式传 `subagent_type="coder"`），依赖 Kimi 内置默认 profile，不假设存在一个名为 `spine-coder` 的自定义 profile"。若未来 Kimi 支持声明式自定义 profile，可作为独立自然增强改写措辞，不影响本 change 正确性。

**F1 修复（round-2 新增，SKILL.md 宿主选择契约）**：同一份 `SKILL.md` 内并列 Codex/Kimi 两套映射表这件事本身不产生歧义的前提，是文件必须显式声明一条**确定性的宿主选择规则**，而不是依赖宿主"隐式知道该看哪段"。三个 SKILL.md 文件在两套 host-adapter 表**之前**统一新增一条与既有编号列表同级的规则（既有列表现为"1. Read.../2. Follow.../3. Apply only..."，新增为第 4 条）：

> 4. This file may contain host-adapter mapping tables for more than one host (each headed `### <Host> host adapter mapping`). Identify your own host identity from your own runtime context (you already know whether you are Claude Code, Codex, or Kimi Code — this file does not tell you). Apply only the mapping table headed with your host's name. MUST NOT read, follow, or otherwise apply any mapping table headed with a different host's name, even when both tables are present in the same file.

同时把现有单一的 `## Host mappings` 标题改造为按宿主命名的三级标题：现有 Codex 段落的标题改为 `### Codex host adapter mapping`，新增并列的 `### Kimi host adapter mapping`；两者仍共享同一个上级 `## Host mappings` 小节。这样"哪一段属于哪个宿主"从标题文本本身就能被字符串匹配工具确定性地界定边界，不只是散文描述。对应的确定性测试（tasks.md 3.3）：分别提取 `### Codex host adapter mapping` 到下一个 `###` 标题（或文件尾）之间的字节区间，与 `### Kimi host adapter mapping` 的字节区间，断言 Codex 区间内不出现 `--runtime-host kimi` 字面串、Kimi 区间内不出现 `--runtime-host codex` 字面串，且上述第 4 条选择规则的字面文本存在于两套映射表之前的公共段落。这把"避免交叉引用"从散文承诺变成可 grep 复核的边界测试，解决 F1 指出的"字面子串测试无法证明运行时选择无歧义"问题。

备选是新建 `skills-kimi/spine-*/SKILL.md` 平行目录；放弃，因为 pattern interrogation 的 Assumptions 明确要求复用同一份 `skills/*/SKILL.md`，且两份平行目录会在后续 command workflow 变更时需要三处（Codex/Kimi/未来宿主）同步维护映射表用语，只是把"双写"问题从 command 正文转移到 skill 正文。

**D2：run.json `runtime_host` 白名单加入 `kimi`，四处硬编码同步扩展。**

`npc init --runtime-host kimi` 把 `runtime_host=kimi` 写入 run metadata。CLI 不传、环境变量兼容路径、旧 run.json 缺字段时均仍解析为 `claude`。四处需要同步扩展白名单的确定性落点见 tasks.md（`grep`/`rg` 命令 + 命中数）：`src/npc/paths.py` 两处（`runtime_host_raw not in (...)` 与 `NPC_RUNTIME_HOST` 环境变量兼容路径）、`src/npc/cli.py` 一处（`--runtime-host` 的 `choices`）。`--backend`/`--engine` 的 CLI choices 里，只有 coder backend（`implement run` / `fix run` 的 `--backend`）需要加 `kimi`；review engine（`review run` / `spec review run` 的 `--engine`）**不加**，因为 `SUPPORTED_ENGINES` 恒为二值。

**D3：coder dispatch 的"未配置默认 in-session"判定泛化为参数化条件，Kimi headless 与 Codex 一致地显式未实现。**

`src/npc/config.py`：`SUPPORTED_CODER_BACKENDS` 加入 `"kimi"`；`DISPATCH_DEFAULTS` 补 `"kimi": "headless"` 基线项（与 `codex` 相同，未走 runtime-match 覆盖时的兜底默认）。

`src/npc/coder.py::resolve_dispatch`：`default_override` 的判定条件从字面量 `runtime_host == "codex" and backend == "codex"` 改写为参数化的 `runtime_host == backend and backend != "claude"`——同一行代码同时覆盖 Codex 与 Kimi 的"未配置默认 in-session"语义，不新增分支。`resolve_backend` 已经是完全通用实现（`cfg.coder.backend_for_phase(phase) or runtime_host`），不需要改。

`src/npc/coder.py::_run_backend`：现有 `if backend == "codex": raise NotImplementedError(...)` 分支扩展为 `if backend in ("codex", "kimi"): raise NotImplementedError(...)`（消息按实际 backend 参数化），保持"显式选择 headless Kimi coder"这条路径明确报错而非落到末尾的"未知 coder backend"通用错误（那条消息语义上是错的——`kimi` 是已知 backend，只是 headless 路径未实现）。

备选是让 Kimi 与 Codex 共享同一个 headless 未实现分支但保留 `backend == "codex"` 单独判断、Kimi 走 `raise ValueError` 兜底；放弃，因为会把"未知 backend"和"已知但未实现"两种语义混淆，且违反"同一段代码同时覆盖两个宿主"的设计目标。

**D4：实际生成身份进入 phase/spec routing 的判定泛化为"非 Claude 生成"，不含 MiMo。**

`src/npc/pipeline.py`：`default_engine = "claude" if generator_backend == "codex" else review_cfg.engine` 改写为 `generator_backend in ("codex", "kimi")`——显式排除 `mimo`（MiMo 生成不强制 Claude review，其现有的"MiMo 只许执行"路由不变量已经独立保证 MiMo 不会被自己评审，这条判定不应因泛化而意外扩大到 MiMo 场景）。

`src/npc/spec_pipeline.py::_effective_spec_routing` / `_spec_routing_violations`：`writer_backend = "codex" if p.runtime_host == "codex" else ...`、`default_engine` 的 Codex 判定、以及 `spec_writer_host_mismatch` 的 `p.runtime_host == "codex" and explicit_writer != "codex"` 三处，全部从字面量 `"codex"` 改写为参数化 `p.runtime_host != "claude"` / `explicit_writer != p.runtime_host`——同一份代码同时覆盖 Codex 与 Kimi，且为未来任何新增 `runtime_host` 值自动生效，不需要逐个宿主再改一次。

`src/npc/verify.py::check_routing` 的 `both_codex = effective_backend == "codex" and review.engine == "codex"` **不需要新增 `both_kimi`**：`review.engine` 恒在 `("codex", "claude")` 取值（D5 之外的既有不变量），Kimi 从未进入这个校验范围，`review.engine == "kimi"` 在正常路径下结构性不可达。这是与 Codex 的关键差异点——不是遗漏，而是显式记录为不需要修改。

作为这条"结构性不可达"保证的回归面（对应用户裁决 #3），新增测试直接调用 `pipeline.run_review_round(..., engine_name="kimi")` 与 `spec_pipeline.spec_review_run(..., engine_name="kimi")`，断言两者都抛出既有的 `ValueError("未知 review engine：'kimi'...")` / `ValueError("未知 spec_review engine：'kimi'...")`，而不是被静默接受或产生模糊的 routing violation。这条校验逻辑本身**不需要新代码**——`engine_name not in ("codex", "claude")` 的判定早已覆盖任意非法值；新增的是显式断言 `kimi` 属于该非法值集合的测试，防止将来有人把 `kimi` 加进 `SUPPORTED_ENGINES` 时漏掉同源守卫。

**F1 修复（新增判定，不是对既有代码的参数化改写）**：`both_codex`／同源拒绝只堵住"engine 字面等于 generator backend"这一种情形；Kimi 从不是合法的 `review.engine` 取值，所以这条同源拒绝逻辑对 Kimi**永远不可达**——如果止步于此，显式 `--engine codex` 配合 Kimi 生成的产物会绕开"MUST 路由到 Claude"（既不同源、也不在白名单拒绝范围内，会被当作合法的 Codex review 正常执行），这正是 F1 指出的矛盾。修复方式：在 `check_routing`／spec 侧同构函数里各新增一条独立判定 `kimi_review_not_claude`（`effective_backend == "kimi" and review.engine != "claude"`）与 `spec_kimi_review_not_claude`（`spec_writer.effective_backend(override) == "kimi" and spec_review.engine != "claude"`），命中即 violation。这条判定与 `both_codex` 并列、不复用同一变量名，因为语义不同——`both_codex` 是"同源"闭环（generator 与 engine 字面相等才拒绝），这条新判定是"来源为 Kimi 时任何非 Claude engine 都拒绝"的更严格闭环（因为 Kimi 永远不会出现在 `review.engine` 里，"同源"这个概念对 Kimi 不成立，必须直接按 generator 身份判定）。`review.engine` 的 `("codex", "claude")` 白名单本身不变——这条新判定和"是否新增 `kimi` 到 `SUPPORTED_ENGINES`"是两件独立的事。

**D5（按 F2/F3/F4 验证结果重写）：Kimi 的 hook 通过 `.kimi-plugin/plugin.json` 自身的 `hooks` 数组声明并显式传参识别宿主，不触碰 `hooks/hooks.json`；session 探测对缺 transcript_path 的部分索引做"视为无条目"处理，不在 `detect_via_hook` 内部调用 mtime。**

按"Verified Platform Facts"第 5 条，Kimi 从不读取 `plugins/agent-spine/hooks/hooks.json`——该文件是 Claude/Codex 专属的发现约定,继续保持现状,**不做任何改动**（`${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` 两级兜底链维持原样,不扩展第三级）。此前"扩展为三级、纳入 `${KIMI_PLUGIN_ROOT}`"的计划基于一个已被推翻的假设,本轮撤销。

**唯一、可执行的传输契约**（解决 F2 的"三份 artifact 各说各话"）：`.kimi-plugin/plugin.json` 新增一个 Kimi 专属的 `"hooks"` 数组字段（manifest 自带的 hook 声明,`{event, matcher?, command, timeout?}`,Kimi 运行时自动为其注入 `KIMI_PLUGIN_ROOT`/`KIMI_CODE_HOME` 环境变量与 `cwd=插件根`，见 Verified Platform Facts 第 4/5 条）：

```json
{
  "hooks": [
    { "event": "SessionStart", "command": "bash \"$KIMI_PLUGIN_ROOT/hooks/index-session.sh\" --runtime-host kimi", "timeout": 10 },
    { "event": "SubagentStop", "matcher": "coder", "command": "bash \"$KIMI_PLUGIN_ROOT/hooks/verify-subagent-result.sh\"", "timeout": 15 }
  ]
}
```

`SubagentStop` 的 `matcher` 字段写 `"coder"` 而不是 `"spine-coder"`（round-2 F2 修复）：按 Verified Platform Facts 第 9 条，`"coder"` 是 `Agent` 工具未显式传 `subagent_type` 时的内置默认 profile 名，也是 Kimi 运行时实际写入 SubagentStop 事件 `matcherValue` 的字符串；`"spine-coder"` 在 Kimi 侧不对应任何真实 profile，若沿用会导致 Kimi 按 `matcherValue` 精确匹配 `matcher` 字段时永远匹配不上，该 hook 在 Kimi 下静默永不触发（不是降级，是完全失效）。

因为这个 `hooks` 数组只存在于 Kimi 专属的 manifest 里（Claude/Codex 的插件加载器根本不解析这个字段，物理上不可能被其他宿主复用/共享），`--runtime-host kimi` 可以直接硬编码在 command 字符串里，不需要任何 shell 条件展开或环境变量猜测技巧——这就是"唯一、可执行的传输契约"：**显式 CLI 参数，来源于宿主专属的 manifest 声明，优先级最高**。`index-session.sh`（同一份物理脚本，Claude/Codex/Kimi 共享，只是被不同的声明方式调用）新增对 `--runtime-host <value>` 位置参数的解析：

- 优先级 1：命令行显式 `--runtime-host <value>`（目前只有 Kimi 的 manifest hook 声明会传；Claude/Codex 的 `hooks/hooks.json` 调用不传，保持现状不变）。
- 优先级 2（无显式参数时）：既有的 `data.get("source")` 字符串含 `"codex"` 猜测（向后兼容，不删除，不改变 Codex 现有安装的行为）。
- 优先级 3（以上都未命中时）：`data.get("runtime_host")` 直通payload 自带字段（历史兜底，保留但不再是本 change 依赖的主路径）。
- 均未命中：不写入该字段（沿用 `None`），下游按既有约定解释为 `claude`。

`plugins/agent-spine/hooks/index-session.sh` 的第二处改动（解决 F3 的必要前提）：**放宽字段校验**——按 Verified Platform Facts 第 6 条，Kimi 的 `SessionStart` payload 结构性地永远不带 `transcript_path`（`triggerSessionStart` 只传 `{source}` + 公共 `session_id`/`cwd`），现有脚本第 18 行 `if not all(... for v in (cwd, session_id, transcript_path)): raise ValueError(...)` 会让这种 payload 直接被最外层 `except Exception: pass` 吞掉、完全不写缓存行——不是"降级为部分索引"，是"整条记录消失"。修复：必需字段收窄为 `cwd`/`session_id`；`transcript_path` 缺失时写入空字符串 `""`（不是省略键，保证下游按同一 schema 读取）。

`src/npc/session.py::detect_via_hook` 的修复（解决 F3 的"回退到已经跑过的 mtime"这句失实描述）：既有 `detect_session` 调用顺序是先 `detect_via_mtime`、后 `detect_via_hook`（Claude 优先 mtime 这条来自 `add-codex-native-runtime` 的既有约束保持不变，不改变探测顺序、不新增第三条路径）。因此"hook 返回空之后回落到 mtime"在当前调用序列下不成立——mtime 已经在 hook 被调用之前跑过并失败了。**修正后的准确语义**：`detect_via_hook` 对 `transcript_path` 为空/缺失的缓存条目，与"该 cwd 在 by-cwd cache 里完全没有条目"一视同仁，直接 `return None`（不新增数据结构、不新增分支，只是把既有的 `if not sid or not tx: return None` 判断保留原样——这一行代码本身不需要改，需要改的是它上游的 `index-session.sh` 不能再让这种 payload 整条丢失）；`detect_via_hook` **不**在内部调用 `detect_via_mtime`（保持 hook-only 职责边界，避免 F3 指出的"detect_via_hook 自身回退 mtime"这种职责混淆）。整体结果：`detect_session` 未变，其行为完全由"mtime 是否已经命中"决定——命中则 hook 分支不会被调用；未命中且 hook 因为空/缺失条目返回 `None`，则结果是既有的 `("-", "-", "unknown")`，不算失败（调用方已有的"探测不到就继续、不阻断 init"语义不变）。这条修正只影响 Scenario 措辞与 `index-session.sh` 的字段校验，不改变 `detect_session`/`detect_via_hook` 的既有调用顺序或返回类型。

现有 SubagentStop 校验（`verify-subagent-result.sh`）已经对 payload 缺 `last_assistant_message` fail-open（`exit 0`）；Kimi stop payload（`{agent_name, response}`，已按 Verified Platform Facts 第 6 条核实不含 `last_assistant_message`）复用这条既有机制，不需要新增 Kimi 专属分支。最终 RESULT 仍由 `npc ... record` 的确定性 schema、commit 和 test gate 校验（沿用 Codex D5 的核心 trade-off：共享 hook 只做兼容性放行，真相源在 `npc record`）。

备选是完全移除 `source` 字符串猜测，只认显式参数；放弃，因为会破坏尚未升级 hooks.json 声明的既存 Codex 安装（向后兼容优先于代码整洁）。

**D6：权限通过文档声明，不写机器专属配置；Kimi 无 shell 级安装命令,文档改写安装步骤而非照抄 Codex 命令。**

Kimi 安装说明要求为 `~/.spine/worktrees` 与 `~/task_log` 提供 scoped write access，与 Codex 相同。但 Kimi 0.27.0 没有类似 `codex plugin marketplace add` / `codex plugin add` 的 shell 命令，文档层描述"通过 Kimi Code 自身的插件管理机制启用本地/git 插件源"（不给出确切命令，因为不存在），并注明这是与 Codex 文档段落的关键差异点。插件本身不修改任何 Kimi 全局配置文件。

## Risks / Trade-offs

- **[Kimi sub-agent API 是否支持自定义 profile，Open Question #2]** → 已按"Verified Platform Facts"第 7 条核实：manifest 无 `agents`/`subagents` 字段，profile 由内建 `DEFAULT_AGENT_PROFILES` 决定，插件不可声明——不再是未验证假设，用户裁决的抽象层措辞是唯一可行路径（不是权宜选择）。若未来 Kimi 版本增加插件声明式 profile 字段，属独立的自然增强，不影响本 change 正确性。
- **[Kimi SessionStart payload 是否含 transcript_path，Open Question #1]** → 已按"Verified Platform Facts"第 6 条核实：`triggerSessionStart` 只传 `{source}` + 公共字段，**结构性地永远不含** `transcript_path`（不是"可能不含"）。这意味着"部分索引降级"对 Kimi 是必经的常态路径，不是边缘 case——`index-session.sh` 必须放宽字段校验才能让 Kimi 的 SessionStart 写入任何缓存行（D5），否则整条记录会被现有 `except Exception: pass` 静默吞掉。
- **[hook 声明机制三宿主不同源]** → Kimi 的 hook 声明在 `.kimi-plugin/plugin.json` 自身的 `hooks` 字段（manifest-embedded），Claude/Codex 的 hook 声明在共享的 `hooks/hooks.json`（目录发现）；两者物理隔离、互不可见，因此 Kimi 侧新增 `--runtime-host kimi` 显式参数不会影响、也不需要触碰 Claude/Codex 现有的 `hooks.json` 声明。SessionStart 仅追加 cache、检测失败退出 0；SubagentStop 只对已知完整 payload 保持原硬校验，Kimi/Codex 缺字段均 fail-open，最终真相源在 `npc record`。
- **[review.engine 白名单不含 kimi，同源拒绝的"防御性测试"是新增测试而非新增运行时代码]** → 按用户裁决 #3，显式测试断言 `--engine kimi` 报错，把这条结构性保证纳入回归面；若未来 `kimi` 被加入 `SUPPORTED_ENGINES`，这条测试会先失败，提醒同步补齐同源守卫。
- **[Kimi 0.27.0 无 shell 级插件安装命令]** → 文档层用"通过 Kimi 自身插件管理机制"这一较模糊但准确的描述，不编造不存在的 CLI 命令；用户目标已明确排除 qlj hub 改造。
- **[旧 state 没有 generator backend]** → review 回退到既有 config 解析，历史行为不变；新 coder phase 均写入真实 backend（Kimi/Codex 同构）。
- **[Claude CLI 不可用或执行失败，round-2 F4 修复]** → 此前设计只在本节以一句话承诺"不降级为自审"，spec.md 未落地对应 Scenario、tasks.md 未落地对应回归测试，属于 F4 指出的缺口。修复：`review.engine` 解析到 `claude`（无论是 Kimi 默认路由还是显式配置）后，Claude 二进制缺失走既有 `_find_claude_bin` 抛出并在 CLI 层被捕获为 `dependency_missing`（`exit_code=4`，`src/npc/pipeline.py:1905/1908`、`src/npc/spec_pipeline.py:1054/1391`）；Claude 进程执行失败走既有 `<engine>-exec-failed`（如 `claude-exec-failed`，`src/npc/pipeline.py` 现有 `test_run_review_round_claude_fails_then_retry_fails` 已验证该路径存在，仅未针对 Kimi 生成场景断言）。这两条路径都是**已存在**的通用错误处理（不因 Kimi 新增代码），只是从未被证明"Kimi 作为生成者触发默认 Claude 路由后走到这两条路径时，不会被任何新增的 Kimi 泛化判定意外绕过或降级"。新增 spec.md Scenario（见 `specs/kimi-native-runtime/spec.md` "Kimi generation is reviewed by Claude" Requirement）与 tasks.md 2.8 的确定性回归测试，直接对 `generator_backend="kimi"` 场景验证这两条既有错误路径可达、且不会静默降级为 Codex/Kimi 自审。

## Migration Plan

1. 发布包含三重 manifest/skills 与 runtime metadata 扩展的插件版本。
2. 旧安装继续通过 `.claude-plugin` 或 `.codex-plugin` 工作；旧 run.json 自动按 `runtime_host=claude` 读取，不受影响。
3. Kimi 用户通过 Kimi 自身插件管理机制启用本地/git 插件源，并按文档授予两个外置目录权限。
4. 回滚时移除 `.kimi-plugin/plugin.json`（含其自带的 `hooks` 数组，不影响 `hooks/hooks.json`——该文件本轮未改动）、还原 SKILL.md 里追加的 Kimi 段落、还原四处白名单泛化即可；新增 run.json `runtime_host=kimi` 值会被旧版本当作未知字段/未知取值降级为 `claude`（现有 `not in (...)` 白名单判定天然兜底）。

## Pattern Mapping

以下 `## Open Questions` 与 `## User Decisions (Interactive)` 段落原样复制自本 change 的 `pattern-interrogation.md`（该文件含 `## User Decisions (Interactive)` 标题，按契约把两段原样带入本节）：

### Open Questions

- Kimi SubagentStop（或等价 stop 事件）payload 是否包含 `transcript_path` 字段？若包含，`hooks/index-session.sh` 的 SessionStart 索引路径可以直接复用现有 by-cwd cache 写入逻辑；若不包含，`npc` 侧的 session 探测（`src/npc/session.py::detect_via_hook`）在 Kimi runtime 下应该走什么降级路径——是完全跳过 hook cache 只靠 mtime 探测，还是需要一种"部分索引"（无 transcript_path 但仍记录 session_id/cwd）的中间态？
- Kimi 的 `Agent(subagent_type=...)` 工具是否允许插件/skill 声明自定义 subagent_type 配置文件（类似 Claude `agents/spine-coder.md` 的 frontmatter 注册机制），还是只能调度 Kimi 内置的通用 sub-agent 类型？若只能用内置类型，Kimi skill 的"近恒等映射"实际上要退化为"用默认 coder sub-agent + `.prompt_file` 契约驱动其行为"，这与 Codex skill 当前采用的抽象层措辞趋同，需要在 design.md 里明确两种情况各自的 SKILL.md 措辞与测试断言差异。
- `check_routing`（`src/npc/verify.py`）里"显式同源 review 被拒绝"这条针对 Codex 的判定（`both_codex`）依赖 `review.engine == "codex"` 可达；由于 Kimi 从不进入 `SUPPORTED_ENGINES`，对应的 "Explicit same-source review is rejected" 场景（对照 codex spec 的同名 Scenario）在 Kimi 侧是否应该：(a) 直接不写这条 Scenario（因为 CLI/pipeline 层的 engine 白名单校验已经结构性拒绝，属于既有行为的自然推论，不需要新测试）；还是 (b) 仍然显式写一条 Scenario + 一个防御性测试，断言"传 `--engine kimi` 时报 `未知 review engine` 而不是被静默接受"，把这个结构性保证也纳入回归面？
- `plugins/agent-spine/hooks/index-session.sh` 第 32 行按 `data.get("source")` 字符串猜测 `"codex"`；Kimi 的 SessionStart payload 里对应字段的取值约定是什么（是否也叫 `source`，取值是否含 `"kimi"` 子串）？还是应该改成更通用的机制——例如让各宿主的 hooks.json 条目显式传一个 `runtime_host` 环境变量或 CLI 参数给 `index-session.sh`，不再靠猜测字符串？

### User Decisions (Interactive)

以下为交互档用户对 4 条开放问题的裁决：

1. **transcript_path 缺失时的 session 探测降级路径** → 采用**部分索引中间态**：SessionStart hook 仍写入 session_id/cwd（transcript_path 缺省为空），`detect_via_hook` 对空 transcript_path 条目跳过、自然回落 mtime 探测——索引数据不丢，实现改动最小。
2. **Kimi 不支持插件自定义 subagent_type profile 时的 SKILL.md 措辞** → 采用**抽象层措辞**，与 Codex skill 同构：只依赖'启动隔离 sub-agent 并传 prompt'这一抽象，用默认 coder sub-agent + .prompt_file 契约；若 Kimi 将来支持自定义 profile 属自然增强，SKILL.md 不用改。
3. **'显式 --engine kimi 被拒'** → **写 Scenario + 防御性测试**：显式断言 --engine kimi 报'未知 review engine'而非被静默接受，把结构性保证纳入回归面，防止将来有人把 kimi 加进 SUPPORTED_ENGINES 时漏掉同源守卫。
4. **index-session.sh 的宿主标识机制** → **显式传参、泛化**：各宿主 hooks 声明里给 index-session.sh 传显式参数（如 --runtime-host kimi 或环境变量），不再猜 source 字符串；codex 的猜测逻辑保留为向后兼容回退。

## Open Questions

无。本 change 覆盖的 4 条开放问题均已由用户在交互档裁决（见上方 Pattern Mapping）。本 change 刻意不覆盖 Kimi headless coder；若未来需要，应以独立 capability 实现和验证。
