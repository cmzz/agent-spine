## 1. 配置

- [ ] 1.1 `[verify].rerun_tests` 配置项（bool，缺省语义：auto 档默认 true）
- [ ] 1.2 配置读取与默认值单测

## 2. 接线

- [ ] 2.1 `record_implement`：RESULT `tests=pass` 且 rerun_tests 开启 → 调 `verify.run_tests`（cwd=worktree）
- [ ] 2.2 `record_fix`：同 2.1
- [ ] 2.3 复跑失败 → 覆盖自报（tests=fail、status=failed），返回 JSON 含 `tests_verified=false` + 失败摘要
- [ ] 2.4 复跑通过 → `tests_verified=true`；探测不到测试命令 → `tests_verified=null`（不阻塞）
- [ ] 2.5 复跑结果 emit telemetry（phase record 事件带 tests_verified）

## 3. 测试

- [ ] 3.1 复跑失败覆盖自报：record 返回 failed、`tests_verified=false`
- [ ] 3.2 复跑通过：状态正常、`tests_verified=true`
- [ ] 3.3 rerun_tests=false：不复跑，行为与现状一致
- [ ] 3.4 探测不到测试命令：`tests_verified=null`，record 不失败
- [ ] 3.5 `pytest` 全绿
