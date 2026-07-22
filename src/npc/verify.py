"""npc verify —— 把"不裸信自报"做成确定性笼子。

两个子命令：

- ``npc verify tests``：真实复跑测试（质量门）。绝不读 LLM 的 RESULT 自报，
  而是在 repo_root 实际执行测试命令、捕获退出码与输出末尾，emit 结构化判定。
  这是"不裸信 RESULT"硬轨的家。

- ``npc verify routing``：把路由不变量编进代码（生成⊥验证 + MiMo 只许执行）。
  纯函数 :func:`check_routing` 校验 coder/review 后端配置，发现"自己评自己"
  或"MiMo 越权到 review"等违规则报 violation。
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path

from . import _io
from . import config as _config
from . import paths as _paths


# 输出末尾保留的行数（stdout/stderr 合并后取尾部）
TAIL_LINES = 30

# ============================================================
# 共享：repo 定位 + config 加载（便于测试 monkeypatch）
# ============================================================


def _resolve_repo_root(args: argparse.Namespace) -> Path:
    """定位 repo_root。verify 只需 git 仓库（无需 active run / npc init）：

    优先 git toplevel；仅当 cwd 不在 git 仓库时回退 load_paths（兼容显式 --run-ts 调试）。
    """
    try:
        return _paths.detect_repo_root()
    except _paths.PathsError:
        return _paths.load_paths(args).repo_root


def _load_cfg(repo_root: Path) -> _config.Config:
    """加载 npc 配置；失败抛 ConfigError。"""
    return _config.load_config(repo_root)


# ============================================================
# 子命令 1：npc verify tests
# ============================================================


def _has_make_test_target(makefile: Path) -> bool:
    """判断 Makefile 是否含 ``test:`` 目标（行首形如 ``test:`` 或 ``test :``）。"""
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        # 只认行首（列 0）的 ``test:`` / ``test :``，避免缩进的配方行误判。
        if line.startswith("test:") or line.startswith("test :"):
            return True
    return False


def _package_json_has_test_script(package_json: Path) -> bool:
    """判断 package.json 的 scripts.test 是否存在且非空。"""
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return False
    test = scripts.get("test")
    return isinstance(test, str) and bool(test.strip())


def resolve_test_cmd(repo_root: Path, cfg: _config.Config) -> str | None:
    """解析测试命令。纯函数，便于单测。

    优先级：
    1. ``cfg.verify.test`` 显式覆盖。
    2. Python：有 ``pyproject.toml`` 或 ``pytest.ini`` 或 ``tests/`` 目录
       → ``python3 -m pytest -q``。
    3. Node：有 ``package.json`` 且 ``scripts.test`` 非空 → ``npm test``。
    4. Make：有 ``Makefile`` 且含 ``test:`` 目标 → ``make test``。
    5. 都没有 → ``None``。
    """
    if cfg.verify.test:
        return cfg.verify.test

    if (
        (repo_root / "pyproject.toml").is_file()
        or (repo_root / "pytest.ini").is_file()
        or (repo_root / "tests").is_dir()
    ):
        return "python3 -m pytest -q"

    pkg = repo_root / "package.json"
    if pkg.is_file() and _package_json_has_test_script(pkg):
        return "npm test"

    makefile = repo_root / "Makefile"
    if makefile.is_file() and _has_make_test_target(makefile):
        return "make test"

    return None


def _tail(stdout: str, stderr: str, lines: int = TAIL_LINES) -> str:
    """合并 stdout/stderr 并取末尾 ``lines`` 行。"""
    combined = (stdout or "") + (stderr or "")
    rows = combined.splitlines()
    return "\n".join(rows[-lines:])


def run_tests_result(
    repo_root: Path, cfg: _config.Config, runner=subprocess.run
) -> dict:
    """record 阶段内部调用：对 coder 自报 tests=pass 做真实复跑。

    返回 dict（不 emit、不 SystemExit）：
    - ``{"no_command": True}``：探测不到测试命令，降级不阻塞。
    - ``{"passed": True, "cmd": str, "tail": str}``：复跑通过。
    - ``{"passed": False, "cmd": str, "tail": str}``：复跑失败。
    """
    cmd = resolve_test_cmd(repo_root, cfg)
    if cmd is None:
        return {"no_command": True}

    argv = shlex.split(cmd)
    proc = runner(
        argv,
        shell=False,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    passed = proc.returncode == 0
    return {
        "no_command": False,
        "passed": passed,
        "cmd": cmd,
        "tail": _tail(proc.stdout or "", proc.stderr or ""),
    }


def run_tests(args: argparse.Namespace, runner=subprocess.run) -> None:
    """``npc verify tests``：在 repo_root 真实复跑测试命令。

    ``runner`` 可注入（默认 :func:`subprocess.run`），测试用假 runner。
    退出码：passed → 0（正常返回）；失败 → 1；无命令/定位失败 → 3。
    """
    try:
        repo_root = _resolve_repo_root(args)
    except _paths.PathsError as e:
        _io.emit_error("env_missing", f"未能定位 repo_root：{e}", exit_code=3)
        return

    try:
        cfg = _load_cfg(repo_root)
    except _config.ConfigError as e:
        _io.emit_error("config_error", f"配置加载失败：{e}", exit_code=1)
        return

    cmd = resolve_test_cmd(repo_root, cfg)
    if cmd is None:
        _io.emit_error(
            "no_test_command",
            f"未能为 repo 探测到测试命令（无 pyproject/pytest.ini/tests/package.json/Makefile）：{repo_root}",
            exit_code=3,
        )
        return

    # 不裸信可写的 cfg.verify.test：用 shlex.split → argv 列表 + shell=False 执行，
    # 杜绝命令注入（``; rm -rf`` 等元字符不会被 shell 解释）。
    argv = shlex.split(cmd)
    proc = runner(
        argv,
        shell=False,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    passed = proc.returncode == 0
    _io.emit(
        {
            "ok": passed,
            "cmd": cmd,
            "exit_code": proc.returncode,
            "passed": passed,
            "tail": _tail(proc.stdout or "", proc.stderr or ""),
        }
    )
    if not passed:
        raise SystemExit(1)


# ============================================================
# 子命令 2：npc verify routing
# ============================================================


def _contains_mimo(value: str | None) -> bool:
    return value is not None and "mimo" in value.lower()


def check_routing(
    cfg: _config.Config,
    *,
    coder_backend_override: str | None = None,
    spec_writer_backend_override: str | None = None,
) -> list[dict]:
    """校验路由不变量，返回 violations 列表（纯函数）。

    每项 ``{"rule", "detail"}``。规则：

    coder ⊥ review（既有）：

    1. ``backend_unsupported`` / ``engine_unsupported``：coder.backend 与
       review.engine 必须在各自 SUPPORTED 列表（backend 用 effective_backend）。
    2. ``gen_not_orthogonal``：coder 与 review 解析到同一执行身份 → 等于自己评
       自己，违反 生成⊥验证。覆盖 (a) 都是 claude 且同 bin+model；(b) 都是
       mimo；(c) 都是 codex（change ``spec-routing-invariant`` 补的既有漏洞）。
    3. ``mimo_exec_only``：review 路由到 MiMo（engine 含 'mimo'，或 claude_model
       / claude_bin 含 'mimo'）→ 违反 MiMo 仅限 coder。合并为单条 violation。
    4. ``mimo_in_session``：coder 某 phase 后端为 mimo 且 dispatch 为
       in-session → 违反 MiMo 只许 headless。

    spec_writer ⊥ spec_review（change ``spec-routing-invariant`` 新增，与上述
    四条同构，spec 侧独立判定、互不影响）：

    5. ``spec_backend_unsupported`` / ``spec_engine_unsupported``：同 1，作用
       于 spec_writer.effective_backend / spec_review.engine。
    6. ``spec_gen_not_orthogonal``：同 2，覆盖 (a) claude 同 bin+model；(b)
       mimo/mimo；(c) codex/codex。
    7. ``spec_mimo_exec_only``：同 3，作用于 spec_review。
    8. ``spec_mimo_in_session``：spec 生成恒 in-session（无 per-phase dispatch
       配置），故 spec_writer.effective_backend == 'mimo' 即违规。
    """
    violations: list[dict] = []
    coder = cfg.coder
    review = cfg.review
    effective_backend = coder_backend_override or coder.effective_backend

    # 规则 1：后端有效性（用 effective_backend，None 解析为 claude）
    if effective_backend not in _config.SUPPORTED_CODER_BACKENDS:
        violations.append(
            {
                "rule": "backend_unsupported",
                "detail": f"coder.backend={effective_backend!r} 不在支持列表 {_config.SUPPORTED_CODER_BACKENDS}",
            }
        )
    # engine=None 表示"未显式配置"，合法——解析默认由 resolve_review_engine
    # 按生成身份给出（结构上不可能落在支持列表之外，也不可能自评）。
    if review.engine is not None and review.engine not in _config.SUPPORTED_ENGINES:
        violations.append(
            {
                "rule": "engine_unsupported",
                "detail": f"review.engine={review.engine!r} 不在支持列表 {_config.SUPPORTED_ENGINES}",
            }
        )

    # 规则 2/3 用解析后的实效引擎判定（显式配置原样透传，None 解析为
    # backend-aware 默认），使 `npc verify routing` 在未显式配置时也校验
    # 真实将要执行的路由。
    resolved_engine = resolve_review_engine(effective_backend, review.engine)

    # 规则 2：gen ⊥ verify（coder 与 review 解析到同一执行身份 = 自己评自己）
    same_claude_identity = (
        effective_backend == "claude"
        and resolved_engine == "claude"
        and coder.bin == review.claude_bin
        and coder.model == review.claude_model
    )
    both_mimo = effective_backend == "mimo" and resolved_engine == "mimo"
    both_codex = effective_backend == "codex" and resolved_engine == "codex"
    if same_claude_identity or both_mimo or both_codex:
        violations.append(
            {
                "rule": "gen_not_orthogonal",
                "detail": "coder 与 review 解析到同一执行身份，等于自己评自己",
            }
        )

    # （原规则 2b kimi_review_not_claude 已废除：change
    # review-routing-backend-aware——"Kimi 产物只许 Claude 评"是默认值偏好而
    # 非结构性不变量，显式指定任意支持引擎均放行，只受 gen⊥verify 与
    # mimo exec-only 约束。）

    # 规则 3：MiMo 只许执行（无条件顶层挡：engine 或 claude_bin/model 含 mimo）→ 单条
    if (
        _contains_mimo(resolved_engine)
        or _contains_mimo(review.claude_model)
        or _contains_mimo(review.claude_bin)
    ):
        violations.append(
            {
                "rule": "mimo_exec_only",
                "detail": "review 路由含 MiMo（engine/claude_bin/claude_model 含 'mimo'），违反 MiMo 仅限 coder",
            }
        )

    # 规则 4：in-session 绝不与 mimo 同源（mimo 只许 headless）
    _check_mimo_in_session(cfg, violations)

    # 规则 5-8：spec_writer ⊥ spec_review（与上述四条同构，独立判定）
    _check_spec_backend_engine_unsupported(
        cfg, violations, effective_backend=spec_writer_backend_override
    )
    _check_spec_gen_not_orthogonal(
        cfg, violations, effective_backend=spec_writer_backend_override
    )
    _check_spec_mimo_exec_only(cfg, violations)
    _check_spec_mimo_in_session(cfg, violations)

    return violations


def resolve_review_engine(
    generator_backend: str,
    configured_engine: str | None,
    *,
    engine_override: str | None = None,
) -> str:
    """review 引擎的 backend-aware 确定性选择（纯函数，review/spec pipeline 共用）。

    优先级：显式 override > 显式配置 ``engine`` > 生成源 backend-aware 默认。

    1. ``engine_override`` 非空 → 原样返回。
    2. ``configured_engine`` 非 ``None``（TOML 显式配置）→ 原样返回。
    3. 均未显式指定 → 按生成身份取默认：生成源为 codex → ``"claude"``；
       其它生成源（claude / kimi / mimo）→ ``"codex"``。

    本函数绝不静默重路由：显式值（override 或配置）无条件透传，其合法性
    （生成⊥验证正交、mimo exec-only、支持列表）交给 :func:`check_routing`
    判定并可观察地拒绝。backend-aware 默认在结构上不可能自评（codex 生成
    配 claude 评、其余生成配 codex 评），无需二次判定。
    """
    if engine_override:
        return engine_override
    if configured_engine is not None:
        return configured_engine
    return "claude" if generator_backend == "codex" else "codex"


def _check_mimo_in_session(cfg: _config.Config, violations: list[dict]) -> None:
    """校验 mimo 后端不得使用 in-session 分发（纯函数，原地追加 violation）。

    遍历所有可能的 phase（implement、fix）校验全局 dispatch 与 per-phase dispatch。
    """
    coder = cfg.coder
    phases_to_check = ["implement", "fix"]

    for phase in phases_to_check:
        resolved_backend = coder.backend_for_phase(phase) or coder.effective_backend
        if resolved_backend != "mimo":
            continue
        # backend 是 mimo，检查该 phase 的 dispatch
        resolved_dispatch = coder.dispatch_for_phase(phase, resolved_backend)
        if resolved_dispatch == "in-session":
            violations.append(
                {
                    "rule": "mimo_in_session",
                    "detail": (
                        f"coder phase={phase!r} 后端=mimo 但 dispatch=in-session，"
                        "违反 MiMo 只许 headless"
                    ),
                }
            )


def _check_spec_backend_engine_unsupported(
    cfg: _config.Config,
    violations: list[dict],
    *,
    effective_backend: str | None = None,
) -> None:
    """校验 spec_writer/spec_review 后端有效性（纯函数，原地追加 violation）。

    与既有规则 1（``backend_unsupported`` / ``engine_unsupported``）同构。
    """
    spec_writer = cfg.spec_writer
    spec_review = cfg.spec_review
    effective_backend = effective_backend or spec_writer.effective_backend

    if effective_backend not in _config.SUPPORTED_CODER_BACKENDS:
        violations.append(
            {
                "rule": "spec_backend_unsupported",
                "detail": (
                    f"spec_writer.backend={effective_backend!r} 不在支持列表 "
                    f"{_config.SUPPORTED_CODER_BACKENDS}"
                ),
            }
        )
    # None = 未显式配置，合法（同非 spec 侧口径）。
    if (
        spec_review.engine is not None
        and spec_review.engine not in _config.SUPPORTED_ENGINES
    ):
        violations.append(
            {
                "rule": "spec_engine_unsupported",
                "detail": (
                    f"spec_review.engine={spec_review.engine!r} 不在支持列表 "
                    f"{_config.SUPPORTED_ENGINES}"
                ),
            }
        )


def _check_spec_gen_not_orthogonal(
    cfg: _config.Config,
    violations: list[dict],
    *,
    effective_backend: str | None = None,
) -> None:
    """校验 spec_writer 与 spec_review 是否解析到同一执行身份（纯函数）。

    与既有规则 2（``gen_not_orthogonal``）同构，覆盖三种同源形态：
    (a) 双方均为 claude 且 bin+model 相同；(b) 双方均为 mimo；(c) 双方均为 codex。
    """
    spec_writer = cfg.spec_writer
    spec_review = cfg.spec_review
    effective_backend = effective_backend or spec_writer.effective_backend

    resolved_engine = resolve_review_engine(effective_backend, spec_review.engine)
    same_claude_identity = (
        effective_backend == "claude"
        and resolved_engine == "claude"
        and spec_writer.bin == spec_review.claude_bin
        and spec_writer.model == spec_review.claude_model
    )
    both_mimo = effective_backend == "mimo" and resolved_engine == "mimo"
    both_codex = effective_backend == "codex" and resolved_engine == "codex"
    if same_claude_identity or both_mimo or both_codex:
        violations.append(
            {
                "rule": "spec_gen_not_orthogonal",
                "detail": "spec_writer 与 spec_review 解析到同一执行身份，等于自己评自己",
            }
        )

    # （原 spec_kimi_review_not_claude 已废除，同非 spec 侧规则 2b：change
    # review-routing-backend-aware。）


def _check_spec_mimo_exec_only(cfg: _config.Config, violations: list[dict]) -> None:
    """校验 spec_review 是否路由到 MiMo（纯函数）。

    与既有规则 3（``mimo_exec_only``）同构，多条件合并为单条 violation。
    """
    spec_review = cfg.spec_review
    resolved_engine = resolve_review_engine(
        cfg.spec_writer.effective_backend, spec_review.engine
    )
    if (
        _contains_mimo(resolved_engine)
        or _contains_mimo(spec_review.claude_model)
        or _contains_mimo(spec_review.claude_bin)
    ):
        violations.append(
            {
                "rule": "spec_mimo_exec_only",
                "detail": (
                    "spec_review 路由含 MiMo（engine/claude_bin/claude_model 含 "
                    "'mimo'），违反 MiMo 仅限执行"
                ),
            }
        )


def _check_spec_mimo_in_session(cfg: _config.Config, violations: list[dict]) -> None:
    """校验 spec_writer 是否路由到 MiMo（纯函数）。

    spec 生成的分发方式恒为 in-session（无 per-phase dispatch 配置，见
    design.md D2），故 ``spec_writer.effective_backend == "mimo"`` 本身即蕴含
    「mimo + in-session」，与既有规则 4（``mimo_in_session``）语义一致，
    但无需像它一样遍历 phase/dispatch。
    """
    spec_writer = cfg.spec_writer
    if spec_writer.effective_backend == "mimo":
        violations.append(
            {
                "rule": "spec_mimo_in_session",
                "detail": (
                    "spec_writer 后端=mimo 但 spec 生成恒 in-session，"
                    "违反 MiMo 只许 headless"
                ),
            }
        )


def run_routing(args: argparse.Namespace) -> None:
    """``npc verify routing``：emit 路由检查结果。

    退出码：无 violation → 0（正常返回）；有 → 1；config 加载失败 → 1。
    """
    try:
        repo_root = _resolve_repo_root(args)
    except _paths.PathsError as e:
        _io.emit_error("env_missing", f"未能定位 repo_root：{e}", exit_code=3)
        return

    try:
        cfg = _load_cfg(repo_root)
    except _config.ConfigError as e:
        _io.emit_error("config_error", f"配置加载失败：{e}", exit_code=1)
        return

    violations = check_routing(cfg)
    _io.emit(
        {
            "ok": len(violations) == 0,
            "coder_backend": cfg.coder.effective_backend,
            # 报告解析后的实效引擎（None=未显式配置时为 backend-aware 默认）
            "review_engine": resolve_review_engine(
                cfg.coder.effective_backend, cfg.review.engine
            ),
            "violations": violations,
        }
    )
    if violations:
        raise SystemExit(1)
