## Why

`npc doctor` 现有体检清单里有一项 `principles.md`（`docs/principles.md` 存在性，warn 级），检验的是"工程原则文档在不在"。但 harness 真正依赖的另一个前提——"所有 worker（coder / spec-writer / reviewer 等 sub-agent）共读同一份项目级技术约定文档 `openspec/project.md`"——目前完全不受体检覆盖：该文档缺失或为空，不会在 `npc doctor` 或 `npc init` 的任何输出里留下痕迹，只会在后续某个 worker 因为"不知道项目约定"而产出不一致结果时才间接暴露，此时已经付出了一整轮 run 的成本。

依据 `docs/optimization-proposals/2026-07-09-bun-migration-lessons.md`「文档先行」小点 4：Bun 迁移过程中，多个 worker 因缺少一份共读的 `PORTING.md` 而各自摸索、结论互相矛盾，直到事后补一份共读文档才收敛。该教训的推广形式是——**共读文档是否存在，应当在每个 run 开始时被显式检验一次**，而不是隐式假设它在。

本仓库已有的两个真实先例可直接复用同一模式：

- `doctor._check_principles`：`docs/principles.md` 缺失 → `status: "warn"`，`required: false`，不阻断。
- `init_cmd.run` 的 step 10：`~/.claude/projects/<proj_key>` 目录不存在时 `_io.warn(...)`，同样不阻断，只是提醒。

本 change 把这两个先例组合成一个新体检项：`npc doctor` 新增 `project.md` 检查（存在性 + 非空 + 含至少一个"约定"类段落标题），warn 级、不阻断；`npc init` 的 JSON 输出新增一个字段，把该检查结果透出，使这个前提在**每个 run 开始时**（而不仅是手动跑 `npc doctor` 时）被显式检验并可被自动化消费（如 `/spine-run` 的 orchestrator 决定是否要先提示用户补文档）。

**硬约束（守 npc 边界，CLAUDE.md）**：本 change 仅做**存在性 / 非空 / 段落标题存在性**三层结构检查，MUST NOT 校验 `openspec/project.md` 的具体业务内容（不检查约定写得对不对、全不全、是否符合某种项目品味）。这类业务校验属于各项目仓库自己的 `scripts/check-*` 家族，不属于 npc 的四项白名单（生命周期钩子 / telemetry / state 读写 / 路由不变量）。

## What Changes

- **新增** `src/npc/doctor.py` 体检项 `_check_shared_context`（复用 `_check_principles` 的实现模式）：检查 `<repo_root>/openspec/project.md`。
  - 文件不存在 → `status: "warn"`，`detail` 含建议动作（如何补）。
  - 文件存在但内容 strip 后为空 → `status: "warn"`。
  - 文件存在且非空，但**不含**任何匹配"约定类段落标题"的 `#`/`##` 级 Markdown 标题（词表：中文含"约定"子串，或英文含 `Convention`/`Conventions` 子串，大小写不敏感）→ `status: "warn"`。
  - 三者都满足 → `status: "ok"`。
  - 全程 `required: false`：**不影响** `npc doctor` 的退出码与 `missing_required` 判定。这是一个纯观察性 warn 项，不是新硬门（守不变量 3：新硬轨须被真实方差打出来，本 change 无方差证据，不立门）。
- **新增** `gather_checks` 调用该检查项（沿用现有 `_check_principles(repo_root=repo_root)` 调用点旁新增一行，`repo_root` 已经是入参）。
- **新增** `npc init` 的 JSON payload 字段 `shared_context_warning`：`null`（检查为 `ok`）或该检查项的 `detail` 字符串（检查为 `warn`）。计算逻辑复用 `doctor._check_shared_context`（同一函数，两处调用，避免逻辑漂移）。**不新增 stderr `_io.warn` 输出**（现有 init 已有的 `_io.warn` 用法是给人看的一次性提示；本字段是给下游自动化消费的结构化信号，二者语义不同，不合并）。
- **新增** 单元测试覆盖三个 warn 分支 + 一个 ok 分支，覆盖 `doctor.py` 与 `init_cmd.py` 两处调用点。

**非目标（Non-Goals）**：

- **不校验 `openspec/project.md` 的业务内容**（约定写得对不对、完不完整、格式是否规范）——仅做结构性存在检查，守 CLAUDE.md 的 npc 边界。
- **不新增任何阻断门**：本检查项 `required` 恒为 `false`，不影响 `npc doctor` / `npc init` 的退出码。
- **不自动生成或修复 `openspec/project.md`**：发现缺失/为空/无约定段落时只报 warn，不做任何写入动作。
- **不改变 `_BIN_CHECKS` 清单或已有体检项的行为**——纯新增一项，旁路现有逻辑。
- **不接入 `/spine-run` 的任何闸口**（是否基于该字段做进一步决策，留给后续 change；本 change 只负责把信号透出）。
- **不定义"约定类段落标题"词表之外的匹配规则**（不做语义理解、不做 NLP，纯子串匹配标题文本）。

## Capabilities

- **New Capabilities**: `doctor-shared-context-check` —— `npc doctor` 新增「共读上下文文档」体检项，并在 `npc init` 输出中透出同一检查结果，使"所有 worker 共读一份项目级技术约定文档"这一前提在每个 run 开始时被显式、非阻断地检验。

## Impact

- **受影响代码**：`src/npc/doctor.py`（新增 `_check_shared_context` 并接入 `gather_checks`）、`src/npc/init_cmd.py`（新增 `shared_context_warning` payload 字段）、`tests/test_doctor.py`、`tests/test_init_cmd.py`。
- **兼容性**：`npc doctor` 的 `checks` 数组新增一个元素（`name: "openspec/project.md"`），`summary.warn` 计数可能相应变化；`required_missing`/退出码语义不变。`npc init` 的 JSON payload 新增一个键 `shared_context_warning`，为**纯新增字段**，不改变任何既有键的语义，向后兼容。
- **不变量影响**：
  - 不变量 1（生成⊥验证）：本检查是**确定性文件系统探测**（存在性/非空/字符串匹配），不涉及 LLM 生成或评审，不产生 rubric。**不适用**。
  - 不变量 2（不信 LLM 散文）：输出为结构化字段（`status`/`detail`/`required` 或 `shared_context_warning: str|null`），不解析 LLM 自由文本。**满足**。
  - 不变量 3（新硬轨须被真实方差打出来）：本 change **不立任何硬门**——检查项 `required` 恒 `false`，只产出观察性 warn 信号，不影响退出码。**满足**。
