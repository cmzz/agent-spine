## 1. `doctor.py`：新增体检项（TDD：先测后写）

- [ ] 1.1 写测试（RED）：`_check_shared_context(repo_root=<无 openspec/project.md 的目录>)` → `status == "warn"`，`required is False`，`detail` 提及 `openspec/project.md`
- [ ] 1.2 写测试（RED）：`openspec/project.md` 存在但内容 strip 后为空（含仅空白/仅换行的情况）→ `status == "warn"`
- [ ] 1.3 写测试（RED）：`openspec/project.md` 非空但不含任何 1~2 级标题匹配 `约定`/`Convention`/`Conventions`（大小写不敏感）→ `status == "warn"`
- [ ] 1.4 写测试（RED）：`openspec/project.md` 含 `## 项目级技术约定` 标题 → `status == "ok"`
- [ ] 1.5 写测试（RED）：约定关键词出现在正文段落而非标题行（如 `我们约定不做 XX`）→ 不计入命中，`status == "warn"`（验证只匹配标题行，不匹配任意正文）
- [ ] 1.6 写测试（RED）：约定关键词出现在 3 级标题（`### 约定`）→ 不计入命中，`status == "warn"`（验证只扫 1~2 级标题）
- [ ] 1.7 写测试（RED）：英文标题 `## Technical Conventions` → `status == "ok"`（验证英文子串大小写不敏感匹配）
- [ ] 1.8 写测试（RED）：`repo_root` 为 `None` 或文件读取抛 `OSError`（如用 monkeypatch 模拟权限错误）→ `status == "warn"`，不抛未捕获异常
- [ ] 1.9 实现 `_check_shared_context(*, repo_root: Path | None) -> dict`，返回四键字典（`name`/`status`/`detail`/`required`），`required` 恒为 `False`
- [ ] 1.10 跑 1.1–1.8 确认 GREEN

## 2. `doctor.py`：接入 `gather_checks`

- [ ] 2.1 写测试（RED）：`gather_checks(...)` 返回值中存在 `name == "openspec/project.md"` 的一项
- [ ] 2.2 在 `gather_checks` 中新增一行调用 `_check_shared_context(repo_root=repo_root)`（复用已有的 `cfg_root`/`repo_root` 变量，与 `_check_principles` 调用点相邻）
- [ ] 2.3 写**负向**测试（RED）：该检查项缺失/为空/无约定段落时，`build_report(...)["ok"]` 仍为 `True`、退出码逻辑不受影响（`missing_required` 不含该项）——验证 `required=False` 真正生效、不新增阻断门
- [ ] 2.4 跑 2.1–2.3 确认 GREEN

## 3. `init_cmd.py`：透出 `shared_context_warning` 字段

- [ ] 3.1 写测试（RED）：`repo_root` 下无 `openspec/project.md` 时执行 `init_cmd.run(...)`（或直接测计算该字段的辅助函数）→ payload 含 `shared_context_warning`，值为非空字符串
- [ ] 3.2 写测试（RED）：`repo_root` 下 `openspec/project.md` 存在且含约定段落 → payload 的 `shared_context_warning == None`
- [ ] 3.3 写测试（RED）：`shared_context_warning` 为 `None` 时的取值与 `doctor._check_shared_context(...)["status"] == "ok"` 一致；为非空字符串时其值等于该检查的 `detail`（验证两处调用点结果一致、无逻辑漂移）
- [ ] 3.4 在 `init_cmd.py` 中 `from . import doctor as _doctor`，在 payload 组装前插入 `_check_shared_context` 调用并按 D2 规则映射为 `shared_context_warning`
- [ ] 3.5 写测试（RED）：检查过程抛 `OSError`（monkeypatch 模拟）不导致 `init_cmd.run(...)` 抛未捕获异常，`shared_context_warning` 降级为该异常的提示文案（warn，不阻断 init）
- [ ] 3.6 跑 3.1–3.5 确认 GREEN

## 4. 回归与边界

- [ ] 4.1 跑现有 `tests/test_doctor.py` 全量，确认无既有用例因新增 check 而回归（如对 `checks` 数组长度做硬编码断言的用例需要同步更新期望值）
- [ ] 4.2 跑现有 `tests/test_init_cmd.py` 全量，同上
- [ ] 4.3 写**负向**测试（RED）：`_check_shared_context` 不解析/不校验 `openspec/project.md` 的具体业务内容——构造一个含约定标题但正文明显"内容很差"（如空约定、占位文本）的文件，断言仍为 `status == "ok"`（验证本检查确实止步于结构层，不逾越 CLAUDE.md 的 npc 边界）
- [ ] 4.4 跑全量 `uv run pytest -q`

## 5. 文档

- [ ] 5.1 若 `docs/cli.md` 记录了 `npc doctor` 的体检清单或 `npc init` 的完整 payload 键集合，同步补充本次新增项；若未逐项枚举则跳过（不引入原本不存在的枚举义务）
- [ ] 5.2 **一次性人工验证**（不进永久测试）：在本仓库当前状态下跑一次 `uv run python -c "from npc import doctor; ..."` 或 `npc doctor`，确认新体检项对本仓库当前 `openspec/project.md`（若存在）给出预期状态，供本 change 作者自查
