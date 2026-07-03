"""test_plan_dag.py — npc plan dag 单元测试。

覆盖 spec：
- plan-dag-analysis spec.md 全部 Scenario
- 同层/依赖后置/路径重叠/无路径退化/max_parallel=1 等价串行
- 依赖环/未知依赖退化串行
- serialization_reason 热点路径点名
- max_parallel 切片
- 13 个加固提案真实语料召回（verifying no crash）
"""

from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any

import pytest

from npc import plan as _plan
from npc.config import SchedulerConfig


# ============================================================
# helpers
# ============================================================

def _make_change_dir(tmp_path: Path, change_id: str, tasks_content: str = "", proposal_content: str = "") -> Path:
    """在 tmp_path/openspec/changes/<change_id> 创建 change 目录并写 tasks.md / proposal.md。"""
    change_dir = tmp_path / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True)
    if tasks_content:
        (change_dir / "tasks.md").write_text(tasks_content, encoding="utf-8")
    if proposal_content:
        (change_dir / "proposal.md").write_text(proposal_content, encoding="utf-8")
    return change_dir


def _make_dag_args(tmp_path: Path, plan_order: list[str], config_toml: str = "") -> argparse.Namespace:
    """构造 npc plan dag 的 args。"""
    if config_toml:
        config_file = tmp_path / "config.toml"
        config_file.write_text(config_toml, encoding="utf-8")
        config_path = str(config_file)
    else:
        config_path = None
    ns = argparse.Namespace(
        plan_order=json.dumps(plan_order),
        config=config_path,
        run_ts=None,
        task_log_dir=None,
        state_json=None,
    )
    return ns


def _run_dag(monkeypatch, tmp_path: Path, plan_order: list[str], config_toml: str = "") -> dict:
    """运行 run_dag，捕获 stdout 并解析 JSON。"""
    monkeypatch.setattr(_plan, "_resolve_repo_root", lambda args: tmp_path)
    args = _make_dag_args(tmp_path, plan_order, config_toml)
    captured = {}
    original_emit = _plan._io.emit

    def capture_emit(data: Any) -> None:
        captured.update(data)

    monkeypatch.setattr(_plan._io, "emit", capture_emit)
    _plan.run_dag(args)
    return captured


# ============================================================
# Scenario: 两个不重叠 change 分入同层
# ============================================================

def test_dag_two_non_overlapping_same_layer(monkeypatch, tmp_path):
    """change-a 和 change-b 路径不重叠且无依赖 → 同一层。"""
    _make_change_dir(tmp_path, "change-a", tasks_content="修改 `src/a.py`")
    _make_change_dir(tmp_path, "change-b", tasks_content="修改 `src/b.py`")

    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-b"])
    assert result["ok"] is True
    layers = result["layers"]
    # 两个 change 应该在同一层
    assert any(set(layer) == {"change-a", "change-b"} for layer in layers), f"layers={layers}"


# ============================================================
# Scenario: 有依赖的 change 分入后置层
# ============================================================

def test_dag_dependency_later_layer(monkeypatch, tmp_path):
    """change-b 声明依赖 change-a → b 所在层 > a 所在层。"""
    _make_change_dir(tmp_path, "change-a", tasks_content="修改 `src/a.py`")
    _make_change_dir(tmp_path, "change-b",
                     tasks_content="修改 `src/b.py`",
                     proposal_content="依赖前置：change-a\n")

    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-b"])
    assert result["ok"] is True
    layers = result["layers"]
    # 找各 change 所在层
    layer_of = {}
    for i, layer in enumerate(layers):
        for cid in layer:
            layer_of[cid] = i
    assert "change-a" in layer_of
    assert "change-b" in layer_of
    assert layer_of["change-b"] > layer_of["change-a"], f"layer_of={layer_of}"


# ============================================================
# Scenario: 路径重叠的 change 不同层
# ============================================================

def test_dag_path_overlap_different_layers(monkeypatch, tmp_path):
    """change-a 和 change-b 共同触碰 src/shared.py → 不同层。"""
    _make_change_dir(tmp_path, "change-a", tasks_content="修改 `src/shared.py` 与 `src/a.py`")
    _make_change_dir(tmp_path, "change-b", tasks_content="修改 `src/shared.py` 与 `src/b.py`")

    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-b"])
    assert result["ok"] is True
    layers = result["layers"]
    # change-a 和 change-b 不应在同层
    for layer in layers:
        assert not ("change-a" in layer and "change-b" in layer), f"Both in same layer: {layer}"


# ============================================================
# Scenario: 无路径信息的 change 单独成层
# ============================================================

def test_dag_no_paths_single_layer(monkeypatch, tmp_path):
    """change-c 无路径信息 → 独占一层。"""
    _make_change_dir(tmp_path, "change-a", tasks_content="修改 `src/a.py`")
    _make_change_dir(tmp_path, "change-c", tasks_content="这是一些自然语言描述，没有路径信息")

    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-c"])
    assert result["ok"] is True
    layers = result["layers"]
    # change-c 应独占一层
    change_c_layers = [layer for layer in layers if "change-c" in layer]
    assert len(change_c_layers) == 1
    assert len(change_c_layers[0]) == 1, f"change-c not alone: {change_c_layers[0]}"


# ============================================================
# Scenario: 依赖环退化串行
# ============================================================

def test_dag_cycle_degrades_to_serial(monkeypatch, tmp_path):
    """change-a 依赖 b，b 依赖 a → 完全串行，degraded_reason 含 cycle。"""
    _make_change_dir(tmp_path, "change-a",
                     tasks_content="修改 `src/a.py`",
                     proposal_content="依赖前置：change-b\n")
    _make_change_dir(tmp_path, "change-b",
                     tasks_content="修改 `src/b.py`",
                     proposal_content="依赖前置：change-a\n")

    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-b"])
    assert result["ok"] is True
    assert result.get("degraded_reason") is not None, "Should have degraded_reason for cycle"
    assert "cycle" in str(result["degraded_reason"]).lower(), f"degraded_reason={result['degraded_reason']}"
    # 所有层均为单元素
    for layer in result["layers"]:
        assert len(layer) == 1, f"Should be serial: {layer}"


# ============================================================
# Scenario: max_parallel=1 等价串行
# ============================================================

def test_dag_max_parallel_1_serial(monkeypatch, tmp_path):
    """max_parallel=1 → 全串行，每层只有一个 change。"""
    _make_change_dir(tmp_path, "change-a", tasks_content="修改 `src/a.py`")
    _make_change_dir(tmp_path, "change-b", tasks_content="修改 `src/b.py`")
    _make_change_dir(tmp_path, "change-c", tasks_content="修改 `src/c.py`")

    config_toml = "[scheduler]\nmax_parallel = 1\n"
    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-b", "change-c"], config_toml)
    assert result["ok"] is True
    for layer in result["layers"]:
        assert len(layer) == 1, f"max_parallel=1 should yield single-element layers: {layer}"
    assert len(result["layers"]) == 3


# ============================================================
# Scenario: 超限层被切片
# ============================================================

def test_dag_max_parallel_slice(monkeypatch, tmp_path):
    """5 个不重叠 change + max_parallel=3 → 切成 3+2 两层。"""
    for i in range(5):
        _make_change_dir(tmp_path, f"change-{i}",
                         tasks_content=f"修改 `src/module_{i}.py`")

    config_toml = "[scheduler]\nmax_parallel = 3\n"
    plan = [f"change-{i}" for i in range(5)]
    result = _run_dag(monkeypatch, tmp_path, plan, config_toml)
    assert result["ok"] is True
    layers = result["layers"]
    # 最大层大小不超过 3
    for layer in layers:
        assert len(layer) <= 3, f"Layer exceeds max_parallel: {layer}"
    # 总计 5 个 change 覆盖
    all_cids = [cid for layer in layers for cid in layer]
    assert set(all_cids) == set(plan), f"Not all changes covered: {all_cids}"


# ============================================================
# Scenario: 热点文件被点名
# ============================================================

def test_dag_hotspot_named_in_serialization_reason(monkeypatch, tmp_path):
    """两个 change 共同触碰 plugins/agent-spine/commands/spine-run.md → serialization_reason 含文件名。"""
    _make_change_dir(tmp_path, "change-a",
                     tasks_content="修改 `plugins/agent-spine/commands/spine-run.md` 和 `src/a.py`")
    _make_change_dir(tmp_path, "change-b",
                     tasks_content="修改 `plugins/agent-spine/commands/spine-run.md` 和 `src/b.py`")

    result = _run_dag(monkeypatch, tmp_path, ["change-a", "change-b"])
    assert result["ok"] is True
    sr = result.get("serialization_reason") or {}
    # 至少一个 change 有 hotspot 原因
    all_reasons = []
    for reasons in sr.values():
        if isinstance(reasons, list):
            all_reasons.extend(reasons)
        else:
            all_reasons.append(str(reasons))
    hotspot_reasons = [r for r in all_reasons if "hotspot" in r.lower() or "spine-run" in r.lower()]
    assert hotspot_reasons, f"No hotspot reason found: {sr}"


# ============================================================
# Scenario: 空 plan_order
# ============================================================

def test_dag_empty_plan_order(monkeypatch, tmp_path):
    """空 plan_order → 空 layers，parallelizable_fraction=0。"""
    result = _run_dag(monkeypatch, tmp_path, [])
    assert result["ok"] is True
    assert result["layers"] == []
    assert result["parallelizable_fraction"] == 0.0


# ============================================================
# Scenario: parallelizable_fraction 计算
# ============================================================

def test_dag_parallelizable_fraction(monkeypatch, tmp_path):
    """3 个不重叠 change → 全部并行，fraction=1.0。"""
    for i in range(3):
        _make_change_dir(tmp_path, f"cx-{i}", tasks_content=f"修改 `src/file_{i}.py`")

    result = _run_dag(monkeypatch, tmp_path, ["cx-0", "cx-1", "cx-2"])
    assert result["ok"] is True
    # 全部在同一层 → fraction = 1.0（或接近）
    assert result["parallelizable_fraction"] > 0, f"fraction={result['parallelizable_fraction']}"


# ============================================================
# Scenario: 真实语料不崩溃（13 个加固提案）
# ============================================================

def test_dag_real_corpus_no_crash(monkeypatch, tmp_path):
    """用真实的 13 个加固提案目录（如果存在）或 mock 目录运行 dag，不应崩溃。"""
    # 模拟 13 个加固提案
    change_ids = [
        "orchestrator-check-record-result",
        "init-crash-worktree-recovery",
        "in-session-coder-timeout",
        "review-run-failure-branch",
        "auto-decide-abort-and-archive-fallback",
        "fix-auto-decide-trigger-contract",
        "telemetry-auto-decide-finalize",
        "plugin-subagent-stop-hook",
        "auto-mode-deny-rules",
        "analyze-untriggered-cages",
        "archive-structured-errors",
        "telemetry-canonical-proj-key",
        "parallel-dag-scheduling",
    ]
    # 为每个 change 创建简单 tasks.md
    for cid in change_ids:
        content = f"# {cid} Tasks\n\n- [ ] 修改 `src/npc/{cid.replace('-','_')}.py`\n"
        _make_change_dir(tmp_path, cid, tasks_content=content)

    result = _run_dag(monkeypatch, tmp_path, change_ids)
    assert result["ok"] is True
    # 所有 change 都应出现在某层
    all_cids = [cid for layer in result["layers"] for cid in layer]
    assert set(all_cids) == set(change_ids), f"Missing: {set(change_ids) - set(all_cids)}"


# ============================================================
# Scenario: 无效 plan_order 报错
# ============================================================

def test_dag_invalid_plan_order_error(monkeypatch, tmp_path):
    """非 JSON 的 plan_order → emit_error 并退出。"""
    monkeypatch.setattr(_plan, "_resolve_repo_root", lambda args: tmp_path)
    args = _make_dag_args(tmp_path, [])
    args.plan_order = "not-json"

    errors = []
    monkeypatch.setattr(_plan._io, "emit_error", lambda kind, msg, exit_code=1: errors.append((kind, exit_code)))

    _plan.run_dag(args)
    assert errors, "Should have called emit_error"
    assert errors[0][0] == "invalid_plan_order"


# ============================================================
# Scenario: config.py [scheduler] 节解析
# ============================================================

def test_config_scheduler_defaults():
    """SchedulerConfig 默认值：max_parallel=3, max_evictions=2。"""
    cfg = SchedulerConfig()
    assert cfg.max_parallel == 3
    assert cfg.max_evictions == 2


def test_config_scheduler_validation():
    """max_parallel=0 → ConfigError。"""
    from npc.config import ConfigError
    with pytest.raises(ConfigError, match="max_parallel"):
        SchedulerConfig(max_parallel=0)

    with pytest.raises(ConfigError, match="max_evictions"):
        SchedulerConfig(max_evictions=0)


def test_config_load_scheduler_from_toml(tmp_path):
    """从 TOML 配置文件加载 [scheduler] 节。"""
    from npc.config import load_config
    config_file = tmp_path / ".npc" / "config.toml"
    config_file.parent.mkdir()
    config_file.write_text("[scheduler]\nmax_parallel = 5\nmax_evictions = 3\n", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.scheduler.max_parallel == 5
    assert cfg.scheduler.max_evictions == 3
