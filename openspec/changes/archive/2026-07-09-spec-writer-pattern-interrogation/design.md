## Context

`spine-spec-writer`（`spec-writer` capability，已归档）已建好 write/fix 两轮结构、routing 隔离、越界确定性拦截、轮次化 review。本 change 只在其**最前面**插入一步，不动 review/fix 循环。

已核实的可复用结构：

- `spec_write_run`/`spec_fix_run`（`src/npc/spec_pipeline.py`）：routing 检查 → scope marker → 渲染 prompt → 返回 `deferred=true` + `spawn_prompt`/`prompt_file`。
- `spec_write_record`/`spec_fix_record`：`_parse_and_validate_result_line` 校验 RESULT 键 → `_scope_guard_violation`（`git status --porcelain` + `pre_head` marker 比对 HEAD）。
- `templates.render_spec_writer`/`render_spec_fixer`：纯函数，不变量 1 由函数本身不 import/嵌入 review rubric 保证。
- `scripts/check_spec.py`：仓库本地 shadow-mode 语义 lint，四条规则均以 `warning` 交付，升级判据写死在 docstring。
- `check_spec.py` 的 `section_of_line`/`strip_code_spans`：按 `##` 标题定界段落、剥离 fenced code block 与 inline code span，避免误报——本 change 的新规则复用同一套工具函数。

## Goals / Non-Goals

**Goals**

- write 轮开始前，强制存在一份结构化的模式盘问产物（analog 引用 + 假设 + 开放问题）。**该强制性由代码门保证**：门校验到"文件存在 + 三个必需 H2 标题（`## Analogs`/`## Assumptions`/`## Open Questions`）齐全"这一结构层级，不靠 prompt 文案约束 writer；标题之下段落内容是否语义完整（如 analog 引用是否真实指向仓库代码），仍留给下一轮 `npc spec review run` 的语义评审兜底——这是代码门与语义评审的既有分工，非本次新增边界。
- 交互档让用户对开放问题拍板；auto 档让开放问题不丢失、原样进入 design.md 供 reviewer 攻击。
- 多落点 change 的 tasks.md 清单能溯源到一条写入 artifact 的确定性搜索命令。
- 全程遵守不变量 1：盘问产物与落点清单不得引用当次 spec review 的评分标准。

**Non-Goals**

- 不对 `pattern-interrogation.md` 做 openspec-schema 强校验（它不进 `openspec validate` 的检查范围）。
- 不用 LLM 或正则「理解」用户对开放问题的裁决语义——`npc spec interrogate decide` 只做机械文本追加。
- 不把 `touchpoint_list_missing_search_command` 做成阻断门。
- 不改变 review/fix 循环、telemetry 事件形态、既有 RESULT 键集合。

## Decisions

**D1：新增独立 phase `spec_interrogate`，而非把盘问塞进 `spec_write_run` 内部一次调用里完成。**

交互档需要在「盘问产出开放问题」和「write 轮消费裁决结果」之间插入一次 `AskUserQuestion`——而 `AskUserQuestion` 只有主 session（`/spine-spec`）能调用，subagent 内部做不到。若盘问和撰写在同一次 subagent 调用里完成，主 session 就没有介入点。故必须拆成两次独立的 subagent spawn（interrogate 一次、write 一次），中间insert主 session 的裁决步骤——与 `spec_write`/`spec_fix` 两轮拆分成两次 spawn 是同一形态。

**D2：`spec_write_run` 的硬门直接查磁盘文件存在性 + 三个必需 H2 标题存在性，不查 RESULT 自报，也不止步于"文件存在"。**

`spec_interrogate_record` 的 RESULT 自报可能被伪造或遗漏；`spec_write_run` 在渲染 write prompt 前直接 `Path(base / "pattern-interrogation.md").exists()`，不存在即 `ok=false`、`error=pattern_interrogation_missing`，MUST NOT 渲染任何 write prompt 文件。这与 `spec_fix_run` 对 `round-(N-1).spec-review.json` 的存在性检查（`prev_spec_review_missing`）同一形态：**上游产物缺失，下游拒绝渲染**，不静默降级。

执行顺序：本门 MUST 排在既有 routing 校验（`_spec_routing_violations`）**之后**——`spec_write_run` 先跑 D8 复用的 routing 检查，routing 违规恒以 `spec_routing_violation` 拒绝并短路返回，不会继续检查 `pattern-interrogation.md`；只有 routing 合法时才会走到本门。两道门的错误标识因此永不冲突。

仅查"文件存在"不足以兑现 Goal 中"结构化产物由代码门保证"的承诺：一个空文件、或 `interrogate record` 已判定 `pattern_interrogation_missing_section`（结构缺陷）但文件本身仍留在磁盘上的半成品，都能通过纯存在性检查蒙混过关。故该门在确认文件存在后，MUST 进一步检查文件正文是否含全部三个必需 H2 标题（`## Analogs`/`## Assumptions`/`## Open Questions`，与"pattern-interrogation.md 产物结构"要求一致）；缺失任一标题 MUST 返回 `ok=false`、`error=pattern_interrogation_missing_section`，同样 MUST NOT 渲染任何 write prompt 文件。这一标题存在性检查复用 D3 为定位 `## Open Questions` 段落而独立实现的段落定界算法（同一函数对三个标题分别做存在性判定，不是第二套解析逻辑）。该检查止步于"标题是否存在"这一机械判据，MUST NOT 延伸到"段落内容是否语义完整"——这层判定不可静态判定，交由下一轮 `npc spec review run` 兜底，与 D5 对 write 轮"誊抄是否完整"不可静态判定的既有结论同一分工。

此门对分支 A（自由目标）与分支 B（补全既有 change）**一视同仁**：即便 change 目录已有半成品草稿，仍需先跑一次 interrogate——半成品草稿本身可能就是遗漏 analog 调研的产物，这正是本 change 要防的问题。

**D3：`.open_questions` 由 npc 独立解析，不信任 writer 自报（不变量 2）。**

`pattern-interrogation.md` 要求 MUST 含 `## Open Questions` 这一 H2 标题；`spec_interrogate_record` 复用 `check_spec.py` 同款的「按 `##` 定界段落」算法（不 import `check_spec.py`——`spec_pipeline.py` 属 npc，`check_spec.py` 属仓库本地资产，两者边界不能破，故在 `spec_pipeline.py` 内独立实现一份等价的最小段落定界逻辑），数出该段落下匹配 `^- ` 的顶层 bullet 行数，作为 `.open_questions` 返回。若产物文件不含 `## Open Questions` 标题，视为结构性缺陷，返回 `ok=false`、`error=pattern_interrogation_missing_section`，MUST NOT 静默按 0 处理（0 和"没写这一段"是两件事，静默按 0 处理会让 `/spine-spec` 误判为"没有开放问题"从而跳过用户裁决）。

**D4：`npc spec interrogate decide` 是纯机械追加，一次性、不覆盖。**

命令签名 `npc spec interrogate decide --change <id> --decisions-md <text>`。行为：

1. `pattern-interrogation.md` 不存在 → `ok=false`、`error=pattern_interrogation_missing`。
2. 文件已含 `## User Decisions (Interactive)` 标题 → `ok=false`、`error=decisions_already_recorded`（防止交互档循环内被误调用两次导致内容重复/覆盖语义不清）。
3. 否则在文件末尾追加 `\n\n## User Decisions (Interactive)\n\n{decisions_md}\n`，返回 `ok=true`。

`decisions_md` 的内容由主 session 从 `AskUserQuestion` 的回答原文拼装（问题 + 用户选择/输入），npc 不解析、不改写、不做语义判断——这与"npc 只做机械动作，内容生成委托给 LLM"的既有分工一致（如 `gate_cmd` 只读 `ok`/`rule_hits` 两个键、不解读规则语义）。

**D5：write 轮不判断哪些 Open Questions"已被回应"——只按一个机械存在性信号，原样带入 design.md，不允许悄悄丢弃。**

`render_spec_writer` 新增指令：读取 `pattern-interrogation.md`。判据是**该文件是否含 `## User Decisions (Interactive)` 这一 H2 标题**，一个纯字符串存在性检查，MUST NOT 尝试判断某条 Open Question 是否"语义上已被回应"（`npc spec interrogate decide` 本身就是机械追加、不带 QID 映射，逐条裁决语义不可判定，故 write 轮也不应尝试判定）：

- 若含该标题（交互档：主 session 已调用过 `npc spec interrogate decide`）：MUST 把 `## Open Questions` 段全文与 `## User Decisions (Interactive)` 段全文原样（逐条 bullet 与用户裁决原文）一并写入 `design.md` 的 `## Pattern Mapping` 段。
- 若不含该标题（auto 档；或交互档下 Open Questions 为空、从未调用过 decide）：MUST 把 `## Open Questions` 段全文与 `## Assumptions` 段全文原样一并写入 `design.md` 的 `## Pattern Mapping` 与 `## Assumptions` 段。
- 若 `## Open Questions` 段为空（无 bullet），上述两个分支均按"该段为空"原样处理，不视为异常，不跳过整个指令。

`design.md` 新段落若已有 `## Open Questions` 段则不重复占用同一标题，避免与 `check_spec.py` 的 `deferred_decision_outside_open_questions` 规则打架——延迟决策措辞若确实出现在这两个新段落之外，仍应被该规则命中，这是期望行为而非误报，因为"假设未被验证"和"决策被推迟"是两个不同维度。

这一步的**信号来源**（是否存在 `## User Decisions (Interactive)` 标题）是机械的、代码可复核的（grep 标题存在性即可断言）；但"是否把段落内容逐字誊抄完整"仍是语义判定，只有下一轮 `npc spec review run` 能可靠地拦（同 `spine-spec-writer` design.md 已核实的结论："缺 abort 错误路径 scenario"类问题不可静态判定）——本 change 只把**触发分支的判据**从不可判定的语义匹配换成可判定的标题存在性检查，不消灭"誊抄是否完整"这层语义判定本身。

**D6：多落点确定性枚举——写作侧指令 + repo-spec-lint 侧 shadow-mode 辅助规则，两道都不是阻断门。**

`render_spec_writer` 新增指令：若本 change 的 tasks.md 需要列出 ≥2 处调用点/文件的落点清单，MUST 先执行一条确定性搜索命令（`grep -rn`/`rg`/`git grep`）枚举，并把该命令原文与匹配计数写入清单所在段落，作为可复核依据。这与用户目标原文一致："使覆盖率判据从『reviewer 觉得全了』变为『清单逐条勾完』"。

`scripts/check_spec.py` 新增第五条规则 `touchpoint_list_missing_search_command` 作为结构性辅助信号（不是强制）：扫描 `tasks.md`，若某 `##`/`###` 段落内的列表项中，引用不同文件路径（反引号包裹、含 `/` 或以常见代码后缀结尾的 token）的行数 ≥3，视为声明了多落点清单；该段内若无任何围栏代码块命中 `grep`/`rg`/`git grep`/`git diff --name-only` 子串，产出一条 `warning`。

严格遵循既有的 shadow-mode 纪律（`repo-spec-lint` design.md D2 的判据原话）：该规则以 `warning` 交付，升级判据与既有四条完全一致——正类样本 ≥ 3 个独立 change 时方可升为 `error`。本 change 提供该规则的**零样本**首次上线，不主张任何方差证据。

**D7：`/spine-spec` 的 `--auto` 标志与 `/spine-run` 同构，不新增第二套语义。**

`/spine-spec` 新增 `--auto` 标志，判断逻辑与 `/spine-run` 完全一致（"模式标志：参数含 `--auto` → 全自主档；否则 → 交互档"）。auto 档下 `/spine-spec` 绝不调用 `AskUserQuestion`——即便 `.open_questions > 0` 也跳过用户裁决步骤，直接进入 write 轮（write 轮读到未裁决的开放问题后按 D5 序列化进 design.md）。这不是新发明，是把 `/spine-run` 已验证过的模式标志搬到 `/spine-spec`，两处 `--auto` 判断逻辑保持字面一致，避免用户要记两套心智模型。

**D8：`npc spec interrogate run` 的 routing/超时/deferred 语义与 `spec write run` 完全复用同一套代码路径。**

不新增第二套后端白名单或路由判定——`spec_interrogate_run` 与 `spec_write_run`/`spec_fix_run` 调用同一个 `_spec_routing_violations(cfg)`；`npc agent timeout-budget --phase spec_interrogate` 复用既有四件套，不新增专属超时逻辑。这与 `spine-spec-writer` design.md D5c 的既有决策（"路由合法性单一真相源"）直接延伸，不重新论证。

## Risks / Trade-offs

- **[多一次 subagent spawn，拉长单个 change 的墙钟时间]** → 盘问轮本身应比撰写轮便宜（只读代码找 analog，不产出完整 artifact）；`npc agent timeout-budget --phase spec_interrogate` 可独立配置更短预算。这是"文档先行"要付的确定性成本，用返工成本换。
- **[`touchpoint_list_missing_search_command` 的多文件路径正则可能误报/漏报]** → 以 `warning` 交付，不阻断；且该正则只影响 lint 的辅助信号，不影响 write 轮本身是否成功。
- **[硬门是破坏性变更，任何直接调 `spec write run` 跳过 interrogate 的旧脚本会失效]** → 有意为之（该门正是本 change 的核心诉求）；`/spine-spec` 命令文档同步更新，无隐藏的旧调用路径。
- **[auto 档下开放问题"原样进 design.md"依赖 writer 遵从指令，非代码强制]** → 这是本 change 明确接受的边界：结构性存在性（三段 H2 标题是否齐全）用代码门覆盖（D2/D3），段落内容是否语义完整、是否被逐字誊抄用下一轮语义评审兜底（D5），与既有 spec-writer 架构的分工一致，不重复发明。

## Migration Plan

1. `src/npc/pipeline.py`：`RESULT_REQUIRED_KEYS["spec_interrogate"] = frozenset({"change","artifacts","summary"})`。
2. `src/npc/templates.py`：新增 `render_spec_interrogator`；扩写 `render_spec_writer` 加入 `pattern-interrogation.md` 必读输入段与 D5/D6 指令段。
3. `src/npc/spec_pipeline.py`：新增 `spec_interrogate_run`、`spec_interrogate_record`、`spec_interrogate_decide`（内部函数名，CLI 层映射为 `npc spec interrogate run|record|decide`）；`spec_write_run` 增加 D2 的文件存在性 + 三段必需 H2 标题存在性硬门；新增独立的 H2 段落定界辅助函数（不 import `check_spec.py`），供 `spec_write_run` 的标题存在性检查与 `spec_interrogate_record` 的 `## Open Questions` bullet 计数复用同一实现，不分裂为两套解析逻辑。
4. `src/npc/cli.py`：注册三个新子命令，参数解析与既有 `spec write`/`spec fix` 同构。
5. `scripts/check_spec.py`：新增 `RULE_TOUCHPOINT_LIST_MISSING_SEARCH_COMMAND`；`ALL_RULE_NAMES` 扩至五项；docstring 更新为"五条规则"，升级判据文本不变。
6. `plugins/agent-spine/agents/spine-spec-writer.md`：补充 `spec_interrogate` phase 的职责段与 RESULT 必需键，补充"撰写 pattern-interrogation.md 时的三段式结构要求"。
7. `plugins/agent-spine/commands/spine-spec.md`：新增 `--auto` 标志解析；新增 Step "模式盘问"（含交互档 `AskUserQuestion` 分支与 `npc spec interrogate decide` 调用）；后续 Step 编号顺延；Step "spec write" 前置条件更新为"仅在盘问步骤完成后调用"。
8. `docs/cli.md`：记录 `npc spec interrogate run|record|decide` 契约，与既有 `npc spec write|fix|review` 并列。
9. 回滚：删除三个新子命令注册与 `spec_write_run` 的硬门；`RESULT_REQUIRED_KEYS` 移除 `spec_interrogate` 键；`scripts/check_spec.py` 移除第五条规则；`/spine-spec` 恢复原 Step 顺序、移除 `--auto`。无持久化状态迁移。

## Open Questions

无。八个决策点（独立 phase 而非合并调用、硬门查磁盘不查自报、开放问题数由 npc 独立解析、decide 命令的一次性追加语义、auto 档序列化为文案指令而非代码门、多落点枚举的两道非阻断信号、`--auto` 标志复用 `/spine-run` 同构语义、interrogate 复用既有 routing/超时基础设施）均已在上文定稿，各自给出代码级依据或明确援引既有决策。不存在留待实施时决定的机制。
