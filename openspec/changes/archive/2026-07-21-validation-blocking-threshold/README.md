# validation-blocking-threshold

validation 类 blocking 双向治理（对应 docs/optimization-proposals/2026-07-20.md 建议 2）：(a) coder 实现 prompt 模板加入固定的 validation 自查清单（边界值/None/类型/外部输入），在 round 0 前置消化 validation 类问题；(b) reviewer focus 模板要求 validation 类 blocking 必须附带"可触发的具体输入或调用路径"，否则降级为 advisory；(c) spec-silent 归因（spec 未覆盖）的 finding 默认降级为 advisory，让 spec 补条款而不是 fix 循环买单。涉及 src/npc/templates.py 与 src/npc/coder.py 的实现 prompt 渲染、src/npc/focus.py 的 review focus 渲染、以及 review 侧 severity 判定，需同步补 tests/。
