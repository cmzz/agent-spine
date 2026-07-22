"""spec 侧路由配置与不变量测试（change: spec-routing-invariant）。

覆盖范围（对应 tasks.md）：

1. 配置层：`[spec_writer]`/`[spec_review]` 的安全默认值与显式解析（tasks 1.x）。
2. 路由不变量：`check_routing` 新增五条 `spec_*` 规则的正例/反例（tasks 2.x）。
3. 既有漏洞修复：`gen_not_orthogonal` 补上 codex/codex 同源形态（tasks 2b.x）。
4. 回归防护：两对规则（coder/review、spec_writer/spec_review）彼此独立，
   既有五条规则的触发条件与语义未被误伤（tasks 3.x）。
"""

from __future__ import annotations

from npc import config as _config
from npc import verify as _verify


# ============================================================
# 1. 配置层：安全默认值 + 显式解析（tasks 1.1–1.5）
# ============================================================


def test_spec_config_defaults_when_unconfigured():
    """未配置 [spec_writer]/[spec_review] 时的 dataclass 默认值。"""
    cfg = _config.Config()
    assert cfg.spec_writer.effective_backend == "claude"
    # None = 未显式配置；claude writer 的实效默认引擎为 codex
    assert cfg.spec_review.engine is None
    assert _verify.resolve_review_engine("claude", cfg.spec_review.engine) == "codex"
    assert _verify.check_routing(cfg) == []


def test_spec_config_defaults_via_toml_load_without_spec_sections(tmp_path):
    """.npc/config.toml 存在但不含 [spec_writer]/[spec_review] 段 → 安全默认值。"""
    npc_dir = tmp_path / ".npc"
    npc_dir.mkdir()
    (npc_dir / "config.toml").write_text('[review]\nengine = "codex"\n')
    cfg = _config.load_config(tmp_path)
    assert cfg.spec_writer.effective_backend == "claude"
    # [spec_review] 段缺失 → engine=None（未显式配置），实效默认 codex
    assert cfg.spec_review.engine is None
    assert _verify.resolve_review_engine("claude", cfg.spec_review.engine) == "codex"
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert not any(r.startswith("spec_") for r in rules)


def test_spec_config_explicit_values_parsed_from_toml(tmp_path):
    """显式配置 [spec_writer]/[spec_review] 被正确解析。"""
    npc_dir = tmp_path / ".npc"
    npc_dir.mkdir()
    (npc_dir / "config.toml").write_text(
        '[spec_writer]\nbackend = "mimo"\n\n[spec_review]\nengine = "codex"\n'
    )
    cfg = _config.load_config(tmp_path)
    assert cfg.spec_writer.effective_backend == "mimo"
    assert cfg.spec_review.engine == "codex"


def test_spec_writer_config_rejects_unknown_backend():
    """SpecWriterConfig 自身对非法 backend 快速失败（构造期即拒）。"""
    try:
        _config.SpecWriterConfig(backend="gpt-9")
    except _config.ConfigError as e:
        assert "gpt-9" in str(e)
    else:
        raise AssertionError("SpecWriterConfig 未拒绝非法 backend")


def test_spec_review_config_rejects_unknown_engine():
    """SpecReviewConfig 自身对非法 engine 快速失败（构造期即拒）。"""
    try:
        _config.SpecReviewConfig(engine="bard")
    except _config.ConfigError as e:
        assert "bard" in str(e)
    else:
        raise AssertionError("SpecReviewConfig 未拒绝非法 engine")


def test_spec_writer_config_no_dispatch_field():
    """SpecWriterConfig MUST NOT 含 dispatch/phase 字段（非目标，tasks 4.5）。"""
    field_names = {f for f in _config.SpecWriterConfig.__dataclass_fields__}
    assert "dispatch" not in field_names
    assert "phase" not in field_names
    assert "phase_backends" not in field_names
    assert "phase_dispatches" not in field_names


# ============================================================
# 2. 路由不变量：check_routing 新增 spec_* 规则（tasks 2.1–2.14）
# ============================================================


def _spec_cfg(
    *,
    writer_backend: str | None = "claude",
    writer_bin: str | None = None,
    writer_model: str | None = None,
    review_engine: str = "codex",
    review_claude_bin: str | None = None,
    review_claude_model: str | None = None,
) -> _config.Config:
    """构造仅关注 spec 侧的 Config；coder/review 保持默认良性组合（claude/codex）。"""
    return _config.Config(
        spec_writer=_config.SpecWriterConfig(
            backend=writer_backend, bin=writer_bin, model=writer_model
        ),
        spec_review=_config.SpecReviewConfig(
            engine=review_engine,
            claude_bin=review_claude_bin,
            claude_model=review_claude_model,
        ),
    )


def test_spec_backend_unsupported_violation():
    # 2.1：非法 spec_writer.backend 通过绕过 __post_init__ 校验模拟（对应既有
    # test_routing_mimo_in_review_engine_violation 的手法，验证 check_routing 兜底）
    cfg = _spec_cfg()
    object.__setattr__(cfg.spec_writer, "backend", "gpt-9")
    violations = _verify.check_routing(cfg)
    matches = [v for v in violations if v["rule"] == "spec_backend_unsupported"]
    assert len(matches) == 1
    assert "gpt-9" in matches[0]["detail"]


def test_spec_engine_unsupported_violation():
    # 2.2
    cfg = _spec_cfg()
    object.__setattr__(cfg.spec_review, "engine", "bard")
    violations = _verify.check_routing(cfg)
    matches = [v for v in violations if v["rule"] == "spec_engine_unsupported"]
    assert len(matches) == 1
    assert "bard" in matches[0]["detail"]


def test_spec_gen_not_orthogonal_claude_same_bin_model():
    # 2.3
    cfg = _spec_cfg(
        writer_backend="claude",
        writer_bin="claude",
        writer_model="claude-opus-4-8",
        review_engine="claude",
        review_claude_bin="claude",
        review_claude_model="claude-opus-4-8",
    )
    matches = [
        v for v in _verify.check_routing(cfg) if v["rule"] == "spec_gen_not_orthogonal"
    ]
    assert len(matches) == 1


def test_spec_gen_not_orthogonal_both_mimo():
    # 2.4：SUPPORTED_ENGINES 目前不含 "mimo"（同既有 mimo_exec_only 测试的手法，
    # 见 test_verify.py::test_routing_mimo_in_review_engine_violation 的注释），
    # 用 object.__setattr__ 绕过 __post_init__ 校验模拟"双方均为 mimo"的同源形态。
    cfg = _spec_cfg(writer_backend="mimo", review_engine="codex")
    object.__setattr__(cfg.spec_review, "engine", "mimo")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_gen_not_orthogonal" in rules


def test_spec_gen_not_orthogonal_both_codex():
    # 2.4b
    cfg = _spec_cfg(writer_backend="codex", review_engine="codex")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_gen_not_orthogonal" in rules


def test_spec_gen_not_orthogonal_claude_diff_model_ok():
    # 2.5：负向 —— 同为 claude 但 model 不同
    cfg = _spec_cfg(
        writer_backend="claude",
        writer_bin="claude",
        writer_model="claude-sonnet",
        review_engine="claude",
        review_claude_bin="claude",
        review_claude_model="claude-opus-4-8",
    )
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_gen_not_orthogonal" not in rules


def test_spec_gen_not_orthogonal_default_config_ok():
    # 2.6：负向 —— 默认配置（claude writer / codex review）
    cfg = _spec_cfg(writer_backend="claude", review_engine="codex")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_gen_not_orthogonal" not in rules


def test_spec_mimo_exec_only_engine_mimo():
    # 2.7：同上，engine="mimo" 需绕过 __post_init__ 校验（SUPPORTED_ENGINES 尚不含 mimo）
    cfg = _spec_cfg(writer_backend="claude", review_engine="codex")
    object.__setattr__(cfg.spec_review, "engine", "mimo")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_mimo_exec_only" in rules


def test_spec_mimo_exec_only_claude_model_carries_mimo_merged_single():
    # 2.8：多条件合并为单条
    cfg = _spec_cfg(
        writer_backend="claude",
        review_engine="claude",
        review_claude_model="mimo-v2.5-pro",
    )
    matches = [
        v for v in _verify.check_routing(cfg) if v["rule"] == "spec_mimo_exec_only"
    ]
    assert len(matches) == 1


def test_spec_writer_mimo_review_codex_benign():
    # 2.9：负向 —— spec_writer=mimo, spec_review=codex 既不同源也不 exec_only
    # （单独校验此规则集合，不含 spec_mimo_in_session，因为那是另一条规则）
    cfg = _spec_cfg(writer_backend="mimo", review_engine="codex")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_mimo_exec_only" not in rules
    assert "spec_gen_not_orthogonal" not in rules


def test_spec_mimo_in_session_writer_mimo():
    # 2.10
    cfg = _spec_cfg(writer_backend="mimo", review_engine="codex")
    matches = [
        v for v in _verify.check_routing(cfg) if v["rule"] == "spec_mimo_in_session"
    ]
    assert len(matches) == 1
    assert "in-session" in matches[0]["detail"]


def test_spec_mimo_in_session_writer_claude_ok():
    # 2.11：负向
    cfg = _spec_cfg(writer_backend="claude", review_engine="codex")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "spec_mimo_in_session" not in rules


# ============================================================
# 2b. 修既有 codex/codex 同源漏洞（tasks 2b.1–2b.6）
# ============================================================


def _coder_review_cfg(
    *,
    coder_backend: str = "claude",
    coder_bin: str | None = None,
    coder_model: str | None = None,
    review_engine: str = "codex",
    review_claude_bin: str | None = None,
    review_claude_model: str | None = None,
) -> _config.Config:
    return _config.Config(
        review=_config.ReviewEngineConfig(
            engine=review_engine,
            claude_bin=review_claude_bin,
            claude_model=review_claude_model,
        ),
        coder=_config.CoderConfig(
            backend=coder_backend,
            bin=coder_bin,
            model=coder_model,
        ),
    )


def test_gen_not_orthogonal_codex_codex_bug_fixed():
    # 2b.1：既有漏洞修复 —— 此前 RED，现在 GREEN
    cfg = _coder_review_cfg(coder_backend="codex", review_engine="codex")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "gen_not_orthogonal" in rules


def test_gen_not_orthogonal_claude_same_bin_model_regression():
    # 2b.3：回归 —— 既有 claude/claude 同 bin 同 model 判定未被新形态污染
    cfg = _coder_review_cfg(
        coder_backend="claude",
        coder_bin="claude",
        coder_model="claude-opus-4-8",
        review_engine="claude",
        review_claude_bin="claude",
        review_claude_model="claude-opus-4-8",
    )
    matches = [v for v in _verify.check_routing(cfg) if v["rule"] == "gen_not_orthogonal"]
    assert len(matches) == 1


def test_mimo_exec_only_regression():
    # 2b.4：回归 —— review.engine == mimo 仍含 mimo_exec_only（绕过校验，同
    # test_verify.py::test_routing_mimo_in_review_engine_violation 的手法）
    cfg = _coder_review_cfg(coder_backend="claude", review_engine="codex")
    object.__setattr__(cfg.review, "engine", "mimo")
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "mimo_exec_only" in rules


def test_mimo_in_session_regression():
    # 2b.5：回归 —— coder 某 phase 为 mimo + in-session 仍含 mimo_in_session，
    # detail 语义不变
    cfg = _config.Config(
        coder=_config.CoderConfig(backend="mimo", dispatch="in-session"),
    )
    matches = [v for v in _verify.check_routing(cfg) if v["rule"] == "mimo_in_session"]
    assert len(matches) >= 1
    assert "mimo" in matches[0]["detail"]
    assert "headless" in matches[0]["detail"]


# ============================================================
# 3. 回归防护：两对规则彼此独立（tasks 3.1–3.4）
# ============================================================


def test_coder_review_orthogonal_violation_no_spec_pollution():
    # 3.1：coder/review 同源 + spec 段未配置 → 含 gen_not_orthogonal，
    # 且不含任何 spec_ 前缀的项
    cfg = _coder_review_cfg(
        coder_backend="claude",
        coder_bin="claude",
        coder_model="claude-opus-4-8",
        review_engine="claude",
        review_claude_bin="claude",
        review_claude_model="claude-opus-4-8",
    )
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "gen_not_orthogonal" in rules
    assert not any(r.startswith("spec_") for r in rules)


def test_both_pairs_orthogonal_violations_independent():
    # 3.2：两侧同时同源 → 同时含 gen_not_orthogonal 与 spec_gen_not_orthogonal
    # （coder/review 用 claude 同 bin+model 形态，spec_writer/spec_review 用
    # codex/codex 形态，证明两对规则各自独立判定、互不覆盖）
    cfg = _config.Config(
        coder=_config.CoderConfig(
            backend="claude", bin="claude", model="claude-opus-4-8"
        ),
        review=_config.ReviewEngineConfig(
            engine="claude", claude_bin="claude", claude_model="claude-opus-4-8"
        ),
        spec_writer=_config.SpecWriterConfig(backend="codex"),
        spec_review=_config.SpecReviewConfig(engine="codex"),
    )
    rules = {v["rule"] for v in _verify.check_routing(cfg)}
    assert "gen_not_orthogonal" in rules
    assert "spec_gen_not_orthogonal" in rules


def test_run_routing_exit_code_semantics_unchanged(tmp_path, make_args, monkeypatch):
    # 3.4：npc verify routing 的退出码语义未变（有 violation → 非零；无 → 0）
    import pytest

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(_verify, "_resolve_repo_root", lambda args: repo)

    monkeypatch.setattr(_verify, "_load_cfg", lambda repo_root: _config.Config())
    _verify.run_routing(make_args())  # 无 violation → 不抛，正常返回（退出码 0）

    bad_cfg = _config.Config(spec_writer=_config.SpecWriterConfig(backend="mimo"))
    monkeypatch.setattr(_verify, "_load_cfg", lambda repo_root: bad_cfg)
    with pytest.raises(SystemExit) as ei:
        _verify.run_routing(make_args())
    assert ei.value.code == 1
