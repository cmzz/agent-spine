## 0. 落点清单（确定性枚举）

以下命令在仓库根（`/Users/ethan/.spine/worktrees/-Users-ethan-Workspace-agent-spine/2026-07-20-1419-00171690`）执行，枚举本 change 需要改动/新增测试覆盖的全部调用点：

```
$ rg -n "SELFCHECK_RUBRIC_MD" --type py
```
匹配 19 处：`src/npc/focus.py:192`（注释，边界提醒）、`src/npc/templates.py:43`（定义）、`src/npc/templates.py:164`（`render_implementer` 注入）、`src/npc/templates.py:340`（`render_fixer` 注入）、`tests/test_reduce_review_fix_cost.py`（14 处，含类目覆盖断言、单一来源断言、`no-stub` 行断言、边界说明断言）。
本 change 只改 `templates.py:43` 常量本体（`validation` 行文案），`templates.py:164`/`templates.py:340` 两处注入点无需改动（同一常量、注入方式不变）；`tests/test_reduce_review_fix_cost.py` 既有用例（类目名存在性断言、单一来源断言）MUST 保持通过（不依赖具体行文案，只依赖类目名 `validation` 与固定标识词 `通用` 仍存在）；新增用例断言四个检查点关键词存在。

```
$ rg -n "_output_requirements_block\(" --type py
```
匹配 9 处：`src/npc/focus.py:189`（注释）、`src/npc/focus.py:196`（定义）、`src/npc/focus.py:250/277/316`（三处调用：对抗式 pass / round 0 / round N）、`tests/test_focus.py`（4 处：227/228/233/238）。
本 change 需要：`focus.py:196` 函数体追加 `VALIDATION_EVIDENCE_REQUIREMENT_MD` 文案，三处调用点（250/277/316）因函数签名不变而自动共享新增文案，无需逐一修改调用点；`tests/test_focus.py` 既有 4 处用例（对比 `authority_disclaimer=True/False` 差异）MUST 保持通过（新增文案不受 `authority_disclaimer` 参数影响，两分支应同步新增）；新增用例断言新增文案存在于返回文本中。

```
$ rg -n "REVIEW_SCHEMA\b" --type py
```
匹配 42 处，跨 `src/npc/schema.py`（7 处，含定义）、`src/npc/spec_pipeline.py`（2 处，均为 `SPEC_REVIEW_SCHEMA`，不受影响）、`src/npc/pipeline.py`（4 处，`jsonschema.validate` 校验点）、`src/npc/templates.py`（2 处，注释提及 `SPEC_REVIEW_SCHEMA` 边界，不受影响）、`src/npc/review.py`（3 处，注释）、`tests/test_pipeline.py`（1 处，注释）、`tests/test_schema.py`（16 处）、`tests/test_spec_attribution_non_goals.py`（1 处）。
本 change 只改 `schema.py` 的 `REVIEW_SCHEMA` 定义本身（新增 `properties.trigger_evidence` 纯可选属性，**不新增** `allOf`/`if`/`then` 条件必需规则——design.md D2 经 Round 4 spec 语义评审裁决修订）；`pipeline.py` 的 4 处 `jsonschema.validate(parsed, _schema.REVIEW_SCHEMA)` 校验点 MUST 无需改动；`tests/test_schema.py` 新增断言覆盖"`category == "validation"` 缺 `trigger_evidence` 字段 MUST 通过 schema 校验"（回归防护：确保未来不会误加条件必需规则）与"非 validation 类缺字段同样通过"两个方向；既有 `data == _schema.REVIEW_SCHEMA` 语义比对类断言因两侧同源不受破坏。

```
$ rg -n "parse_review\(" --type py
```
匹配 16 处：`src/npc/agent.py:218`、`src/npc/pipeline.py:907`、`src/npc/coder.py:373`、`src/npc/fixer.py:54`、`src/npc/review.py:29`（定义）、`src/npc/review.py:150`、`tests/test_review.py`（10 处：64/71/76/82/91/116/145/164/190/191）。
本 change 只改 `review.py:29` 函数体（新增两条降级谓词与 `downgrade_counts` 返回键，签名不变，不新增参数）；`agent.py:218`/`pipeline.py:907`/`coder.py:373`/`fixer.py:54`/`review.py:150` 五个既有调用点 MUST 因签名不变而无需改动；`tests/test_review.py` 新增用例覆盖两条降级谓词的独立与组合场景。

```
$ rg -n "spec_attribution_counts" --type py
```
匹配 49 处（跨 `src/npc/review.py`、`src/npc/pipeline.py`、`src/npc/telemetry.py`、`tests/test_review.py`、`tests/test_spec_attribution_agg.py`、`tests/test_spec_pipeline.py`、`tests/test_structural_invariants.py`）。
本 change 参照该字段的既有传递路径新增 `downgrade_counts`（不修改 `spec_attribution_counts` 自身逻辑）：`review.py::parse_review` 返回值新增键（镜像第 68 行 `"spec_attribution_counts": spec_attribution_counts,` 的写法新增一行）；`telemetry.py::emit_review_round` 新增同名可选参数并写入事件字典（镜像第 966/999 行）；`pipeline.py::run_review_round` 两处调用点新增传参（镜像第 929/968 行：失败路径传 `None`，成功路径传 `metrics.get("downgrade_counts")`）；`telemetry.py` 聚合分支（`EMIT_FIELD_CONTRACT`/`agg` 内部逐 key 累加逻辑，紧邻第 410/459/463/488/490 行 `spec_attribution_counts` 聚合代码）新增镜像实现。`spec_attribution_counts` 的**统计范围语义**（哪些 finding 计入）随降级谓词落地自动收窄（候选内被降级的 finding 不再进入 `spec_attribution_counts` 归属分支），对应 `openspec/specs/spec-attribution/spec.md` 新增第三条 MODIFIED Requirement（见 6.3）；代码层面不需要为此单独改动 `review.py:44-57` 的既有 `if sev in BLOCKING_SEVERITIES and in_scope:` 结构本身，只需按 D6 把该判定条件替换为 `_is_effective_blocking(f)`（见下）。

```
$ rg -n "_recompute_verdict\(" --type py
```
匹配处：`src/npc/review.py`（定义处 + `merge_review_passes()` 内 1 处调用）、`tests/test_review.py`（若干处间接覆盖，通过 `merge_review_passes` 返回值断言）。
本 change 需要：`_recompute_verdict()` 的 `has_blocking` 判定改为基于降级后集合（design.md D6：新增 `_is_effective_blocking(f)` helper，供 `parse_review()`/`_recompute_verdict()` 共用）；`merge_review_passes()` 调用点签名不变，无需改动调用处代码，仅函数体内部判定逻辑变化；`tests/test_review.py` 新增用例覆盖"降级后 verdict 不再是 changes-requested"的单 pass 与双 pass 场景（见 4.15-4.17）。

```
$ rg -n "EMIT_FIELD_CONTRACT" --type py
```
匹配 20 处：`src/npc/telemetry.py:62`（定义）、`tests/test_structural_invariants.py`（10 处）、`tests/test_spec_pipeline.py`（3 处）。
本 change 需要：`telemetry.py:62` 定义处 `"review.round"` 对应的 `frozenset` 新增 `"downgrade_counts"`；`tests/test_structural_invariants.py` 既有 R1a 类断言（`EMIT_FIELD_CONTRACT[kind] - set(captured[0].keys())` 应为空集）MUST 因 `emit_review_round` 同步新增参数写入而保持通过，不新增/不删除既有断言用例本身（只是其覆盖的字段集合隐式扩大）。

## 1. `templates.py`：coder 自查清单细化（(a)）

- [ ] 1.1 新增失败测试（`tests/test_reduce_review_fix_cost.py` 或新建 `tests/test_templates_validation_selfcheck.py`，二选一，落笔时按仓库既有归档惯例决定并在 summary.md 中记录理由）：`SELFCHECK_RUBRIC_MD` 的 `validation` 行同时包含"边界值"/"None"或等价空值措辞/"类型"/"外部输入"四个关键词
- [ ] 1.2 新增失败测试：`SELFCHECK_RUBRIC_MD` 的 `validation` 行 MUST NOT 包含 `trigger_evidence`/"可触发"/"调用路径" 等 (b) 的 reviewer 侧措辞（生成 ⊥ 验证边界回归防护）
- [ ] 1.3 落地 `templates.py::SELFCHECK_RUBRIC_MD` 的 `validation` 行文案（design.md D1）
- [ ] 1.4 运行既有 `tests/test_reduce_review_fix_cost.py` 全量，确认类目存在性/单一来源/`no-stub` 相关断言零回归

## 2. `schema.py`：`trigger_evidence` 可选字段（(b) schema 侧，Round 4 修订：不做条件必需；Round 5 修订：类型允许 null）

- [ ] 2.1 新增失败测试（`tests/test_schema.py`）：`category == "validation"` 且缺 `trigger_evidence` 的 finding **通过** `REVIEW_SCHEMA` 校验（Round 4 裁决：该字段对所有 category 均为可选，缺失不导致校验失败；回归防护避免未来误加条件必需规则）
- [ ] 2.2 新增失败测试：`category == "validation"` 且 `trigger_evidence` 为空字符串 `""` 的 finding **通过** schema 校验（schema 层只保证类型为 `["string", "null"]`，不保证非空——design.md D2 显式设计，回归防护避免误加 `minLength`）
- [ ] 2.2b 新增失败测试（Round 5，F1 回归防护）：`category == "validation"` 且 `trigger_evidence` 显式为 `null` 的 finding **通过** `REVIEW_SCHEMA` 校验（锁死 Round 5 裁决：类型允许 `["string", "null"]`，显式 `null` 不被 schema 拒绝，能正常到达 `parse_review()` 的 `null` 降级分支）
- [ ] 2.3 新增失败测试：`category != "validation"`（如 `"security"`）缺 `trigger_evidence` 的 finding 通过 schema 校验（非 validation 类同样不受约束）
- [ ] 2.4 新增失败测试：`SPEC_REVIEW_SCHEMA` 不含 `trigger_evidence` 属性、不含针对 `category` 的 `allOf`/`if`/`then` 条件规则（回归防护）
- [ ] 2.4b 新增失败测试：`REVIEW_SCHEMA` 顶层/finding items 不含任何针对 `trigger_evidence` 的 `required`/`allOf`/`if`/`then` 条件必需规则（回归防护，锁死 Round 4 裁决：确定性判定只在 `parse_review()`，不在 schema）
- [ ] 2.5 落地 `REVIEW_SCHEMA["properties"]["findings"]["items"]` 的 `properties.trigger_evidence` 纯可选属性，类型 `["string", "null"]`（**不加** `required`/`allOf`/`if`/`then`，design.md D2）
- [ ] 2.6 运行 `tests/test_schema.py` 全量，确认新增用例通过、既有用例（含 `test_spec_attribution_non_goals.py` 依赖的 finding schema 结构断言）不回归

## 3. `focus.py`：举证要求文案（(b) prompt 侧）

- [ ] 3.1 新增失败测试（`tests/test_focus.py`）：`_output_requirements_block()`（默认参数与 `authority_disclaimer=False` 两种取值）输出均含 `trigger_evidence` 举证要求文案
- [ ] 3.2 新增失败测试：`_round_0_template(...)` 与 `_round_n_template(...)` 的渲染结果均包含该举证要求文案（验证三处调用点——round0/roundN/对抗式 pass——共享同一文案，对抗式 pass 见 `_adversarial_round_0_template`）
- [ ] 3.3 落地 `focus.py` 新增 `VALIDATION_EVIDENCE_REQUIREMENT_MD` 常量并接入 `_output_requirements_block()`（design.md D2）
- [ ] 3.4 运行 `tests/test_focus.py` 全量确认通过（含既有 227/228/233/238 行用例零回归）

## 4. `review.py`：降级判据与 `downgrade_counts`（(b)+(c) 判定逻辑）

- [ ] 4.1 新增失败测试（`tests/test_review.py`）：`category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence` 缺失（key 不存在）的 finding → 不计入 `blocking`/`blocking_findings`，计入 `advisory`，`downgrade_counts["validation_missing_evidence"] == 1`
- [ ] 4.2 新增失败测试：同上但 `trigger_evidence=""`（空字符串）→ 同样降级
- [ ] 4.3 新增失败测试：同上但 `trigger_evidence="-"`（占位符）→ 同样降级
- [ ] 4.4 新增失败测试：同上但 `trigger_evidence="传入 limit=-1 触发下标越界"`（非空非占位符）→ **不**降级，正常计入 blocking
- [ ] 4.5 新增失败测试：`category="validation"`、`severity="critical"`、`trigger_evidence` 缺失 → 仍降级（举证门槛不因 severity=critical 而豁免，只有 (c) 的 spec-silent 降级才对 critical 豁免——两条谓词互相独立，回归防护避免混淆）
- [ ] 4.6 新增失败测试：`category != "validation"`（如 `"security"`）、`trigger_evidence` 缺失 → 不触发 (b) 降级（谓词仅约束 validation 类）
- [ ] 4.7 新增失败测试：`spec_attribution="spec-silent"`、`severity="high"`、`in_scope=true`、`category != "validation"`（避免与 (b) 谓词交叉，隔离测试 (c)）→ 不计入 blocking，计入 advisory，`downgrade_counts["spec_silent_non_critical"] == 1`
- [ ] 4.8 新增失败测试：同上但 `severity="critical"` → **不**降级，正常计入 blocking（Q3 裁决回归防护）
- [ ] 4.9 新增失败测试：`spec_attribution="spec-ambiguous"`（或 `spec-contradicted`/`impl-deviation`）、`severity="high"` → 不触发 (c) 降级（窄化范围回归防护，仅 `spec-silent` 触发）
- [ ] 4.10 新增失败测试：某 finding 同时满足 (b) 与 (c) 两条降级谓词（`category="validation"` 缺证据 且 `spec_attribution="spec-silent"` 非 critical）→ 仅降级一次（不重复计入 `advisory_count`），但 `downgrade_counts` 的两个键各自 `+1`（design.md D5 的"重叠计数"回归防护）
- [ ] 4.11 新增失败测试：`spec_attribution_counts` 的统计范围不含被降级的 finding（既有「统计范围与 blocking 一致」语义在新增降级谓词后依然成立的回归防护）
- [ ] 4.12 新增失败测试：不触发任何降级谓词的既有用例集合（`tests/test_review.py` 现有 64-191 行用例）保持全绿（默认行为回归防护）
- [ ] 4.13 实现 `_validation_evidence_missing` / `_spec_silent_non_critical` 两个模块级谓词函数与 `parse_review()` 内的二次过滤逻辑、`downgrade_counts` 返回键（design.md D3/D4）
- [ ] 4.14 新增失败测试：唯一 finding 为 `category="validation"`、`severity="high"`、`in_scope=true`、`trigger_evidence=""` 的单 pass review（顶层自报 `verdict="changes-requested"`）→ `parse_review()` 返回 `blocking == 0`、`verdict == "passed-with-advisory"`（不采信引擎自报值，design.md D6 回归防护）
- [ ] 4.15 新增失败测试：pass1 唯一 finding 为 `spec_attribution="spec-silent"`、`severity="high"`、`in_scope=true`，pass2 为空 → `merge_review_passes()` 合并结果 `verdict == "passed-with-advisory"`（不是 `"changes-requested"`）
- [ ] 4.16 新增失败测试：一轮 review 含两条 finding 分别因两条不同降级谓词被降级、无其它 blocking 候选 → `blocking == 0` 且 `verdict == "passed-with-advisory"`
- [ ] 4.17 更新既有 `test_parse_review_counts`（`SAMPLE_REVIEW` 的 F1 为 `category="validation"` 缺 `trigger_evidence`）：F1 在新规则下被降级，`blocking`/`advisory`/`verdict` 断言值需同步调整（design.md D6 备注段落已标注此处的既有用例需要更新，不能简单当作"零回归"处理）
- [ ] 4.18 实现 `_is_effective_blocking(f)` helper 并接入 `parse_review()`（替换 4.13 的候选内过滤为该 helper）与 `_recompute_verdict()`（替换 `has_blocking` 的原始 severity/in_scope 判定）；`parse_review()` 的 `"verdict"` 键改为按 `blocking_list`/`findings` 是否非空重算，不再读取 `review_json.get("verdict")`（design.md D6）
- [ ] 4.19 运行 `tests/test_review.py` 全量确认通过

## 5. `telemetry.py` + `telemetry_schema_v1.json` + `pipeline.py`：降级可观测性（(c) 可观测性，Q4）

- [ ] 5.1 新增失败测试（`tests/test_structural_invariants.py` 或 `tests/test_telemetry.py`，视既有归档位置决定）：`EMIT_FIELD_CONTRACT["review.round"]` 含 `"downgrade_counts"`
- [ ] 5.2 新增失败测试：`emit_review_round(..., downgrade_counts={"validation_missing_evidence": 1, "spec_silent_non_critical": 2})` 捕获的事件字典含该键且值一致
- [ ] 5.3 新增失败测试：`emit_review_round` 不传 `downgrade_counts`（默认 `None`）时事件字典仍含该键、值为 `None`（向后兼容既有调用点的回归防护）
- [ ] 5.4 新增失败测试（`tests/test_spec_attribution_agg.py` 同级新建或追加）：`npc telemetry agg` 对含 `downgrade_counts` 的多条 `review.round` 事件做逐 key 累加聚合
- [ ] 5.5 新增失败测试：`npc telemetry agg` 面对缺 `downgrade_counts` 键的历史事件时 exit code 为 `0`，该事件不贡献聚合值、不抛异常
- [ ] 5.6 实现 `telemetry.py::emit_review_round` 新增 `downgrade_counts` 参数与事件字典写入、`EMIT_FIELD_CONTRACT["review.round"]` 新增键、聚合分支新增逐 key 累加逻辑（design.md D5）
- [ ] 5.7 落地 `src/npc/telemetry_schema_v1.json` 新增 `downgrade_counts` 属性（镜像 `spec_attribution_counts` 条目结构）
- [ ] 5.8 落地 `pipeline.py::run_review_round` 两处 `emit_review_round` 调用点新增 `downgrade_counts` 传参（失败路径 `None`，成功路径 `metrics.get("downgrade_counts")`）
- [ ] 5.9 运行 `tests/test_structural_invariants.py`、`tests/test_spec_attribution_agg.py`（或新建对应文件）、`tests/test_pipeline.py` 全量确认通过

## 6. spec delta：`validation-blocking-threshold`（新能力） + `implement-selfcheck-rubric`（修订） + `spec-attribution`（修订） + `review-adversarial-pass`（修订）

- [ ] 6.1 撰写 `openspec/changes/validation-blocking-threshold/specs/validation-blocking-threshold/spec.md`（`## ADDED Requirements`）：validation 类 blocking 举证门槛（`trigger_evidence` 为 schema 纯可选字段、类型 `["string", "null"]` + `parse_review()` 侧确定性缺失降级，不含 schema 失败流程 Scenario——Round 4/Round 5 裁决修订）、spec-silent 非 critical 降级、降级可观测性、**verdict 必须与降级后的最终 blocking 集合保持一致**四条 Requirement 及各自 Scenario
- [ ] 6.2 撰写 `openspec/changes/validation-blocking-threshold/specs/implement-selfcheck-rubric/spec.md`（`## MODIFIED Requirements`）：细化后的 validation 自查要点 Requirement 与对应 Scenario
- [ ] 6.3 撰写 `openspec/changes/validation-blocking-threshold/specs/spec-attribution/spec.md`（`## MODIFIED Requirements`）：窄化后的「spec 归因不参与 blocking 判定」（Round 5 修订：补充 validation 举证门槛降级作为与 spec-silent 例外并列的独立引用）、统计范围改写后的「派生 spec 归因分布并向后兼容」、「本 change 不引入任何闸门」**三条** Requirement 与对应 Scenario
- [ ] 6.4 撰写 `openspec/changes/validation-blocking-threshold/specs/review-adversarial-pass/spec.md`（`## MODIFIED Requirements`，Round 5 新增，修复 F3）：「findings 合并去重规则确定性」第 3 条 verdict 重算规则改为基于降级后最终 blocking 集合、「telemetry 透出对抗通道运行状态」显式裁决 `adversarial_blocking_count` 为"pass2 原始候选数、不感知降级"语义，与对应新增 Scenario
- [ ] 6.5 运行 `openspec validate validation-blocking-threshold --type change --strict`，确认新增 `review-adversarial-pass` capability delta 被正确识别、无重复/矛盾 Requirement 校验错误

## 7. 收尾

- [ ] 7.1 运行 `openspec validate validation-blocking-threshold --type change --strict`，修复全部报错直至通过
- [ ] 7.2 运行 `uv run pytest tests/test_schema.py tests/test_review.py tests/test_focus.py tests/test_reduce_review_fix_cost.py tests/test_structural_invariants.py tests/test_spec_attribution_agg.py tests/test_pipeline.py -v`，确认全绿
- [ ] 7.3 运行 `uv run pytest -q` 全量测试，确认零回归
- [ ] 7.4 确认改动范围仅限 `src/npc/templates.py` / `src/npc/schema.py` / `src/npc/focus.py` / `src/npc/review.py` / `src/npc/telemetry.py` / `src/npc/telemetry_schema_v1.json` / `src/npc/pipeline.py` 与对应 `tests/test_*.py`，未触及 `src/npc/fixer.py` / `src/npc/spec_pipeline.py` / `src/npc/trend.py`（`git status`/`git diff --stat` 自检）
