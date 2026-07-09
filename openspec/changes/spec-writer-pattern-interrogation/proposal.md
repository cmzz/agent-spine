## Why

`spine-spec-writer` 目前在收到一句话目标或半成品草稿后，直接一步撰写 `proposal.md`/`design.md`/`tasks.md`/`specs/**/spec.md`。它从不显式枚举「仓库里已经有哪些与本次改动最相似的实现」，也从不把自己的关键假设摆出来给人或 reviewer 挑战——所有隐含假设第一次被检验，是在下一轮 `npc spec review run` 的 LLM 语义评审里，而那时候已经产出了一整份 artifact，返工成本远高于在动笔前把假设说清楚。

`tasks.md` 的落点清单（多处调用点/多个文件的改动分解）同样如此：判据是"reviewer 读完覚得全了"，而不是"清单能对着一条确定性命令逐项勾完"。历史上遗漏调用点属于开放式语义判定，只有 codex spec review 能拦（见 `spine-spec-writer` design.md 的核实结论），但这类问题本可以在写作阶段用一条 `grep`/`rg` 命令自查掉，不必等到语义评审。

依据 `docs/optimization-proposals/2026-07-09-bun-migration-lessons.md`「文档先行」的两条经验（Bun 的 `PORTING.md` 先盘问后写、`LIFETIMES.tsv` 用确定性清单代替印象覆盖率），本 change 给 `spine-spec-writer` 加两道机制：**盘问先于序列化**（写 artifact 前先产出一份结构化的「模式盘问」中间产物，交互档给用户裁决、auto 档序列化进 design.md 供 reviewer 攻击），以及**落点清单的确定性派生**（多落点 change 的 tasks.md 清单必须能溯源到一条写入 artifact 的搜索命令）。

## What Changes

- **新增** `npc spec interrogate run|record`：与 `npc spec write run|record` 结构同构的新 phase，`spine-spec-writer` 在写任何 artifact 之前先被 spawn 一次，产出 `openspec/changes/<id>/pattern-interrogation.md`（`## Analogs` / `## Assumptions` / `## Open Questions` 三段）。
- **新增** phase `spec_interrogate` 的 RESULT 必需键集合 `{"change","artifacts","summary"}`（不含 `validate`——该产物不是 openspec-schema 校验对象）。
- **新增** `npc spec write run` 的硬前置门：`pattern-interrogation.md` 不存在时直接 `ok=false`、`error=pattern_interrogation_missing`，MUST NOT 渲染 write prompt——机制而非文案。
- **新增** `npc spec interrogate decide --change <id> --decisions-md <text>`：纯机械追加命令，把交互档下用户对 Open Questions 的裁决原文追加进 `pattern-interrogation.md` 的 `## User Decisions (Interactive)` 段，供后续 write 轮读取。这不是内容生成，npc 不解读裁决语义。
- **新增** `npc spec interrogate record` 独立计算 `.open_questions`（解析 `## Open Questions` 段落下的顶层 bullet 数），不信任 writer 自报——`/spine-spec` 用这个数字决定是否要调用 `AskUserQuestion`。
- **修改** `/spine-spec`：新增 `--auto` 标志（与 `/spine-run` 同构：省略即交互档，关键闸口用 `AskUserQuestion` 问用户；`--auto` 全程不问人）；新增 Step "模式盘问"，插在 Step "spec write" 之前；交互档在此步用 `AskUserQuestion` 把 `pattern-interrogation.md` 的 Open Questions 摆给用户裁决，auto 档跳过。
- **修改** `render_spec_writer`（write 轮 prompt）：新增必读输入 `pattern-interrogation.md`；新增指令——按该文件是否含 `## User Decisions (Interactive)` H2 标题这一机械存在性信号（而非语义判定哪些 Open Question "已被回应"）二选一：含该标题时把 `## Open Questions` + `## User Decisions (Interactive)` 段原样写入 `design.md` 的 `## Pattern Mapping` 段；不含时把 `## Open Questions` + `## Assumptions` 段原样写入 `design.md` 的 `## Pattern Mapping` 与 `## Assumptions` 段；新增指令——若本 change 涉及 ≥2 处调用点/文件的落点清单，MUST 先跑确定性搜索命令（`grep`/`rg`/`git grep`）枚举，并把命令原文与结果计数写入 `tasks.md` 对应段落。
- **新增** `templates.render_spec_interrogator`：渲染 interrogate 轮 prompt，与 `render_spec_writer`/`render_spec_fixer` 受同一条不变量 1 约束（MUST NOT 引用本轮 spec-review 的 rubric/category 措辞）。
- **新增** `scripts/check_spec.py` 第五条规则 `touchpoint_list_missing_search_command`（`warning`，shadow mode，与既有四条同一升级判据）：`tasks.md` 中某段落若含 ≥3 条引用不同文件路径的列表项，该段内 MUST 有一个含 `grep`/`rg`/`git grep`/`git diff --name-only` 的围栏代码块，否则命中。
- **修改** `plugins/agent-spine/agents/spine-spec-writer.md`：正文补充 `spec_interrogate` phase 的职责与 RESULT 必需键。

**非目标（Non-Goals）**：

- 不改变 `npc spec write run` 对已有草稿（分支 B）以外的既有行为——盘问对分支 A/B 一视同仁地前置，但 write 轮本身的撰写逻辑不变。
- 不引入 `pattern-interrogation.md` 的 openspec-schema 校验（它不是 `openspec validate` 认识的 artifact 类型）。
- 不把 `touchpoint_list_missing_search_command` 升级为 error——按既有升级判据（正类样本 ≥ 3 个独立 change），本 change 零样本，只能以 warning 交付。
- 不改变 `npc spec review run`、fix 循环、telemetry 事件形态、`spec_write`/`spec_fix` 既有 RESULT 键集合。
- 不接管 `/spine-run` Step 2B（沿用 `spine-spec-writer` 既有非目标）。

## Capabilities

- **Modified Capabilities**: `spec-writer` —— 在 write 轮前新增强制的「模式盘问」中间产物与硬门，并给 write 轮的 tasks.md 生成加确定性落点枚举指令。
- **Modified Capabilities**: `repo-spec-lint` —— 新增第五条 shadow-mode 规则，弱校验多落点清单是否带确定性搜索命令依据。

## Impact

- **受影响代码**：`src/npc/spec_pipeline.py`（`spec_interrogate_run/record/decide`、`spec_write_run` 硬门）、`src/npc/templates.py`（`render_spec_interrogator`、`render_spec_writer` 扩写）、`src/npc/pipeline.py`（`RESULT_REQUIRED_KEYS["spec_interrogate"]`）、`src/npc/cli.py`（注册 `npc spec interrogate run|record|decide`）、`scripts/check_spec.py`（第五条规则）、`plugins/agent-spine/commands/spine-spec.md`、`plugins/agent-spine/agents/spine-spec-writer.md`、`docs/cli.md`。
- **兼容性**：`spec_write`/`spec_fix` 既有 RESULT 键集合、既有 code 流水线（`implement`/`fix`/`review`/`archive`）行为不变。`spec_write_run` 新增硬门是**破坏性**的（旧调用方若跳过 interrogate 直接调 write 会失败）——这是有意的：该门本身就是本 change 的核心诉求，`/spine-spec` 命令的 Step 顺序同步更新以适配。
- **不变量影响**：
  - **不变量 1（生成 ⊥ 验证）**：`render_spec_interrogator` 与 `pattern-interrogation.md`/`tasks.md` 的落点清单 MUST NOT 引用 `SPEC_REVIEW_SCHEMA` 的 category 枚举或任何 `round-*.spec-review.json` 原文——盘问产物讨论的是"仓库里已有什么"，不是"本轮怎么被打分"。新增负向测试覆盖 interrogate prompt。
  - **不变量 2（不信 LLM 散文）**：`.open_questions` 由 npc 独立解析 `## Open Questions` 段落计数得出，不采信 writer 自报的任何数字；`pattern_interrogation_missing` 硬门直接查磁盘文件是否存在，不采信 RESULT 自报。
  - **不变量 3（新硬轨须被真实方差打出来）**：`touchpoint_list_missing_search_command` 以 `warning` 交付、复用既有升级判据，不新增任何阻断性阈值。「先盘问后写」的顺序门本身不是质量判据（不依赖历史方差），是流程结构约束，与 `openspec validate --strict` 先于 `gate_cmd` 先于 LLM 评审的既有顺序门同类。
