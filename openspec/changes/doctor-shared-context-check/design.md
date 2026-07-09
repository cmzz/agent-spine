## Context

`npc doctor` 已有 `_check_principles`（`docs/principles.md` 存在性，warn 级）与 `_check_schema`/`_check_mimo_env`（同样 warn 级、`required: false`）三个不阻断的体检项，`gather_checks` 把它们组装成一个统一 list，`build_report` 只用 `required` 缺失来决定 `ok`/退出码。`npc init` 已经有一处非结构化的一次性提醒（`~/.claude/projects/<proj_key>` 缺失时 `_io.warn(...)`），但那条提醒不进入 JSON payload，下游自动化（如 `/spine-run` 的 orchestrator）读不到。

本 change 要解决的具体问题：`openspec/project.md`（项目级技术约定，所有 worker 共读的前提文档）目前既不在 `npc doctor` 的体检清单里，也不在 `npc init` 的输出里，缺失/为空这个事实完全不可观察，直到某个 worker 因缺约定而跑偏才间接暴露。

## Goals / Non-Goals

**Goals**：
- 在 `npc doctor` 增加一个 warn 级、`required: false` 的体检项，检验 `openspec/project.md` 的**结构性**健康（存在 / 非空 / 含约定类段落标题）。
- 在 `npc init` 的 JSON 输出里透出同一检查结果，使这个前提在**每个 run 开始时**（而不只是手动跑 `npc doctor` 时）被显式检验。
- 两处调用同一个纯函数，避免逻辑双份维护造成漂移。

**Non-Goals**：
- 不校验 `openspec/project.md` 的业务内容质量。
- 不新增任何阻断门或退出码变化。
- 不自动生成/修复该文件。
- 不接入 `/spine-run` 等更上层的决策流程（本 change 只负责把信号透出，"透出后怎么用"留给未来 change）。

## Decisions

**D1：检查函数落在 `doctor.py`，`init_cmd.py` 直接 import 调用，不复制逻辑。**
`doctor.py` 里已有 5 个 `_check_*` 纯函数，模式高度一致（接收路径/repo_root，返回 `{"name","status","detail","required"}` 字典，不做 I/O 副作用之外的输出）。新函数 `_check_shared_context(*, repo_root: Path) -> dict` 直接加入这个家族，`init_cmd.py` 从 `doctor` 模块 import 并调用同一个函数，两处调用结果保证语义一致。备选方案是在 `init_cmd.py` 里独立实现一份精简版检查逻辑——放弃，因为两份实现迟早会因为独立演进而在边界条件（如 BOM、纯空白文件）上产生行为分歧，这正是"共读文档"这个主题本身想避免的那类漂移。

**D2：`npc init` 的字段是 `shared_context_warning: str | None`，不是完整 check 字典。**
`npc doctor` 的 `checks` 数组元素是 `{"name","status","detail","required"}` 四键字典，服务于"体检报告"这个场景，字段丰富是因为要展示一整份清单。但 `npc init` 的 payload 是"这次 run 的启动状态"，其它类似的一次性提醒（如 `state_drift`）在 `ok` 情况下就是 `null`，出问题时才是非空值。`shared_context_warning` 遵循同一约定：`status == "ok"` 时该字段为 `null`；`status == "warn"` 时该字段为该检查的 `detail` 字符串。备选方案是照搬 `{"status","detail"}` 的完整字典——放弃，因为 payload 里绝大多数信号字段都是"扁平值，语义在字段名里"的风格（如 `needs_resume: bool`、`fresh: bool`），插入一个结构不同的嵌套字典会破坏 payload 的一致读法；且下游只关心"有没有 warning、warning 文案是什么"，不需要 `name`/`required` 这两个在单次 init 场景下恒定的字段。

**D3：不阻断，`required` 恒为 `false`——无方差证据不立门（不变量 3）。**
本 change 是"让一个已知隐患变得可观察"，不是"证明了这个隐患导致过具体的、可复现的失败方差"。类比 `repo-spec-lint` change 的纪律：四条规则里唯一有方差证据的规则也只升到 `warning`，因为 N=1、机理未充分证明。本 change 的证据链更薄（一份迁移经验教训文档的转述，无本仓库内的 telemetry 方差数据），所以起点必须更保守——`required: false`，纯观察信号。若未来 telemetry（`npc telemetry` / `spec_attribution`）显示该 warning 与具体的 spec-silent/跑偏类问题存在跨 run 的稳定关联，才有资格考虑升级为阻断项，但那是另一个 change 的事。

**D4："约定类段落标题"判定：子串匹配 Markdown 标题行，不解析语义。**
判定"含项目级技术约定段落"具体怎么落地是本设计的核心含糊点。选择：扫描文件全部 `#`/`##`（1~2 级）标题行（`^#{1,2}\s+.+$`），若任一标题文本包含中文子串 `约定` 或英文子串 `Convention`/`Conventions`（大小写不敏感）即命中。命中即视为"含约定段落"，否则视为不含（连同"非空但无该标题"一起报 warn）。

理由：
- 只匹配标题行而非全文任意位置——避免正文提及"我们约定不做 XX"这类自然语言噪音被误判为"有专门段落"。
- 只用两个子串、不做同义词扩展（不认"规范"/"规则"/"guideline"等）——刻意收窄，宁可放过一些用词不同但实质等价的项目（漏报），也不做语义理解式的宽松匹配（避免把结构检查做成内容质量判断，逾越"仅做段落存在性检查"的硬约束边界）。
- 1~2 级标题（不含 3 级及以下）——`openspec/project.md` 作为顶层共读文档，约定类内容预期是一等段落而非某个子段落下的细节，收窄扫描范围也降低误报面。

备选方案"要求标题精确等于某个固定字符串（如仅认 `## 技术约定`）"被放弃：过于死板，任何标题措辞变体（"项目约定"/"技术约定"/"开发约定"）都会被误判为缺失，而子串匹配已经足够覆盖这些变体，且仍然是纯结构匹配、不涉及业务内容判断。

**D5：`init_cmd.py` 的计算时机与失败降级。**
`shared_context_warning` 的计算插入在现有 payload 组装之前（紧邻 step 10 的 `~/.claude/projects` sanity check 附近，同属"非阻断前置探测"这一组步骤）。计算过程只做文件系统读取，不涉及网络或子进程；若读取过程抛出 `OSError`（如权限问题），按 `_check_config` 的降级模式处理——捕获异常，返回 `status: "warn"`、`detail` 含异常信息，绝不让 init 因这个体检项而崩溃。

## Risks / Trade-offs

- **子串匹配可能有假阴性**（用词不在词表内的项目会被误判缺失约定段落）。可接受：本检查是 warn 级，误报成本是"多看一眼、发现其实有"，不是阻断性成本；且这正是不做语义理解判断所必须付出的代价，是刻意的收窄而非疏漏。
- **两处调用点耦合**：`init_cmd.py` 依赖 `doctor.py` 的内部函数。可接受：`doctor.py` 已经是 `npc` 包内模块，同包内 import 私有函数（`_check_shared_context`）是现有代码库的既有模式（`init_cmd.py` 已经 import `schema`/`resume`/`git_chain` 等同包模块）；若未来该函数需要被更多调用点复用，可在函数名去掉下划线前缀正式对外暴露，但这不是本 change 的范围。

## Migration Plan

纯新增，无需迁移。`npc doctor` 现有调用方（若解析 `checks` 数组）会看到多一个元素，属于向后兼容的数组扩展；`npc init` 现有调用方（若严格模式解析 payload 键集合）会看到多一个键 `shared_context_warning`，同样是向后兼容的新增。

## Open Questions

- 该 warning 未来是否要接入 `/spine-run` 的某个决策点（例如 auto 模式下自动提示用户先补 `openspec/project.md`）——留给后续 change，视本 change 上线后的实际观察数据（该 warn 触发频率、是否确实和跑偏类 blocking 相关）决定是否值得投入。
