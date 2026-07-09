## ADDED Requirements

### Requirement: npc doctor 体检共读上下文文档的结构性存在
`npc doctor` MUST 在 `gather_checks` 返回的体检项中新增一项 `name == "openspec/project.md"`，检查 `<repo_root>/openspec/project.md` 的结构性健康：文件不存在、或存在但内容 strip 空白后为空、或非空但不含任何匹配约定类段落标题（见下条 Requirement）——三者任一成立 MUST 得到 `status == "warn"`；三者均不成立（文件存在、非空、含约定类段落标题）MUST 得到 `status == "ok"`。该检查项 `required` MUST 恒为 `false`，即该项的 `status` MUST NOT 影响 `npc doctor` 整体 `ok` 字段或退出码（不新增阻断门）。检查过程中若发生 `OSError`（如权限问题），MUST 降级为 `status == "warn"` 并在 `detail` 中说明原因，MUST NOT 抛出未捕获异常。

本检查 MUST 仅做存在性 / 非空 / 段落标题存在性三层结构判断，MUST NOT 校验 `openspec/project.md` 的具体业务内容（内容是否准确、完整、符合项目品味均不在检查范围内）。

#### Scenario: 文件缺失报 warn 且不阻断
- **GIVEN** `<repo_root>/openspec/project.md` 不存在
- **WHEN** 执行 `npc doctor`
- **THEN** `checks` 数组中存在一项 `name == "openspec/project.md"` 且 `status == "warn"`、`required == false`
- **AND** `npc doctor` 的整体 `ok` 字段与退出码不受该项影响（`missing_required` 不含该项）

#### Scenario: 文件存在但为空报 warn
- **GIVEN** `<repo_root>/openspec/project.md` 存在，内容 strip 空白后为空字符串
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "warn"`

#### Scenario: 文件非空但无约定段落报 warn
- **GIVEN** `<repo_root>/openspec/project.md` 非空，但不含任何 1~2 级标题匹配约定类词表
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "warn"`

#### Scenario: 文件非空且含约定段落报 ok
- **GIVEN** `<repo_root>/openspec/project.md` 非空，且含一个 1~2 级标题 `## 项目级技术约定`
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "ok"`

#### Scenario: 该体检项不影响整体退出码
- **GIVEN** `<repo_root>/openspec/project.md` 缺失（该体检项为 `warn`）
- **AND** 其余所有 `required == true` 的体检项均为 `ok`
- **WHEN** 执行 `npc doctor`
- **THEN** 整体 `ok` 为 `true`，退出码为 `0`

#### Scenario: 检查过程异常时降级为 warn
- **GIVEN** 读取 `<repo_root>/openspec/project.md` 时抛出 `OSError`（如权限被拒绝）
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "warn"`
- **AND** `npc doctor` 进程 MUST NOT 因此抛出未捕获异常

#### Scenario: 不校验业务内容
- **GIVEN** `<repo_root>/openspec/project.md` 含一个匹配约定类词表的标题（如 `## 技术约定`），但该标题下的正文内容为空占位文本（如仅一句 `TBD`）
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "ok"`（本检查止步于「标题是否存在」，不判断标题下内容质量）

### Requirement: 约定类段落标题的判定词表与匹配范围
约定类段落标题的判定 MUST 满足：仅扫描 Markdown 1~2 级标题行（`#` 或 `##` 起始的整行），逐行匹配标题文本是否包含以下任一子串（大小写不敏感）：中文 `约定`，英文 `Convention` 或 `Conventions`。命中任一即视为「含约定类段落标题」。出现在标题行以外的正文段落、或出现在 3 级及以下标题中的同类词汇 MUST NOT 计入命中。

#### Scenario: 正文中的关键词不计入命中
- **GIVEN** `openspec/project.md` 正文含一句 `我们约定不做 XX`，但该文件不含任何标题行包含「约定」或 `Convention`
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "warn"`

#### Scenario: 三级标题中的关键词不计入命中
- **GIVEN** `openspec/project.md` 含一个 3 级标题 `### 约定`，但没有 1~2 级标题匹配该词表
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "warn"`

#### Scenario: 英文标题大小写不敏感匹配
- **GIVEN** `openspec/project.md` 含 2 级标题 `## Technical Conventions`
- **WHEN** 执行 `npc doctor`
- **THEN** 对应体检项 `status == "ok"`

### Requirement: npc init 透出共读上下文体检结果
`npc init` 的 JSON payload MUST 新增字段 `shared_context_warning`，其值 MUST 与同一次调用「npc doctor 体检共读上下文文档的结构性存在」Requirement 所定义的检查结果一致：当该检查 `status == "ok"` 时，`shared_context_warning` MUST 为 `null`；当该检查 `status == "warn"` 时，`shared_context_warning` MUST 为该检查的 `detail` 字符串（非空）。该字段的计算 MUST NOT 影响 `npc init` 的成功/失败判定或退出码——即该体检项本身仍是非阻断的观察性信号，`npc init` 在该字段为非 `null` 时仍 MUST 正常完成并返回 exit 0（除非有其它独立原因导致 init 失败）。

#### Scenario: 缺失共读文档时 init 输出非空 warning
- **GIVEN** worktree 的 `openspec/project.md` 不存在
- **WHEN** 执行 `npc init`
- **THEN** 输出的 JSON payload 含键 `shared_context_warning`，其值为非空字符串
- **AND** `npc init` 正常完成（不因该字段而失败）

#### Scenario: 共读文档健康时 init 输出 null
- **GIVEN** worktree 的 `openspec/project.md` 非空且含约定类段落标题
- **WHEN** 执行 `npc init`
- **THEN** 输出的 JSON payload 含键 `shared_context_warning`，其值为 `null`

#### Scenario: init 与 doctor 的判定结果一致（避免逻辑漂移）
- **GIVEN** 同一个 `repo_root`（`openspec/project.md` 处于任意状态）
- **WHEN** 分别执行 `npc doctor` 与 `npc init`
- **THEN** `npc doctor` 中对应体检项的 `status` 为 `warn` 当且仅当 `npc init` payload 的 `shared_context_warning` 非 `null`
- **AND** 二者由同一个检查函数计算，不存在两套独立实现

#### Scenario: 检查异常时 init 不崩溃
- **GIVEN** 读取 `openspec/project.md` 时抛出 `OSError`
- **WHEN** 执行 `npc init`
- **THEN** `npc init` MUST NOT 因此抛出未捕获异常，正常完成并返回 exit 0
- **AND** `shared_context_warning` 字段为该异常对应的提示文案（非 `null`）
