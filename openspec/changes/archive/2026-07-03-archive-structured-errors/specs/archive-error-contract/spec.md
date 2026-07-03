## ADDED Requirements

### Requirement: archive 所有失败路径输出单行结构化 JSON

`npc archive run` 的任何失败（含 `git add`、`_git_head`、commit 等子进程失败）MUST 捕获并转为 stdout 单行 JSON（`ok=false` + `error` 分类 + 摘要），exit code 1；MUST NOT 向 stdout 泄漏裸 traceback 或空输出。

#### Scenario: git add 因 index.lock 失败仍返回单行 JSON

- **WHEN** archive 阶段 `git add openspec/` 因 index.lock（或权限、hook）非零退出
- **THEN** stdout 是单行合法 JSON：`ok=false`、`error="git-add-failed"`、含 stderr 摘要，进程 exit 1
- **AND** 主 session `jq -r '.ok'` 读到 `false`（非空串），可转 3d 决策点

#### Scenario: _git_head 失败结构化报错

- **WHEN** `_git_head` 的 `git rev-parse` 非零退出
- **THEN** stdout 单行 JSON `ok=false`、`error="git-head-failed"`，无裸 traceback

#### Scenario: 正常路径不受影响

- **WHEN** archive 各 git 步骤全部成功
- **THEN** 返回原契约字段（`ok=true`、`archive_commit` 等），行为不变
