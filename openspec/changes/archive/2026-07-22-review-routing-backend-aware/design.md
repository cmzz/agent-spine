## Context

`src/npc/verify.py::check_routing`（第 214-330 行）实现八条路由不变量：既有四条 coder⊥review（`backend_unsupported`/`engine_unsupported`/`gen_not_orthogonal`/`mimo_exec_only`/`mimo_in_session`）+ 后来加的规则 2b `kimi_review_not_claude`，以及 `spec-routing-invariant` change 补的四条 spec 侧同构规则（含同构副本 `spec_kimi_review_not_claude`）。`kimi_review_not_claude` 的注释自陈设计意图："Kimi 从不是合法的 review.engine 取值，'同源'判定对它结构性不可达，必须直接按 generator 身份判定"——这个判断本身没错（Kimi 确实不在 `SUPPORTED_ENGINES` 里，`both_codex`/`both_mimo` 那种同源判定确实覆盖不到它），但由此选择的实现"生成方是 Kimi 时非 Claude engine 一律拒绝"混淆了两件事：(a) 结构性上 Kimi 不可能自评自己（因为 kimi 从不是合法 review engine，这条永真，不需要额外规则），(b) 策略上"Kimi 生成的代码只能给 Claude 评"（这是一条业务默认值偏好，不是结构性不可违反的不变量）。规则 2b 把 (b) 实现成了和 (a) 同等强度的无条件硬闸，导致显式 `--engine codex` 这种合法诉求被一并挡住。

`pipeline.py::run_review_round`（第 748-776 行）与 `spec_pipeline.py::_effective_spec_routing`（第 163-196 行）已经各自实现了"默认引擎按生成身份选择"的一半：前者把 codex/kimi 都映射到 claude 默认；后者按 `runtime_host`（而非 `spec_writer.effective_backend`）分支，两处测的都是"是否非 Claude 生成"这一件事，但计算路径和覆盖范围不完全对齐。`ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 恒为具体字符串（默认 `"codex"`），与 `CoderConfig.backend: str | None = None` + `effective_backend` 的既有模式不对称——这个不对称正是"未显式配置"与"显式配置为 codex"无法区分的根源，也是本次要修的结构性缺口。

用户在盘问阶段已就四个关键问题拍板（见下方 Pattern Mapping）：(1) 只废除 `kimi_review_not_claude`/`spec_kimi_review_not_claude`，`gen_not_orthogonal`/`mimo_exec_only`/`mimo_in_session` 及其 spec 侧同构规则全部维持现状；(2) `engine` 字段改为 `str | None = None`，接受批量机械性更新既有测试 fixture；(3) 存量测试翻转断言方向而非删除；(4) `coder.py` 措辞最小更新。

## Goals / Non-Goals

**Goals：**

- 删除 `check_routing`/`_check_spec_gen_not_orthogonal` 里的 `kimi_review_not_claude`/`spec_kimi_review_not_claude` 判定段，不影响同函数内其它规则的判定逻辑与顺序。
- `ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 改为 `str | None = None`；`config.py::_build()` 两处 TOML 解析同步保留 `None`（不再用 `str(..., "codex")` 吞掉"未配置"信息）。
- `check_routing`（`src/npc/verify.py` 第 260 行，规则 1 `engine_unsupported`）的判定 MUST 同步加 `review.engine is not None and` 前缀守卫，与 `_check_spec_backend_engine_unsupported` 里 `spec_engine_unsupported` 已有的 None-safe 判定语义对齐（详见 D2.5）——否则 `engine` 字段类型从"恒具体字符串"改为 `str | None` 后，`npc verify routing` 等直接对未经 `effective_engine` 解析的原始 `cfg` 调用 `check_routing(cfg)` 的路径会在"未配置 `[review].engine`"这一新合法状态下误报 `engine_unsupported`。
- 新增一个共享的按生成身份解析默认引擎的规则：生成方 `effective_backend == "codex"` → 默认 `"claude"`；否则（`"claude"`/`"kimi"`/`"mimo"`）→ 默认 `"codex"`。`pipeline.py`/`spec_pipeline.py` 原地改写各自 `default_engine` 计算处，统一到这一条规则，两处不各写一套判断条件。
- 显式指定（CLI `--engine` 覆盖，或 TOML 显式配置的具体字符串）永远优先于按生成身份的默认值；显式指定的合法性只受 `gen_not_orthogonal`/`mimo_exec_only` 两条既有结构性规则约束，不受"生成者是谁"这单一维度的一刀切禁令约束。
- 存量测试翻转断言方向；批量更新直接构造 `ReviewEngineConfig(engine=...)`/`SpecReviewConfig(engine=...)` 的既有 fixture，显式传具体字符串保持向后兼容行为不变。
- `src/npc/coder.py::_reject_host_dispatch_mismatch` 错误消息里对 `kimi_review_not_claude` 的字面引用换成"路由不变量"泛称。

**Non-Goals：**

- 不改变 `gen_not_orthogonal`/`spec_gen_not_orthogonal`（`both_claude`/`both_mimo`/`both_codex` 三种同源形态）与 `mimo_exec_only`/`spec_mimo_exec_only`/`mimo_in_session`/`spec_mimo_in_session` 的判定范围、触发条件或 `rule`/`detail` 措辞。
- 不把 `kimi` 加入 `SUPPORTED_ENGINES`。
- 不改变 `check_routing`/`_check_spec_gen_not_orthogonal` 的入参签名风格（纯函数、原地 append violations 到传入 list）。
- 不引入独立的"backend→engine 默认映射表"常量；不引入"is_explicit"布尔标记参数——用 `engine: str | None` 本身表达"是否显式配置"，与既有 `effective_backend` 模式对齐。
- 不重审 `_reject_host_dispatch_mismatch` 的校验范围（该函数逻辑与 review engine 路由无关，独立成立）。

## Pattern Mapping

> 本段落原样带入 `pattern-interrogation.md` 的 `## Open Questions` 与 `## User Decisions (Interactive)`（该文件含 `## User Decisions (Interactive)` 标题，按 write 轮契约取该分支）。

### Open Questions

- 用户原始目标第 4 点明确写"生成⊥验证正交不变量（gen_not_orthogonal）与 mimo exec-only 等结构性不变量的去留在盘问阶段与用户确认"——这两条规则是否维持现状不变（本次盘问的默认假设），还是需要一并调整判定范围（例如 `gen_not_orthogonal` 的 `both_codex`/`both_mimo` 判定是否也要区分"显式 vs 默认"，类比 kimi 规则的废除逻辑）？
- `ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 从"恒具体字符串"改为"可为 `None`（未显式配置）"是一次 dataclass 字段类型改动，会影响所有直接构造 `ReviewEngineConfig(engine=...)`/`SpecReviewConfig(engine=...)` 的既有调用点与测试 fixture（`tests/test_verify.py`、`tests/test_pipeline.py`、`tests/test_config.py` 等大量直接传具体字符串的用例）。是否接受这次改动连带修改所有既有测试 fixture 的默认构造方式（例如统一加 `engine="codex"` 显式传参以保持向后兼容），还是要求新字段默认值仍取 `"codex"`（即"未显式配置"只在 TOML/`_build()` 层面区分，dataclass 本身仍不携带这个信息，`effective_engine` 的"未配置"只能由调用方另行传入 `explicit: bool` 参数表达）？
- `tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected` 与 `tests/test_spec_pipeline.py` 里断言 `spec_kimi_review_not_claude` 命中的用例，是直接删除，还是改写断言方向（同一测试函数名下改成"应被放行"）？删除会丢失"kimi 生成 + 显式 codex review"这个组合曾经被测试覆盖过的事实，改写更符合仓库既有习惯（保留测试名的历史语境，只翻转断言），本次盘问倾向改写但留给用户/write 轮确认。
- `src/npc/coder.py::_reject_host_dispatch_mismatch` 的错误消息与 docstring 引用了 `kimi_review_not_claude` 作为"绕过风险"的措辞（第 132 行），规则废除后这段文字需要更新——是只改字面提及的规则名（换成"路由不变量"泛称），还是需要重新审视这个函数本身要不要因为 kimi 规则语义变化而调整校验范围（盘问结论：不需要，逻辑独立；但措辞更新范围留给 write 轮确认是否只改一处还是需要顺带检查同文件其它注释）？

### User Decisions (Interactive)

1. **结构性不变量维持不变**：只废除 kimi_review_not_claude / spec_kimi_review_not_claude；gen_not_orthogonal（自己不评自己：codex+codex、同 bin+model claude、mimo/mimo）与 mimo_exec_only / mimo_in_session 全部保持现状。「没有限制」的准确语义 = 显式指定任意支持引擎均放行，但以不违反生成⊥验证正交与 mimo 仅限执行为前提。
2. **unset 表达**：ReviewEngineConfig.engine / SpecReviewConfig.engine 字段改为 str | None = None（None = 未显式配置），解析默认时按生成身份感知：codex coding → claude review；其它后端 → codex review。显式指定无条件生效（仅受第 1 条结构性不变量约束）。接受批量机械性更新既有测试 fixture。
3. **存量测试**：翻转断言方向——kimi 产物 + 显式 codex review 的用例保留测试名与场景，断言从「被拒」改为「放行」。
4. **coder.py 措辞**：最小更新——只把字面引用 kimi_review_not_claude 的一处换成路由不变量泛称；write 轮顺带扫同文件其它注释确认无残留引用，不重审 _reject_host_dispatch_mismatch 的校验范围。

## Decisions

**D1：`check_routing`/`_check_spec_gen_not_orthogonal` 直接删除规则 2b/同构段，不做条件收窄。**

```python
# 删除（verify.py 第 285-302 行）：
kimi_review_not_claude = (
    effective_backend == "kimi" and review.engine != "claude"
)
if kimi_review_not_claude:
    violations.append({"rule": "kimi_review_not_claude", ...})
```

同样删除 `_check_spec_gen_not_orthogonal` 内的 `spec_kimi_review_not_claude` 段（第 426-441 行）。`check_routing`/`_check_spec_gen_not_orthogonal` 的 docstring 同步删除对这两条规则的描述（规则编号 2b 与列表中的第 6 条相应说明）。`both_codex`/`both_mimo`/`same_claude_identity`（`gen_not_orthogonal`）判定段本身不改一行——这条规则从未依赖 `kimi_review_not_claude` 的存在，两者在代码里是并列 `if` 块。

**D2：`ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 改为 `str | None = None`；新增 `effective_engine(generator_backend: str) -> str` 方法，与既有 `CoderConfig.effective_backend` property 同构（但需要一个参数，因为默认值依赖对方——生成方——的身份，不像 `effective_backend` 只依赖自身字段）。**

```python
@dataclasses.dataclass(frozen=True)
class ReviewEngineConfig:
    engine: str | None = None  # None = 未显式配置
    ...

    def effective_engine(self, generator_backend: str) -> str:
        """按生成身份感知解析默认值；显式配置永远优先。"""
        if self.engine is not None:
            return self.engine
        return "claude" if generator_backend == "codex" else "codex"

    def __post_init__(self) -> None:
        if self.engine is not None and self.engine not in SUPPORTED_ENGINES:
            raise ConfigError(...)
```

`SpecReviewConfig` 同构新增 `effective_engine(spec_writer_backend: str) -> str`。`__post_init__` 的合法性校验只在 `engine is not None` 时触发——`None` 本身永远合法（代表"未配置"，不是一个需要落在 `SUPPORTED_ENGINES` 里的取值）。`config.py::_build()` 第 368/454 行两处从 `str(review_raw.get("engine", "codex"))` 改为 `_opt_str(review_raw.get("engine"), "review.engine", source)`（复用既有 `_opt_str` helper，与 `spec_writer.bin`/`spec_writer.model` 等既有 Optional 字符串字段解析方式一致）。

选择"方法而非 property"是因为默认值依赖外部参数（generator_backend），不是 `effective_backend` 那种只读自身字段就能算出结果的 property——如果强行做成 property 需要在构造时就注入 generator_backend，会破坏 `dataclasses.replace(cfg.review, engine=selected_engine)`（`pipeline.py` 第 767 行既有用法）的"先构造配置、后按需解析"顺序。

**D3：`pipeline.py::run_review_round`/`spec_pipeline.py::_effective_spec_routing` 的 `default_engine` 计算原地改写为调用 `effective_engine`，不再自行判断 codex/kimi 与静态默认值。**

```python
# pipeline.py（原第 758-761 行）：
selected_engine = (engine_name or review_cfg.effective_engine(generator_backend)).lower()
```

```python
# spec_pipeline.py（原第 182-187 行，同时把分支条件从 runtime_host 改为 writer_backend，
# 与 code 侧统一措辞——writer_backend 已经是"生成身份"的规范值，不需要另外读 runtime_host）：
selected_engine = (
    engine_name or cfg.spec_review.effective_engine(writer_backend)
).lower()
```

`engine_name` 仍是最高优先级（CLI 显式覆盖），未变。`review_cfg.engine`（TOML 显式配置的具体字符串）现在通过 `effective_engine` 内部的 `if self.engine is not None: return self.engine` 分支自动生效，不需要在调用处再写一层"CLI > TOML 配置 > 默认"的三级判断——`effective_engine` 已经把"TOML 配置 > 按生成身份的默认值"这两级折叠进一个方法，调用处只需再叠一层"CLI 覆盖"即可。

下游 `check_routing(effective_cfg, coder_backend_override=generator_backend)` 调用不变——`effective_cfg` 仍然是把 `selected_engine` 写回 `review.engine`（`dataclasses.replace`）之后的具体值，`run_review_round` 这条路径下 `check_routing` 内部读 `review.engine` 时永远是一个具体字符串（因为已经在这一步被 `effective_engine` 解析过）。但这**不代表 `check_routing` 自身的判定逻辑可以假设 `review.engine` 恒非 `None`**——`check_routing` 是纯函数、被多处调用（见 D2.5），`run_review_round` 只是其中一个调用方，其它调用方（如 `npc verify routing`）可能传入未经 `effective_engine` 解析的原始 `cfg`。

**D2.5：`check_routing`（`src/npc/verify.py` 第 260 行）规则 1 对 `review.engine` 的校验、`_check_spec_backend_engine_unsupported`（第 382 行）对 `spec_review.engine` 的校验，MUST 同步加 `... is not None and` 前缀守卫。**

```python
# src/npc/verify.py::check_routing 规则 1（原第 260 行）：
if review.engine not in _config.SUPPORTED_ENGINES:
    ...
# 改为：
if review.engine is not None and review.engine not in _config.SUPPORTED_ENGINES:
    ...
```

```python
# src/npc/verify.py::_check_spec_backend_engine_unsupported（原第 382 行）：
if spec_review.engine not in _config.SUPPORTED_ENGINES:
    ...
# 改为：
if spec_review.engine is not None and spec_review.engine not in _config.SUPPORTED_ENGINES:
    ...
```

`ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 当前（改动前）均为 `engine: str = "codex"`（恒具体字符串，`config.py` 第 54/228 行），本 change 才把两者一并改为 `str | None = None`（D2）——这两处判定守卫是**同一次改动新引入的必需配套修复**，不是"code 侧补齐到 spec 侧既有形态"：字段类型改动前，`review.engine`/`spec_review.engine` 恒非 `None`，两处判定原本就不需要感知 `None`；字段类型改动落地后若不加此守卫，`npc verify routing`（`verify.py` 第 504 行 `check_routing(cfg)`，直接对原始 `cfg` 调用、不经过 `effective_engine` 解析）与任何直接调用 `check_routing`/`_check_spec_backend_engine_unsupported` 校验未解析 `spec_review` 段的路径，会在"用户未配置 `[review].engine`/`[spec_review].engine`"这一本次新引入的合法状态下，误将 `None` 当越界取值命中 `engine_unsupported`/`spec_engine_unsupported`——这是一个会在默认（未配置）项目上炸穿 `npc verify routing` 的回归，不仅是文档措辞问题。两处判定逻辑本身不新增判定分支、不改变"非法字符串仍拒绝"的既有行为。

**D4：存量测试 — 翻转断言方向，不删除测试名。**

- `tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected`：断言从"抛 routing-violation / `kimi_review_not_claude` in violations"改为"`run_review_round(..., engine_name="codex")` 正常执行、返回值 `ok` 字段反映实际 review 结果（非 routing-violation 提前拒绝）"。
- `tests/test_spec_pipeline.py`：断言 `spec_kimi_review_not_claude in violations` 的用例改为断言该 rule 不在 violations 里、且 spec review 正常继续执行。
- `tests/test_verify.py`（若存在直接调用 `check_routing` 断言 `kimi_review_not_claude` 命中的用例）同构翻转。
- **新增**对称场景：kimi 生成 + 未显式指定 engine → 默认解析为 `codex`（替代原先的"默认 claude"断言，因为默认规则本身变了，不是只有显式覆盖变了）。

**D5：`src/npc/coder.py::_reject_host_dispatch_mismatch` 第 132 行措辞更新，函数逻辑不变。**

```python
# 原：
"绕过 kimi_review_not_claude 不变量）。"
# 改：
"绕过路由不变量）。"
```

docstring 其它段落（第 102-131 行）描述的是"in-session 分发时 backend 必须与 runtime_host 一致"这条独立不变量，不涉及 review engine 路由，不需要改动。扫描确认 `coder.py` 全文无其它对 `kimi_review_not_claude`/`spec_kimi_review_not_claude` 的字面引用。

## Risks / Trade-offs

- **[默认路由行为变化：kimi 生成的代码默认 review engine 从 claude 变为 codex]** 这是用户原始目标第 2 点的显式要求（"其它后端（claude/kimi/mimo）coding 优先路由 codex review"），不是意外副作用。已依赖此前"kimi 默认 claude"行为的用户/文档需要更新预期；`docs/`（若有）与本 change 的 spec delta 均需同步反映新默认值。
- **[dataclass 字段类型改动的测试面]** `engine: str | None = None` 影响所有直接构造 `ReviewEngineConfig`/`SpecReviewConfig` 的既有测试（Open Questions 已列出的 `test_engines.py`/`test_spec_routing.py`/`test_coder_dispatch.py`/`test_spec_pipeline.py`/`test_verify.py` 等），Decision 2 已接受批量机械性更新的成本，但需要逐文件核对不遗漏。
- **[`effective_engine` 是方法而非 property]** 与仓库里 `effective_backend` 的 property 命名习惯不完全对称（因为多了一个参数），调用处需要显式传参而非属性访问；已在 D2 说明选择依据，接受这一处命名不对称。

## Migration Plan

1. `.npc/config.toml` 未显式配置 `[review].engine`/`[spec_review].engine` 的既有项目：字段解析结果从具体字符串 `"codex"` 变为 `None`；`effective_engine()` 解析出的最终值在 coder/spec_writer 为 `claude`/`mimo` 时不变（仍是 `"codex"`），仅在生成方为 `kimi` 时从 `"claude"` 变为 `"codex"`——这是本 change 的核心行为变更，不是兼容性回归。
2. 显式配置了 `[review].engine = "codex"`（或 `"claude"`）的既有项目：解析结果不变（`_opt_str` 保留显式值，与之前的 `str(...)` 结果一致）。
3. 无需数据迁移——`engine` 字段只存在于内存配置对象，不落盘到任何持久化 state。
4. 回滚：还原 D1-D5 四处改动即可；不涉及 schema version bump。

## Open Questions

无。四条关键裁决已在 Pattern Mapping 段落记录并在 Decisions D1-D5 中兑现。
