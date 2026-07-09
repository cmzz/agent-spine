## ADDED Requirements

### Requirement: 模式盘问先于序列化——write 轮的硬前置门
`npc spec write run` MUST 在渲染 write 轮 prompt 之前，检查 `openspec/changes/<id>/pattern-interrogation.md` 是否存在。该文件不存在时 MUST 返回 `ok == false`、稳定错误标识 `pattern_interrogation_missing`，MUST NOT 渲染任何 `spec-write.prompt.md` 文件。

错误优先级：本门 MUST 在"v1 只支持 in-session 分发，路由合法性单一真相源"一条所定义的路由校验（`check_routing`/`_spec_routing_violations`）**之后**执行。即：路由违规时 MUST 恒以 `spec_routing_violation` 拒绝，MUST NOT 先报告 `pattern_interrogation_missing`/`pattern_interrogation_missing_section`——无论 `pattern-interrogation.md` 是否存在或结构是否完整，路由违规配置下的错误标识恒为 `spec_routing_violation`。

文件存在时，MUST 进一步检查其正文是否含全部三个必需 H2 标题：`## Analogs`、`## Assumptions`、`## Open Questions`（复用与"pattern-interrogation.md 产物结构"一条中 `npc spec interrogate record` 定位 `## Open Questions` 段落相同的段落定界算法）。缺失任一标题时 MUST 返回 `ok == false`、稳定错误标识 `pattern_interrogation_missing_section`，MUST NOT 渲染任何 `spec-write.prompt.md` 文件。此检查仅为标题级字符串存在性判定，MUST NOT 校验各段内容是否语义完整（如 `## Analogs` 引用是否真实指向仓库代码）——段内内容完整性仍由下一轮 `npc spec review run` 的语义评审兜底。

此门对分支 A（自由目标）与分支 B（补全既有 change）同等生效，MUST NOT 因草稿已存在而豁免。

#### Scenario: 盘问产物缺失时 write 轮被拒
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 不存在
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** 返回 `.ok == false`
- **AND** 输出含稳定错误标识 `pattern_interrogation_missing`
- **AND** 未写出任何 `spec-write.prompt.md` 文件

#### Scenario: 盘问产物存在但缺少必需 H2 段落时 write 轮被拒
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 存在，但不含 `## Assumptions` 标题（例如 writer 遗漏了该段，或 `npc spec interrogate record` 已判定该产物 `pattern_interrogation_missing_section` 但文件本身仍留在磁盘上）
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** 返回 `.ok == false`
- **AND** 输出含稳定错误标识 `pattern_interrogation_missing_section`
- **AND** 未写出任何 `spec-write.prompt.md` 文件

#### Scenario: 盘问产物存在且三段齐全时 write 轮行为不变
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** `.ok == true` 且 `.deferred == true`
- **AND** 返回 JSON 含 `.spawn_prompt` 与 `.prompt_file`

#### Scenario: 硬门对已有草稿的补全分支同样生效
- **GIVEN** `openspec/changes/<id>/proposal.md` 已存在（分支 B：补全已有 change），但 `pattern-interrogation.md` 不存在
- **WHEN** 执行 `npc spec write run --change <id>`（不传 `--goal`）
- **THEN** 返回 `.ok == false`，错误标识 `pattern_interrogation_missing`

### Requirement: npc spec interrogate run 契约
`npc spec interrogate run --change <id> [--goal <text>]` MUST 在渲染 prompt 之前调用 `check_routing(cfg)`（与 `spec write run`/`spec fix run` 复用同一函数，MUST NOT 引入独立的第二套后端白名单）；违规时 MUST 返回 `ok == false`、`spec_routing_violation`，MUST NOT 渲染任何 prompt 文件。合法时 MUST 恒返回 `deferred == true`，含 `.spawn_prompt` 与 `.prompt_file`（`prompt_file` MUST 以 `pattern-interrogation.prompt.md` 结尾）。`--goal` 透传语义与 `spec write run` 一致：非空时原文嵌入 prompt，不做任何改写/摘要。

超时预算 MUST 复用既有的 `npc agent timeout-budget`/`npc agent record-timeout` 四件套，phase 名为 `spec_interrogate`。

#### Scenario: 恒为 in-session
- **WHEN** 执行 `npc spec interrogate run --change <id>`
- **THEN** 返回 JSON 的 `.deferred == true`
- **AND** `.prompt_file` 以 `pattern-interrogation.prompt.md` 结尾

#### Scenario: routing 违规经由 check_routing 被拒
- **GIVEN** `.npc/config.toml` 含 `[spec_writer] backend = "mimo"`
- **WHEN** 执行 `npc spec interrogate run --change <id>`
- **THEN** `.ok == false`，输出含 `spec_routing_violation`，violations 含 `rule == "spec_mimo_in_session"`
- **AND** 未渲染任何 prompt 文件

#### Scenario: --goal 原文透传
- **GIVEN** 执行 `npc spec interrogate run --change <id> --goal "给认证模块加限流"`
- **WHEN** 读取渲染出的 prompt 文件全文
- **THEN** 其文本含子串 `给认证模块加限流`

#### Scenario: 超时预算复用既有四件套
- **WHEN** 执行 `npc agent timeout-budget --change <id> --phase spec_interrogate`
- **THEN** 返回 JSON 的 `.ok == true` 且 `.timeout_sec` 为正整数

### Requirement: pattern-interrogation.md 产物结构
`npc spec interrogate run` 渲染的 prompt MUST 要求 `spine-spec-writer` 撰写 `openspec/changes/<id>/pattern-interrogation.md`，其内容 MUST 含三个 H2 段落：`## Analogs`（枚举仓库内与本次改动最近似的 analog 实现，文件+函数级引用）、`## Assumptions`（关键假设）、`## Open Questions`（开放问题，逐条以顶层 `- ` bullet 列出）。

`npc spec interrogate record` MUST 独立解析该产物的 `## Open Questions` 段落，统计其下顶层 `- ` bullet 行数作为 `.open_questions`，MUST NOT 采信 RESULT 行中任何 writer 自报的开放问题计数字段（RESULT 契约本身不含此类字段，见下一条 Requirement）。该段落定界算法 MUST 与 `npc spec write run` 检查三个必需 H2 标题是否存在时所用的实现相同（见"模式盘问先于序列化"一条），不得分裂为两套解析逻辑。

- 产物文件不存在 MUST 返回 `ok == false`、`pattern_interrogation_missing`。
- 产物文件存在但缺少 `## Analogs`、`## Assumptions`、`## Open Questions` 三个必需 H2 标题中的**任意一个** MUST 返回 `ok == false`、`pattern_interrogation_missing_section`，并在输出中列出缺失的标题名；缺 `## Open Questions` 时 MUST NOT 静默按 `0` 处理。
  即：`npc spec interrogate record` 是三段结构的**首道校验点**（fail fast，缺任一段即拒绝记录）；`npc spec write run` 的同名硬门是**纵深防御**（覆盖绕过 record 直接跑 write 的路径），二者使用同一套标题存在性判据与同一错误标识，MUST NOT 出现"record 通过但 write gate 拒绝"的判定分歧。
- `## Open Questions` 标题存在但其下无 bullet（合法的"无开放问题"）MUST 返回 `ok == true`、`.open_questions == 0`。

#### Scenario: 独立计数不采信自报
- **GIVEN** `pattern-interrogation.md` 的 `## Open Questions` 段落含 3 条顶层 `- ` bullet
- **WHEN** 执行 `npc spec interrogate record --change <id> --result "<合法 RESULT 行>"`
- **THEN** 返回 JSON 的 `.open_questions == 3`

#### Scenario: 产物缺失
- **GIVEN** `pattern-interrogation.md` 不存在
- **WHEN** 执行 `npc spec interrogate record --change <id> --result "<合法 RESULT 行>"`
- **THEN** `.ok == false`，错误标识 `pattern_interrogation_missing`

#### Scenario: 缺 Analogs 段落时 record 拒绝

- **GIVEN** `pattern-interrogation.md` 存在且含 `## Assumptions` 与 `## Open Questions`，但不含 `## Analogs` H2 标题
- **WHEN** 执行 `npc spec interrogate record --change <id> --result "<合法 RESULT 行>"`
- **THEN** `.ok == false`，错误标识 `pattern_interrogation_missing_section`
- **AND** 输出列出的缺失标题名含 `## Analogs`

#### Scenario: 缺 Assumptions 段落时 record 拒绝

- **GIVEN** `pattern-interrogation.md` 存在且含 `## Analogs` 与 `## Open Questions`，但不含 `## Assumptions` H2 标题
- **WHEN** 执行 `npc spec interrogate record --change <id> --result "<合法 RESULT 行>"`
- **THEN** `.ok == false`，错误标识 `pattern_interrogation_missing_section`
- **AND** 输出列出的缺失标题名含 `## Assumptions`

#### Scenario: record 与 write gate 判定一致

- **GIVEN** 任一缺少三个必需 H2 标题中至少一个的 `pattern-interrogation.md`
- **WHEN** 分别执行 `npc spec interrogate record` 与 `npc spec write run`
- **THEN** 二者均 `.ok == false`，且错误标识均为 `pattern_interrogation_missing_section`
- **AND** 二者列出的缺失标题名集合完全相同

#### Scenario: 缺 Open Questions 段落不得静默按 0 处理
- **GIVEN** `pattern-interrogation.md` 存在，但不含 `## Open Questions` H2 标题
- **WHEN** 执行 `npc spec interrogate record --change <id> --result "<合法 RESULT 行>"`
- **THEN** `.ok == false`，错误标识 `pattern_interrogation_missing_section`

#### Scenario: 标题存在但无 bullet 时合法记为 0
- **GIVEN** `pattern-interrogation.md` 含 `## Open Questions` 标题，其下无任何顶层 `- ` bullet
- **WHEN** 执行 `npc spec interrogate record --change <id> --result "<合法 RESULT 行>"`
- **THEN** `.ok == true`，`.open_questions == 0`

### Requirement: npc spec interrogate decide 的一次性机械追加语义
`npc spec interrogate decide --change <id> --decisions-md <text>` MUST 为纯机械文本追加命令：MUST NOT 对 `--decisions-md` 的内容做任何解析、改写或语义判断。`pattern-interrogation.md` 不存在时 MUST 返回 `ok == false`、`pattern_interrogation_missing`。该文件已含 `## User Decisions (Interactive)` 段落时 MUST 返回 `ok == false`、`decisions_already_recorded`，MUST NOT 修改文件内容（一次性、不覆盖）。否则 MUST 在文件末尾追加一个新的 `## User Decisions (Interactive)` 段落，其正文恰为 `--decisions-md` 的原文。

#### Scenario: 正常追加
- **GIVEN** `pattern-interrogation.md` 存在且不含 `## User Decisions (Interactive)` 段落
- **WHEN** 执行 `npc spec interrogate decide --change <id> --decisions-md "Q1: 用户选择方案 A"`
- **THEN** `.ok == true`
- **AND** 文件末尾新增 `## User Decisions (Interactive)` 段落，正文恰为 `Q1: 用户选择方案 A`

#### Scenario: 重复调用被拒且不覆盖
- **GIVEN** `pattern-interrogation.md` 已含 `## User Decisions (Interactive)` 段落
- **WHEN** 再次执行 `npc spec interrogate decide --change <id> --decisions-md "<其它文本>"`
- **THEN** `.ok == false`，错误标识 `decisions_already_recorded`
- **AND** 文件内容与调用前逐字节相同

#### Scenario: 产物缺失时拒绝
- **GIVEN** `pattern-interrogation.md` 不存在
- **WHEN** 执行 `npc spec interrogate decide --change <id> --decisions-md "<text>"`
- **THEN** `.ok == false`，错误标识 `pattern_interrogation_missing`

### Requirement: render_spec_writer 消费 pattern-interrogation.md
`npc spec write run` 渲染的 write 轮 prompt MUST 列出 `openspec/changes/<id>/pattern-interrogation.md` 为必读输入。该 prompt MUST 含以下判据与指令的原文，判据 MUST 为机械的字符串存在性检查（`pattern-interrogation.md` 是否含 `## User Decisions (Interactive)` 这一 H2 标题），MUST NOT 要求 writer 对任一条 Open Question 单独判断其是否"已被回应"/"resolved"：

- 若 `pattern-interrogation.md` 含 `## User Decisions (Interactive)` 标题：MUST 把该文件的 `## Open Questions` 段全文与 `## User Decisions (Interactive)` 段全文原样写入 `design.md` 的 `## Pattern Mapping` 段。
- 若不含该标题：MUST 把 `## Open Questions` 段全文与 `## Assumptions` 段全文原样写入 `design.md` 的 `## Pattern Mapping` 与 `## Assumptions` 段。

该 prompt MUST 另含以下指令：若本 change 的 `tasks.md` 需要列出涉及 ≥2 处调用点/文件的落点清单，MUST 先执行一条确定性搜索命令（`grep`/`rg`/`git grep`）枚举，并把命令原文与匹配计数写入该清单所在的 tasks.md 段落。

#### Scenario: prompt 列出 pattern-interrogation.md 为必读输入
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>` 并读取渲染出的 prompt 文件全文
- **THEN** 其文本含子串 `pattern-interrogation.md`

#### Scenario: prompt 含机械判据而非语义裁决指令
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>` 并读取渲染出的 write prompt 全文
- **THEN** 其文本含子串 `## User Decisions (Interactive)`
- **AND** MUST NOT 含要求逐条判断 Open Question 是否"已被回应"或"resolved"的措辞

#### Scenario: 含 User Decisions 标题分支的指令原文
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>` 并读取渲染出的 write prompt 全文
- **THEN** 其文本含"把 `## Open Questions` + `## User Decisions (Interactive)` 段原样写入 design.md 的 `## Pattern Mapping` 段"这一指令的原文（或与之逐字一致的表述）

#### Scenario: 不含 User Decisions 标题分支的指令原文
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>` 并读取渲染出的 write prompt 全文
- **THEN** 其文本含"把 `## Open Questions` + `## Assumptions` 段原样写入 design.md 的 `## Pattern Mapping` 与 `## Assumptions` 段"这一指令的原文（或与之逐字一致的表述）

#### Scenario: 多落点清单需先跑确定性搜索命令
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>` 并读取渲染出的 write prompt 全文
- **THEN** 其文本含要求"先执行确定性搜索命令（`grep`/`rg`/`git grep`）枚举涉及 ≥2 处调用点/文件的落点清单，并把命令原文与匹配计数写入 tasks.md 对应段落"的指令原文


## MODIFIED Requirements

### Requirement: spec writer 的 RESULT 契约
`RESULT_REQUIRED_KEYS` MUST 新增 phase `spec_write`，其必需键集合恰为 `{"change", "artifacts", "validate", "summary"}`；MUST 新增 phase `spec_fix`，其必需键集合恰为 `{"change", "fixed", "validate", "summary"}`；MUST 新增 phase `spec_interrogate`，其必需键集合恰为 `{"change", "artifacts", "summary"}`（不含 `validate`——`pattern-interrogation.md` 不是 `openspec validate` 认识的 artifact 类型）。`npc spec write record`、`npc spec fix record` 与 `npc spec interrogate record` MUST 在 RESULT 行缺少任一必需键时返回 `ok == false` 与稳定错误标识，MUST NOT 静默接受。

#### Scenario: 缺必需键的 RESULT 被拒
- **GIVEN** spec writer 回报的 RESULT 行缺少 `validate` 键
- **WHEN** 执行 `npc spec write record --result "<该行>"`
- **THEN** 返回 JSON 满足 `.ok == false`
- **AND** 输出含稳定错误标识，且指明缺失的键名 `validate`

#### Scenario: 完整 RESULT 被接受
- **GIVEN** spec writer 回报的 RESULT 行含全部四个必需键
- **WHEN** 执行 `npc spec write record --result "<该行>"`
- **THEN** `.ok == true`

#### Scenario: 既有 phase 的必需键未被改动
- **WHEN** 读取 `RESULT_REQUIRED_KEYS`
- **THEN** `RESULT_REQUIRED_KEYS["implement"]` 等于 `{"commit","tasks","tests","summary"}`
- **AND** `RESULT_REQUIRED_KEYS["fix"]` 等于 `{"commit","fixed","tests","summary","categories_scanned","regressions_added"}`
- **AND** `RESULT_REQUIRED_KEYS["spec_write"]` 等于 `{"change","artifacts","validate","summary"}`
- **AND** `RESULT_REQUIRED_KEYS["spec_fix"]` 等于 `{"change","fixed","validate","summary"}`

#### Scenario: spec_interrogate 的必需键集合
- **WHEN** 读取 `RESULT_REQUIRED_KEYS["spec_interrogate"]`
- **THEN** 其等于 `{"change","artifacts","summary"}`

#### Scenario: spec_interrogate 缺必需键的 RESULT 被拒
- **GIVEN** spec writer 回报的 spec_interrogate RESULT 行缺少 `summary` 键
- **WHEN** 执行 `npc spec interrogate record --result "<该行>"`
- **THEN** 返回 `.ok == false`，输出含稳定错误标识且指明缺失的键名 `summary`

### Requirement: 生成侧不得预知本轮评判标准
`npc spec write run` 渲染给 `spine-spec-writer` 的 prompt 文件 MUST NOT 包含本轮 spec-review 的 focus 渲染文本、评分 rubric 细则、或任何 `SPEC_REVIEW_SCHEMA` 的 `category` 枚举列表。`npc spec fix run` 渲染的 prompt MAY 包含**上一轮已签发**的 blocking findings 原文。`npc spec interrogate run` 渲染的 prompt 同样 MUST NOT 包含上述内容——盘问轮讨论的是仓库内已有的 analog 实现，不是本轮评判标准。此边界为**时点**边界，与 `spine-coder` 的 implement/fix 结构同构。

`spine-spec-writer` 撰写的 `pattern-interrogation.md` 与 `tasks.md` 的落点清单，正文 MUST NOT 引用 `SPEC_REVIEW_SCHEMA` 的任一 `category` 枚举值（`ambiguity`/`missing-scenario`/`implementation-leak`/`untestable`/`deferred-decision`/`contradiction`/`scope-creep`），MUST NOT 引用任何 `round-*.spec-review.json` 的 findings 原文。

#### Scenario: 负向断言——write 轮 prompt 不含 rubric
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>` 并读取渲染出的 prompt 文件全文
- **THEN** 其文本 MUST NOT 含子串 `scope-creep`
- **AND** MUST NOT 含子串 `implementation-leak`
- **AND** MUST NOT 含任何 `spec-review.json` 的 findings 原文

#### Scenario: fix 轮 prompt 可含上一轮已签发 findings
- **GIVEN** `round-0.spec-review.json` 已产出，含一条 `category == "ambiguity"` 的 blocking finding
- **WHEN** 执行 `npc spec fix run --change <id> --round 1` 并读取渲染出的 prompt 文件
- **THEN** 其文本含该 finding 的 `detail` 原文

#### Scenario: fix 轮 prompt 不含当轮 review 内容
- **GIVEN** 磁盘上同时存在 `round-0.spec-review.json` 与 `round-1.spec-review.json`，两者 findings 的 `detail` 互不相同
- **WHEN** 执行 `npc spec fix run --change <id> --round 1` 并读取渲染出的 prompt 文件
- **THEN** 其文本含 `round-0.spec-review.json` 的 finding `detail` 原文
- **AND** MUST NOT 含 `round-1.spec-review.json` 的 finding `detail` 原文

#### Scenario: 上一轮 review 未落盘时 fix 拒绝渲染
- **GIVEN** `round-0.spec-review.json` 不存在
- **WHEN** 执行 `npc spec fix run --change <id> --round 1`
- **THEN** 返回 `.ok == false`
- **AND** 输出含稳定错误标识 `prev_spec_review_missing`

#### Scenario: 负向断言——interrogate 轮 prompt 不含 rubric
- **WHEN** 执行 `npc spec interrogate run --change <id>` 并读取渲染出的 prompt 文件全文
- **THEN** 其文本 MUST NOT 含子串 `scope-creep`
- **AND** MUST NOT 含子串 `implementation-leak`
- **AND** MUST NOT 含任何 `SPEC_REVIEW_SCHEMA` 的 `category` 枚举值
- **AND** MUST NOT 含任何 `round-*.spec-review.json` 原文

### Requirement: 用户入口与 subagent 注册
仓库 MUST 提供 `plugins/agent-spine/commands/spine-spec.md` 作为 `/spine-spec` 的入口，与 `plugins/agent-spine/agents/spine-spec-writer.md` 作为执行体契约。两者 MUST 在 `plugins/agent-spine/.claude-plugin/plugin.json` 的对应清单中注册。`spine-spec.md` MUST 支持 `--auto` 标志：省略时为交互档（关键闸口调用 `AskUserQuestion`），含 `--auto` 时为全自主档（全程不调用 `AskUserQuestion`），语义 MUST 与 `plugins/agent-spine/commands/spine-run.md` 的 `--auto` 判断逻辑一致。

`spine-spec.md` 记录的核心编排顺序 MUST 恒为：先 `npc spec interrogate run` → spawn `spine-spec-writer` 撰写 `pattern-interrogation.md` → `npc spec interrogate record` → 依据 `.open_questions` 分支 → 再 `npc spec write run`（write 轮）。MUST NOT 记录任何跳过 interrogate 阶段、直接从入口进入 `npc spec write run` 的路径。分支细则：
- 交互档（未传 `--auto`）且 `.open_questions > 0`：MUST 记录先调用 `AskUserQuestion` 收集用户对每条开放问题的裁决，再调用 `npc spec interrogate decide` 把裁决原文追加进 `pattern-interrogation.md`，然后才进入 write 轮。
- 交互档且 `.open_questions == 0`：MUST NOT 调用 `AskUserQuestion` 或 `npc spec interrogate decide`，直接进入 write 轮。
- `--auto` 档：无论 `.open_questions` 是否 `> 0`，MUST NOT 调用 `AskUserQuestion` 或 `npc spec interrogate decide`；MUST 在 interrogate 阶段（`run` + `record`）完成后直接进入 write 轮。

**职责边界 MUST 由确定性校验强制，不得依赖 prompt 文案的口头约束**（`spine-spec-writer` 持有 `Bash`，仅靠文案无法阻止它 `git commit` 或改源码）。`npc spec write record`、`npc spec fix record` 与 `npc spec interrogate record` MUST 在装订 RESULT 前，用 `git status --porcelain` 检查工作区变更集：若存在任何位于 `openspec/changes/<id>/` 之外的路径变更，MUST 返回 `ok == false` 与稳定错误标识 `out_of_scope_changes`，并把越界路径列入输出，MUST NOT 装订该 RESULT。`spine-spec-writer` MUST NOT 产生任何 git commit——`spec_write`/`spec_fix`/`spec_interrogate` 三个 RESULT 契约均不存在 `commit` 键，其自报的 commit 无处安放。

#### Scenario: 越界修改被 record 拒绝
- **GIVEN** spec writer 除了写 `openspec/changes/my-change/` 下的 artifact，还修改了 `src/npc/cli.py`
- **WHEN** 执行 `npc spec write record --change my-change --result "<合法 RESULT 行>"`
- **THEN** 返回 `.ok == false`
- **AND** 输出含稳定错误标识 `out_of_scope_changes`
- **AND** 输出的越界路径列表含 `src/npc/cli.py`

#### Scenario: 仅改 change 目录时 record 通过
- **GIVEN** spec writer 只修改了 `openspec/changes/my-change/` 下的文件
- **WHEN** 执行 `npc spec write record --change my-change --result "<合法 RESULT 行>"`
- **THEN** `.ok == true`

#### Scenario: spec writer 产生 git commit 时被拒
- **GIVEN** spec writer 执行了 `git commit`，使 `HEAD` 相对 record 前发生变化
- **WHEN** 执行 `npc spec write record --change my-change --result "<合法 RESULT 行>"`
- **THEN** 返回 `.ok == false`
- **AND** 输出含稳定错误标识 `unexpected_commit`

#### Scenario: interrogate record 同样受越界拦截
- **GIVEN** spec writer 在盘问轮除了写 `pattern-interrogation.md`，还修改了 `src/npc/templates.py`
- **WHEN** 执行 `npc spec interrogate record --change my-change --result "<合法 RESULT 行>"`
- **THEN** 返回 `.ok == false`，输出含 `out_of_scope_changes`

#### Scenario: subagent 契约含 RESULT schema
- **WHEN** 读取 `plugins/agent-spine/agents/spine-spec-writer.md`
- **THEN** 其正文列出 `spec_write`、`spec_fix`、`spec_interrogate` 三个 phase 的 RESULT 必需键
- **AND** 其正文要求第一步 Read npc 渲染的 prompt 文件绝对路径
- **AND** 其正文明令 MUST NOT 运行 `git commit`、MUST NOT 修改 `openspec/changes/<id>/` 之外的任何文件

#### Scenario: 入口命令不接管 spine-run Step 2B
- **WHEN** 读取 `plugins/agent-spine/commands/spine-run.md`
- **THEN** 其 Step 2B 的文本未被本 change 修改
- **AND** 其中不含 `spine-spec-writer` 字样

#### Scenario: --auto 标志与 spine-run 同构
- **WHEN** 读取 `plugins/agent-spine/commands/spine-spec.md`
- **THEN** 其含 `--auto` 判断逻辑段落，语义为"参数含 `--auto` → 全自主档；否则 → 交互档"
- **AND** auto 档描述中明令不调用 `AskUserQuestion`

#### Scenario: 编排顺序恒为先盘问后撰写
- **WHEN** 读取 `plugins/agent-spine/commands/spine-spec.md`
- **THEN** 其文本记录的 Step 顺序为 `npc spec interrogate run` → spawn `spine-spec-writer` 撰写 `pattern-interrogation.md` → `npc spec interrogate record` → 分支裁决 → `npc spec write run`
- **AND** MUST NOT 含任何在 `npc spec interrogate run`/`record` 完成前直接调用 `npc spec write run` 的路径描述

#### Scenario: 交互档且存在开放问题时调用 AskUserQuestion 与 decide
- **WHEN** 读取 `plugins/agent-spine/commands/spine-spec.md` 中交互档（未传 `--auto`）分支的文本
- **THEN** 其记录：`.open_questions > 0` 时先调用 `AskUserQuestion` 收集用户裁决，再调用 `npc spec interrogate decide` 把裁决写入 `pattern-interrogation.md`，然后才进入 write 轮

#### Scenario: 交互档且无开放问题时跳过用户裁决
- **WHEN** 读取 `plugins/agent-spine/commands/spine-spec.md` 中交互档分支的文本
- **THEN** 其记录：`.open_questions == 0` 时 MUST NOT 调用 `AskUserQuestion` 或 `npc spec interrogate decide`，直接进入 write 轮

#### Scenario: auto 档无论是否有开放问题均跳过用户裁决但仍先完成盘问
- **WHEN** 读取 `plugins/agent-spine/commands/spine-spec.md` 中 `--auto` 档分支的文本
- **THEN** 其记录：`--auto` 档下无论 `.open_questions` 是否 `> 0`，MUST NOT 调用 `AskUserQuestion` 或 `npc spec interrogate decide`
- **AND** 仍要求先完成 `npc spec interrogate run`/`record` 再进入 `npc spec write run`

### Requirement: v1 只支持 in-session 分发，路由合法性单一真相源
`npc spec write run`、`npc spec fix run` 与 `npc spec interrogate run` MUST 恒返回 `deferred == true`（in-session，由编排者 spawn `spine-spec-writer` subagent）。本版本 MUST NOT 支持 headless 分发。

路由合法性 MUST NOT 由本 change 独立判定。三个 `run` 命令 MUST 在渲染任何 prompt 之前完成路由校验，且 MUST 与既有 `npc verify routing` 使用同一套 `spec_` 前缀规则集判定：任一 `spec_` 规则被命中时，MUST 返回 `ok == false` 与稳定错误标识 `spec_routing_violation`，并把命中的 `rule` 与 `detail` 原样列入输出。三个命令对同一份非法配置 MUST 给出完全相同的判定结果与 violations 列表（同一真相源），MUST NOT 出现只有某一个命令能拒绝的配置。

因此 `spec_writer.backend = "mimo"` 被拒的路径是：`check_routing` 产出 `spec_mimo_in_session` → 三个 `run` 命令均以 `spec_routing_violation` 拒绝执行。`spec_mimo_in_session` 是规则名（`npc verify routing` 的输出），`spec_routing_violation` 是命令级错误标识（`run` 命令的输出），二者层级不同、不重复。

超时预算 MUST 复用既有的 `npc agent timeout-budget` / `npc agent record-timeout`，phase 名为 `spec_write`、`spec_fix-r{N}` 与 `spec_interrogate`。

#### Scenario: 恒为 in-session
- **GIVEN** `openspec/changes/<id>/pattern-interrogation.md` 已存在，且含 `## Analogs`、`## Assumptions`、`## Open Questions` 三个 H2 标题
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** 返回 JSON 的 `.deferred == true`
- **AND** 返回 JSON 含 `.spawn_prompt` 与 `.prompt_file`

#### Scenario: mimo 后端经由共享路由规则集被拒
- **GIVEN** `.npc/config.toml` 含 `[spec_writer] backend = "mimo"`
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** `.ok == false`
- **AND** 输出含稳定错误标识 `spec_routing_violation`
- **AND** 输出的 violations 列表含 `rule == "spec_mimo_in_session"`
- **AND** 未渲染任何 prompt 文件

#### Scenario: 路由检查先于 prompt 渲染
- **GIVEN** `.npc/config.toml` 使 `spec_writer` 与 `spec_review` 解析到同一执行身份
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** `.ok == false` 且输出含 `spec_routing_violation`
- **AND** 输出的 violations 列表含 `rule == "spec_gen_not_orthogonal"`
- **AND** 未产生任何 LLM 引擎子进程调用

#### Scenario: 三个 run 命令对同一非法配置给出一致判定
- **GIVEN** 任一使 `spec_` 前缀路由规则被命中的 `.npc/config.toml`
- **WHEN** 分别执行 `npc spec write run`、`npc spec fix run`、`npc spec interrogate run`
- **THEN** 三者均 `.ok == false`，均以 `spec_routing_violation` 为错误标识
- **AND** 三者输出的 violations 列表（`rule` 集合）完全相同
- **AND** 三者均未渲染 prompt 文件

#### Scenario: 路由拒绝的错误标识不随命令而异
- **GIVEN** `.npc/config.toml` 含 `[spec_writer] backend = "mimo"`
- **WHEN** 执行上述三个 run 命令中的任意一个
- **THEN** 其输出的错误标识恒为 `spec_routing_violation`，MUST NOT 是任何该命令专属的其它错误标识

#### Scenario: 路由违规优先于模式盘问硬门
- **GIVEN** `.npc/config.toml` 含 `[spec_writer] backend = "mimo"`，且 `openspec/changes/<id>/pattern-interrogation.md` 不存在
- **WHEN** 执行 `npc spec write run --change <id>`
- **THEN** `.ok == false`，错误标识恒为 `spec_routing_violation`
- **AND** MUST NOT 是 `pattern_interrogation_missing`

#### Scenario: 超时预算复用既有四件套
- **WHEN** 执行 `npc agent timeout-budget --change <id> --phase spec_write`
- **THEN** 返回 JSON 的 `.ok == true` 且 `.timeout_sec` 为正整数

#### Scenario: interrogate 阶段同样恒为 in-session 且复用路由检查
- **WHEN** 执行 `npc spec interrogate run --change <id>`
- **THEN** 返回 JSON 的 `.deferred == true`
- **AND** `.npc/config.toml` 含 `[spec_writer] backend = "mimo"` 时该命令同样以 `spec_routing_violation` 拒绝
