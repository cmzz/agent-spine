# clean-worktree Specification

## Purpose
TBD - created by archiving change clean-worktree-aware. Update Purpose after archive.
## Requirements
### Requirement: npc clean 清理孤儿 spine worktree

`npc clean` MUST 在清理陈旧 task_log run 的同时，移除悬空的 `spine/*` worktree 及其分支；但 MUST NOT 移除仍有 in-progress state **且该 state 的 owner 仍存活**的 worktree（owner 存活判定见 `worktree-owner-liveness` capability）。owner 已死的 in-progress worktree 不再被无条件保护，MUST 落入与普通 orphan 相同的 age-gate（`keep_days` 保留窗口）二次判定：只有对应 task_log run 已过保留窗口才可被回收，未过保留窗口的 MUST 继续保守跳过（不清理），避免刚崩溃不久、仍可能被后续 `npc init` 续跑接管的 run 被过早物理删除。

#### Scenario: 孤儿 worktree 被清

- **WHEN** 存在一个 `spine/*` worktree，其 task_log 无 in-progress state（已陈旧）
- **AND** 执行 `npc clean`
- **THEN** 该 worktree 被 `git worktree remove`，对应分支被删

#### Scenario: owner 存活的 in-progress worktree 保留

- **WHEN** 某 `spine/*` worktree 的 task_log 有 in-progress state，且该 state 的 owner 仍存活
- **THEN** `npc clean` 不移除它，也不删其分支

#### Scenario: owner 已死但仍在保留窗口内的 in-progress worktree 暂不回收

- **WHEN** 某 `spine/*` worktree 的 task_log 有 in-progress state，该 state 的 owner 已死，但对应 task_log run 未超过 `keep_days` 保留窗口
- **THEN** `npc clean` 暂不移除该 worktree（保守跳过，留给后续 `npc init` 可能的续跑接管）

#### Scenario: owner 已死且超出保留窗口的 in-progress worktree 被回收

- **WHEN** 某 `spine/*` worktree 的 task_log 有 in-progress state，该 state 的 owner 已死，且对应 task_log run 已超过 `keep_days` 保留窗口
- **THEN** `npc clean` 将该 worktree 列为可回收，执行 `git worktree remove` 并删除对应分支

