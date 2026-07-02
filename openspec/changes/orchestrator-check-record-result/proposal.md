## Why

审计 B2（严重）：in-session 分支下 `IMPL.ok`（spine-run.md:122）恒为 true（coder.py:424-434，只代表 prompt 渲染成功），真正判定 coder 成败的 `npc implement record` / `npc fix record` 的返回值 skill **从不检查**（spine-run.md:133/160）。`record_fix` 失败时把 progress 置 `needs-user-decision`（pipeline.py:1067-1122），但主循环无视、继续 review；若后续某轮恰好 blocking==0，archive 会把状态覆盖成 archived（pipeline.py:874），人工闸门被静默抹掉。这同时违反不变量 1（archive 闸门只认 review，不认 coder 自报——而这里连 record 失败都不认）与不变量 2（主 session 必须以结构化契约返回值做分支）。

## What Changes

- 纯 skill markdown 契约修改（不改 src/ 代码）：`spine-run.md` 3a 的 `npc implement record` 与 3b 的 `npc fix record` 调用后 MUST 检查返回 JSON 的 `.ok` 与 `.status`。
- `.ok=false` 或 `.status=needs-user-decision` → 立即转 3d 决策点（auto 档 `npc auto-decide --trigger implementer-failed|fixer-failed`；交互档 AskUserQuestion），**不再盲目继续 review**。
- Guardrails 一节补一条硬约束：record 返回值是 coder 成败的唯一真相，`IMPL.ok`/`FIX.ok`（deferred=true 时）只代表 prompt 渲染成功，不得当作执行成功。
- 文档同步：docs 中主循环数据流图（如有）标注该检查点。

## Capabilities

### New Capabilities

- `orchestrator-record-check`: 主循环对 implement/fix record 返回值的强制检查契约，失败即转决策点。

### Modified Capabilities

## Impact

- `plugins/agent-spine/commands/spine-run.md`（3a/3b record 检查 + Guardrails 补条）
- `docs/`（主循环契约描述同步）
- 不改任何 `src/npc/` 代码
