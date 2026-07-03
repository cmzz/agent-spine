## 1. 接线

- [x] 1.1 `run_review_round` 入口加载 config 并调用 `verify.check_routing`
- [x] 1.2 violations 非空 → `emit_error("routing-violation", 含 violation 列表, exit_code=1)`，不执行 review
- [x] 1.3 校验失败信息含 rule 名与违规字段值，单行 JSON

## 2. 测试

- [x] 2.1 接线测试：配置 review 引擎含 mimo → `npc review run` 拒绝执行并返回 routing-violation
- [x] 2.2 接线测试：review 与 coder 同源（同 backend/bin）→ 拒绝执行
- [x] 2.3 接线测试：合法配置（coder=claude/mimo，review=codex）→ review 正常进入原逻辑
- [x] 2.4 `pytest` 全绿

## 3. 文档对齐

- [x] 3.1 核对 principles.md:47 与实现一致（「代码层强制」自此为真）；如描述需细化（强制点=review 入口）则更新
