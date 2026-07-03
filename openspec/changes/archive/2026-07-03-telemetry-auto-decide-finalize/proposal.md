## Why

审计 B14（低但高价值信号）：telemetry 有两处完整性缺口——(1) `auto_decide.py` 完全不 emit telemetry：skip/force-archive/各 trigger 频次对 `/spine-analyze` 不可见，而这恰是「harness 在哪卡住」的最高价值信号；(2) `state.py` finalize 与 ff-merge 结果不 emit（state.py:502-616）：run 级成败、merged_back、合回失败率进不了 `~/task_log/_telemetry/` 指标流。不变量 2 要求全轨迹落 telemetry 作为复盘与 `/spine-analyze` 的唯一依据；不变量 4 的越界审计（auto-decide 决策是否合规）也依赖这些事件。

## What Changes

- `auto_decide.py` 每次决策 emit 一条 telemetry 事件（kind=`auto_decide.decision`）：trigger / action / reason / seq / change_id / applied。
- `state.py` finalize emit 一条 run 级事件（kind=`run.finalize`）：顶层 status / merged_back / worktree_removed / spine_branch / 各 change 终态计数。
- telemetry 写入失败不阻塞主流程（现有 telemetry 层容错语义不变）。
- 补测试：auto-decide 决策后事件落盘且字段齐全；finalize 后 run 级事件落盘（merged_back 真/假两态）。

## Capabilities

### New Capabilities

- `decision-telemetry`: auto-decide 决策与 finalize/ff-merge 结果进入 telemetry 指标流的契约。

### Modified Capabilities

## Impact

- `src/npc/auto_decide.py`（决策后 emit telemetry）
- `src/npc/state.py`（finalize 出口 emit run 级事件）
- `src/npc/telemetry.py`（如需新增 kind 常量/字段）
- `tests/`（两类事件的落盘用例）
