## Why

审计 B5（高）：`run_archive` 有两处 `subprocess.run(..., check=True)` 的裸失败路径——`git add openspec/`（src/npc/pipeline.py:831）与 `_git_head`（pipeline.py:737/854）。`cli_archive_run` 只捕获 FileNotFoundError/ValueError（pipeline.py:1202-1207）。`git add` 因 index.lock、权限、pre-commit hook 失败时 → 裸 traceback、exit 1、stdout 无 JSON → 主 session `jq -r '.ok'` 读到空串，分支行为未定义。直接违反不变量 2（npc→主 session 的交接必须是一行结构化 JSON，不信散文/traceback）。

## What Changes

- `run_archive` / `cli_archive_run` 捕获 `git add openspec/` 与 `_git_head` 的 `subprocess.CalledProcessError`（含 FileNotFoundError），转为 `emit_error` 结构化单行 JSON（`error=git-add-failed|git-head-failed`，附 stderr 摘要），exit 1。
- 保证 archive 的**所有**失败路径 stdout 都是单行 JSON：`ok=false` + `error` 字段可被主 session `jq` 稳定读取，供 3d 以 `--trigger archive-failed` 决策。
- 补测试：注入会失败的 git runner（index.lock / 非零退出），断言 stdout 是单行合法 JSON、`ok=false`、无裸 traceback。

## Capabilities

### New Capabilities

- `archive-error-contract`: archive 阶段失败输出的结构化契约——任何 git 子进程失败均以单行 JSON 报错，杜绝裸 traceback。

### Modified Capabilities

## Impact

- `src/npc/pipeline.py`（run_archive 的 git add / _git_head 异常捕获与 emit_error）
- `tests/`（git add 失败仍输出单行 JSON 的用例）
