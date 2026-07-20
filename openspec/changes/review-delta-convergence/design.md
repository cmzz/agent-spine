## Context

`src/npc/focus.py::_round_n_template`（`round_n >= 1`）已经区分 round-0/round-N 两套模板，并注入 Already-Fixed History（`extract_fixed_history` / `render_fixed_history_section`）避免 reviewer 重报已修复 finding。但"是否计入 blocking"仍完全由 reviewer 自报的 `severity` + `in_scope` 决定（`src/npc/review.py::parse_review`），npc 侧不做任何来源区分。这意味着 reviewer 在 round≥2 时仍可以对存量代码（既非上轮遗留、也非本轮 fix 改动）新挑出的问题判 `severity=high`，从而无限期阻塞循环，即便这些问题与本轮 fix 的实际改动无关。

`src/npc/trend.py` 已有 `STALE_THRESHOLD=3` 的止损机制，但它只在 blocking 总数连续 3 轮不严格下降时触发强制 archive，语义是"防止死循环"而非"识别健康收敛提前放行"。`src/npc/review.py::merge_review_passes` 已经提供了 `(file, line_range, category)` 三元组做 finding 去重/匹配的确定性算法，以及 `_recompute_verdict` 这一"不信任引擎自报 verdict、npc 侧重算"的先例，本 change 直接复用这两个模式。

## Goals / Non-Goals

**Goals:**

- `round_n >= 2` 时，reviewer 必须显式标注每条 finding 的来源（`finding_origin`），npc 侧对该自报做几何交叉核验后计算"有效来源"，不完全信任自报。
- 存量代码新发现的问题（有效来源 `pre-existing-new`）不计入 blocking，但仍完整保留在 `round-N.review.json` 与新增的 `round-N.advisory-carryover.md` 中，供 archive 后人工回顾。
- 连续两轮（`round_n` 与 `round_n - 1`，均需 `>= 2`，故最早在 `round_n >= 3` 生效）都没有"上轮遗留未修复"blocking 时，npc 侧确定性把本轮 `blocking` 覆盖为 `0`，`verdict` 按标准规则（advisory 非空 → `passed-with-advisory`；否则 → `approve`）重新计算，让既有的 `while [ .blocking -gt 0 ]` 循环判据（`plugins/agent-spine/commands/spine-run.md`）自然退出。
- `round_n < 2`（round 0、round 1）**派生的** `blocking`/`advisory`/`verdict` 计算语义与本 change 引入前一致：仍完全由自报 `severity`/`in_scope` 决定，不计算/应用 `effective_origin`。这不等于"输出内容逐字节不变"——`REVIEW_SCHEMA` 新增必填字段 `finding_origin` 对所有轮次生效，`_output_requirements_block` 的字段说明文本也对 round 0/1 同样新增，二者是本 change 有意引入的破坏性变更（见 Migration Plan）。

**Non-Goals:**

- 不改变 `trend.py` 的 stale 止损机制；两套收敛判据并存。
- 不识别/校正 reviewer 在 `severity` 字段本身的自报可靠性（例如刻意把应为 `medium` 的问题报成 `high` 以让它计入 blocking）——本 change 的几何交叉核验只约束 `finding_origin`，不扩展到 `severity`。
- 不改变 round 0 / round 1 的 verdict 计算路径（仍直接信任引擎自报值，不引入 `_recompute_verdict` 之外的重算）。
- 不改变 spec review（`SPEC_REVIEW_SCHEMA` / `spec_pipeline.py`）。

## Pattern Mapping

> 本段落原样带入 `pattern-interrogation.md` 的 `## Open Questions` 与 `## User Decisions (Interactive)`（该文件含 `## User Decisions (Interactive)` 标题，按契约取该分支）。

### Open Questions

- 硬收敛规则「连续两轮无上轮遗留未修复的 blocking 即 approve」的落地位置：是在
  `pipeline.py::_do_review_phase_exit_and_trend`（或紧邻新函数）里做 npc 侧确定性覆盖 verdict
  （类似 `_recompute_verdict` 风格，不依赖 reviewer 自报的 verdict 字段），还是仅通过 focus
  prompt 指示 reviewer 自行在 `verdict` 字段体现该规则？两种实现的可信度和确定性程度不同，
  需要用户拍板。
- 「本轮 fix diff 新引入的问题」的判定，是否需要在 `REVIEW_SCHEMA` 里新增一个显式字段（如
  `finding` 增加 `carry_over: bool` 或复用/扩展 `spec_attribution` 式的枚举），让 reviewer
  自报并结构化产出，还是完全由 npc 侧用 `(file, line_range, category)` 与上轮
  `round-{N-1}.review.json` 的 blocking 集合做几何匹配、reviewer 侧不感知这个区分？
- advisory 降级后的持久化形态：是否需要新增一份「存量问题清单」产物（例如
  `round-N.advisory-carryover.md` 或写入 `change.md` 的固定段落），供 archive 后人工回顾，
  还是维持现状（信息只留在各轮 `round-N.review.json` 里，state 只存计数）？

### User Decisions (Interactive)

#### Q1 硬收敛规则落地位置
问题：连续两轮无"上轮遗留未修复"blocking 即 approve——npc 侧确定性覆盖 verdict，还是仅 focus prompt 指示 reviewer 自报？
用户裁决：**npc 侧确定性覆盖**。在 pipeline 的 review 阶段结束处按上轮匹配结果确定性改写 verdict（_recompute_verdict 风格），不依赖 reviewer 自觉。

#### Q2 carry-over vs 新问题的归属判定
问题：是否在 REVIEW_SCHEMA 新增显式字段让 reviewer 自报，还是 npc 侧纯几何匹配？
用户裁决：**schema 加字段 + npc 校验**。REVIEW_SCHEMA 的 finding 新增 carry_over/origin 枚举由 reviewer 结构化自报；npc 侧再用 (file, line_range, category) 与上轮 round-{N-1}.review.json 的 blocking 集合做交叉核验。

#### Q3 advisory 降级后的持久化形态
问题：是否新增"存量问题清单"产物供 archive 后回顾？
用户裁决：**新增 carryover 清单产物**。每轮写 round-N.advisory-carryover（或 archive 时汇总一份清单），供人工回顾，不阻塞流程。

### 落地映射（本 change 如何兑现三条裁决）

- Q1 → 见 Decisions D5：`run_review_round` 在 `round_n >= 3` 时读取 state 中前一轮持久化的 `carryover_unresolved_blocking`，与本轮值一起做 npc 侧确定性覆盖，不依赖 focus prompt 文案让 reviewer "自觉"。
- Q2 → 见 Decisions D1/D2：`REVIEW_SCHEMA.finding_origin` 由 reviewer 结构化自报三值枚举；`parse_review` 的几何交叉核验（`(file, line_range, category)` 命中上一轮 blocking 集合）对自报值做覆盖，几何命中优先于自报。
- Q3 → 见 Decisions D6：每个 `round_n >= 2` 轮次落盘 `round-{round_n}.advisory-carryover.md`（每轮独立快照，不做跨轮汇总——见 proposal Non-Goals 的显式收窄）。

## Decisions

**D1：REVIEW_SCHEMA 新增 `finding_origin` 三值枚举字段，对所有轮次统一生效。**

`src/npc/schema.py::REVIEW_SCHEMA` 的 finding `required` 新增 `finding_origin`，`enum` 为 `["carry-over-unresolved", "round-diff-new", "pre-existing-new"]`：

- `carry-over-unresolved`：与上一轮已报告且仍未修复的 blocking finding 是同一个问题。
- `round-diff-new`：位置落在当前评审 diff 新引入/修改的代码内（round 0/1 语境下即整段 diff；round≥2 语境下特指本轮 fix 新增的增量 diff）。
- `pre-existing-new`：位置落在 diff 未修改的既有代码内，是本次新发现的既有问题。

字段对 round 0/1 也必填（保持 schema 单一、避免按轮次分裂 schema 变体），但只有 `round_n >= 2` 时才参与 blocking 计算（见 D3）；round 0/1 语境下 reviewer 按"无更早轮次，不选 `carry-over-unresolved`"的约定天然兼容。这是对所有轮次（含 round 0/1）都生效的**破坏性 schema 变更**：round 0/1 的 review JSON 从此也必须包含该字段，缺字段的 JSON（含本 change 落地前的旧 producer/旧 prompt 输出）会被 `REVIEW_SCHEMA` 拒绝——round 0/1 保持不变的只是 `blocking`/`advisory`/`verdict` 的**派生计算方式**（见 D7），不是 JSON 结构或 focus 提示文本本身（见 Migration Plan）。`SPEC_REVIEW_SCHEMA` 不受影响。

`finding_origin` 与既有 `in_scope` 字段回答的是两个正交问题，不存在互相覆盖或需要仲裁优先级的冲突，二者以逻辑 AND 组合参与 blocking 判定（见 D2）：

- `in_scope`（既有字段，语义不变）：该位置是否落在本次 change **累计** diff 范围内（`{implement_commit}~1..HEAD`）。
- `finding_origin` 的 `round-diff-new`/`pre-existing-new` 二分（仅在 `round_n >= 2` 的 delta 语境下参与 blocking 计算）：该位置是否落在**本轮 fix 自身**的增量 diff 范围内（`{round_fix_commit}~1..{round_fix_commit}`，比累计 diff 更窄）。

因此一条 `in_scope=true`（位于累计 diff 内）但有效来源为 `pre-existing-new`（未被本轮增量 diff 触碰，是本轮新发现的既有问题）的 finding 是合法、非冲突的组合——它表示"这段代码是本 change 之前某一轮引入的，本轮 fix 没有再碰它，reviewer 这轮才第一次挑出这个问题"；`in_scope=false` 的 finding 无论 `finding_origin` 取何值都已经因 `in_scope` 本身不满足 blocking 判定的必要条件而不计入 blocking（既有语义不变，不依赖本 change 新增判定）。

`finding_origin` 是 reviewer 结构化自报字段，理论上不是每条 finding 都能天然对应到单一明确代码位置——删除代码引发的问题、缺失实现（应新增但未新增的逻辑）、跨文件交互缺陷、`line_range` 为占位符 `"-"` 或无法解析等边界场景均需要明确的分类优先级，否则同一场景下不同合理分类会产生不同 `verdict`（无确定性）。spec.md「findings 携带结构化的来源自报字段」Requirement 定义了确定性优先级：任一涉及位置触及本轮 fix 增量 diff 即归 `round-diff-new`；仅当全部涉及位置均明确位于增量 diff 之外才归 `pre-existing-new`；无法归属单一明确位置（含 `line_range` 为占位符或无法解析、跨模块设计层面问题）时保守归 `round-diff-new`，不允许因归属模糊而被静默排除出 blocking 判定。该优先级规则由 D4 的 focus 模板分类准则文案传达给 reviewer。

备选是只对 round≥2 生效的独立 schema 变体；放弃，因为 `ensure_schema`/`run_review_round` 目前按单一 `REVIEW_SCHEMA` 路径工作，引入按轮次切换 schema 会新增一条从未有过的分支，风险高于统一必填字段的成本。

**D2：`_finding_key`（精确三元组，供 `merge_review_passes` 既有同轮去重复用）与新增的 `_is_carry_over_match`（区间重叠，供跨轮 carry-over 匹配）是两个不同用途的函数；`parse_review` 扩展 `round_n`/`prior_blocking` 可选参数做几何交叉核验。**

把 `merge_review_passes` 内部的 `_key()` 提升为 `review.py` 模块级 `_finding_key(f) -> tuple`（`(file, line_range, category)`），`merge_review_passes` 改为调用该共享函数（内部重构，不改变其既有对外契约与测试）。这个精确三元组函数只服务于 `merge_review_passes` 现有的"同一轮内跨 pass 去重"场景，`(file, line_range, category)` 在同一轮内本就应逐字符相等，不存在跨轮行号漂移问题。

跨轮 carry-over 匹配是单独的新增函数 `_is_carry_over_match(finding, prior_finding) -> bool`，判据：

1. `finding["file"] == prior_finding["file"]`（精确匹配）。
2. `finding["category"] == prior_finding["category"]`（精确匹配）。
3. `line_range` 做**区间重叠**而非逐字符相等比较，解析规则覆盖 `REVIEW_SCHEMA` 允许的全部输入域、且 MUST 确定性、MUST NOT 抛出异常：
   - 可解析：单行 `"N"`（视为区间 `[N, N]`）、区间 `"N-M"`（`N`/`M` 为非负整数，允许前后及连字符两侧空白，如 `"10 - 20"`）。若 `N > M`（反向区间，如 `"25-15"`），MUST 取 `[min(N,M), max(N,M)]` 归一化后再参与比较，不视为非法。
   - 不可解析：占位符 `"-"`（允许前后空白）、空字符串、或任何无法从中提取出两个整数端点的字符串（如任意自由文本）。
   - 判定规则：只要参与比较的两条 finding（本轮 finding 与 `prior_blocking` 中的条目）之一的 `line_range` 不可解析，`_is_carry_over_match` MUST 直接返回 `False`（不做区间比较、不抛异常）；两者均可解析时才执行 `max(start1, start2) <= min(end1, end2)` 的重叠判定。
   - 可解析且重叠时视为同一问题，容忍修复本身导致的行号小幅漂移（插入/删除若干行使区间整体上移/下移，但两区间仍有交集的常见情形）。若修复导致区间整体位移到完全不重叠（如函数被移动到文件很远处），或 `line_range` 不可解析，或 reviewer 把 `category` 改写为不同取值，则 `_is_carry_over_match` 判定为不匹配——这是已记录的接受限制（见 Risks），不在本 change 范围内用启发式文本相似度等方式进一步兜底。

`parse_review(review_json, *, round_n: int = 0, prior_blocking: list[dict] | None = None)`：

- `round_n < 2` 或 `prior_blocking is None`：忽略 `finding_origin` 字段，`verdict` 直接取自报值——这是**派生计算方式**不变，不代表输入 JSON 结构或返回值 keys 集合不变（返回值新增的 `carryover_unresolved_blocking`/`finding_origins` 两键此时为 `None`/空列表，是本 change 引入的新增返回字段，见下）。
- `round_n >= 2` 且提供 `prior_blocking`：对每条 finding 计算「有效来源」`effective_origin`：
  1. 存在 `g in prior_blocking` 使 `_is_carry_over_match(f, g)` 为真 → `effective_origin = "carry-over-unresolved"`（几何命中覆盖自报值，即使自报为其它值）。
  2. 未命中且自报 `finding_origin == "carry-over-unresolved"`（自报声称是遗留但几何核验不通过）→ `effective_origin = "round-diff-new"`（保守回退，仍计入 blocking 候选，不允许"自称遗留但查无实据"被当场判定为不可信而直接丢弃阻塞资格）。
  3. 未命中且自报为 `round-diff-new` / `pre-existing-new` → 直接采用自报值。
  4. 自报字段缺失或非法枚举值（防御性分支，理论上 schema 已强制必填合法枚举）→ 回退 `round-diff-new`（保守：不允许无法归类的 finding 被静默排除在 blocking 判定外）。
- blocking 判定：`severity ∈ {critical, high} and in_scope and effective_origin != "pre-existing-new"`（`in_scope` 与 `effective_origin` 是两个独立必要条件，逻辑 AND 组合，无优先级仲裁，见 D1）。
- `verdict` 在此调整后的 blocking 集合上重新计算（存在 blocking → `changes-requested`；否则 findings 非空 → `passed-with-advisory`；否则 → `approve`），不采信引擎自报 `verdict`（与 D7 的"round 0/1 仍信任自报 verdict"形成的差异，见 Risks）。
- 返回值新增 `carryover_unresolved_blocking: int | None`（`round_n < 2` 或未提供 `prior_blocking` 时为 `None`；否则为有效来源 `carry-over-unresolved` 且满足 blocking 判定的 finding 数）与 `finding_origins: list[dict]`（`[{"id": ..., "effective_origin": ...}]`，供渲染 `round-N.advisory-carryover.md` 与测试断言使用）。

备选是把几何核验做成独立的 `review.py` 新函数（不塞进 `parse_review`）；放弃，因为 blocking/advisory/verdict 三者必须在同一份"有效来源"计算结果上保持一致，拆成两个函数需要调用方手动对齐两次计算的输入，容易产生"覆盖了 blocking 但漏覆盖 verdict"一类的漂移。

**D3：`pre-existing-new` 的 finding 不计入 blocking，但完整保留在 `round-N.review.json` 与 advisory 计数中。**

`parse_review` 不修改/丢弃任何 finding 记录本身（`round-N.review.json` 落盘内容与引擎原始输出一致，不做 npc 侧重写）；`effective_origin == "pre-existing-new"` 只影响 `parse_review` 派生的 `blocking`/`advisory`/`blocking_findings`/`verdict` 四个计算结果，即：这类 finding 从 `blocking_findings` 移入 `advisory` 计数，不再触发 `src/npc/fixer.py::render_findings` 渲染进下一轮 fix prompt（`fixer.py` 现有"仅渲染 blocking_findings"逻辑天然兼容，无需改动）。

**D4：`_round_n_template`（`round_n >= 2`）新增 delta 分类规则块与本轮增量 diff 指令；`round_n < 2` 不追加该规则块，但 `_output_requirements_block` 的字段说明新增行对所有轮次生效（不是"逐字节不变"）。**

`src/npc/focus.py::_round_n_template` 新增可选参数 `round_fix_commit: str | None = None`（`round_n >= 2` 时由 `pipeline.py::_render_focus` 传入上一轮 `fix-r{round_n-1}` 阶段记录的 `commit`）。两部分内容条件独立，均只在 `round_n >= 2` 时才可能追加：

1. **分类准则文案（始终追加，不依赖 `round_fix_commit`）**：`round_n >= 2` 时 MUST 无条件追加 `finding_origin` 三值分类准则文案（对齐 D1 的枚举语义），显式说明 `finding_origin` 与 `in_scope` 是两个正交问题（前者看本轮增量 diff、后者看累计 diff，见 D1）与"不要为了让 finding 计入 blocking 而误填"的提示。该文案 MUST 包含 D1 定义的边界场景确定性优先级规则（删除代码、缺失实现、跨文件交互、无法归属单一位置或 `line_range` 为占位符等场景：任一位置触及增量 diff 归 `round-diff-new`；仅全部位置明确在增量 diff 之外才归 `pre-existing-new`；无法判定时保守归 `round-diff-new`），不能只是三值枚举名称的罗列。这段文案不依赖是否提供了 `round_fix_commit`——即使 `round_fix_commit` 缺失，reviewer 仍需要知道三值分类准则本身，只是少了一条辅助 diff 指令来精确核对。
2. **增量 diff 指令（仅当 `round_fix_commit` 非空时追加）**：指令 `git --no-pager diff {round_fix_commit}~1..{round_fix_commit}`，用于核对某 finding 是否落在"本轮 fix 自身引入"的范围内（区别于既有的累计 diff 指令 `git diff {implement_commit}~1..HEAD`，二者并存，前者用于 `finding_origin` 分类，后者用于整体审阅范围）。

`round_fix_commit` 缺失（如历史 state 缺该字段）时只跳过第 2 部分（增量 diff 指令），第 1 部分（分类准则文案）仍然追加——模板不会退化到"完全不含 delta 规则"的状态，只是损失一条辅助指令，`finding_origin` 仍可基于 Already-Fixed History 与 change.md 既有信息填写。`round_n < 2` 分支两部分均不追加。

`_output_requirements_block` 新增常量 `FINDING_ORIGIN_ENUM_SEMANTICS`（对齐 `SPEC_ATTRIBUTION_ENUM_SEMANTICS` 先例），在"字段含义"列表追加一行 `finding_origin` 说明，对 round 0/1/N **统一生效**（字段必填，语义单一来源）——这意味着 round 0/1 的模板渲染输出文本本身会新增这一行，不是"逐字节不变"；round 0/1 唯一不变的是 `parse_review` 对该字段的**派生计算方式**（忽略它，见 D2/D7）。

**D5：硬收敛覆盖在 `run_review_round` 内、`_do_review_phase_exit_and_trend` 调用之前完成，覆盖后的结果贯穿 state / telemetry / fixer 渲染 / 返回值；`prior_blocking` 必须来自上一轮持久化的最终有效 blocking 集合，而非重新默认解析上一轮原始 JSON。**

`run_review_round`：

1. 构造 `prior_blocking`（`round_n >= 2` 时需要）：
   - `round_n == 2`：读取 `round-1.review.json`，用 `parse_review`（默认参数，不传 `round_n`/`prior_blocking`）取其 `blocking_findings` 作为 `prior_blocking`。round 1 没有 delta 计算概念，其 `blocking_findings` 就是朴素 `severity`/`in_scope` 语义下的原始集合，直接复用是安全的。
   - `round_n >= 3`：从 state 读取 `entry["phases"][f"review-r{round_n-1}"]["effective_blocking_findings"]`（见步骤 5 的持久化定义）作为 `prior_blocking`；若该字段缺失（历史 state，早于本能力落地的进行中 run），`prior_blocking` MUST 取值 `None`（不是 `[]`，见 Migration Plan 第 2 条的语义区分）。**MUST NOT** 通过对 `round-{round_n-1}.review.json` 重新执行不带 `round_n`/`prior_blocking` 的默认 `parse_review` 来重建 `prior_blocking`——那样会把上一轮已经因 `pre-existing-new` 被移出 blocking 的 finding、或已被上一轮硬收敛覆盖降级的 finding，重新当作"上一轮 blocking"计入本轮的几何核验基准，违背"`prior_blocking` = 上一轮最终 blocking_findings"的定义，可能导致同一 finding 被反复误判、或错误地重新触发 `carry-over-unresolved` 匹配（这是本轮修复的问题，见本 change 的 spec.md「跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果」Requirement）。
2. 调用 `parse_review(review_data, round_n=round_n, prior_blocking=prior_blocking)` 得到 `metrics`。
3. `round_n >= 3`：从 state 读取 `entry["phases"][f"review-r{round_n-1}"]["carryover_unresolved_blocking"]`（记为 `prev_carryover`）。若 `prev_carryover == 0` 且 `metrics["carryover_unresolved_blocking"] == 0`：构造覆盖后的 `effective_metrics`——`blocking=0`、`advisory = metrics["advisory"] + len(metrics["blocking_findings"])`、`blocking_findings=[]`、`hard_convergence_applied=True`；`verdict` 按标准规则在覆盖后的集合上重新计算（`advisory > 0` → `"passed-with-advisory"`；否则 → `"approve"`，与既有 REVIEW_SCHEMA 的 verdict 语义、spec.md 第 49-51 行的规则完全一致，不再固定写死 `"approve"`）。原属 blocking 的 finding，无论其 `effective_origin` 是 `carry-over-unresolved` 还是 `round-diff-new`，均转记为 advisory——按用户裁决"连续两轮无遗留 blocking 即不再阻塞，advisory 照常携带"字面执行，见 Risks 对此的显式讨论。
4. 不满足覆盖条件（含 `round_n < 3`、`prev_carryover` 字段缺失即视为不满足）：`effective_metrics = metrics`（附加 `hard_convergence_applied=False`）。
5. `_do_review_phase_exit_and_trend`、`_telemetry.emit_review_round`、`fixer.render_findings` 触发条件（`blocking > 0`）、函数返回值，全部改用 `effective_metrics`（不是原始 `metrics`），确保 state/telemetry/循环判据三者一致。
6. `_do_review_phase_exit_and_trend` 写入的 `new_phase` 字典新增三个键：`carryover_unresolved_blocking` / `hard_convergence_applied` / `effective_blocking_findings`（`round_n >= 2` 时为 `effective_metrics["blocking_findings"]` 中每条 finding 的 `{file, line_range, category}` 三元组列表，供下一轮 `round_n + 1 >= 3` 时读取作为 `prior_blocking` 来源；`round_n < 2` 时三键分别写 `None` / `False` / `None`）。

备选是把硬收敛判定放进 `_do_review_phase_exit_and_trend` 内部（与 state mutate 合并成一次 IO）；放弃，因为该函数当前只负责"写入已给定的 metrics"，判定逻辑需要读 `prior_blocking`（跨文件 IO）与之前轮次的 state，混入会让该函数职责从"原子写入"膨胀为"计算 + 写入"，且 telemetry/fixer 渲染都在其调用前后独立发生，覆盖必须在它们共同的上游一次性完成才能保证一致性。

**D6：新增 `round-{round_n}.advisory-carryover.md`（`round_n >= 2`），复用 `fixer.render_findings` 渲染。**

`run_review_round` 在 `round_n >= 2` 时，把 `finding_origins` 中 `effective_origin == "pre-existing-new"` 对应的原始 finding，加上（若发生）D5 硬收敛覆盖降级的原 blocking findings，合并为一个列表，用既有 `src/npc/fixer.py::render_findings` 渲染（该函数已处理空列表 → `"（本轮无 in_scope blocking findings）\n"` 文案，此处复用时允许该文案原样出现，含义仍准确：本轮无需强制修复的 finding）写入 `round-{round_n}.advisory-carryover.md`。该产物是每轮独立快照，不做跨轮汇总/去重（对齐 proposal Non-Goals）。

**D7：`round_n < 2` 的执行路径与派生判定语义不受影响；既有 stale 机制不受影响。**

`round_n ∈ {0, 1}` 路径不调用任何 D1-D6 新增的 delta 计算逻辑（`parse_review` 默认参数、`_round_n_template` 不追加 delta 规则块、`run_review_round` 跳过跨轮读取与硬收敛判断）——round 0/1 的 `blocking`/`advisory`/`verdict` 计算方式与本 change 引入前一致。这条"不受影响"承诺的范围**仅限于派生计算方式**，不包括 REVIEW_SCHEMA 新增必填字段 `finding_origin`（D1，对所有轮次生效）或 `_output_requirements_block` 新增的字段说明文本（D4，对所有轮次生效）——这两者是本 change 有意引入、对 round 0/1 同样生效的破坏性变更，round 0/1 的 review JSON 结构与 focus 提示文本因此确实会变化（见 Migration Plan）。`trend.py` 的 `update_trend`/`check_stale`/`STALE_THRESHOLD` 不做任何修改，二者与本 change 的硬收敛覆盖各自独立写入/读取 state 的不同字段（`blocking_trend`/`rounds_since_strict_decrease` vs `carryover_unresolved_blocking`/`hard_convergence_applied`），互不干扰、互不替代。

## Risks / Trade-offs

- **[硬收敛覆盖可能豁免 `round-diff-new` blocking]** 用户裁决字面表述是"连续两轮无『上轮遗留未修复』的 blocking 即不再阻塞"，只约束 `carry-over-unresolved` 子集为零，不要求 `round-diff-new` 子集也为零。因此存在这种情形：round 2、round 3 均无遗留 blocking，但 round 3 本身有一条全新的、位于本轮 fix diff 内的 `round-diff-new` blocking，仍会被硬收敛覆盖为 `blocking=0`（`verdict` 因该 finding 转记为 advisory 而通常是 `passed-with-advisory`，不是 `approve`——只有当覆盖前本就没有任何 advisory/blocking finding 时才会是 `approve`）。这是按用户原话字面实现的结果（"总是能修复但总有新小问题"场景下避免死循环），但会放行一条尚未处理的新 blocking finding。缓解：该 finding 不会被丢弃——D5 步骤 3 明确把它转记为 advisory 并写入 `round-{round_n}.advisory-carryover.md`，archive 后可人工回顾；且这是显式裁决的产物，非本 change 引入的隐藏行为，已在 proposal 与本节中显式记录供用户/审阅者复核。
- **[`severity` 自报、以及 `round-diff-new`/`pre-existing-new` 自报仍不受几何核验约束]** reviewer 理论上可以把本应 `pre-existing-new` 的问题谎报为 `round-diff-new` 以维持 blocking 资格（或反向操作规避 blocking）。本 change 只对 `finding_origin` 的 `carry-over-unresolved` 子集做几何核验（`_is_carry_over_match` 命中 `prior_blocking`），`round-diff-new`/`pre-existing-new` 二者之间的自报值本身不做 npc 侧几何核验（不解析 `round_fix_commit` 的实际 diff 内容逐行比对 finding 位置）——`_round_n_template` 只是把增量 diff 指令交给 reviewer 自行核对，不代表 npc 侧确定性校验。这与既有 `parse_review` 对 `severity`/`in_scope` 的信任模型一致，不是本 change 引入的新风险面，但也意味着"存量代码新发现问题一律降级"的核心收益仍部分依赖 reviewer 自报的可靠性。
- **[跨轮 finding 身份匹配依赖 `(file, category)` 精确匹配 + `line_range` 区间重叠，无法覆盖所有场景]** `_is_carry_over_match`（D2）用区间重叠替代逐字符相等，缓解了修复导致行号小幅漂移的常见情形，但两类情形仍无法被识别为同一问题：(a) 修复导致该问题的代码被移动到区间完全不重叠的位置（如函数搬到文件另一端）；(b) reviewer 在两轮之间把同一问题的 `category` 改写为不同取值。这两种情形下，`_is_carry_over_match` 判定为不匹配，`effective_origin` 按 D2 规则回退（若自报仍为 `carry-over-unresolved` 则降级为 `round-diff-new`，否则采用自报值）——finding 本身不会被丢弃或静默排除出 blocking 判定（仍计入 blocking 候选，除非自报为 `pre-existing-new`），但会被错误地排除出 `carryover_unresolved_blocking` 计数，理论上可能导致连续两轮的该计数被错误地记为 0，从而触发本不该发生的硬收敛覆盖。缓解：(1) 该 finding 若确实构成 blocking（`round-diff-new` 分支），仍会出现在 `blocking_findings` 中，只是不计入 `carryover_unresolved_blocking`——与上一条 Risk（硬收敛可能豁免 `round-diff-new` blocking）是同一类已接受的字面裁决后果，而非本 change 引入的新失效模式；(2) `round≥2` 的 focus 模板已注入 Already-Fixed History，提示 reviewer 不要随意改写已知问题的 `category`；(3) 该 finding 无论如何都会被完整保留在 `round-N.review.json` 与（若被降级）`round-{round_n}.advisory-carryover.md` 中，供人工回顾发现误判。本 change 不引入基于文本相似度等启发式的进一步兜底，超出本次范围。
- **[`round_fix_commit` 缺失导致辅助指令缺位]** 历史 run 若 `fix-r{round_n-1}` 阶段记录缺 `commit` 字段（不应发生，但防御性处理），`_round_n_template` 退化为不含增量 diff 指令的版本；`finding_origin` 判断精度下降但不阻断渲染，符合仓库既有"缺失历史数据时降级但不失败"的惯例（对照 `_render_focus` 对 state 缺失的处理）。

## Migration Plan

1. `REVIEW_SCHEMA` 新增必填字段会被 `ensure_schema`（内容比对触发重写）自动同步到 `~/task_log/.new-plan-review-schema.json`，无需手工迁移。
2. 历史 state（`progress[].phases["review-rN"]` 缺 `carryover_unresolved_blocking`/`hard_convergence_applied`/`effective_blocking_findings`）分别按 `None`/`False`/`None` 读取，round 2/3 判定天然按"不满足覆盖条件"处理，不会对正在进行中的旧 run 产生意外的覆盖；`round_n == 2` 分支不依赖该字段（直接对 round-1.review.json 走默认 `parse_review`）。`round_n >= 3` 时若上一轮 `effective_blocking_findings` 字段缺失，`run_review_round` 传给 `parse_review` 的 `prior_blocking` MUST 为 `None`（不是 `[]`）：`None` 会命中「round_n < 2 或 prior_blocking 为 None 时 MUST NOT 计算 effective_origin」的既有降级路径，本轮完全信任自报 `severity`/`in_scope`/`verdict`（等价于该轮临时退化为 round<2 的计算方式）；而 `[]` 会被当作"有 prior_blocking 但为空集合"，正常进入几何核验路径（只是没有历史 blocking 可命中，所有自报 `carry-over-unresolved` 都会回退为 `round-diff-new`），仍会重算 `verdict`——两者结果不同，本 change 选择前者（`None`），因为空历史数据语义上更接近"无法判定"而非"确认没有遗留 blocking"，详见 spec.md 对应 Scenario。
3. `finding_origin` 是对所有轮次（含 round 0/1）生效的破坏性 schema 变更：本 change 落地后，任何**当前正在生成**的轮次的 review JSON（即引擎产出后、写入 `round-{round_n}.review.json` 前触发的写入前 `jsonschema.validate` 校验门）若缺该字段或取值非法枚举，均会被 `REVIEW_SCHEMA` 拒绝（见 spec.md「findings 携带结构化的来源自报字段」Requirement 的 Scenario）；唯一需要确认的是 focus 提示文本（`_round_n_template`/`_output_requirements_block`）已同步要求 reviewer 输出该字段（D1/D4），否则新一轮 review 会持续产出未通过 schema 校验的 JSON。

   这条拒绝规则 MUST NOT 扩展到"读取磁盘上历史 `round-M.review.json` 做内部计算"这一路径——`round_n == 2` 时（D5 步骤 1）系统会对 `round-1.review.json` 执行默认 `parse_review`（不带 `round_n`/`prior_blocking`）以提取 `prior_blocking`，这是一次纯函数只读提取（`parse_review` 默认模式不引用 `finding_origin`，不做 schema 校验），MUST 兼容本 change 落地前已完成 round 1、落地后才继续 round 2 的进行中 run——即使其 `round-1.review.json` 缺 `finding_origin` 字段，`prior_blocking` 提取仍须成功、round 2 的 delta 计算仍须正常进行，不因升级中途而中止或降级（见 spec.md「跨轮 prior_blocking 必须来自上一轮持久化的有效 blocking 结果」Requirement 对应 Scenario）。这与"review 阶段 JSON 每轮实时生成"的既有事实并不冲突：`prior_blocking` 提取消费的是**上一轮**已经生成并落盘的产物，不是"迁移旧 JSON 文件"意义上的批量迁移，只是一次跨轮读取，因此不需要额外的文件迁移脚本，只需明确 schema 拒绝规则的作用范围。
4. 回滚：移除 D1-D6 增量代码与 state 新字段读取分支即可；`round_n < 2` 的派生计算路径本就不依赖它们（但 D1 的 schema 必填字段回滚会同时影响所有轮次，需与代码回滚一并处理，不能只回滚部分轮次）。

## Open Questions

无。三条关键裁决已在 Pattern Mapping 段落记录并在 Decisions D1/D2/D5/D6 中兑现；本轮 spec-fix 新增的匹配算法调整（区间重叠替代逐字符三元组相等）、`prior_blocking` 持久化来源修正、verdict 计算方式修正，均是在不改变三条用户裁决字面结论的前提下修复的实现层矛盾（详见 round-1.spec-fix.summary.md）。round-3 spec-fix 进一步明确了两点：(1) `finding_origin` 边界场景（删除代码/缺失实现/跨文件交互/无法归属单一位置）的确定性分类优先级（D1/D4）；(2) `finding_origin` schema 拒绝规则的作用范围仅限当前正在生成的那一轮，不扩展到对历史 `round-1.review.json` 的只读 `prior_blocking` 提取，确保升级中途的进行中 run 兼容（Migration Plan 第 3 条）。
