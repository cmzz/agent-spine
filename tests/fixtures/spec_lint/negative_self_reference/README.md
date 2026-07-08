# Fixture: negative_self_reference

**快照来源**：`openspec/changes/archive/2026-07-08-spec-schema-hardening/`
（`proposal.md` / `design.md` / `tasks.md`，三个 artifact 原样复制）。

**快照时 git commit**：`8eb6a4fc701d9235c3b7586483c85222b514eb74`

**用途**：`deferred_decision_outside_open_questions` 规则的负例回归 fixture。
这三个文件都在**讨论该规则本身**，因此出现 `TBD` 等延迟措辞字面量，但均位于
反引号代码 span 或引号列表内——朴素子串匹配会误报，本 fixture 用于锁定
"跳过 code span" 这一行为不退化。

**这是一份静态快照，不引用活体目录**：`openspec/changes/archive/...` 目录
本身会随仓库演进（且已被 archive，理论上还可能被后续工具改写/归档流程接触），
把测试真值绑定在这样一个活体路径上会让测试脆弱。若未来需要更新此 fixture，
必须显式重新执行本 README 记录的复制动作，并更新上方 commit hash，
**不要**依赖 `openspec/changes/archive/` 目录自动同步。
