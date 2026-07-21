# review-delta-convergence

review 轮次收敛改造（对应 docs/optimization-proposals/2026-07-20.md 建议 1）：r≥2 的 review focus 模板切换为 delta-review 模式——(a) 逐条核验上轮 blocking finding 的修复状态；(b) 仅本轮 fix diff 新引入的问题可判 blocking；(c) 存量代码中新发现的问题一律降级为 advisory（随 archive 记录、不阻塞）。并加入硬收敛规则：连续两轮无"上轮遗留未修复"的 blocking 即 approve（advisory 照常携带）。涉及 src/npc/focus.py 的 round focus 渲染与 pipeline 的 verdict 判定，需同步补 tests/。
