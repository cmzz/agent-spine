## Why

审计 B4（高）：`record_implement/record_fix` 只信 RESULT 行的 `tests` 字段（src/npc/pipeline.py:974/1080），从不复跑。而 `verify.py:123-171` 整套 `run_tests`（真实复跑、shlex 防注入、探测 pytest/npm/make）已造好却从未被 pipeline 或 skill 调用——笼子造好只差接线（对应 docs/optimization-proposals/2026-06-22.md 提案 1 与 principles.md Roadmap「复跑测试硬轨」）。tests=pass 裸信 coder 自报违反不变量 2（不信 LLM 散文/自报，信可复验的结构化事实）；--auto 档去掉人后按不变量 3 恰恰需要这道硬轨。

## What Changes

- `record_implement` / `record_fix` 在 RESULT 报 `tests=pass` 时调用 `verify.run_tests` 真实复跑（在 run 的 worktree cwd 下）。
- 复跑失败 → 覆盖 coder 自报：record 结果 `tests` 置 fail、状态置 failed，返回 JSON 标注 `tests_verified=false` + 复跑摘要——不采信自报。
- 复跑通过 → `tests_verified=true` 进返回 JSON 与 telemetry。
- **可配置关闭**（遵不变量 3 笼子最小化）：`[verify].rerun_tests = true|false`，默认开启于 `--auto` 档、交互档可关；无法探测测试命令时降级为 `tests_verified=null`（记录、不阻塞）。
- 补测试：复跑失败覆盖自报、复跑通过、配置关闭跳过、探测不到测试命令的降级路径。

## Capabilities

### New Capabilities

- `record-test-verification`: record 阶段对 coder 自报 tests=pass 的真实复跑验证契约。

### Modified Capabilities

## Impact

- `src/npc/pipeline.py`（record_implement / record_fix 接 verify.run_tests）
- `src/npc/verify.py`（run_tests 如需返回结构微调）
- `src/npc/_config.py`（`[verify].rerun_tests` 配置项）
- `tests/`（四条路径用例）
