## ADDED Requirements

### Requirement: 多落点清单需要可复核的确定性枚举命令
脚本 MUST 实现规则 `touchpoint_list_missing_search_command`：扫描 `openspec/changes/<id>/tasks.md`，逐个 `##`/`###` 段落检查其列表项（以 `- ` 开头的行，含任务清单形式 `- [ ]`）。若某段落内，引用不同文件路径的列表项（该行含至少一个反引号包裹、且包含 `/` 或以常见代码文件后缀结尾的 token）数量达到 3 条或以上，视为该段落声明了一个多落点清单。此时该段落正文内 MUST 存在至少一个围栏代码块，且块内文本命中 `grep`、`rg`、`git grep`、`git diff --name-only` 中任一子串；不满足时 MUST 产出一条 `touchpoint_list_missing_search_command` finding，`detail` MUST 含该段落标题，`line` MUST 为该段落标题行的 1-based 行号。`tasks.md` 不存在时该规则 MUST 静默跳过。

判定 MUST 复用既有的 `section_of_line`/`strip_code_spans` 段落定界与代码块剥离逻辑，MUST NOT 重新实现一套不一致的解析。

#### Scenario: 多落点段落缺搜索命令依据
- **GIVEN** `tasks.md` 某段落含 3 条列表项，各引用一个不同的、反引号包裹的文件路径，且该段落内无任何围栏代码块
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.warnings` 中存在 `rule == "touchpoint_list_missing_search_command"`
- **AND** 该项 `detail` 含该段落标题
- **AND** `.ok == true` 且退出码为 `0`（shadow mode，不阻断）

#### Scenario: 段内含搜索命令则不命中
- **GIVEN** 与上一场景相同的段落，另在其中新增一个围栏代码块，内含一行 `grep -rn "foo" src/`
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.rule_hits["touchpoint_list_missing_search_command"]` 等于 `0`

#### Scenario: 未达阈值不视为多落点清单
- **GIVEN** `tasks.md` 某段落只含 2 条引用不同文件路径的列表项，且无围栏代码块
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.rule_hits["touchpoint_list_missing_search_command"]` 等于 `0`

#### Scenario: tasks.md 缺失时跳过而非报错
- **GIVEN** 一个 change 目录不含 `tasks.md`
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.warnings` 中不含 `rule == "touchpoint_list_missing_search_command"`
- **AND** 进程退出码为 `0`

## MODIFIED Requirements

### Requirement: 仓库本地脚本与结构化输出
仓库 MUST 提供 `scripts/check_spec.py`，以 `uv run scripts/check_spec.py --change <id>` 调用。其 stdout MUST 为单行合法 JSON，含键 `ok`、`change`、`errors`、`warnings`、`rule_hits`。`errors` 与 `warnings` MUST 为数组，每项含 `rule`、`file`、`line`、`detail`。`rule_hits` MUST 为映射，键集合恒等于本脚本实现的全部规则名集合（含零命中项），值为该规则本次命中次数。当且仅当 `errors` 为空时 `ok` 为 `true`。退出码 MUST 为：存在 `errors` → `1`；仅有 `warnings` 或全部干净 → `0`。

#### Scenario: 干净的 change 输出 ok 且退出 0
- **GIVEN** 一个不触发任何规则的 change
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** stdout 为合法 JSON 且 `.ok == true`
- **AND** `.errors` 为空数组
- **AND** 进程退出码为 `0`

#### Scenario: 仅有 warning 时退出 0
- **GIVEN** 一个 change，其某个 Scenario 正文缺 WHEN/THEN
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.ok == true`
- **AND** `.warnings` 长度至少为 `1`
- **AND** 进程退出码为 `0`

#### Scenario: errors 通道保留但本版本无 error 级规则
- **GIVEN** 一个 change 触发了本脚本实现的全部规则
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.errors` 为空数组（本版本交付的五条规则 severity 均为 `warning`）
- **AND** `.ok == true` 且进程退出码为 `0`

#### Scenario: errors 非空时的退出码语义（供未来升级）
- **GIVEN** 脚本内部产生了一条 severity 为 `error` 的 finding
- **WHEN** 该 finding 被写入 `.errors`
- **THEN** `.ok == false`
- **AND** 进程退出码为 `1`

#### Scenario: rule_hits 含全部规则名（含零命中）
- **GIVEN** 一个不触发任何规则的 change
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.rule_hits` 的键集合等于本脚本实现的全部规则名集合（五项）
- **AND** 其全部值为 `0`

#### Scenario: 不存在的 change 报结构化错误
- **GIVEN** `--change` 指向 `openspec/changes/` 下不存在的目录
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** stdout 为合法 JSON 且 `.ok == false`
- **AND** 输出含稳定错误标识 `change_not_found`
- **AND** 进程退出码为非零

#### Scenario: --change 只接受单段 id，不接受路径分隔符
- **GIVEN** `--change` 取值为 `archive/2026-07-03-parallel-dag-scheduling`（含 `/`）
- **WHEN** 执行脚本
- **THEN** `.ok == false`
- **AND** 输出含稳定错误标识 `invalid_change_id`
- **AND** 进程退出码为非零

#### Scenario: --change 拒绝路径穿越
- **GIVEN** `--change` 取值为 `../../etc`
- **WHEN** 执行脚本
- **THEN** `.ok == false`
- **AND** 输出含稳定错误标识 `invalid_change_id`

#### Scenario: --dir 用于直接检查一个 change 目录（供 fixture 与 archive 使用）
- **GIVEN** `--dir` 指向任意一个含 `design.md` 的目录
- **WHEN** 执行 `uv run scripts/check_spec.py --dir <path>`
- **THEN** stdout 为合法 JSON
- **AND** 该模式下 spec delta 相关规则（`scenario_missing_when_then`、`vague_adverb`）MUST 被跳过并在 `rule_hits` 中记为 `0`（`openspec show` 只认 active change id）
- **AND** `touchpoint_list_missing_search_command`（只读 `tasks.md`，不依赖 `openspec show`）MUST NOT 被跳过

### Requirement: 全部规则以 warning 交付（shadow mode）
本脚本交付的五条规则（`deferred_decision_outside_open_questions`、`scenario_missing_when_then`、`vague_adverb`、`proposal_missing_non_goals`、`touchpoint_list_missing_search_command`）的 severity MUST 均为 `warning`。任一规则命中 MUST NOT 使 `.ok` 变为 `false`，MUST NOT 使退出码非零。

理由：前四条规则的方差证据在其交付时已记录（正类 N=1，见既有 docstring）。`touchpoint_list_missing_search_command` 是本次新增的**零样本**规则，按不变量 3「新硬轨须被真实方差打出来」，同样只能以 `warning` 交付。

升级判据（MUST 写入脚本的模块级 docstring）：当 `spec_review.round` 或 code review 的 `spec_attribution` 聚合数据显示某规则的命中与 `spec-silent`/`spec-ambiguous`/`spec-contradicted` 类 blocking 存在跨 change 的稳定关联（正类样本 ≥ 3 个独立 change）时，方可将该规则升为 `error`。此判据对五条规则一体适用，不因新增规则而降低门槛。

#### Scenario: 延迟措辞命中时只警告不阻断
- **GIVEN** `design.md` 的 `## Decisions` 段落含一行 `per-change worktree 的 run 绑定用 CLI 参数还是 pointer 文件，实施时定`
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.warnings` 中存在 `rule == "deferred_decision_outside_open_questions"`
- **AND** `.errors` 为空数组
- **AND** `.ok == true` 且进程退出码为 `0`

#### Scenario: 脚本 docstring 载明升级判据
- **WHEN** 读取 `scripts/check_spec.py` 的模块级 docstring
- **THEN** 其文本含子串 `正类样本 ≥ 3 个独立 change`

#### Scenario: 五条规则同时命中仍不阻断
- **GIVEN** 一个 change 同时触发本脚本实现的全部五条规则
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** `.ok == true`
- **AND** 退出码为 `0`

#### Scenario: 新规则同样受 warning 门槛约束
- **GIVEN** `tasks.md` 触发 `touchpoint_list_missing_search_command`
- **WHEN** 执行 `uv run scripts/check_spec.py --change <id>`
- **THEN** 该 finding 出现在 `.warnings` 而非 `.errors`
- **AND** `.ok == true` 且退出码为 `0`
