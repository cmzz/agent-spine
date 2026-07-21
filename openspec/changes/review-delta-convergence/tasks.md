## 0. 落点清单（确定性枚举）

以下命令在仓库根（`/Users/ethan/.spine/worktrees/-Users-ethan-Workspace-agent-spine/2026-07-20-1419-00171690`）执行，枚举本 change 需要改动/新增测试覆盖的全部调用点：

```
$ rg -n "parse_review\(" --type py
```
匹配 15 处：`src/npc/fixer.py:54`、`src/npc/pipeline.py:907`、`src/npc/coder.py:373`、`src/npc/review.py:29`（定义）、`src/npc/review.py:150`、`src/npc/agent.py:218`、`tests/test_review.py`（9 处：64/71/76/82/91/116/145/164/190/191，共 10 处，含定义共 15）。
本 change 只改 `review.py:29` 的函数签名（新增可选关键字参数，默认值保持旧行为），`fixer.py:54`/`pipeline.py:907`(→将在 D5 改为条件调用)/`coder.py:373`/`agent.py:218`/`review.py:150` 五个既有调用点 MUST 因默认参数不变而无需改动（除 `pipeline.py:907` 按 design D5 显式传参外）；`tests/test_review.py` 新增用例覆盖 `round_n`/`prior_blocking` 分支。

```
$ rg -n "merge_review_passes\(" --type py
```
匹配 12 处：`src/npc/pipeline.py:893,899`、`src/npc/review.py:89`（定义）、`tests/test_review.py`（9 处）。
本 change 只做内部重构（`_key` 提升为模块级 `_finding_key`），MUST NOT 改变其对外行为；`tests/test_review.py` 既有 9 个 `merge_review_passes` 用例 MUST 保持全绿，不新增/不删除。

```
$ rg -n "_round_n_template\(|_render_focus\(" --type py
```
匹配 5 处：`src/npc/focus.py:281`（定义）、`src/npc/focus.py:375`（`render()` 内调用）、`src/npc/pipeline.py:608`（`_render_focus` 定义）、`src/npc/pipeline.py:631`（内部调用 `_round_n_template`）、`src/npc/pipeline.py:783`（`run_review_round` 调用 `_render_focus`）；另有 `tests/test_focus.py:253` 一处既有测试调用。
本 change 需要：`focus.py:281` 定义新增可选参数 `round_fix_commit`；`focus.py:375`/`pipeline.py:631`/`pipeline.py:783` 三处调用链路需要传递该参数（`round_n >= 2` 时取值，否则为 `None`）；`tests/test_focus.py:253` 既有用例（`round_n=2` 但未传 `round_fix_commit`）MUST 保持通过（验证缺省时的降级行为）。

```
$ rg -n "REVIEW_SCHEMA\b" --type py
```
匹配 34 处，跨 `src/npc/schema.py`（7 处，含定义与 `ensure_schema` 默认参数）、`src/npc/spec_pipeline.py`（3 处，均为 `SPEC_REVIEW_SCHEMA`，不受影响）、`src/npc/pipeline.py`（4 处，`jsonschema.validate` 校验点）、`src/npc/templates.py`（2 处，仅注释提及 `SPEC_REVIEW_SCHEMA` 边界，不受影响）、`src/npc/review.py`（3 处，注释）、`tests/test_pipeline.py`（1 处）、`tests/test_schema.py`（14 处）、`tests/test_spec_attribution_non_goals.py`（1 处）。
本 change 只改 `schema.py` 的 `REVIEW_SCHEMA` 定义本身（新增 `finding_origin` 必填字段）；`pipeline.py` 的 4 处 `jsonschema.validate(parsed, _schema.REVIEW_SCHEMA)` 校验点 MUST 无需改动（校验逻辑对 schema 内容透明）；`tests/test_schema.py` 新增 `finding_origin` 枚举/必填断言，既有断言（如 `data == _schema.REVIEW_SCHEMA` 语义比对）因两侧同源不受破坏。

```
$ rg -n "_do_review_phase_exit_and_trend\(" --type py
```
匹配 6 处：`src/npc/pipeline.py:396`（定义）、`src/npc/pipeline.py:947`（`run_review_round` 调用）、`tests/test_pipeline.py`（4 处：1993/2016/2039/2058）。
本 change 需要：`pipeline.py:396` 定义处 `new_phase` 字典新增三个键（`carryover_unresolved_blocking` / `hard_convergence_applied` / `effective_blocking_findings`）；`pipeline.py:947` 调用点改为传入 D5 计算出的 `effective_metrics`；`tests/test_pipeline.py` 既有 4 处直接调用该函数的用例 MUST 保持通过（新键为可选/有默认值，不破坏既有调用签名），并新增用例断言新键写入正确。

## 1. Schema：`finding_origin` 三值枚举

- [ ] 1.1 为 `tests/test_schema.py` 新增失败测试：`REVIEW_SCHEMA` 的 finding `required` 含 `finding_origin`，`enum` 恰为 `["carry-over-unresolved", "round-diff-new", "pre-existing-new"]`；`SPEC_REVIEW_SCHEMA` 不含该字段（回归防护）
- [ ] 1.2 在 `src/npc/schema.py::REVIEW_SCHEMA` 落地该字段（`required` + `properties` + `description`）
- [ ] 1.3 运行 `tests/test_schema.py` 全量，确认新增用例通过、既有用例不回归

## 2. `review.py`：几何核验与 delta 计算

- [ ] 2.1 新增失败测试（`tests/test_review.py`）：`_finding_key` 作为模块级函数可被独立调用且与 `merge_review_passes` 内部去重键行为一致（精确三元组，仅供同轮去重使用）
- [ ] 2.2 把 `merge_review_passes` 内联的 `_key()` 提升为模块级 `_finding_key`，`merge_review_passes` 改为调用它；运行既有 `merge_review_passes` 全部用例确认零回归
- [ ] 2.2b 新增失败测试：`_is_carry_over_match(finding, prior_finding)` —— `file`/`category` 精确匹配 + `line_range` 区间重叠（覆盖：三元组完全相等 → True；行号漂移但区间仍重叠（如 `10-20` vs `15-25`）→ True；区间完全不重叠（如 `10-20` vs `80-90`）→ False；`category` 不同 → False；`file` 不同 → False；单行 `line_range`（如 `"18"` 落在 `15-25` 内）→ True；反向区间（如 `"25-15"` 归一化为 `[15,25]` 后与 `10-20` 重叠）→ True；`line_range="-"` 占位符 → False 且不抛异常；`line_range` 为非法格式如 `"foo"` → False 且不抛异常）
- [ ] 2.2c 实现 `_is_carry_over_match`（`review.py` 新增模块级函数，含 `line_range` 字符串解析为整数区间的辅助逻辑，兼容单行 `"N"`、区间 `"N-M"`（含空白与反向区间归一化）两种格式；`"-"` 或任何无法解析出两个整数端点的字符串一律视为不可解析，返回 `False`，不抛异常）
- [ ] 2.3 新增失败测试：`parse_review(data)`（不传 `round_n`/`prior_blocking`）派生的 `blocking`/`advisory`/`verdict`/`blocking_findings` 计算方式与改动前一致（默认参数回归防护；不断言返回值 keys 集合逐字节不变，因为本 change 新增 `carryover_unresolved_blocking`/`finding_origins` 两个返回键）
- [ ] 2.4 新增失败测试：`round_n=2`，某 finding 与 `prior_blocking` 中某条目 `_is_carry_over_match` 为 True（含三元组完全相等与区间重叠两种子用例）→ `carryover_unresolved_blocking` 计数包含它，即使其自报 `finding_origin` 不是 `carry-over-unresolved`
- [ ] 2.5 新增失败测试：`round_n=2`，某 finding 自报 `finding_origin="pre-existing-new"` 且未命中 `prior_blocking` → 不计入 `blocking`/`blocking_findings`，计入 `advisory`
- [ ] 2.6 新增失败测试：`round_n=2`，某 finding 自报 `carry-over-unresolved` 但未命中 `prior_blocking`（几何核验失败，含区间完全不重叠、`category` 改写两种子用例）→ 有效来源回退 `round-diff-new`，仍计入 blocking 候选
- [ ] 2.7 新增失败测试：`round_n=2` 时 `verdict` 按调整后 blocking 集合重新计算（存在有效 blocking → `changes-requested`；否则 findings 非空 → `passed-with-advisory`；否则 → `approve`），不采信自报 `verdict`
- [ ] 2.8 新增失败测试：`round_n=1`（或 `prior_blocking=None`）传参不改变现状**派生计算方式**（`finding_origin` 字段被忽略，`verdict` 仍取自报值）
- [ ] 2.9 实现 `parse_review` 的 `round_n`/`prior_blocking` 参数与 D2 计算逻辑（调用 `_is_carry_over_match` 而非精确三元组集合成员判断），新增常量 `FINDING_ORIGIN_VALUES`；返回值新增 `carryover_unresolved_blocking` / `finding_origins`
- [ ] 2.10 运行 `tests/test_review.py` 全量确认通过

## 3. `focus.py`：round≥2 delta 规则块

- [ ] 3.1 新增失败测试（`tests/test_focus.py`）：`_round_n_template(change_id, 2, implement_commit, ctx, round_fix_commit="abcd123")` 输出含增量 diff 指令 `git --no-pager diff abcd123~1..abcd123` 与 `finding_origin` 三值分类准则文案
- [ ] 3.2 新增失败测试：`_round_n_template(..., round_n=2, round_fix_commit=None)`（缺省）输出不含增量 diff 指令，但不抛异常，且仍包含 `finding_origin` 三值分类准则文案（分类准则不依赖 `round_fix_commit`，回归防护：不得因缺省 commit 而连分类准则一并丢失）
- [ ] 3.3 新增失败测试：`_round_n_template(..., round_n=1, ...)` 即使传入 `round_fix_commit` 也不追加 delta 规则块与增量 diff 指令（round 1 不追加 delta 规则块的回归防护；注意 `_output_requirements_block` 的 `finding_origin` 字段说明仍会出现在 round 1 输出中，属预期变化，见 3.4）
- [ ] 3.4 新增失败测试：`_output_requirements_block()` 输出含 `finding_origin` 字段说明（对 round 0 模板同样生效）
- [ ] 3.5 实现 `_round_n_template` 新增可选参数与条件追加逻辑、新增 `FINDING_ORIGIN_ENUM_SEMANTICS` 常量并接入 `_output_requirements_block`
- [ ] 3.6 运行 `tests/test_focus.py` 全量确认通过（含既有 `tests/test_focus.py:253` 用例不回归）

## 4. `pipeline.py`：跨轮读取、硬收敛覆盖、advisory carryover 产物

- [ ] 4.1 新增失败测试（`tests/test_pipeline.py`）：`_do_review_phase_exit_and_trend` 写入的 `phases["review-rN"]` 新增 `carryover_unresolved_blocking`/`hard_convergence_applied`/`effective_blocking_findings` 三键，缺省输入时分别为 `None`/`False`/`None`
- [ ] 4.2 实现 `_do_review_phase_exit_and_trend` 新增字段写入（`effective_blocking_findings` 为 `effective_metrics["blocking_findings"]` 中每条 finding 的 `{file, line_range, category}` 三元组列表）；运行既有 4 处直接调用该函数的测试确认零回归
- [ ] 4.3 新增失败测试：`run_review_round` 在 `round_n=2` 时，`_render_focus` 调用链路收到从 `phases["fix-r1"]["commit"]` 读取的 `round_fix_commit`
- [ ] 4.4 新增失败测试：`run_review_round` 在 `round_n=2` 时读取 `round-1.review.json` 并用**默认参数**的 `parse_review` 取其 `blocking_findings` 作为 `prior_blocking` 传给 `parse_review(round_n=2, ...)`
- [ ] 4.4b 新增失败测试：`run_review_round` 在 `round_n=3` 时，`prior_blocking` 取自 `phases["review-r2"]["effective_blocking_findings"]`（state 持久化的有效 blocking 集合），而不是对 `round-2.review.json` 重新执行默认 `parse_review`；构造一个 round 2 曾把某三元组降级为 `pre-existing-new` 的 fixture，断言该三元组不出现在 round 3 的 `prior_blocking` 中
- [ ] 4.4c 新增失败测试：`round_n=3`，state 中 `phases["review-r2"]` 缺失 `effective_blocking_findings` 字段（历史 state）→ 传给 `parse_review` 的 `prior_blocking` 为 `None`（非 `[]`），本轮不计算 `effective_origin`、`verdict` 直接信任自报值、`carryover_unresolved_blocking` 为 `None` 从而不满足硬收敛覆盖前置条件
- [ ] 4.5 新增失败测试：`round_n=3`，round-2/round-3 的 `carryover_unresolved_blocking` 均为 0、且本轮存在一条 `round-diff-new` blocking finding → 返回值 `blocking=0`、该 finding 计入 `advisory`、`verdict="passed-with-advisory"`、`hard_convergence_applied=True`
- [ ] 4.5b 新增失败测试：同上覆盖条件成立，但覆盖前本轮 `advisory==0` 且 `blocking_findings` 为空 → `verdict="approve"`（验证 verdict 不被硬编码为固定值，而是按覆盖后集合重新计算）
- [ ] 4.6 新增失败测试：`round_n=3`，round-2 的 `carryover_unresolved_blocking` 非 0（或 round-3 本身非 0）→ 不触发覆盖，`hard_convergence_applied=False`，返回值与未覆盖前一致
- [ ] 4.7 新增失败测试：`round_n=2`（`< 3`）即使 `carryover_unresolved_blocking=0` 也不触发硬收敛覆盖（最早生效轮次边界回归防护）
- [ ] 4.8 新增失败测试：硬收敛覆盖发生时，MUST NOT 执行“渲染下一轮 fix findings”分支（`round-{round_n+1}.fix.findings.md` 不产出），因为 `effective_metrics["blocking"] == 0`——注意 `fixer.render_findings` 本身仍会被调用以渲染 `round-{round_n}.advisory-carryover.md`（见 4.9/D6），这是同一函数服务于两个不同输出路径的两次独立调用，二者不冲突；测试 MUST 分别断言：(a) 不存在写出 `round-{round_n+1}.fix.findings.md` 的调用/产物，(b) `round-{round_n}.advisory-carryover.md` 存在且由 `render_findings` 渲染（用 mock 断言调用次数/参数按用途区分，或直接断言两个文件路径各自的存在性）
- [ ] 4.9 新增失败测试：`round_n >= 2` 时新增产物 `round-{round_n}.advisory-carryover.md` 被写出，内容含 `effective_origin == "pre-existing-new"` 的 finding；硬收敛覆盖发生时额外含被降级的原 blocking finding
- [ ] 4.10 新增失败测试：`round_n < 2` 时不产出 `round-{round_n}.advisory-carryover.md`（回归防护）
- [ ] 4.11 实现 `run_review_round` 的跨轮读取（`round_n==2` 时对 round-1 走默认 `parse_review`；`round_n>=3` 时从 state 读 `effective_blocking_findings` 作为 `prior_blocking`；`round_fix_commit`）、D5 硬收敛覆盖逻辑（`effective_metrics` 构造，`verdict` 按覆盖后集合重新计算而非硬编码）、D6 advisory carryover 渲染（复用 `fixer.render_findings`），并确保 state/telemetry/fixer 渲染门槛/返回值统一改用 `effective_metrics`
- [ ] 4.12 运行 `tests/test_pipeline.py` 全量确认通过

## 5. 收尾

- [ ] 5.1 运行 `openspec validate review-delta-convergence --type change --strict`，修复全部报错直至通过
- [ ] 5.2 运行 `uv run pytest tests/test_schema.py tests/test_review.py tests/test_focus.py tests/test_pipeline.py -v`，确认全绿
- [ ] 5.3 运行 `uv run pytest -q` 全量测试，确认零回归
- [ ] 5.4 确认改动范围仅限 `src/npc/schema.py` / `src/npc/review.py` / `src/npc/focus.py` / `src/npc/pipeline.py` 与对应 `tests/test_*.py`，未触及 `spec_pipeline.py` / `trend.py` / `fixer.py`（`git status`/`git diff --stat` 自检）
