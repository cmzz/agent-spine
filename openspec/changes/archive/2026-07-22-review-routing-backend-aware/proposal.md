## Why

`src/npc/verify.py::check_routing` 硬编码规则 `kimi_review_not_claude`（第 285-302 行）：只要 `coder.effective_backend == "kimi"` 且 `review.engine != "claude"` 就无条件报 violation——**不区分**"未显式配置" vs "用户显式 `--engine codex`"。生产中，用户显式请求 `--engine codex` 评审 Kimi 生成的代码这一合法操作被这条规则一刀切挡住（`tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected` 当前把这个 bug 断言为"期望行为"）。`_check_spec_gen_not_orthogonal` 里的 `spec_kimi_review_not_claude`（第 426-441 行）是同构的 spec 侧副本，同一缺陷复制了一份。

与此同时，`pipeline.py::run_review_round` 里"未显式配置时按生成身份选默认 review engine"的逻辑（第 748-776 行）只覆盖了一半：codex/kimi 生成 → 默认 claude；claude/mimo 生成 → 默认落到 `review_cfg.engine`（硬编码字符串 `"codex"`，且与"未配置"字面无法区分）。`spec_pipeline.py::_effective_spec_routing`（第 163-196 行）有一份按 `runtime_host` 分支的同构实现，措辞路径不一致。

## What Changes

- **废除** `kimi_review_not_claude` / `spec_kimi_review_not_claude` 两条硬编码禁令（`src/npc/verify.py`）。显式指定的 review engine 不再因"生成者是 Kimi"被无条件拒绝。
- **统一默认路由规则**（code 侧与 spec 侧同构）：未显式配置 review engine 时，按生成方（`coder.effective_backend` / `spec_writer.effective_backend`）身份感知选择默认引擎——生成方为 `codex` 时默认 `claude`；生成方为其它受支持后端（`claude`/`kimi`/`mimo`）时默认 `codex`。Kimi 的默认引擎从"强制 `claude`"改为与 Claude/MiMo 生成者相同的"默认 `codex`"，与其它三条一样都可被显式覆盖。
- **可区分"未显式配置"**：`ReviewEngineConfig.engine` / `SpecReviewConfig.engine` 字段类型从恒为具体字符串（默认 `"codex"`）改为 `str | None = None`（`None` = 未显式配置）；`config.py::_build()` 的 TOML 解析层同步从 `str(review_raw.get("engine", "codex"))` 改为保留 `None`。批量机械性更新既有直接构造这两个 dataclass 的测试 fixture（补显式 `engine="codex"` 等传参维持既有断言意图）。
- **显式指定的边界不变**：显式指定任意受支持引擎（`codex`/`claude`）永远生效，唯一仍受限的是两条既有结构性不变量——生成⊥验证正交（`gen_not_orthogonal`/`spec_gen_not_orthogonal`，自己不评自己：`both_claude`/`both_mimo`/`both_codex`）与 MiMo 仅限执行（`mimo_exec_only`/`spec_mimo_exec_only`）。两者维持现状不变，不扩大或收窄判定范围。
- **存量测试翻转**：`tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected` 与 `tests/test_spec_pipeline.py` 里断言 `spec_kimi_review_not_claude` 命中的用例，保留测试名与场景，断言方向从"被拒绝"改为"被放行"。
- **措辞更新**：`src/npc/coder.py::_reject_host_dispatch_mismatch` 第 132 行字面引用 `kimi_review_not_claude` 的一处改为"路由不变量"泛称；顺带扫描同文件确认无其它残留引用。

## Capabilities

### Modified Capabilities

- `kimi-native-runtime`：Requirement "Kimi generation is reviewed by Claude" 改写为 "Kimi generation follows generic backend-aware review routing, kimi remains an invalid review engine value"——默认引擎从强制 Claude 改为与 Claude/MiMo 生成者同构的默认 Codex，显式指定任意受支持引擎不再被 Kimi 生成身份拒绝；`kimi` 本身仍恒为非法 `review.engine`/`spec_review.engine` 取值（不变）。
- `spec-routing-invariant`：Requirement "spec 侧路由配置与安全默认值" 更新以反映 `spec_review.engine` 字段可为 `None`（未显式配置）与按生成身份感知解析的 `effective_engine`；全无配置时的最终解析结果（`spec_writer` 缺省 `claude` → `spec_review` 有效引擎 `codex`）不变。
- `review-routing-guard`：新增两条 Requirement，把"显式指定任意支持引擎不受一刀切禁令限制"与"未显式配置时按生成身份感知默认路由（`codex`→`claude`，其余→`codex`）"这两条此前分散在 kimi/codex 专属能力里、从未被通用化文档记录的规则，提升为该能力的显式契约。

## Impact

- **路由判定**：`src/npc/verify.py::check_routing` 删除规则 2b（`kimi_review_not_claude`），`_check_spec_gen_not_orthogonal` 删除对应 spec 侧判定段。
- **配置层**：`src/npc/config.py::ReviewEngineConfig.engine` / `SpecReviewConfig.engine` 字段类型改为 `str | None = None`；`_build()` 第 368/454 行两处 TOML 解析改为保留 `None`。
- **路由解析**：`src/npc/pipeline.py::run_review_round` 第 758 行 `default_engine` 判定改写为按生成身份统一分支（`codex`→`claude`，其余→显式配置值或 `codex`）；`src/npc/spec_pipeline.py::_effective_spec_routing` 第 182 行同构改写，从按 `runtime_host` 分支改为按 `writer_backend`（与 code 侧统一措辞）。
- **CLI 校验**：`src/npc/pipeline.py` 第 739-742 行 `engine_name` 合法性校验本身已允许任意 `SUPPORTED_ENGINES` 取值，无需改动。
- **注释措辞**：`src/npc/coder.py::_reject_host_dispatch_mismatch`（第 132 行）。
- **测试**：`tests/test_verify.py`、`tests/test_pipeline.py`、`tests/test_spec_pipeline.py`、`tests/test_coder_dispatch.py`、`tests/test_config.py`、`tests/test_engines.py`、`tests/test_spec_routing.py` 中直接构造 `ReviewEngineConfig`/`SpecReviewConfig` 或断言 `kimi_review_not_claude`/`spec_kimi_review_not_claude` 的既有用例。

## Non-Goals

- 不改变 `gen_not_orthogonal` / `spec_gen_not_orthogonal`（生成⊥验证正交，自己不评自己：`both_claude`/`both_mimo`/`both_codex`）与 `mimo_exec_only` / `spec_mimo_exec_only` / `mimo_in_session` / `spec_mimo_in_session` 的判定范围或触发条件——盘问阶段已与用户确认全部维持现状（见 `pattern-interrogation.md` User Decisions #1）。
- 不把 `kimi` 加入 `SUPPORTED_ENGINES`（review engine 恒为 `codex`/`claude` 二选一，`kimi` 从不是合法的 review engine 取值）。
- 不改变 `SUPPORTED_CODER_BACKENDS`、runtime host 解析、in-session 分发默认等既有 Kimi/Codex 原生运行载体行为。
- 不重新审视 `_reject_host_dispatch_mismatch` 的校验范围本身——该函数校验的是 `dispatch=in-session` 时 backend 与 runtime_host 一致，与 review engine 路由无关，逻辑独立、不受本次影响，只更新其错误消息里对已废除规则名的字面引用。
- 不引入新的"backend→engine 默认映射表"常量；默认映射直接在 `pipeline.py`/`spec_pipeline.py` 既有的 `default_engine` 计算处原地改判定条件。
