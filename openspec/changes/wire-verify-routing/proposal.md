## Why

审计 B3（严重/与不变量矛盾）：docs/principles.md:47 声称不变量 1/4 的路由约束「由 `npc verify routing` 在代码层强制」，但 `check_routing`（src/npc/verify.py:183）只在独立子命令 `npc verify routing`（verify.py:294）里被调用；`run_review_round`（src/npc/pipeline.py:490）与 `run_implement/run_fix`（src/npc/coder.py:358/535）都不调用，spine-run.md 全文也从不执行它。「review 与 coder 同源」在运行时零阻拦——宪法级不变量 1（生成⊥验证）实际是 opt-in 且未接主回路。审计建议 4 指出：接线成本极低，收益是不变量从「声明」变「执行」。

## What Changes

- `run_review_round` 入口调用 `verify.check_routing(cfg)`：发现 violation（review 与 coder 同源、review 引擎/bin/model 含 mimo 等）即 `emit_error("routing-violation", ...)` 拒绝执行 review，exit 1——review 永不在违规路由下运行。
- violation 详情（rule / 字段 / 值）进入错误 JSON，供主 session 报人；不做静默降级。
- 补「接线」测试：不只测 `check_routing` 函数本身，而是断言 `run_review_round` 在违规配置下拒绝执行、合法配置下正常执行。
- principles.md 措辞核对：接线后「代码层强制」的声明变为事实，不需改文；如有出入按实际实现微调。

## Capabilities

### New Capabilities

- `review-routing-guard`: review 执行前的路由强制校验——生成⊥验证不变量的运行时执行点。

### Modified Capabilities

## Impact

- `src/npc/pipeline.py`（run_review_round 入口接 check_routing）
- `src/npc/verify.py`（如需暴露可复用的校验入口，最小重构）
- `tests/`（接线测试：违规拒绝 / 合法放行）
- `docs/principles.md`（声明与实现对齐核对）
