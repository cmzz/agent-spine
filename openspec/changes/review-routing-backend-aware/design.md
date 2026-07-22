## Context

`run_review_round`（`src/npc/pipeline.py:717`）目前内联实现 backend-aware 默认：`generator_backend in ("codex","kimi")` 时默认 claude（`pipeline.py:758-761`），否则用 `[review].engine` 配置。spec 侧 `_effective_spec_routing`（`src/npc/spec_pipeline.py:163-196`）有另一份形式不同的重复逻辑。缺口：(1) claude 生成源 + 配置引擎同源（claude/claude 同 bin 同 model）时，`check_routing` 只拒绝，无自动选路；(2) 两处内联分支无单一可单测的纯函数；(3) `cli.py:258` help 与 `pipeline.py:731` docstring 及插件 SKILL.md 编排规则仍描述「默认从配置读，缺省 codex」的旧行为。

生成源身份来源：phase 记录中的 `generator_backend`（`state.json` 的 `progress[seq].phases.<phase>.generator_backend`），缺失时回退配置解析——该机制本 change 不动。

## Goals / Non-Goals

**Goals:**

- 单一确定性纯函数 resolver，集中表达「显式 override > 生成源默认 > 配置引擎」的优先级，review pipeline 与 spec pipeline 共用。
- claude 生成源在配置同源时自动选 codex，消掉「配置即违法」死局（config 里 `[review].engine=claude` 与同 bin/model 的 claude coder 组合目前必然 violation）。
- 文档/help/编排规则与代码行为对齐。

**Non-Goals:**

- 不改 `check_routing` 规则、rule 字符串、detail 语义与退出码。
- 不改 `generator_backend` 记录机制与 legacy phase 回退。
- 不新增引擎或后端。
- 显式 override 被拒路径形态不变。

## Decisions

### D1: resolver 落位 `src/npc/verify.py`，纯函数 `resolve_review_engine`

签名（示意）：`resolve_review_engine(generator_backend, configured_engine, *, engine_override=None, generator_identity=None, review_identity=None) -> str`。放 verify.py 而非新模块：路由「选择」与「校验」是不变体的两面，同模块便于保持语义同步；纯函数、无副作用、可直接单测。备选（新建 `routing.py` 模块）被否：为一个函数新建模块过度，`check_routing` 已聚合全部路由语义。

优先级实现：
1. `engine_override` 非空 → 返回 override（合法性交给 `check_routing`，resolver 不做校验，保持单一职责）。
2. `generator_backend in ("codex", "kimi")` → `"claude"`（固化现有内联行为）。
3. `generator_backend == "claude"`：配置引擎与生成源同源（engine == "claude" 且 bin/model 相同，复用 `check_routing` 既有的同源判定口径）→ `"codex"`；否则 → 配置引擎。
4. 其余（mimo 等）→ 配置引擎。

identity 参数用于 claude/claude 同源判定；缺省为 None 时按「同源」保守处理（即选 codex），与 `check_routing` 的保守拒绝口径一致。

### D2: pipeline 与 spec pipeline 改为调用 resolver

- `pipeline.py:758-761` 内联分支替换为 `resolve_review_engine(...)` 调用；未知引擎校验（`pipeline.py:739-742`）与 `check_routing` 调用顺序不变。
- `spec_pipeline.py:163-196` 的 `_effective_spec_routing` 内部改为委托同一 resolver（保留其现有签名/返回形态，最小侵入）。

### D3: 文档对齐范围

- `src/npc/cli.py:258` `--engine` help：改为「缺省按生成源 backend-aware 解析（codex/kimi→claude，claude 同源→codex），否则取 [review].engine」。
- `src/npc/pipeline.py:731` docstring 同步。
- `plugins/agent-spine/skills/spine-run/SKILL.md` 与 `plugins/agent-spine/skills/spine-spec/SKILL.md` 的 host adapter mapping：把「backend=codex/kimi 时必须显式传 `--engine claude`」改写为「npc 已内置自动选路；显式传 `--engine claude` 仍合法但非必需；绝不回退到自评」的语义保留。

### D4: 不改 legacy 回退

`generator_backend` 缺失时的 config 回退（`pipeline.py:749-753`）保持原样——历史记录修复属另一 change 的事。

## Risks / Trade-offs

- [claude 生成源 + 配置 engine=claude（不同 model）的合法组合被 D1 步骤 3 精确判定，不会误改] → 同源判定复用 `check_routing` 口径并配单测覆盖。
- [spec 侧 `_effective_spec_routing` 委托后返回形态变化破坏 spec 流程] → 保留原签名与返回结构，仅替换内部选择逻辑；跑既有 spec routing 测试回归。
- [编排者继续显式传 `--engine claude`（旧 SKILL.md 习惯）] → 完全兼容：kimi/codex 生成源下该 override 本就合法；文档更新后逐步自然消亡。

## Migration Plan

纯代码+文档变更，无数据迁移。合入后既有 run 的 review 行为在 codex/kimi 生成源下不变；claude 生成源 + 同源配置的 run 从「必然 routing-violation」变为「自动 codex review」，属行为修复而非回归。

## Open Questions

（无）
