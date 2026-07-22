## 0. 落点确定性枚举（先跑命令，再动手改代码）

以下命令在 `REPO_ROOT` 下逐条执行，命中数与命中行已核对（本轮 write 阶段跑出的实际结果，供后续逐项勾完）：

```bash
grep -n "kimi_review_not_claude" src/npc/*.py
```
命中 6 行：`src/npc/verify.py` 5 行（289/292/295/428/431/434 一组，`kimi_review_not_claude` 判定段本体 + `spec_kimi_review_not_claude` 同构段本体 + 注释）与 `src/npc/coder.py` 第 132 行（仅字面引用，非判定逻辑）。verify.py 两段判定 MUST 整段删除；coder.py 一行 MUST 只改措辞、不改逻辑。

```bash
grep -n '"engine", "codex"\|engine: str = "codex"' src/npc/config.py
```
命中 4 行：`ReviewEngineConfig.engine`（56）、`SpecReviewConfig.engine`（228，含行内注释）两处 dataclass 字段默认值声明；`_build()` 内 `engine = str(review_raw.get("engine", "codex"))`（368）、`spec_review_engine = str(spec_review_raw.get("engine", "codex"))`（454）两处 TOML 解析。四处均需改为 `None` 默认 / `_opt_str(...)` 解析。

```bash
grep -n "default_engine" src/npc/pipeline.py src/npc/spec_pipeline.py
```
命中 4 行：`pipeline.py` 758（赋值）/761（使用）、`spec_pipeline.py` 182（赋值）/187（使用）——均需改为调用新增的 `effective_engine()` 方法。

```bash
grep -rn "kimi_review_not_claude\|spec_kimi_review_not_claude" tests/
```
命中 5 行：`tests/test_pipeline.py:2263`（`assert "kimi_review_not_claude" in rules`）、`tests/test_spec_pipeline.py:2017`（`v["rule"] == "spec_kimi_review_not_claude"`）、`tests/test_coder_dispatch.py:797`（注释提及，非断言，措辞需同步更新）。前两处 MUST 翻转断言方向，保留测试函数名。

```bash
grep -rn "ReviewEngineConfig(" tests/*.py
```
命中 10 行，分布于 `tests/test_coder_dispatch.py:508`、`tests/test_engines.py:73/80/95/102/109/116`、`tests/test_spec_routing.py:248/332`、`tests/test_verify.py:34`——逐行核对后**全部已显式传 `engine=` 具体字符串**，字段类型改为 `str | None` 后这些构造调用无需改动（`engine=` 传参本身就是"显式配置"语义，行为不变）。

```bash
grep -rn "SpecReviewConfig(" tests/*.py
```
命中 6 行，分布于 `tests/test_spec_pipeline.py:365/374/1985`、`tests/test_spec_routing.py:68/103/336`——同上，逐行核对后全部已显式传 `engine=`，字段类型改动对这些调用点无破坏性影响。

结论：Open Questions 里"字段类型改动是否会大面积破坏既有测试 fixture"的顾虑，经枚举核实**不成立**——现存全部 16 处直接构造调用都已显式传 `engine=` 参数，字段默认值从 `"codex"` 改为 `None` 只影响**未传 `engine=` 参数**的构造调用，而枚举显示这样的调用点数量为 0。批量修复的实际工作量收窄为：仅需新增测试覆盖"未传 `engine=` 时字段值为 `None`"这一新行为本身（tasks 1.x）。

## 1. 配置层：engine 字段可区分"未显式配置"

- [ ] 1.1 补充失败测试：`tests/test_config.py` 新增 `test_review_engine_config_defaults_to_none_when_unset`（`ReviewEngineConfig()` 不传 `engine` → `.engine is None`）与 `test_spec_review_config_defaults_to_none_when_unset`（同构，`SpecReviewConfig()`）；新增 `test_build_config_review_engine_unset_is_none` / `test_build_config_spec_review_engine_unset_is_none`（TOML 无 `[review]`/`[spec_review]` 段或段内无 `engine` key → `_build()` 解析出的 `cfg.review.engine`/`cfg.spec_review.engine` 均为 `None`，与 `_build()` 显式配置 `engine = "claude"` 时解析出具体字符串对比）。
- [ ] 1.2 `src/npc/config.py::ReviewEngineConfig.engine`（56 行）与 `SpecReviewConfig.engine`（228 行）改为 `str | None = None`；`__post_init__` 的 `SUPPORTED_ENGINES` 校验加 `self.engine is not None and` 前缀守卫，`None` 视为永远合法。
- [ ] 1.3 `_build()` 第 368 行 `engine = str(review_raw.get("engine", "codex"))` 改为 `engine = _opt_str(review_raw.get("engine"), "review.engine", source)`；第 454 行 `spec_review_engine` 同构改写，复用既有 `_opt_str` helper（与 `spec_writer.bin`/`spec_writer.model` 解析方式一致）。
- [ ] 1.4 `ReviewEngineConfig`/`SpecReviewConfig` 各新增 `effective_engine(generator_backend: str) -> str` 方法：`self.engine` 非 `None` 时原样返回；否则 `"claude" if generator_backend == "codex" else "codex"`（design.md D2）。补充失败测试 `tests/test_config.py`：`test_review_engine_effective_engine_explicit_overrides_default`（`engine="claude"` + `generator_backend="claude"` → 返回 `"claude"`，验证显式值优先于按身份默认值）、`test_review_engine_effective_engine_codex_generator_defaults_claude`（`engine=None` + `"codex"` → `"claude"`）、`test_review_engine_effective_engine_non_codex_generator_defaults_codex`（`engine=None` + 分别传 `"claude"`/`"kimi"`/`"mimo"` → 均返回 `"codex"`，三选一参数化）；`SpecReviewConfig.effective_engine` 对称四个用例。
- [ ] 1.5 跑 `uv run pytest tests/test_config.py -v`，确认新增用例绿、既有 `test_config.py` 用例不回归。
- [ ] 1.6 补充失败测试：`tests/test_verify.py` 新增 `test_check_routing_review_engine_none_not_engine_unsupported`（`ReviewEngineConfig(engine=None)` 构造的 `cfg` 直接传入 `check_routing(cfg)`，即不经 `effective_engine` 解析的原始 cfg → violations 不含 `rule == "engine_unsupported"`）与 `test_check_routing_spec_review_engine_none_not_spec_engine_unsupported`（同构，`SpecReviewConfig(engine=None)`）；同时各补一个"非法字符串仍拒绝"的对照用例（`engine="bard"` → violations 含对应 rule），证明 None 守卫不放宽既有的非法字符串校验（design.md D2.5）。
- [ ] 1.7 `src/npc/verify.py::check_routing` 规则 1（第 260 行）与 `_check_spec_backend_engine_unsupported`（第 382 行附近）对 `review.engine`/`spec_review.engine` 的判定分别加 `... is not None and` 前缀守卫（design.md D2.5 代码块）；跑 1.6 新增用例转绿。
- [ ] 1.8 跑 `uv run pytest tests/test_verify.py -v`，确认既有 `engine_unsupported`/`spec_engine_unsupported`/`backend_unsupported`/`spec_backend_unsupported` 用例不回归。

## 2. 路由判定：删除 kimi_review_not_claude / spec_kimi_review_not_claude

- [ ] 2.1 补充失败测试：`tests/test_verify.py` 把断言 `kimi_review_not_claude`/`spec_kimi_review_not_claude` 命中的既有用例（若存在，按 0 节枚举结果核对）翻转为断言该 rule **不**出现在 violations 里（`coder_backend_override="kimi"`、`review.engine="codex"` 组合下 `check_routing` 返回的 violations 不含 `rule == "kimi_review_not_claude"`；spec 侧同构）；同时保留/新增对 `gen_not_orthogonal`/`mimo_exec_only` 的既有正向用例不变，证明这两条判定不受本次删除影响。
- [ ] 2.2 `src/npc/verify.py::check_routing` 删除规则 2b 判定段（289-302 行，`kimi_review_not_claude` 变量赋值 + `if` 块 + violations.append），docstring 里对应描述（列出规则 2b 的段落）同步删除。
- [ ] 2.3 `src/npc/verify.py::_check_spec_gen_not_orthogonal` 删除 `spec_kimi_review_not_claude` 判定段（426-441 行），函数 docstring 同步更新（若有对应描述）。
- [ ] 2.4 跑 `uv run pytest tests/test_verify.py -v`，确认 `gen_not_orthogonal`/`mimo_exec_only`/`mimo_in_session`/spec 侧四条同构规则用例全绿，且新删除的两条规则再无任何测试断言其存在。

## 3. 默认引擎解析：code 侧与 spec 侧统一按生成身份

- [ ] 3.1 补充失败测试：`tests/test_pipeline.py` 新增 `test_kimi_generated_code_defaults_to_codex_review`（对称于既有 `test_codex_generated_code_defaults_to_claude_review`，`generator_backend="kimi"` 且未传 `engine_name` → 断言实际执行的 review engine 为 `codex`，**替代**原有"默认 claude"预期，因为默认规则本身变了）；`tests/test_spec_pipeline.py` 对称新增 `test_kimi_runtime_spec_review_defaults_to_codex`。
- [ ] 3.2 `src/npc/pipeline.py::run_review_round` 第 758-761 行改写为：
  ```python
  selected_engine = (
      engine_name or review_cfg.effective_engine(generator_backend)
  ).lower()
  ```
  删除原先按 `generator_backend in ("codex", "kimi")` 分支硬编码 `"claude"` 的 `default_engine` 计算与相关注释；补一句注释说明"默认引擎解析已下沉到 `ReviewEngineConfig.effective_engine`，显式 `engine_name` 仍是最高优先级"。
- [ ] 3.3 `src/npc/spec_pipeline.py::_effective_spec_routing` 第 182-187 行同构改写为：
  ```python
  selected_engine = (
      engine_name or cfg.spec_review.effective_engine(writer_backend)
  ).lower()
  ```
  删除原先按 `p.runtime_host != "claude" and writer_backend == p.runtime_host` 分支的 `default_engine` 计算；`writer_backend` 已经是本函数上方算出的生成身份规范值，直接传给 `effective_engine`，不再引用 `p.runtime_host` 做二次判断——统一 code 侧与 spec 侧的措辞路径（design.md D3）。函数 docstring 同步更新，删除"非 Claude writer 未显式覆盖 review 时强制选 Claude"的过期描述。
- [ ] 3.4 跑 `uv run pytest tests/test_pipeline.py tests/test_spec_pipeline.py tests/test_spec_routing.py -v`，确认 codex/claude/mimo 三种既有生成身份的默认路由行为不变（codex→claude 不变；claude/mimo→codex 不变，只是解析路径变了），kimi 的默认路由从 claude 改为 codex 按预期生效。

## 4. 存量测试翻转（显式覆盖不再被拒绝）

- [ ] 4.1 `tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected`（约第 2233-2264 行）：保留函数名与测试场景（`generator_backend="kimi"`、`engine_name="codex"`），断言方向从"抛 `SystemExit`/routing-violation、`kimi_review_not_claude` in violations"翻转为"`run_review_round` 正常执行、未产生 routing-violation、实际使用 `codex` engine"。
- [ ] 4.2 `tests/test_spec_pipeline.py`（约第 2017 行所在测试函数）：同构翻转，断言 `spec_kimi_review_not_claude` **不**出现在 violations 里，`spec_review_run(..., engine_name="codex")` 对 kimi 写的 spec 正常执行。
- [ ] 4.3 `tests/test_coder_dispatch.py:797` 附近注释里对 `kimi_review_not_claude` 的字面提及同步更新为"路由不变量"泛称（注释性改动，不影响断言逻辑；若该注释描述的场景本身依赖已废除规则的存在，需要同步核实场景描述是否仍准确）。
- [ ] 4.4 跑 `uv run pytest tests/test_pipeline.py tests/test_spec_pipeline.py tests/test_coder_dispatch.py -v`，确认三个文件全绿。

## 5. coder.py 措辞更新

- [ ] 5.1 `src/npc/coder.py::_reject_host_dispatch_mismatch` 第 132 行 `"绕过 kimi_review_not_claude 不变量）。"` 改为 `"绕过路由不变量）。"`；docstring 其余段落（102-131 行）不改（校验逻辑与 review engine 路由无关，独立成立，design.md D5）。
- [ ] 5.2 `grep -n "kimi_review_not_claude" src/npc/coder.py` 确认改动后命中 0 行，无残留引用。
- [ ] 5.3 跑 `uv run pytest tests/test_coder_dispatch.py -v`（`_reject_host_dispatch_mismatch` 相关既有用例），确认函数行为（非措辞）不受影响。

## 6. Spec artifact 与全量回归

- [ ] 6.1 更新 `openspec/specs/kimi-native-runtime/spec.md` 对应 Requirement（本 change `specs/kimi-native-runtime/spec.md` 已含 MODIFIED 版本，`openspec archive` 时会合并）。
- [ ] 6.2 更新 `openspec/specs/spec-routing-invariant/spec.md` 对应 Requirement（本 change `specs/spec-routing-invariant/spec.md` 已含 MODIFIED 版本）。
- [ ] 6.3 新增 `openspec/specs/review-routing-guard/spec.md` 的 ADDED Requirements（本 change `specs/review-routing-guard/spec.md` 已含）。
- [ ] 6.4 跑 `openspec validate review-routing-backend-aware --type change --strict`，修复报出的全部结构性问题。
- [ ] 6.5 跑 `uv run pytest -q` 全量回归，确认无既有测试因本次改动意外回归。
- [ ] 6.6 确认 `git status --porcelain` 只涉及 `src/npc/verify.py`、`src/npc/config.py`、`src/npc/pipeline.py`、`src/npc/spec_pipeline.py`、`src/npc/coder.py`、`tests/test_config.py`、`tests/test_verify.py`、`tests/test_pipeline.py`、`tests/test_spec_pipeline.py`、`tests/test_coder_dispatch.py`、`openspec/changes/review-routing-backend-aware/**`；原始 checkout 不受影响。
