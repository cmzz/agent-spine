# Fixture: positive_long_tail

**快照来源**：`openspec/changes/archive/2026-07-03-parallel-dag-scheduling/design.md`

**快照时 git commit**：`5b7ffef72f7a90545e8a5a2e7cba3fb2c82c8240`

**用途**：`deferred_decision_outside_open_questions` 规则的正例回归 fixture——
本仓库对 6 个带 `design.md` 的已归档 change 做检测时唯一命中的长尾样本
（`total_rounds=6`，全仓最高）。

`## Decisions` 段正文含 2 处裸露的 `实施时定`（design.md:43、design.md:82），
`## Open Questions` 段另有 2 处 `实施时定`（design.md:103、design.md:104）
应被正确放行。预期 `rule_hits["deferred_decision_outside_open_questions"] == 2`
且 `.ok == true`（本规则为 warning，不阻断）。

**这是一份静态快照，不引用活体目录**：`openspec/changes/archive/...` 目录
会随仓库演进。若未来需要更新此 fixture，必须显式重新执行复制动作并更新上方
commit hash，**不要**依赖 archive 目录自动同步。
