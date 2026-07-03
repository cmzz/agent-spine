## 1. 代码侧：archive-failed 分支

- [x] 1.1 `auto_decide.py`：`VALID_TRIGGERS` 增 `archive-failed`
- [x] 1.2 `_decide` 增 archive-failed 分支：首次 `continue-retry`（计 `auto_retry_archive-failed`）、再失败 `skip`（status=skipped-auto）
- [x] 1.3 单测：archive-failed 首次 retry / 二次 skip / apply mutation 正确

## 2. skill 侧：词表修正

- [x] 2.1 spine-run.md:184 示范词表改为真实词表，按场景标注映射（implement→implementer-failed、fix→fixer-failed、review 卡死→stale|max-rounds、archive→archive-failed）
- [x] 2.2 全文扫一遍 spine-run.md，确认无其他过期 trigger 字样

## 3. 守卫测试

- [x] 3.1 新增测试：正则解析 spine-run.md 中所有 `--trigger` 候选值（含 `<a|b|c>` 枚举形态），断言每个值 ∈ `auto_decide.VALID_TRIGGERS`
- [x] 3.2 `pytest` 全绿
