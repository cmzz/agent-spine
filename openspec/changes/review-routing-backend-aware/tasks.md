## 1. Resolver 纯函数

- [x] 1.1 在 `src/npc/verify.py` 新增 `resolve_review_engine` 纯函数（优先级：override > codex/kimi→claude > claude 同源→codex > 配置引擎；同源判定复用 check_routing 口径，identity 缺省保守按同源）
- [x] 1.2 在 `tests/test_verify.py` 补 resolver 单测：override 优先、codex/kimi→claude、claude 同源→codex、claude 不同源→配置引擎、mimo→配置引擎、identity 缺省保守分支

## 2. Pipeline 接入

- [x] 2.1 `src/npc/pipeline.py` `run_review_round`：内联 backend-aware 分支替换为 resolver 调用，未知引擎校验与 check_routing 顺序不变
- [x] 2.2 `src/npc/spec_pipeline.py` `_effective_spec_routing`：内部委托同一 resolver，签名与返回形态不变
- [x] 2.3 `tests/test_pipeline.py` 补 claude 生成源 + 配置同源时默认选 codex 的端到端测试；既有 codex/kimi 默认 claude、显式 override 被拒等测试保持绿

## 3. 文档对齐

- [x] 3.1 `src/npc/cli.py` `--engine` help 与 `run_review_round` docstring 更新为 backend-aware 默认描述
- [x] 3.2 `plugins/agent-spine/skills/spine-run/SKILL.md` 与 `spine-spec/SKILL.md` 的 host adapter review 路由规则改写为「自动选路内置，显式 --engine claude 合法但非必需」

## 4. 回归验证

- [x] 4.1 `uv run pytest tests/test_verify.py tests/test_pipeline.py tests/test_spec_routing.py` 全绿
- [x] 4.2 `uv run pytest` 全量无新增失败
