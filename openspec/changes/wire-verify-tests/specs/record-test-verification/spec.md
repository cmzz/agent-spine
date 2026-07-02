## ADDED Requirements

### Requirement: record 阶段真实复跑验证 tests=pass 自报

`record_implement` / `record_fix` 在 RESULT 行报 `tests=pass` 且 `[verify].rerun_tests` 开启时 MUST 调用 `verify.run_tests` 真实复跑；复跑失败时 MUST 覆盖 coder 自报（tests 置 fail、状态置 failed）并在返回 JSON 标注 `tests_verified=false`。该行为 MUST 可通过配置关闭（笼子按需，遵不变量 3）。

#### Scenario: 复跑失败覆盖 coder 自报

- **WHEN** coder RESULT 报 `tests=pass`，但 `verify.run_tests` 复跑非零退出
- **THEN** record 结果状态置 failed、返回 JSON `tests_verified=false` + 复跑失败摘要
- **AND** 主 session 依 record 失败契约转决策点，不进入 archive

#### Scenario: 复跑通过正常放行

- **WHEN** coder 报 `tests=pass` 且复跑通过
- **THEN** record 按原契约成功，返回 JSON 含 `tests_verified=true`

#### Scenario: 配置关闭时不复跑

- **WHEN** `[verify].rerun_tests=false`
- **THEN** record 不调用 run_tests，行为与现状一致（采信自报），返回 JSON 不误标 verified

#### Scenario: 探测不到测试命令时降级不阻塞

- **WHEN** rerun_tests 开启但项目无可探测的测试命令（无 pytest/npm test/make test）
- **THEN** `tests_verified=null` 记录在案，record 不因此失败
