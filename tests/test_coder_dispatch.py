"""coder dispatch routing 测试：dispatch resolve + in-session 分发指令 + verify routing 扩展。

任务 4.1–4.6（coder-dispatch-routing change）：
- 4.1 dispatch resolve：默认表 + 覆盖优先级
- 4.2 implement in-session：返回 deferred 指令且不调用 runner
- 4.3 fix in-session：含 round 的 deferred 指令
- 4.4 headless 回归：mimo / 显式 headless 仍 spawn→record
- 4.5 verify routing：mimo+in-session 判 violation
- 4.6 pytest 全绿（由 CI 统一跑）

注意：集成测试（需真实文件系统 + state）直接构造 Paths 与 state_json，
绕过 init_run（init_run 在活跃 npc run 环境会因 state_already_exists 失败）。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from npc import coder as _coder
from npc import paths as _paths
from npc import verify as _verify
from npc.config import Config, CoderConfig, DISPATCH_DEFAULTS


# ============================================================
# Helpers
# ============================================================


def _real_commit(fake_repo: Path, fname: str = "f.txt", content: str = "x") -> str:
    (fake_repo / fname).write_text(content)
    subprocess.run(["git", "add", "."], cwd=fake_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"feat: {fname}"], cwd=fake_repo, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=fake_repo, capture_output=True, text=True
    ).stdout.strip()


def _never_called_runner(*, argv, cwd, env=None, timeout=None):
    """跑到这里即测试失败：in-session 分支不得调用 runner。"""
    raise AssertionError(f"runner 不应被调用（dispatch=in-session）；argv={argv}")


def _fake_runner(stdout: str, exit_code: int = 0):
    """构造假 runner，记录被调用的 argv/cwd/env，返回预设 stdout。"""
    calls: list[dict] = []

    def runner(*, argv, cwd, env=None, timeout=None):
        calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout})
        return _coder.CoderRunResult(stdout=stdout, exit_code=exit_code)

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _dispatch_cfg(dispatch: str | None = None, phase_dispatches=()) -> Config:
    return Config(coder=CoderConfig(dispatch=dispatch, phase_dispatches=phase_dispatches))


def _make_paths_and_state(
    tmp_path: Path,
    fake_repo: Path,
    change_id: str = "foo-change",
) -> tuple[_paths.Paths, Path]:
    """直接构造 Paths 与初始 state_json（绕过 init_run，避免活跃 run 的 state_already_exists）。"""
    task_log_dir = tmp_path / "task_log"
    run_dir = task_log_dir / f"001-{change_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    state_json = task_log_dir / "state.json"
    state_md = task_log_dir / "state.md"
    schema_path = task_log_dir / "schema.json"
    index_file = task_log_dir / "index.json"
    run_events = task_log_dir / "run.events.jsonl"

    schema_path.write_text("{}", encoding="utf-8")
    index_file.write_text("{}", encoding="utf-8")
    run_events.write_text("", encoding="utf-8")
    state_md.write_text("", encoding="utf-8")

    # 最小 state 结构
    state = {
        "version": "1",
        "plan_order": [change_id],
        "progress": [
            {
                "seq": 1,
                "change_id": change_id,
                "status": "implementing",
                "base": str(run_dir),
                "phases": {},
                "implement_commit": None,
            }
        ],
        "last_updated_at": "2026-06-24T00:00:00Z",
    }
    state_json.write_text(json.dumps(state), encoding="utf-8")

    p = _paths.Paths(
        repo_root=fake_repo,
        proj_key="test",
        task_log_dir=task_log_dir,
        run_ts="2026-06-24-0000",
        run_dir=task_log_dir,
        state_json=state_json,
        state_md=state_md,
        index_file=index_file,
        schema_path=schema_path,
        run_events=run_events,
    )
    return p, run_dir


# ============================================================
# 4.1 dispatch resolve：默认表 + 覆盖优先级
# ============================================================


def test_dispatch_default_claude_is_in_session():
    """Scenario: claude 默认走 in-session。"""
    cfg = Config()  # 无 dispatch 配置
    assert _coder.resolve_dispatch(cfg, "implement", "claude") == "in-session"


def test_dispatch_default_mimo_is_headless():
    """Scenario: mimo 默认走 headless。"""
    cfg = Config()
    assert _coder.resolve_dispatch(cfg, "implement", "mimo") == "headless"


def test_dispatch_default_codex_is_headless():
    """codex 内置默认 headless。"""
    cfg = Config()
    assert _coder.resolve_dispatch(cfg, "implement", "codex") == "headless"


def test_codex_runtime_default_is_codex_in_session():
    cfg = Config()
    backend = _coder.resolve_backend(cfg, "implement", runtime_host="codex")
    dispatch = _coder.resolve_dispatch(
        cfg, "implement", backend, runtime_host="codex"
    )
    assert backend == "codex"
    assert dispatch == "in-session"


def test_kimi_runtime_default_is_kimi_in_session():
    cfg = Config()
    backend = _coder.resolve_backend(cfg, "implement", runtime_host="kimi")
    dispatch = _coder.resolve_dispatch(
        cfg, "implement", backend, runtime_host="kimi"
    )
    assert backend == "kimi"
    assert dispatch == "in-session"


def test_kimi_runtime_explicit_headless_remains_authoritative():
    cfg = Config(coder=CoderConfig(dispatch="headless"))
    assert (
        _coder.resolve_dispatch(
            cfg, "implement", "kimi", runtime_host="kimi"
        )
        == "headless"
    )


def test_kimi_runtime_explicit_backend_remains_authoritative():
    cfg = Config(coder=CoderConfig(backend="mimo"))
    assert _coder.resolve_backend(cfg, "implement", runtime_host="kimi") == "mimo"


def test_codex_runtime_explicit_headless_remains_authoritative():
    cfg = Config(coder=CoderConfig(dispatch="headless"))
    assert (
        _coder.resolve_dispatch(
            cfg, "implement", "codex", runtime_host="codex"
        )
        == "headless"
    )


def test_codex_runtime_explicit_backend_remains_authoritative():
    cfg = Config(coder=CoderConfig(backend="mimo"))
    assert _coder.resolve_backend(cfg, "implement", runtime_host="codex") == "mimo"


def test_codex_runtime_implement_deferred_records_generator_backend(
    tmp_path: Path, fake_repo: Path
):
    p, _ = _make_paths_and_state(tmp_path, fake_repo)
    p = replace(p, runtime_host="codex")
    result = _coder.run_implement(
        p, 1, "foo-change", runner=_never_called_runner
    )
    assert result["deferred"] is True
    assert result["backend"] == "codex"
    state = json.loads(p.state_json.read_text(encoding="utf-8"))
    phase = state["progress"][0]["phases"]["implement"]
    assert phase["generator_backend"] == "codex"


def test_dispatch_global_config_overrides_default():
    """Scenario: per-phase 与全局覆盖生效 —— 全局 dispatch 覆盖内置默认。"""
    cfg = _dispatch_cfg(dispatch="headless")
    # 即使 claude 默认 in-session，全局配置 headless 应覆盖
    assert _coder.resolve_dispatch(cfg, "implement", "claude") == "headless"


def test_dispatch_per_phase_overrides_global():
    """Scenario: per-phase 优先级高于全局。"""
    cfg = _dispatch_cfg(
        dispatch="headless",
        phase_dispatches=(("implement", "in-session"),),
    )
    assert _coder.resolve_dispatch(cfg, "implement", "claude") == "in-session"
    # fix 未覆盖 → 走全局 headless
    assert _coder.resolve_dispatch(cfg, "fix", "claude") == "headless"


def test_dispatch_cli_override_wins_over_per_phase():
    """Scenario: CLI override 优先级最高。"""
    cfg = _dispatch_cfg(
        dispatch="in-session",
        phase_dispatches=(("implement", "in-session"),),
    )
    assert _coder.resolve_dispatch(cfg, "implement", "claude", "headless") == "headless"


def test_dispatch_defaults_table_completeness():
    """DISPATCH_DEFAULTS 必须包含全部 SUPPORTED_CODER_BACKENDS。"""
    from npc.config import SUPPORTED_CODER_BACKENDS
    for backend in SUPPORTED_CODER_BACKENDS:
        assert backend in DISPATCH_DEFAULTS, f"{backend!r} 未在 DISPATCH_DEFAULTS 中"


# ============================================================
# 4.2 implement in-session：deferred 指令，不调用 runner
# ============================================================


def test_implement_in_session_returns_deferred(tmp_path: Path, fake_repo: Path):
    """Scenario: implement in-session 返回 deferred 指令且不调用 runner。"""
    p, run_dir = _make_paths_and_state(tmp_path, fake_repo)

    result = _coder.run_implement(
        p,
        1,
        "foo-change",
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    assert result.get("ok") is True
    assert result.get("deferred") is True
    assert result.get("dispatch") == "in-session"
    assert result.get("phase") == "implement"
    assert result.get("seq") == 1
    assert result.get("change_id") == "foo-change"
    assert "spawn_prompt" in result and result["spawn_prompt"]
    assert "prompt_file" in result and result["prompt_file"]


def test_implement_in_session_prompt_file_written(tmp_path: Path, fake_repo: Path):
    """in-session 分支必须把 prompt 文件真实落盘。"""
    p, run_dir = _make_paths_and_state(tmp_path, fake_repo)

    result = _coder.run_implement(
        p,
        1,
        "foo-change",
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    prompt_file = Path(result["prompt_file"])
    assert prompt_file.exists(), f"prompt_file 未落盘：{prompt_file}"
    assert prompt_file.stat().st_size > 0


def test_implement_in_session_not_recorded(tmp_path: Path, fake_repo: Path):
    """in-session 分支不做 record：state 中该 phase 应仍为 in-progress（非 done/failed）。"""
    p, run_dir = _make_paths_and_state(tmp_path, fake_repo)

    _coder.run_implement(
        p,
        1,
        "foo-change",
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    s = json.loads(p.state_json.read_text())
    phase_status = s["progress"][0]["phases"].get("implement", {}).get("status")
    # deferred 不 record → phase 留在 in-progress（不 done 也不 failed）
    assert phase_status == "in-progress", f"预期 in-progress，实际 {phase_status}"


def test_implement_in_session_backend_field_present(tmp_path: Path, fake_repo: Path):
    """in-session 返回结果含 backend 字段。"""
    p, _ = _make_paths_and_state(tmp_path, fake_repo)

    result = _coder.run_implement(
        p,
        1,
        "foo-change",
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    assert result.get("backend") == "claude"


# ============================================================
# 4.3 fix in-session：含 round 的 deferred 指令
# ============================================================


def _make_paths_and_state_for_fix(
    tmp_path: Path, fake_repo: Path, impl_commit: str
) -> _paths.Paths:
    """构造有 implement_commit 的 state（供 fix 测试用）。"""
    p, _ = _make_paths_and_state(tmp_path, fake_repo)

    state = json.loads(p.state_json.read_text())
    state["progress"][0]["implement_commit"] = impl_commit
    p.state_json.write_text(json.dumps(state), encoding="utf-8")
    return p


def _write_prev_review(p: _paths.Paths, round_n: int, detail: str = "") -> Path:
    """在该 seq 的 base 目录写一份 round-<round_n>.review.json（fix 输入新鲜度校验的前置产物）。"""
    state = json.loads(p.state_json.read_text())
    base = Path(state["progress"][0]["base"])
    base.mkdir(parents=True, exist_ok=True)
    findings = (
        [{"id": "F1", "severity": "blocking", "category": "correctness",
          "in_scope": True, "detail": detail}]
        if detail
        else []
    )
    (base / f"round-{round_n}.review.json").write_text(
        json.dumps({"verdict": "changes-requested" if detail else "approve",
                    "findings": findings}),
        encoding="utf-8",
    )
    return base


def test_fix_in_session_returns_deferred_with_round(tmp_path: Path, fake_repo: Path):
    """Scenario: fix in-session 返回 deferred 指令，含 round 字段。"""
    impl_commit = _real_commit(fake_repo, "impl.txt", "i")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    _write_prev_review(p, 0)  # round-1 fix 消费 round-0.review.json

    result = _coder.run_fix(
        p,
        1,
        "foo-change",
        1,
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    assert result.get("ok") is True
    assert result.get("deferred") is True
    assert result.get("dispatch") == "in-session"
    assert result.get("round") == 1
    assert result.get("phase") == "fix-r1"
    assert result.get("seq") == 1
    assert "spawn_prompt" in result and result["spawn_prompt"]
    assert "prompt_file" in result and result["prompt_file"]


def test_fix_in_session_prompt_file_named_correctly(tmp_path: Path, fake_repo: Path):
    """fix in-session prompt 文件名形如 round-N.fix.prompt.md。"""
    impl_commit = _real_commit(fake_repo, "impl2.txt", "i2")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    _write_prev_review(p, 1)  # round-2 fix 消费 round-1.review.json

    result = _coder.run_fix(
        p,
        1,
        "foo-change",
        2,  # round=2
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    prompt_file = Path(result["prompt_file"])
    assert prompt_file.name == "round-2.fix.prompt.md", f"文件名不符：{prompt_file.name}"
    assert prompt_file.exists()


def test_fix_in_session_not_recorded(tmp_path: Path, fake_repo: Path):
    """fix in-session 不 record：phase 留在 in-progress。"""
    impl_commit = _real_commit(fake_repo, "impl3.txt", "i3")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    _write_prev_review(p, 0)

    _coder.run_fix(
        p,
        1,
        "foo-change",
        1,
        backend="claude",
        dispatch="in-session",
        runner=_never_called_runner,
    )

    s = json.loads(p.state_json.read_text())
    phase_status = s["progress"][0]["phases"].get("fix-r1", {}).get("status")
    assert phase_status == "in-progress", f"预期 in-progress，实际 {phase_status}"


# ============================================================
# 4.4 headless 回归：mimo / 显式 headless 仍走 spawn→record
# ============================================================


def test_implement_mimo_uses_headless_by_default(
    tmp_path: Path, fake_repo: Path
):
    """Scenario: headless 分发维持原行为 —— mimo 默认 headless，runner 被调用。"""
    p, run_dir = _make_paths_and_state(tmp_path, fake_repo)

    commit = _real_commit(fake_repo)
    summary = run_dir / "implement.summary.md"
    summary.write_text("# s\n")

    env_file = tmp_path / "mimo.env"
    env_file.write_text(
        "export ANTHROPIC_BASE_URL=https://mimo.example\nexport ANTHROPIC_AUTH_TOKEN=tok\n"
    )
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text(
        f'[coder]\nbackend = "mimo"\n[coder.mimo]\nenv_file = "{env_file}"\n'
    )

    stdout = f"RESULT: commit={commit} tasks=1 tests=pass summary={summary} notes=-\n"
    runner = _fake_runner(stdout, exit_code=0)

    result = _coder.run_implement(
        p,
        1,
        "foo-change",
        config_path=cfg_path,
        runner=runner,
    )

    # runner 必须被调用（headless 路径）
    assert len(runner.calls) == 1, "mimo headless 路径应调用 runner 一次"
    assert result.get("ok") is True
    assert result.get("backend") == "mimo"
    # 结果不含 deferred 字段（或为 False）
    assert not result.get("deferred", False)


def test_implement_explicit_headless_uses_runner(tmp_path: Path, fake_repo: Path):
    """显式 --dispatch headless 即使 claude 后端也走 runner（headless 路径）。"""
    p, run_dir = _make_paths_and_state(tmp_path, fake_repo)

    commit = _real_commit(fake_repo)
    summary = run_dir / "implement.summary.md"
    summary.write_text("# s\n")

    stdout = f"RESULT: commit={commit} tasks=1 tests=pass summary={summary} notes=-\n"
    runner = _fake_runner(stdout, exit_code=0)

    result = _coder.run_implement(
        p,
        1,
        "foo-change",
        backend="claude",
        dispatch="headless",
        runner=runner,
    )

    assert len(runner.calls) == 1, "显式 headless 应调用 runner"
    assert result.get("ok") is True
    assert not result.get("deferred", False)


# ============================================================
# 4.5 verify routing：mimo+in-session 判 violation
# ============================================================


def _routing_cfg(
    *,
    coder_backend: str = "claude",
    coder_dispatch: str | None = None,
    phase_dispatches: tuple = (),
    review_engine: str = "codex",
) -> Config:
    from npc.config import ReviewEngineConfig
    return Config(
        review=ReviewEngineConfig(engine=review_engine),
        coder=CoderConfig(
            backend=coder_backend,
            dispatch=coder_dispatch,
            phase_dispatches=phase_dispatches,
        ),
    )


def test_verify_routing_mimo_in_session_violation():
    """Scenario: mimo + in-session 判为 violation。"""
    cfg = _routing_cfg(coder_backend="mimo", coder_dispatch="in-session")
    violations = _verify.check_routing(cfg)
    rules = {v["rule"] for v in violations}
    assert "mimo_in_session" in rules, f"预期 mimo_in_session violation，实际 violations={violations}"


def test_verify_routing_mimo_per_phase_in_session_violation():
    """mimo 全局 + implement phase 显式 in-session → violation。"""
    cfg = _routing_cfg(
        coder_backend="mimo",
        phase_dispatches=(("implement", "in-session"),),
    )
    violations = _verify.check_routing(cfg)
    rules = {v["rule"] for v in violations}
    assert "mimo_in_session" in rules


def test_verify_routing_mimo_headless_no_in_session_violation():
    """mimo + headless（内置默认）→ 无 mimo_in_session violation。"""
    cfg = _routing_cfg(coder_backend="mimo", review_engine="codex")
    violations = _verify.check_routing(cfg)
    rules = {v["rule"] for v in violations}
    assert "mimo_in_session" not in rules


def test_verify_routing_claude_in_session_no_violation():
    """claude + in-session（内置默认）→ 无 mimo_in_session violation。"""
    cfg = _routing_cfg(coder_backend="claude", review_engine="codex")
    violations = _verify.check_routing(cfg)
    rules = {v["rule"] for v in violations}
    assert "mimo_in_session" not in rules


def test_verify_routing_claude_fix_in_session_no_violation():
    """claude 后端 + fix phase in-session → 无 mimo_in_session violation（claude 允许）。"""
    cfg = _routing_cfg(
        coder_backend="claude",
        phase_dispatches=(("fix", "in-session"),),
    )
    violations = _verify.check_routing(cfg)
    rules = {v["rule"] for v in violations}
    assert "mimo_in_session" not in rules


def test_verify_routing_mimo_fix_phase_in_session_violation():
    """mimo 后端、fix phase 配置 in-session → violation。"""
    cfg = _routing_cfg(
        coder_backend="mimo",
        phase_dispatches=(("fix", "in-session"),),
    )
    violations = _verify.check_routing(cfg)
    rules = {v["rule"] for v in violations}
    assert "mimo_in_session" in rules


# ============================================================
# F1 回归：CLI --backend mimo --dispatch in-session 不变量守卫
# ============================================================


def test_implement_mimo_in_session_raises_before_phase_enter(
    tmp_path: Path, fake_repo: Path
):
    """CLI --backend mimo --dispatch in-session：run_implement 必须在 phase_enter 之前拒绝。

    期望抛 ValueError，且 state 中 implement phase 完全不存在（未 enter）。
    """
    p, _ = _make_paths_and_state(tmp_path, fake_repo)

    with pytest.raises(ValueError, match="mimo"):
        _coder.run_implement(
            p,
            1,
            "foo-change",
            backend="mimo",
            dispatch="in-session",
            runner=_never_called_runner,
        )

    # phase 未 enter → state 里 implement phase 记录不存在
    s = json.loads(p.state_json.read_text())
    phases = s["progress"][0].get("phases", {})
    assert "implement" not in phases, (
        f"phase_enter 不应被调用（mimo+in-session 应在 enter 前被拒绝）；phases={phases}"
    )


def test_fix_mimo_in_session_raises_before_phase_enter(
    tmp_path: Path, fake_repo: Path
):
    """CLI --backend mimo --dispatch in-session：run_fix 必须在 phase_enter 之前拒绝。

    期望抛 ValueError，且 state 中 fix-r1 phase 完全不存在（未 enter）。
    """
    impl_commit = _real_commit(fake_repo, "impl_mimo.txt", "m")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)

    with pytest.raises(ValueError, match="mimo"):
        _coder.run_fix(
            p,
            1,
            "foo-change",
            1,
            backend="mimo",
            dispatch="in-session",
            runner=_never_called_runner,
        )

    # phase 未 enter
    s = json.loads(p.state_json.read_text())
    phases = s["progress"][0].get("phases", {})
    assert "fix-r1" not in phases, (
        f"phase_enter 不应被调用（mimo+in-session 应在 enter 前被拒绝）；phases={phases}"
    )


def test_implement_mimo_headless_still_works(tmp_path: Path, fake_repo: Path):
    """明确 --backend mimo --dispatch headless：不应触发不变量守卫，应正常走 runner。"""
    p, run_dir = _make_paths_and_state(tmp_path, fake_repo)

    commit = _real_commit(fake_repo, "mimo_ok.txt", "ok")
    summary = run_dir / "implement.summary.md"
    summary.write_text("# s\n")

    env_file = tmp_path / "mimo2.env"
    env_file.write_text(
        "export ANTHROPIC_BASE_URL=https://mimo.example\nexport ANTHROPIC_AUTH_TOKEN=tok\n"
    )
    cfg_path = tmp_path / "cfg2.toml"
    cfg_path.write_text(
        f'[coder]\nbackend = "mimo"\n[coder.mimo]\nenv_file = "{env_file}"\n'
    )

    stdout = f"RESULT: commit={commit} tasks=1 tests=pass summary={summary} notes=-\n"
    runner = _fake_runner(stdout, exit_code=0)

    # dispatch=headless 显式传入 → 不触发守卫
    result = _coder.run_implement(
        p,
        1,
        "foo-change",
        backend="mimo",
        dispatch="headless",
        config_path=cfg_path,
        runner=runner,
    )

    assert len(runner.calls) == 1, "mimo headless 应调用 runner"
    assert result.get("ok") is True
    assert not result.get("deferred", False)


# ============================================================
# F2 回归：codex/kimi headless 尚未实现 → 在 phase_enter 之前显式拒绝
# （review add-kimi-native-runtime round 1 F2；与上面 mimo+in-session 守卫同构，
# 但方向相反——这里是"该 backend 只许 in-session，headless 未实现"）
# ============================================================


@pytest.mark.parametrize("backend", ["codex", "kimi"])
def test_implement_headless_unimplemented_backend_raises_before_phase_enter(
    backend: str, tmp_path: Path, fake_repo: Path
):
    """显式 --backend codex/kimi、默认 dispatch=headless（非对应 runtime_host）：
    run_implement 必须在 phase_enter 之前拒绝，且 runner 完全不被调用。
    """
    p, _ = _make_paths_and_state(tmp_path, fake_repo)

    with pytest.raises(ValueError, match=backend):
        _coder.run_implement(
            p, 1, "foo-change", backend=backend, runner=_never_called_runner,
        )

    s = json.loads(p.state_json.read_text())
    phases = s["progress"][0].get("phases", {})
    assert "implement" not in phases, (
        f"phase_enter 不应被调用（{backend} headless 应在 enter 前被拒绝）；phases={phases}"
    )


@pytest.mark.parametrize("backend", ["codex", "kimi"])
def test_fix_headless_unimplemented_backend_raises_before_phase_enter(
    backend: str, tmp_path: Path, fake_repo: Path
):
    """fix 阶段同构：--backend codex/kimi + 默认 headless 必须在 phase_enter 之前拒绝。"""
    impl_commit = _real_commit(fake_repo, f"impl_{backend}.txt", backend)
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)

    with pytest.raises(ValueError, match=backend):
        _coder.run_fix(
            p, 1, "foo-change", 1, backend=backend, runner=_never_called_runner,
        )

    s = json.loads(p.state_json.read_text())
    phases = s["progress"][0].get("phases", {})
    assert "fix-r1" not in phases, (
        f"phase_enter 不应被调用（{backend} headless 应在 enter 前被拒绝)；phases={phases}"
    )


def test_codex_runtime_explicit_headless_override_still_rejected(
    tmp_path: Path, fake_repo: Path
):
    """即便处于 codex runtime、[coder].dispatch 显式覆盖为 headless（resolve_dispatch
    层面"remains authoritative"，见上面 test_codex_runtime_explicit_headless_
    remains_authoritative），run_implement 仍必须拒绝——headless 编排本身未实现，
    显式配置不能让不存在的执行路径变得可用。
    """
    p, _ = _make_paths_and_state(tmp_path, fake_repo)
    p = replace(p, runtime_host="codex")
    cfg_path = tmp_path / "codex_headless.toml"
    cfg_path.write_text('[coder]\ndispatch = "headless"\n')

    with pytest.raises(ValueError, match="codex"):
        _coder.run_implement(
            p, 1, "foo-change", config_path=cfg_path, runner=_never_called_runner,
        )


def test_kimi_runtime_explicit_headless_override_still_rejected(
    tmp_path: Path, fake_repo: Path
):
    """kimi runtime + 显式 [coder].dispatch=headless：同上，仍必须拒绝。"""
    p, _ = _make_paths_and_state(tmp_path, fake_repo)
    p = replace(p, runtime_host="kimi")
    cfg_path = tmp_path / "kimi_headless.toml"
    cfg_path.write_text('[coder]\ndispatch = "headless"\n')

    with pytest.raises(ValueError, match="kimi"):
        _coder.run_implement(
            p, 1, "foo-change", config_path=cfg_path, runner=_never_called_runner,
        )


def test_implement_codex_in_session_still_deferred_no_regression(
    tmp_path: Path, fake_repo: Path
):
    """回归护栏：codex runtime 下默认路径（backend=codex, dispatch=in-session）
    不应被新守卫误伤——必须仍走 deferred 分支，不调用 runner。
    """
    p, _ = _make_paths_and_state(tmp_path, fake_repo)
    p = replace(p, runtime_host="codex")

    result = _coder.run_implement(p, 1, "foo-change", runner=_never_called_runner)

    assert result["deferred"] is True
    assert result["backend"] == "codex"


def test_implement_kimi_in_session_still_deferred_no_regression(
    tmp_path: Path, fake_repo: Path
):
    """回归护栏：kimi runtime 下默认路径（backend=kimi, dispatch=in-session）
    不应被新守卫误伤——必须仍走 deferred 分支，不调用 runner。
    """
    p, _ = _make_paths_and_state(tmp_path, fake_repo)
    p = replace(p, runtime_host="kimi")

    result = _coder.run_implement(p, 1, "foo-change", runner=_never_called_runner)

    assert result["deferred"] is True
    assert result["backend"] == "kimi"


# ============================================================
# run-stale-review-guard（code 侧 fix 输入新鲜度 + missing 结构化拒绝）
# ============================================================


def _prog_status(p: _paths.Paths) -> str:
    return json.loads(p.state_json.read_text())["progress"][0]["status"]


def _fix_prompt_path(p: _paths.Paths, round_n: int) -> Path:
    base = Path(json.loads(p.state_json.read_text())["progress"][0]["base"])
    return base / f"round-{round_n}.fix.prompt.md"


def test_fix_stale_review_rejected_headless(tmp_path: Path, fake_repo: Path):
    """stale（子进程分发）：round-0 与 round-1 同存 → fix --round 1 拒绝，runner 不被调用。"""
    impl_commit = _real_commit(fake_repo, "impl_stale.txt", "s")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    _write_prev_review(p, 0)
    _write_prev_review(p, 1)  # 更高轮次存在 → 过期输入

    result = _coder.run_fix(
        p, 1, "foo-change", 1,
        backend="claude", dispatch="headless", runner=_never_called_runner,
    )

    assert result["ok"] is False
    assert result["error"] == "stale_review_input"
    assert not _fix_prompt_path(p, 1).exists()
    assert _prog_status(p) == "needs-user-decision"


def test_fix_stale_review_rejected_in_session(tmp_path: Path, fake_repo: Path):
    """stale（in-session 分发）：拒绝且返回体 MUST NOT 含 deferred==true。"""
    impl_commit = _real_commit(fake_repo, "impl_stale2.txt", "s2")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    _write_prev_review(p, 0)
    _write_prev_review(p, 1)

    result = _coder.run_fix(
        p, 1, "foo-change", 1,
        backend="claude", dispatch="in-session", runner=_never_called_runner,
    )

    assert result["ok"] is False
    assert result["error"] == "stale_review_input"
    assert result.get("deferred") is not True
    assert not _fix_prompt_path(p, 1).exists()
    assert _prog_status(p) == "needs-user-decision"


def test_fix_missing_review_rejected_headless(tmp_path: Path, fake_repo: Path):
    """missing（子进程分发）：round-0 缺失 → prev_review_missing，runner 不被调用。"""
    impl_commit = _real_commit(fake_repo, "impl_miss.txt", "m")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    # 不写任何 review 文件

    result = _coder.run_fix(
        p, 1, "foo-change", 1,
        backend="claude", dispatch="headless", runner=_never_called_runner,
    )

    assert result["ok"] is False
    assert result["error"] == "prev_review_missing"
    assert not _fix_prompt_path(p, 1).exists()
    assert _prog_status(p) == "needs-user-decision"


def test_fix_missing_review_rejected_in_session(tmp_path: Path, fake_repo: Path):
    """missing（in-session 分发）：拒绝且返回体 MUST NOT 含 deferred==true。"""
    impl_commit = _real_commit(fake_repo, "impl_miss2.txt", "m2")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)

    result = _coder.run_fix(
        p, 1, "foo-change", 1,
        backend="claude", dispatch="in-session", runner=_never_called_runner,
    )

    assert result["ok"] is False
    assert result["error"] == "prev_review_missing"
    assert result.get("deferred") is not True
    assert _prog_status(p) == "needs-user-decision"


def test_fix_missing_takes_precedence_over_stale(tmp_path: Path, fake_repo: Path):
    """2.3a：round-0 缺失但存在更高轮次 round-1 → 返回 prev_review_missing 而非 stale_review_input。"""
    impl_commit = _real_commit(fake_repo, "impl_prec.txt", "p")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    _write_prev_review(p, 1)  # 只有更高轮次，基线 round-0 缺失

    result = _coder.run_fix(
        p, 1, "foo-change", 1,
        backend="claude", dispatch="headless", runner=_never_called_runner,
    )

    assert result["ok"] is False
    assert result["error"] == "prev_review_missing"
    assert not _fix_prompt_path(p, 1).exists()


def test_fix_no_higher_round_renders_headless(tmp_path: Path, fake_repo: Path):
    """无更高轮次（子进程分发）：round-0 存在且无更高轮次 → 正常渲染并调用 runner。"""
    impl_commit = _real_commit(fake_repo, "impl_ok.txt", "o")
    p = _make_paths_and_state_for_fix(tmp_path, fake_repo, impl_commit)
    base = _write_prev_review(p, 0)

    fix_commit = _real_commit(fake_repo, "fix_ok.txt", "f")
    summary = base / "round-1.fix.summary.md"
    summary.write_text("# fix summary\n")
    stdout = (
        f"RESULT: commit={fix_commit} fixed=1 tests=pass summary={summary} "
        f"categories_scanned=- regressions_added=- notes=-\n"
    )
    runner = _fake_runner(stdout, exit_code=0)

    result = _coder.run_fix(
        p, 1, "foo-change", 1,
        backend="claude", dispatch="headless", runner=runner,
    )

    # render 未被 stale/missing 拦截：runner 被调用、prompt 落盘、record 成功
    assert len(runner.calls) == 1
    assert _fix_prompt_path(p, 1).exists()
    assert result["ok"] is True
