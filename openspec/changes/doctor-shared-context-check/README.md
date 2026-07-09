# doctor-shared-context-check

npc doctor 增加「共读上下文文档」体检项：检查 openspec/project.md 存在且非空、且含项目级技术约定段落；缺失或为空时以 warning 报出（不阻断 run），并在 npc init 的输出中透出该 warning 字段，保证「所有 worker 有一份共读的约定文档」这个前提在每个 run 开始时被显式检验（Bun 的 PORTING.md 共读前提）。硬约束：仅做存在性/非空/段落存在性检查，MUST NOT 校验业务内容（守 npc 边界：不放具体项目的业务校验）。依据 docs/optimization-proposals/2026-07-09-bun-migration-lessons.md「文档先行」小点 4。
