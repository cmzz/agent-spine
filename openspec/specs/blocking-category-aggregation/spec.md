# blocking-category-aggregation Specification

## Purpose
TBD - created by archiving change aggregate-blocking-categories. Update Purpose after archive.
## Requirements
### Requirement: 聚合输出 top_blocking_categories

`aggregate()` MUST 在每个桶（by-phase / by-change / by-week）累计事件的 `blocking_categories`（按 category 计数），并在该桶输出中新增 `top_blocking_categories`（按出现次数降序的 top-N 映射）。事件缺失 `blocking_categories`（如 review 失败路径）MUST NOT 报错，按无贡献处理。

#### Scenario: by-phase 汇总 blocking 类别

- **WHEN** 聚合含两条 review-r1 事件、`blocking_categories` 分别为 `["correctness","perf"]` 与 `["correctness"]`
- **THEN** `by-phase` 的 `review-r1` 输出含 `top_blocking_categories`，其中 `correctness=2`、`perf=1`

#### Scenario: 缺字段不报错

- **WHEN** 某事件无 `blocking_categories` 字段
- **THEN** 聚合正常完成，该事件对 `top_blocking_categories` 无贡献

### Requirement: hotspots 透出 top_blocking_categories

`hotspots()` 输出的每个 scored phase MUST 含 `top_blocking_categories`，取自该 phase 的聚合结果，供 `/spine-analyze` 直接读取而无需再翻原始事件。

#### Scenario: hotspot 项带 blocking 类别

- **WHEN** 对含 blocking_categories 的 review 事件调用 `hotspots()`
- **THEN** 对应 phase 的 scored 项含非空 `top_blocking_categories`

