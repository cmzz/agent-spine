# scripts/

仓库本地脚本（不进 npc CLI，不属于 `docs/cli.md` 的契约面）。

## `check_spec.py` —— spec 静态语义 lint（本 change 新增）

```bash
uv run scripts/check_spec.py --change <id>     # openspec/changes/<id>/
uv run scripts/check_spec.py --dir <path>      # 任意含 design.md 的目录（fixture / archive）
```

stdout 输出单行合法 JSON（`ok` / `change` / `errors` / `warnings` / `rule_hits`）。
本脚本交付的四条规则 —— `deferred_decision_outside_open_questions`、
`scenario_missing_when_then`、`vague_adverb`、`proposal_missing_non_goals`
—— **一律为 `warning`**（shadow mode，不阻断，退出码不因命中而非零）。升级
判据见脚本模块 docstring。

**不要**把它跟下面两个名字相近的工具搞混——三者职责完全不同：

| 工具 | 层次 | 检查什么 | 是否确定性 | 是否进 npc |
|---|---|---|---|---|
| `uv run scripts/check_spec.py`（本脚本） | **实现前**，语义层 | 单个 change 的 `design.md`/`proposal.md`/spec delta 有没有写作品味问题（延迟决策藏在 Decisions 里、Scenario 无 WHEN/THEN、含糊副词、缺 Non-Goals） | 是，纯静态规则 | 否，仓库本地脚本 |
| `npc spec analyze` | **实现前**，结构层 | artifact 之间是否漂移（capability 有没有对应 spec.md、spec 有没有对应 tasks、tasks 是否为空） | 是，跨项目通用 | 是，`src/npc/spec_analyze.py` |
| `npc spec-report render` | **交付后**（archived 之后） | 已完结 change 的 agent 表现回执（review/fix 轮数、blocking 趋势、耗时、成本） | 是，纯派生 | 是 |

分界依据（详见 `openspec/changes/repo-spec-lint/design.md` D1）：`npc spec
analyze` 检查的是 artifact 间的结构一致性，对任何使用 openspec 的项目都
成立，零项目品味，因此进 npc；本脚本检查的内容——中文延迟措辞词表、含糊
副词表、"必须有 Non-Goals 段落"——是 agent-spine 自己的写作品味，外部没有
任何来源要求，因此按 `CLAUDE.md` 的 npc 边界（npc 只放跨项目通用的原子
操作），MUST 留在仓库脚本内。

`check_spec.py` 零依赖（仅用标准库 + `openspec` 二进制），可在未安装 `npc`
的环境中独立运行。与 npc 的接线（`npc spec review run` 通过
`[spec_review] gate_cmd` 调用本脚本并透传 `rule_hits` 进 telemetry）留到
`spine-spec-writer`，本 change 不改 `src/npc/` 任何文件。

## 回归 fixture

`tests/fixtures/spec_lint/` 下两份快照（非活体目录引用）：

- `negative_self_reference/`：`spec-schema-hardening` 归档语料，讨论
  `deferred_decision_outside_open_questions` 规则本身、延迟措辞全部位于反
  引号内，用于锁定「跳过 code span」不退化。
- `positive_long_tail/`：`parallel-dag-scheduling` 归档语料，`## Decisions`
  正文有 2 处裸露延迟措辞、`## Open Questions` 另有 2 处应被放行。

各自目录下的 `README.md` 记录了快照来源与快照时的 git commit。
