# Pattern Interrogation — review-delta-convergence

## Analogs

- `src/npc/focus.py::_round_n_template`（L281-317）— 现有 round≥1 focus 模板已经与
  round-0 (`_round_0_template`) 分叉：注入 `Already-Fixed History`（见下条）、要求「验证
  上轮 findings 是否被真正修复」「不要重复列已修复的项」。这是本次改动**最直接的落点**——
  delta-review 模式（round≥2 只验证上轮 blocking + 新 diff 问题）应该在这个函数（或它拆出的
  新分支）里实现，而不是另起一套模板机制。

- `src/npc/focus.py::extract_fixed_history` / `render_fixed_history_section`（L26-84）—
  已有「从 `round-{1..N-1}.fix.summary.md` 的 `## Per-Finding Resolution` 段抽取修复记录并
  注入 focus.md」的完整管线，且已序列化 `fixed-history.json`（`write_fixed_history_json`，
  L87-95）供调试。本次「逐条核验上轮 blocking finding 的修复状态」应**复用**这条既有管线，
  而非新造一套 finding-tracking 机制。

- `src/npc/focus.py::_adversarial_round_0_template` + `ReviewEngineConfig.adversarial_round0`
  （`src/npc/config.py` L67-70,L89-92）— 仓库里已有「按轮次切换 review 行为」的先例：
  round-0 在 compliance pass 之外可选追加一次 diff-only 对抗式 pass，`round_n != 0` 时该配置
  无效（恒单通道）。这印证了 `docs/optimization-proposals/2026-07-20.md` 建议 1 诊断中的
  「架构上已有轮次分层先例，但主 review 没有分层」——本次改动是把这套「按 round_n 分支渲染
  + 按 config 开关」的模式，从 `round==0` 维度平移到 `round>=2` 维度。

- `src/npc/review.py::parse_review`（L29-69）与 `_recompute_verdict`（L72-86）— 现有
  verdict/blocking/advisory 的计算**完全由 npc 侧确定性重算**，不采信引擎自报的 verdict
  字段本身的权威性（`_recompute_verdict` 的 docstring 明写「不采信任一 pass 自报的
  verdict」，`merge_review_passes` 同理，L97-98）。这是本次「(c) 存量代码新发现问题一律降级
  advisory」「硬收敛规则连续两轮 approve」的关键先例：降级/收敛判定应该做成 npc 侧对
  `findings` 数组的确定性后处理（如 `parse_review` 增加一个 round-aware 变体，或在
  `merge_review_passes` 旁新增一个「carry-over 加权」函数），而不是仅指望 prompt 文案让
  reviewer 自觉遵守。

- `src/npc/review.py::merge_review_passes`（L89-133）— 提供了「用 `(file, line_range,
  category)` 三元组做 finding 去重/匹配键」的确定性算法，以及「合并后在全集上重算 verdict、
  side-channel 统计单独来源的 blocking 数（`adversarial_blocking_count`）」的模式。这正是
  「区分上轮遗留 blocking vs 本轮 diff 新引入 blocking」所需要的键匹配算法的现成模板——
  应复用同一个 `_key()` 函数或其等价物，而不是发明新的 finding 身份判定规则。

- `src/npc/trend.py`（全文件）— 已有一套独立的「blocking 趋势 + 收敛」机制：
  `STALE_THRESHOLD = 3`（L17），`update_trend` 维护 `rounds_since_strict_decrease`
  （L129-141, L171-214：持平或上升则计数器 +1，严格下降则清零），`check_stale`
  判定 `rsd >= STALE_THRESHOLD`（L217-247）。这是仓库里**唯一现存的「跨轮收敛」判据**，
  但语义是「blocking 总数连续 N 轮不降 → 视为 stale，交给 `auto_decide` 强制 archive」，
  与本次要求的「连续两轮无遗留未修复 blocking → 直接 approve」是**不同的收敛路径**（一个是
  兜底止损，一个是正向提前批准）——需要在 design 里明确两者关系（见 Assumptions / Open
  Questions）。

- `src/npc/pipeline.py::_do_review_phase_exit_and_trend`（L396-507）— 每轮 review 结束时
  把 `verdict` / `blocking` / `advisory` / `categories` 写入
  `entry["phases"][f"review-r{N}"]`、更新 `entry["blocking_trend"]` /
  `entry["rounds_since_strict_decrease"]`。这是本次新增「硬收敛规则」判定与状态写入的落点
  ——新规则大概率要在这个函数（或紧邻的新函数）里，对比本轮与上一轮的「遗留未修复 blocking」
  集合，而不是新开一条平行的 state 更新路径。

- `src/npc/auto_decide.py`（L1-40+）— `stale` 是 `VALID_TRIGGERS` 之一，consumers 用
  `rounds_since_strict_decrease` 决策 `continue-retry` / `force-archive`。若本次新增的硬收敛
  规则要落地为一个新的自动 approve 触发点，需要判断它是接入 `auto_decide` 现有的
  trigger/action 体系，还是在 `pipeline.py` 的 review-round 主循环里直接短路（更接近
  `_recompute_verdict` 那种「npc 侧确定性覆盖」的风格）。

- `src/npc/schema.py::REVIEW_SCHEMA`（L14-94）— findings 每条的 `required` 字段目前是
  `id/severity/category/title/file/line_range/detail/recommendation/in_scope/
  spec_attribution`，**没有**任何「是否属于本轮新引入 diff」或「是否与上轮某条 blocking
  同源」的字段。`spec_attribution` 四值枚举本身就是「先加 schema 字段 + 单一语义来源常量
  （`SPEC_ATTRIBUTION_ENUM_SEMANTICS`，focus.py L185）+ 分类计数」的完整先例，若本次判定
  「是否为存量代码新发现问题」需要 reviewer 自报而非纯 npc 侧几何匹配，应循此先例扩展 schema
  而非塞进自由文本字段。

- `src/npc/spec_pipeline.py` 模块 docstring（L19-21）— 明确记录了一条**刻意不复用**的边界
  决策：`run_spec_fix_loop` 固定轮次上限，「不复用 code review 的『blocking 单调下降代表
  收敛』stale 检测——spec 的 ambiguity/scope-creep 可以在改写后反弹，blocking 单调下降不是
  这里的收敛前提」。这条边界对本次改动的启示：`trend.py` 的 stale 机制是 **code review 专属**
  的既有设计选择，本次新收敛规则若要与之共存或替换，需要显式说明关系，不能默认「反正都是
  review 就该共用一套」。

- `src/npc/fixer.py`（`findings` 子命令）— 从 `round-N.review.json` 抽 `in_scope=true` 且
  `severity ∈ {critical, high}` 的 findings 喂给下一轮 fix prompt。若 (c) 把存量代码新发现
  问题的 `severity` 降级为 `medium/low`（advisory 语义），本函数**不需要改**——它已经天然
  按 severity 过滤，降级后的 finding 自动不会进入下一轮 fix 范围。这是一个「下游已经自动兼容，
  无需改动」的正向确认，值得在 design 里点出以缩小改动面。

## Assumptions

- **round 阈值对齐**：`_round_n_template` 目前统一处理 `round_n >= 1`；本次「r≥2 切
  delta-review」意味着 round 1 仍沿用现有全量模板语义（因为 round 1 是对 round 0 首次
  fix 的复查，尚无「上一轮 delta 判定」的基线），delta 模式从 round 2 开始生效。若这个
  round 边界理解有误，会直接改变 focus.py 的分支条件。
- **finding 身份匹配键复用 `merge_review_passes._key`**：「上轮遗留未修复 blocking」与
  「本轮新引入 blocking」的区分，采用与 `merge_review_passes` 相同的
  `(file, line_range, category)` 三元组做跨轮匹配（因为 schema 里 `id` 只在本轮唯一，
  不能跨轮直接比较）。
- **「本轮 fix diff」的范围 = 累计 diff，而非增量 diff**：`in_scope` 字段现有语义是「与
  本次 change diff 直接相关」，这里的 diff 是 `_round_n_template` 里 `git diff
  {implement_commit}~1..HEAD` 的**累计**范围（round 0 至今全部改动），不是仅本轮 fix 新增的
  行。规则 (b)(c) 要求的「仅本轮 fix diff 新引入的问题可判 blocking」「存量代码新发现问题
  降级」需要一个更细粒度的「本轮增量」概念（如 `git diff round-{N-1}.fix 落地时的 commit..
  HEAD`），这与现有 `in_scope` 的累计语义不同，需要在 design 里新定义而非复用 `in_scope`。
- **硬收敛规则与既有 stale 机制并存、互不替代**：新规则（连续两轮无遗留未修复 blocking →
  approve）是正向提前批准路径，`trend.py` 的 `STALE_THRESHOLD` 机制是负向止损路径
  （blocking 不降 → 强制 archive），两者判定的输入不同（前者看「遗留未修复」子集，后者看
  blocking 总数趋势），本次改动只新增前者，不改动 `trend.py` 现有逻辑。
- **advisory 降级只作用于「存量代码新发现」，不含「上轮遗留未修复」**：规则 (a)(b)(c) 三条
  的关系是——上轮遗留未修复的 blocking 无论是否属于本轮 diff，MUST 仍判 blocking（否则收敛
  规则的分母就没意义了）；只有「reviewer 在本轮里新提出、且不落在本轮 fix diff 范围内」的
  问题才降级 advisory。
- **降级后的 advisory「随 archive 记录」= 沿用现有 `round-N.review.json` 落盘 + state
  `phases[].advisory` 计数**，不新增独立的跨轮 advisory 累积 ledger 文件——仓库里没有现成的
  「advisory 持久化清单」先例（`lessons.py` / `spec_report.py` 都只读 `categories`
  聚合，不读 finding 全文），若确实需要一份可读的「本 change 存量问题清单」，属于本次新增
  范围，需在 design 里明确产物形态。

## Open Questions

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


## User Decisions (Interactive)

### Q1 硬收敛规则落地位置
问题：连续两轮无"上轮遗留未修复"blocking 即 approve——npc 侧确定性覆盖 verdict，还是仅 focus prompt 指示 reviewer 自报？
用户裁决：**npc 侧确定性覆盖**。在 pipeline 的 review 阶段结束处按上轮匹配结果确定性改写 verdict（_recompute_verdict 风格），不依赖 reviewer 自觉。

### Q2 carry-over vs 新问题的归属判定
问题：是否在 REVIEW_SCHEMA 新增显式字段让 reviewer 自报，还是 npc 侧纯几何匹配？
用户裁决：**schema 加字段 + npc 校验**。REVIEW_SCHEMA 的 finding 新增 carry_over/origin 枚举由 reviewer 结构化自报；npc 侧再用 (file, line_range, category) 与上轮 round-{N-1}.review.json 的 blocking 集合做交叉核验。

### Q3 advisory 降级后的持久化形态
问题：是否新增"存量问题清单"产物供 archive 后回顾？
用户裁决：**新增 carryover 清单产物**。每轮写 round-N.advisory-carryover（或 archive 时汇总一份清单），供人工回顾，不阻塞流程。
