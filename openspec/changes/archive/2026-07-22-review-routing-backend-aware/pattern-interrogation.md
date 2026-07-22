## Analogs

### 1. 硬编码禁令的确切落点（要废除的对象）

- `src/npc/verify.py::check_routing` 第 285-302 行（规则 2b `kimi_review_not_claude`）：
  `effective_backend == "kimi" and review.engine != "claude"` → 无条件 violation，
  不区分"未显式配置" vs "用户显式 `--engine codex`"。这是用户目标要废除的
  核心硬规则，注释里明写"kimi 从不是合法的 review.engine 取值，必须直接按
  generator 身份判定"——即当初设计者认为 kimi 结构性不可能作为 review 执行者，
  所以选择在 coder 侧（而非 review 侧）加一刀切禁令。
- `src/npc/verify.py::_check_spec_gen_not_orthogonal` 第 426-441 行（规则
  `spec_kimi_review_not_claude`）：与上条完全同构，作用于
  `spec_writer.effective_backend`/`spec_review.engine`，注释自称"与非 spec 侧
  kimi_review_not_claude 同构（design.md F1 修复）"。两处必须同步改，否则会
  出现"code 侧放开、spec 侧仍硬锁"的不对称。
- `tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected`
  （第 2233-2264 行）与 `tests/test_spec_pipeline.py:2017`
  （断言 `spec_kimi_review_not_claude in violations`）：两个测试当前把"显式
  `--engine codex` 评审 kimi 产物必须被拒绝"断言为期望行为——这正是用户描述的
  "生产中挡住合法评审"的那个用例，write 轮必须把这两个测试改写为"显式指定被
  放行"（或删除并新增对称的"显式放行"用例），而不是保留原断言。

### 2. 已存在但只做了一半的"backend-aware 默认"逻辑（要扩展的对象）

- `src/npc/pipeline.py::run_review_round` 第 748-776 行：
  `generator_backend = phase_record.get("generator_backend") or cfg.coder.backend_for_phase(...) or p.runtime_host`；
  `default_engine = "claude" if generator_backend in ("codex", "kimi") else review_cfg.engine`；
  `selected_engine = (engine_name or default_engine).lower()`。**这是本 change
  真正要修改的默认解析函数**——当前只把 codex/kimi 两个后端归一映射到 claude，
  claude/mimo 后端落到 `review_cfg.engine`（静态默认 `"codex"`，见下条）。
  用户目标要求 codex→claude、{claude,kimi,mimo}→codex，即需要把 kimi 从
  "强制 claude 分支"移到"默认 codex 分支"，同时保留"显式 `engine_name` 永远
  优先"这条既有优先级不变。
- 第 763-776 行：`selected_engine` 算出后立即调用 `_verify.check_routing`
  做门禁——这是 default_engine 计算与硬编码禁令交互的确切位置：目前即使
  `default_engine` 已经算出了合法值，`check_routing` 里的
  `kimi_review_not_claude` 仍会在 `engine_name` 显式覆盖时二次拒绝，是"默认
  已经对，但显式覆盖被误杀"的 bug 根因。
- `src/npc/spec_pipeline.py::_effective_spec_routing` 第 163-196 行：spec 侧
  的同构实现，`default_engine = "claude" if (非 claude runtime_host 且
  writer_backend == runtime_host) else cfg.spec_review.engine`——这条判定是按
  `runtime_host`（宿主身份）而非 `spec_writer.effective_backend`（配置身份）
  分支，与 code 侧 `pipeline.py` 按 `generator_backend`（已解析的实际执行身份，
  等价于 runtime_host 归一后的值）分支的形态基本一致，但措辞路径不同，改动时
  需要对齐到同一套"按生成身份感知默认"的语言，不能各写一套判断条件。
- `src/npc/config.py::ReviewEngineConfig.engine`（第 56 行）与
  `SpecReviewConfig.engine`（第 228 行）：默认值都是硬编码字符串 `"codex"`，
  **不是** `None`（对照 `CoderConfig.backend: str | None = None` +
  `effective_backend` property 的既有模式，第 106/120-123 行）。这意味着
  "未显式配置 engine" 目前在类型层面**不可区分**于"显式配置 engine=codex"——
  两者读到的字段值完全相同。要做"未显式配置时按 coder 身份感知默认"，必须先
  解决这个可观察性缺口（见 Assumptions/Open Questions）。
- `src/npc/config.py::_build` 第 368 行 `engine = str(review_raw.get("engine", "codex"))`
  与第 454 行 `spec_review_engine = str(spec_review_raw.get("engine", "codex"))`：
  TOML 解析层同样在字符串层面吞掉了"缺省 vs 显式 codex"的区别，是上一条问题的
  真正源头（dataclass 默认值只是复述了这里已经丢失的信息）。

### 3. 结构性不变量的既有实现（第 4 点开放问题涉及的对象）

- `src/npc/verify.py::check_routing` 第 268-283 行（`gen_not_orthogonal`）与
  `_check_spec_gen_not_orthogonal` 第 410-424 行：三种同源形态
  （claude 同 bin+model / mimo+mimo / codex+codex）目前完全独立于
  `kimi_review_not_claude`，废除后者不影响这条规则的判定逻辑，两者在代码上
  是并列 `if` 块、不共享条件。
- 第 304-315 行（`mimo_exec_only`）与 `_check_spec_mimo_exec_only` 第
  444-463 行：判定 `review.engine`/`claude_model`/`claude_bin` 三个字段是否
  含 `"mimo"` 子串，与 `SUPPORTED_ENGINES = ("codex", "claude")`（不含
  `"mimo"`）配合，结构性保证 review 侧永远无法路由到 MiMo；同样与
  `kimi_review_not_claude` 无耦合。
- `src/npc/coder.py::_reject_host_dispatch_mismatch` 第 102-135 行：docstring
  与错误消息**显式引用了 `kimi_review_not_claude` 不变量**作为其存在理由的
  一部分（"继续下去会…绕过 kimi_review_not_claude 不变量"）——这是唯一一处
  会在废除该规则后**注释语义过期**（不是代码逻辑失效：这个函数本身校验的是
  `dispatch=in-session` 时 backend 与 runtime_host 一致，与 review engine 无关，
  逻辑仍然成立）的既有代码，write 轮需要更新该注释措辞，不能整体删除函数。

### 4. review engine 显式指定的既有 CLI/校验路径（第 1 点的落点）

- `src/npc/pipeline.py` 第 739-742 行：`if engine_name and engine_name not in
  ("codex", "claude"): raise ValueError(...)`——engine_name 的合法性校验独立
  于 `check_routing`，本身已经是"任意 SUPPORTED_ENGINES 取值都可显式指定"，
  说明"允许显式指定任意支持引擎"这条语义在 CLI 入参层面已经成立，真正拦住
  合法显式指定的是下游 `check_routing` 里的硬规则，而不是入参校验层。

## Assumptions

- `ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 需要从"永远是具体字符串
  （默认 `'codex'`）"改为可区分"未显式配置"的形态，最贴近仓库既有模式的做法
  是照抄 `CoderConfig.backend: str | None = None` + `effective_backend`
  property 的形状（改成 `engine: str | None = None` + `effective_engine`
  property，或等价的"resolved_engine(generator_backend)"纯函数）。本次盘问
  假设 write 轮会走这条路，而不是引入一个新的 sentinel 值（如空串）或在
  `_build()` 里传递一个额外的"is_explicit"布尔标记——后者会让
  `dataclasses.replace(cfg.review, engine=selected_engine)`（`pipeline.py`
  第 767 行既有用法）复杂化，破坏现有"用 dataclasses.replace 生成 effective_cfg"
  的既有约定。
- "codex coding 优先路由 claude review，其它后端（claude/kimi/mimo）优先路由
  codex review"这条默认映射，假设是在 `pipeline.py::run_review_round` 的
  `default_engine` 计算与 `spec_pipeline.py::_effective_spec_routing` 的
  `default_engine` 计算里**原地改判定条件**（把 kimi 从"强制 claude"分支移到
  "默认走 review_cfg 显式值或 codex"分支），而不是新增一张独立的
  "backend→engine 默认映射表"常量。理由：现有两处的条件分支已经承担了这个
  职责，仓库里没有第三处需要复用同一张表的调用点（`grep default_engine` 只命中
  这两处），提前抽表是过度设计。
- "显式指定任意支持引擎不再有一刀切禁令"，假设**仍然保留** `gen_not_orthogonal`
  / `mimo_exec_only` 两条结构性不变量对显式指定的约束——即用户显式
  `--engine codex` 评审 kimi 生成的产物应该被放行，但显式 `--engine codex`
  评审 codex 生成的产物仍应被 `gen_not_orthogonal`（`both_codex`）拒绝，显式
  指定任何含 "mimo" 的 engine 取值仍应被 `mimo_exec_only` 拒绝（这两条规则的
  语义与"是否显式"无关，是纯粹的执行身份/能力边界判定，不属于本次要废除的
  "按 coder 后端一刀切禁令"范畴）。这个边界在用户原始目标第 4 点里被明确
  留作"盘问阶段确认"，故同时列入 Open Questions。
- `check_routing` 的入参签名（`coder_backend_override` / 新增
  `review_engine_explicit` 之类）假设会保持"纯函数、原地 append violations 到
  传入 list"的既有风格（第 214-330 行的整体形态），不引入类/状态对象。
- spec 侧改动假设与 code 侧在**规则命名**上保持 `spec_` 前缀镜像既有约定
  （如 `spec_gen_not_orthogonal` 对 `gen_not_orthogonal`），废除
  `spec_kimi_review_not_claude` 后不留同名占位规则。

## Open Questions

- 用户原始目标第 4 点明确写"生成⊥验证正交不变量（gen_not_orthogonal）与 mimo
  exec-only 等结构性不变量的去留在盘问阶段与用户确认"——这两条规则是否维持
  现状不变（本次盘问的默认假设），还是需要一并调整判定范围（例如
  `gen_not_orthogonal` 的 `both_codex`/`both_mimo` 判定是否也要区分"显式 vs
  默认"，类比 kimi 规则的废除逻辑）？
- `ReviewEngineConfig.engine`/`SpecReviewConfig.engine` 从"恒具体字符串"改为
  "可为 `None`（未显式配置）"是一次 dataclass 字段类型改动，会影响所有直接
  构造 `ReviewEngineConfig(engine=...)`/`SpecReviewConfig(engine=...)` 的既有
  调用点与测试 fixture（`tests/test_verify.py`、`tests/test_pipeline.py`、
  `tests/test_config.py` 等大量直接传具体字符串的用例）。是否接受这次改动
  连带修改所有既有测试 fixture 的默认构造方式（例如统一加
  `engine="codex"` 显式传参以保持向后兼容），还是要求新字段默认值仍取
  `"codex"`（即“未显式配置”只在 TOML/`_build()` 层面区分，dataclass 本身
  仍不携带这个信息，`effective_engine` 的“未配置”只能由调用方另行传入
  `explicit: bool` 参数表达）？
- `tests/test_pipeline.py::test_explicit_codex_review_of_kimi_generated_code_is_rejected`
  与 `tests/test_spec_pipeline.py` 里断言 `spec_kimi_review_not_claude` 命中
  的用例，是直接删除，还是改写断言方向（同一测试函数名下改成"应被放行"）？
  删除会丢失"kimi 生成 + 显式 codex review"这个组合曾经被测试覆盖过的事实，
  改写更符合仓库既有习惯（保留测试名的历史语境，只翻转断言），本次盘问倾向
  改写但留给用户/write 轮确认。
- `src/npc/coder.py::_reject_host_dispatch_mismatch` 的错误消息与 docstring
  引用了 `kimi_review_not_claude` 作为"绕过风险"的措辞（第 132 行），规则
  废除后这段文字需要更新——是只改字面提及的规则名（换成"路由不变量"泛称），
  还是需要重新审视这个函数本身要不要因为 kimi 规则语义变化而调整校验范围
  （盘问结论：不需要，逻辑独立；但措辞更新范围留给 write 轮确认是否只改一处
  还是需要顺带检查同文件其它注释）？


## User Decisions (Interactive)

1. **结构性不变量维持不变**：只废除 kimi_review_not_claude / spec_kimi_review_not_claude；gen_not_orthogonal（自己不评自己：codex+codex、同 bin+model claude、mimo/mimo）与 mimo_exec_only / mimo_in_session 全部保持现状。「没有限制」的准确语义 = 显式指定任意支持引擎均放行，但以不违反生成⊥验证正交与 mimo 仅限执行为前提。
2. **unset 表达**：ReviewEngineConfig.engine / SpecReviewConfig.engine 字段改为 str | None = None（None = 未显式配置），解析默认时按生成身份感知：codex coding → claude review；其它后端 → codex review。显式指定无条件生效（仅受第 1 条结构性不变量约束）。接受批量机械性更新既有测试 fixture。
3. **存量测试**：翻转断言方向——kimi 产物 + 显式 codex review 的用例保留测试名与场景，断言从「被拒」改为「放行」。
4. **coder.py 措辞**：最小更新——只把字面引用 kimi_review_not_claude 的一处换成路由不变量泛称；write 轮顺带扫同文件其它注释确认无残留引用，不重审 _reject_host_dispatch_mismatch 的校验范围。
