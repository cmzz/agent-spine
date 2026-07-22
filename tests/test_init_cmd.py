"""init_cmd 模块测试。

需要 chdir 到 fake_repo + 覆盖 Path.home 到 fake_home，否则会污染真实环境。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from npc import init_cmd as _init
from npc import git_ops as _git_ops


@pytest.fixture
def init_env(monkeypatch, fake_repo: Path, fake_home: Path):
    """切到 fake_repo 工作目录 + 把 Path.home 替换为 fake_home。"""
    monkeypatch.chdir(fake_repo)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    return fake_repo, fake_home


@pytest.fixture
def worktree_env(monkeypatch, tmp_path: Path):
    """worktree 测试环境：使用短路径 repo + home，避免 proj_key 超出文件名长度限制。"""
    import tempfile, shutil

    # 在 /private/tmp 下建短路径，确保 proj_key 不超过 255 字符
    base = Path(tempfile.mkdtemp(prefix="wt-"))
    repo = base / "r"
    home = base / "h"
    repo.mkdir()
    home.mkdir()

    # 初始化 git 仓库
    import subprocess as sp
    sp.run(["git", "init", "-q"], cwd=repo, check=True)
    sp.run(["git", "config", "user.email", "test@local"], cwd=repo, check=True)
    sp.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# test\n")
    sp.run(["git", "add", "."], cwd=repo, check=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    monkeypatch.chdir(repo)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    yield repo, home
    shutil.rmtree(base, ignore_errors=True)


def test_ensure_portable_timeout_creates(tmp_path):
    target, created = _init.ensure_portable_timeout(home=tmp_path)
    assert created is True
    assert target.exists()
    assert target.stat().st_mode & 0o111  # executable
    content = target.read_text()
    assert "portable-timeout" in content


def test_ensure_portable_timeout_idempotent(tmp_path):
    _init.ensure_portable_timeout(home=tmp_path)
    target, created = _init.ensure_portable_timeout(home=tmp_path)
    assert created is False


def test_init_run_basic(init_env, capsys, make_args):
    """--no-worktree 就地行为（旧行为兼容）。"""
    _, home = init_env
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert payload["repo_root"].endswith("/repo")
    assert payload["needs_resume"] is False
    assert payload["mode"] == "interactive"
    # 自举产物
    assert (home / "task_log" / ".new-plan-review-schema.json").exists()
    assert (home / ".local" / "bin" / "portable-timeout").exists()


def test_init_run_auto_mode_label(init_env, capsys, make_args):
    args = make_args(auto=True, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["mode"] == "auto"


def test_init_codex_runtime_is_persisted(init_env, capsys, make_args):
    args = make_args(
        auto=False,
        fresh=True,
        shell_exports=False,
        no_worktree=True,
        runtime_host="codex",
    )
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["runtime_host"] == "codex"
    run_json = json.loads(Path(payload["run_json"]).read_text(encoding="utf-8"))
    assert run_json["runtime_host"] == "codex"


def test_init_kimi_runtime_is_persisted(init_env, capsys, make_args):
    args = make_args(
        auto=False,
        fresh=True,
        shell_exports=False,
        no_worktree=True,
        runtime_host="kimi",
    )
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["runtime_host"] == "kimi"
    run_json = json.loads(Path(payload["run_json"]).read_text(encoding="utf-8"))
    assert run_json["runtime_host"] == "kimi"


def test_init_shell_exports_format(init_env, capsys, make_args):
    args = make_args(auto=False, fresh=True, shell_exports=True, no_worktree=True)
    _init.run(args)
    out = capsys.readouterr().out
    assert "export NPC_REPO_ROOT=" in out
    assert "export NPC_STATE_JSON=" in out
    assert "export NPC_NEEDS_RESUME='false'" in out
    assert "export NPC_FRESH='true'" in out
    assert "export NPC_RUNTIME_HOST='claude'" in out


def test_init_resume_detection(init_env, capsys, make_args):
    """有 in-progress 旧 run 时，init 应汇报 needs_resume=true 并复用其 run_ts。"""
    repo, home = init_env
    proj_key = "-" + str(repo).lstrip("/").replace("/", "-")
    task_log = home / "task_log" / proj_key
    task_log.mkdir(parents=True)
    old_state = task_log / "2026-05-01-1000-plan-state.json"
    old_state.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_ts": "2026-05-01-1000",
                "status": "in-progress",
                "progress": [],
            }
        )
    )

    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is True
    assert payload["resume_state_json"] == str(old_state)
    assert payload["run_ts"] == "2026-05-01-1000"


def test_init_fresh_ignores_in_progress(init_env, capsys, make_args):
    repo, home = init_env
    proj_key = "-" + str(repo).lstrip("/").replace("/", "-")
    task_log = home / "task_log" / proj_key
    task_log.mkdir(parents=True)
    old_state = task_log / "2026-05-01-1000-plan-state.json"
    old_state.write_text(json.dumps({"status": "in-progress", "run_ts": "old"}))

    args = make_args(auto=False, fresh=True, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is False
    assert payload["fresh"] is True
    # 新 run_ts 不会等于 "old"
    assert payload["run_ts"] != "old"


def test_init_writes_run_and_active_json(init_env, capsys, make_args):
    """v0.2: init 落 run.json 与 active.json，子命令可不依赖 env 自包含 resolve。"""
    _, home = init_env
    args = make_args(auto=False, fresh=True, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    run_json = Path(payload["run_json"])
    active_json = Path(payload["active_json"])
    assert run_json.is_file()
    assert active_json.is_file()
    rj = json.loads(run_json.read_text())
    aj = json.loads(active_json.read_text())
    assert rj["run_ts"] == payload["run_ts"]
    assert rj["state_json"] == payload["state_json"]
    assert aj["current_run_ts"] == payload["run_ts"]


def test_init_shell_exports_emits_deprecation(init_env, capsys, make_args):
    args = make_args(auto=False, fresh=True, shell_exports=True, no_worktree=True)
    _init.run(args)
    err = capsys.readouterr().err
    assert "deprecated" in err.lower()


def test_init_non_git_repo(monkeypatch, tmp_path, capsys, make_args):
    """非 git 目录应报 exit 3。"""
    non_repo = tmp_path / "plain"
    non_repo.mkdir()
    monkeypatch.chdir(non_repo)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    with pytest.raises(SystemExit) as ei:
        _init.run(args)
    assert ei.value.code == 3
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["error"] == "not_git_repo"


# ============================================================
# 新测试：worktree 功能（task 5.1 ~ 5.5）
# ============================================================


def _make_mock_runner(
    worktree_list_output: str = "",
    worktree_add_rc: int = 0,
    worktree_add_stderr: str = "",
    current_branch: str = "main",
):
    """构造可注入的 runner mock，模拟 git worktree 操作。"""

    def runner(cmd, cwd=None, capture_output=False, text=False, env=None, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""

        if "worktree" in cmd and "list" in cmd:
            result.stdout = worktree_list_output
        elif "worktree" in cmd and "add" in cmd:
            result.returncode = worktree_add_rc
            result.stderr = worktree_add_stderr
            if worktree_add_rc == 0:
                # 模拟 git worktree add：创建目录（路径在 cmd 中）
                # cmd = ["git", "worktree", "add", "-b", branch, path, base_ref]
                path_str = cmd[5]
                Path(path_str).mkdir(parents=True, exist_ok=True)
        elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
            result.stdout = current_branch + "\n"
        elif "rev-parse" in cmd and "--show-toplevel" in cmd:
            result.stdout = cwd + "\n"
        return result

    return runner


def test_init_worktree_creates_branch_and_dirs(worktree_env, capsys, make_args):
    """默认 init（无 --no-worktree）应创建 worktree 目录 + spine 分支，emit 字段齐。

    Task 5.1: 默认创建 worktree + 分支，Paths.repo_root=worktree，emit 字段齐。
    """
    repo, home = worktree_env
    mock_runner = _make_mock_runner(
        worktree_list_output="",  # 无既有 spine worktree
        worktree_add_rc=0,
        current_branch="main",
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["worktree_root"] is not None
    assert payload["spine_branch"] is not None
    assert payload["spine_branch"].startswith("spine/")
    assert payload["canonical_proj_key"] is not None
    assert payload["canonical_repo_root"] is not None
    # repo_root 应等于 worktree_root（不是主 checkout）
    assert payload["repo_root"] == payload["worktree_root"]
    # worktree_root 应在 ~/.spine/worktrees/ 下
    assert ".spine" in payload["worktree_root"]


def test_init_run_json_canonical_fields_roundtrip(worktree_env, capsys, make_args):
    """worktree 模式 run.json 回指字段往返一致；旧 run.json 缺字段可读。

    Task 5.2: run.json 回指字段往返一致；旧 run.json 缺字段可读。
    """
    from npc import paths as _paths

    repo, home = worktree_env
    mock_runner = _make_mock_runner(
        worktree_list_output="",
        worktree_add_rc=0,
        current_branch="main",
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    run_json_path = Path(payload["run_json"])
    assert run_json_path.is_file()
    rj_data = json.loads(run_json_path.read_text())

    # 确认 canonical 字段已写入 run.json
    assert "canonical_repo_root" in rj_data
    assert "canonical_proj_key" in rj_data
    assert "base_branch" in rj_data
    assert "spine_branch" in rj_data
    assert rj_data["canonical_repo_root"] == payload["canonical_repo_root"]
    assert rj_data["spine_branch"] == payload["spine_branch"]

    # 往返：read_run_json 能还原这些字段
    p = _paths.read_run_json(run_json_path)
    assert str(p.canonical_repo_root) == rj_data["canonical_repo_root"]
    assert p.canonical_proj_key == rj_data["canonical_proj_key"]
    assert p.base_branch == rj_data["base_branch"]
    assert p.spine_branch == rj_data["spine_branch"]

    # 旧 run.json（无 canonical 字段）应可读，字段为 None
    old_rj = {k: v for k, v in rj_data.items() if k not in {
        "canonical_repo_root", "canonical_proj_key", "base_branch", "spine_branch"
    }}
    old_rj_path = run_json_path.parent / "old_run.json"
    old_rj_path.write_text(json.dumps(old_rj))
    p_old = _paths.read_run_json(old_rj_path)
    assert p_old.canonical_repo_root is None
    assert p_old.canonical_proj_key is None
    assert p_old.base_branch is None
    assert p_old.spine_branch is None


def test_init_no_worktree_inplace(init_env, capsys, make_args):
    """--no-worktree 就地行为：repo_root = 主 checkout，无 worktree 字段。

    Task 5.3: --no-worktree 就地行为。
    """
    repo, home = init_env
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    # --no-worktree 时 worktree_root 和 spine_branch 应为 null
    assert payload["worktree_root"] is None
    assert payload["spine_branch"] is None
    # repo_root 应是主 checkout（fake_repo）
    assert payload["repo_root"].endswith("/repo")


def test_init_worktree_create_failure_exit3(worktree_env, capsys, make_args):
    """worktree 创建失败 → exit 3，不写 run.json/active.json。

    Task 5.4: worktree 创建失败 → exit 3 无半残。
    """
    repo, home = worktree_env
    mock_runner = _make_mock_runner(
        worktree_list_output="",
        worktree_add_rc=128,
        worktree_add_stderr="fatal: branch already exists",
        current_branch="main",
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    with pytest.raises(SystemExit) as ei:
        _init.run(args, runner=mock_runner)
    assert ei.value.code == 3

    out_lines = capsys.readouterr().out.strip().splitlines()
    payload = json.loads(out_lines[-1])
    assert payload.get("error") == "worktree_create_failed"

    # 确认没有写入任何 run.json / active.json
    proj_key = "-" + str(repo).lstrip("/").replace("/", "-")
    task_log = home / "task_log" / proj_key
    if task_log.is_dir():
        import glob
        run_jsons = list(task_log.glob("*/run.json"))
        assert len(run_jsons) == 0, f"不应有半残 run.json，但发现：{run_jsons}"


def test_init_resume_detects_dangling_spine_worktree(worktree_env, capsys, make_args):
    """有悬空 in-progress spine worktree → needs_resume=true + worktree_root 指向它。

    Task 5.5: 续跑扫描：有悬空 in-progress spine worktree → needs_resume 指向它。
    """
    repo, home = worktree_env

    # 准备一个"悬空" spine worktree 目录（路径要足够短以防 proj_key 超长）
    # 使用 home 下的固定短路径
    fake_wt_path = home / ".spine" / "worktrees" / "p" / "ts1"
    fake_wt_path.mkdir(parents=True)

    # 为该 worktree 路径建 in-progress state 文件
    from npc import paths as _paths
    wt_proj_key = _paths.proj_key_for(fake_wt_path)
    wt_task_log = home / "task_log" / wt_proj_key
    wt_task_log.mkdir(parents=True)
    state_file = wt_task_log / "2026-05-01-1000-plan-state.json"
    state_file.write_text(json.dumps({
        "schema_version": 2,
        "run_ts": "2026-05-01-1000",
        "status": "in-progress",
        "progress": [],
    }))

    # worktree list 输出含 spine/* 分支 + 指向 fake_wt_path
    wt_list_output = (
        f"worktree {fake_wt_path}\n"
        "HEAD abc123\n"
        "branch refs/heads/spine/2026-05-01-1000\n"
        "\n"
    )

    mock_runner = _make_mock_runner(
        worktree_list_output=wt_list_output,
        worktree_add_rc=0,
        current_branch="main",
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is True
    assert payload["worktree_root"] == str(fake_wt_path)


def test_init_no_dangling_worktree_creates_new(worktree_env, capsys, make_args):
    """无悬空 in-progress spine worktree → 正常创建新 worktree。

    Task 5.5: 无悬空 → 正常新建。
    """
    repo, home = worktree_env
    # worktree list 返回空（无 spine/* 分支）
    mock_runner = _make_mock_runner(
        worktree_list_output="",
        worktree_add_rc=0,
        current_branch="main",
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is False
    assert payload["worktree_root"] is not None
    assert payload["spine_branch"] is not None
    assert payload["spine_branch"].startswith("spine/")


def test_init_worktree_ignores_canonical_task_log_in_progress(worktree_env, capsys, make_args):
    """Regression F1: worktree 模式下，若 canonical task_log 有 in-progress 状态，
    init 不应将旧 run_ts 用于新 worktree 的 Paths，而应以 needs_resume=false 新建。

    修复前：canonical in-progress → needs_resume=True → 以旧 run_ts 键入新 worktree
    → state 路径错位（worktree 路径 != 旧 run_ts 对应路径）。
    修复后：worktree 模式跳过 canonical 检查，always needs_resume=false（无悬空时）。
    """
    repo, home = worktree_env

    # 在 canonical task_log 写一个 in-progress state
    from npc import paths as _paths
    canonical_proj_key = _paths.proj_key_for(repo)
    canonical_task_log = home / "task_log" / canonical_proj_key
    canonical_task_log.mkdir(parents=True, exist_ok=True)
    old_run_ts = "2026-01-01-0000"
    old_state = canonical_task_log / f"{old_run_ts}-plan-state.json"
    old_state.write_text(json.dumps({
        "schema_version": 2,
        "run_ts": old_run_ts,
        "status": "in-progress",
        "progress": [],
    }))

    # 无悬空 spine worktree，worktree list 返回空
    mock_runner = _make_mock_runner(
        worktree_list_output="",
        worktree_add_rc=0,
        current_branch="main",
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    # worktree 模式：canonical 旧状态不应触发 resume
    assert payload["needs_resume"] is False, (
        "worktree 模式下不应因 canonical task_log 的旧状态触发 needs_resume=True"
    )

    # run_ts 应与 spine_branch 一致（不是旧 run_ts）
    assert payload["run_ts"] != old_run_ts, (
        f"run_ts 不应复用旧 canonical run_ts ({old_run_ts})，实际={payload['run_ts']}"
    )
    spine_branch = payload["spine_branch"]
    assert spine_branch is not None and spine_branch.startswith("spine/")
    branch_run_ts = spine_branch.split("spine/", 1)[1]
    assert payload["run_ts"] == branch_run_ts, (
        f"worktree 模式 run_ts({payload['run_ts']}) 应与 spine_branch 后缀({branch_run_ts})一致"
    )


# ============================================================
# shared_context_warning：透出 openspec/project.md 体检结果
# ============================================================


def _write_project_md(repo: Path, content: str) -> None:
    pm = repo / "openspec" / "project.md"
    pm.parent.mkdir(parents=True, exist_ok=True)
    pm.write_text(content, encoding="utf-8")


def test_init_shared_context_missing_warns(init_env, capsys, make_args):
    # 3.1 无 openspec/project.md → shared_context_warning 为非空字符串
    repo, _ = init_env
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "shared_context_warning" in payload
    assert isinstance(payload["shared_context_warning"], str)
    assert payload["shared_context_warning"]


def test_init_shared_context_healthy_is_null(init_env, capsys, make_args):
    # 3.2 存在且含约定段落 → shared_context_warning == None
    repo, _ = init_env
    _write_project_md(repo, "# 项目\n\n## 技术约定\n\n内容\n")
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["shared_context_warning"] is None


def test_init_shared_context_matches_doctor(init_env, capsys, make_args):
    # 3.3 两处调用点结果一致：warn 时值 == doctor detail；ok 时 == None
    from npc import doctor as _doctor

    repo, _ = init_env
    # warn 分支（无 project.md）
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    check = _doctor._check_shared_context(repo_root=Path(payload["repo_root"]))
    assert check["status"] == "warn"
    assert payload["shared_context_warning"] == check["detail"]


def test_init_shared_context_oserror_does_not_crash(
    init_env, capsys, make_args, monkeypatch
):
    # 3.5 读取抛 OSError → init 不崩溃，shared_context_warning 降级为非空提示
    repo, _ = init_env
    _write_project_md(repo, "# 项目\n\n## 技术约定\n\nx\n")

    _orig_read_text = Path.read_text

    def _boom(self, *a, **k):
        if self.name == "project.md" and self.parent.name == "openspec":
            raise PermissionError("denied")
        return _orig_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _boom)
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)  # 不抛未捕获异常
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert isinstance(payload["shared_context_warning"], str)
    assert payload["shared_context_warning"]


# ============================================================
# worktree provisioning（fix-coder-cwd-desync）
# ============================================================


def _write_home_config(home: Path, provision_cmd: str) -> None:
    cfg_dir = home / ".config" / "npc"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        f'[worktree]\nprovision_cmd = "{provision_cmd}"\n', encoding="utf-8"
    )


def test_init_worktree_provision_not_configured(worktree_env, capsys, make_args):
    """未配置 provision_cmd：不执行，payload.provision.ran=False，其余行为不变。"""
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["worktree_root"] is not None
    assert payload["provision"] == {"ran": False}


def test_init_worktree_provision_success(worktree_env, capsys, make_args):
    """provision_cmd 成功：ran=True ok=True，在 worktree 内执行。"""
    repo, home = worktree_env
    _write_home_config(home, "true")
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["worktree_root"] is not None
    assert payload["provision"]["ran"] is True
    assert payload["provision"]["ok"] is True
    assert payload["provision"]["cmd"] == "true"


def test_init_worktree_provision_failure_does_not_block(worktree_env, capsys, make_args):
    """provision_cmd 失败：仅告警，init 正常完成且 worktree 已建。"""
    repo, home = worktree_env
    _write_home_config(home, "false")
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args)
    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert payload["worktree_root"] is not None
    assert Path(payload["worktree_root"]).is_dir()
    assert payload["provision"]["ran"] is True
    assert payload["provision"]["ok"] is False


def test_init_no_worktree_provision_not_run(init_env, capsys, make_args):
    """--no-worktree 就地模式：不执行 provisioning。"""
    repo, home = init_env
    _write_home_config(home, "true")
    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["worktree_root"] is None
    assert payload["provision"] == {"ran": False}


# ============================================================
# owner 存活门槛（worktree-owner-liveness change，D2/D3/D4）
# ============================================================


def _dead_pid() -> int:
    """获取一个确定已退出且已回收的 pid。"""
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _fresh_heartbeat() -> str:
    return (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")


def _stale_heartbeat() -> str:
    """过期心跳（25h 前）。dead pid 本身不构成死亡证据，判死靠心跳过期。"""
    return (datetime.now().astimezone() - timedelta(hours=25)).isoformat(timespec="seconds")


def _skeleton_path_for(home: Path, worktree_root: str, run_ts: str) -> Path:
    from npc import paths as _paths

    wt_proj_key = _paths.proj_key_for(Path(worktree_root))
    return home / "task_log" / wt_proj_key / f"{run_ts}-plan-state.json"


def _wt_list_output(wt_path: Path, run_ts: str) -> str:
    return (
        f"worktree {wt_path}\n"
        "HEAD abc123\n"
        f"branch refs/heads/spine/{run_ts}\n"
        "\n"
    )


def _setup_wt_with_state(home: Path, name: str, run_ts: str, state: dict) -> Path:
    """建一个 fake spine worktree 目录 + 对应 task_log 的 plan-state 文件。"""
    from npc import paths as _paths

    wt_path = home / ".spine" / "worktrees" / "p" / name
    wt_path.mkdir(parents=True)
    wt_proj_key = _paths.proj_key_for(wt_path)
    wt_task_log = home / "task_log" / wt_proj_key
    wt_task_log.mkdir(parents=True)
    (wt_task_log / f"{run_ts}-plan-state.json").write_text(json.dumps(state))
    return wt_path


# ---- 3.1 / 3.1a / 3.1b：initializing 骨架 owner 字段 + 原子写 ----


def test_init_skeleton_contains_owner_fields(worktree_env, capsys, make_args):
    """npc init 建 worktree 前落盘的 initializing 骨架含 owner_pid / 心跳；session_id 为 None。"""
    repo, home = worktree_env
    mock_runner = _make_mock_runner(
        worktree_list_output="", worktree_add_rc=0, current_branch="main"
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    skeleton = _skeleton_path_for(home, payload["worktree_root"], payload["run_ts"])
    assert skeleton.is_file()
    data = json.loads(skeleton.read_text())
    assert data["status"] == "initializing"
    assert data["owner_pid"] is not None
    assert data["owner_pid"] == os.getppid()
    datetime.fromisoformat(data["owner_heartbeat_at"])  # ISO8601 可解析
    assert data["owner_session_id"] is None


def test_init_skeleton_written_atomically(worktree_env, capsys, make_args, monkeypatch):
    """骨架落盘 MUST 经由 tmp + os.replace 原子替换（round-4 评审 F1）。"""
    repo, home = worktree_env
    replace_calls: list[tuple[str, str]] = []
    orig_replace = os.replace

    def _spy(src, dst):
        replace_calls.append((str(src), str(dst)))
        return orig_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    mock_runner = _make_mock_runner(
        worktree_list_output="", worktree_add_rc=0, current_branch="main"
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=mock_runner)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    skeleton = _skeleton_path_for(home, payload["worktree_root"], payload["run_ts"])
    assert any(dst == str(skeleton) for _, dst in replace_calls), (
        f"骨架写入应经由 os.replace，实际 replace 调用：{replace_calls}"
    )
    # 正常路径无 .tmp 残留
    assert list(skeleton.parent.glob("*.tmp")) == []


def test_init_skeleton_write_failure_aborts(worktree_env, capsys, make_args, monkeypatch):
    """骨架落盘底层写入失败 → 异常向上抛出、中断 run()，不留半态骨架文件。"""
    repo, home = worktree_env

    def _boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    mock_runner = _make_mock_runner(
        worktree_list_output="", worktree_add_rc=0, current_branch="main"
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    with pytest.raises(OSError):
        _init.run(args, runner=mock_runner)

    # 目标骨架路径不存在（写入前本无旧文件）——不产生缺 owner 字段的半态新文件
    leftovers = list(home.glob("task_log/**/*-plan-state.json"))
    assert leftovers == [], f"落盘失败不应留下骨架文件：{leftovers}"


# ---- 3.2 / 3.3 / 3.4 / 3.5：悬空扫描 owner 门槛 ----


def test_scan_skips_in_progress_with_alive_owner(worktree_env, make_args):
    """in-progress 候选 owner 存活 → 不进候选池，返回 (False, None, False)。"""
    repo, home = worktree_env
    run_ts = "2026-05-01-1000"
    wt_path = _setup_wt_with_state(home, "ts1", run_ts, {
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "in-progress",
        "progress": [],
        "owner_pid": os.getpid(),
        "owner_heartbeat_at": _fresh_heartbeat(),
    })
    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(wt_path, run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (False, None, False)


def test_scan_hits_in_progress_with_dead_owner(worktree_env, make_args):
    """in-progress 候选 owner 已死 → 进候选池（既有行为）。"""
    repo, home = worktree_env
    run_ts = "2026-05-01-1000"
    wt_path = _setup_wt_with_state(home, "ts1", run_ts, {
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "in-progress",
        "progress": [],
        "owner_pid": _dead_pid(),
        "owner_heartbeat_at": _stale_heartbeat(),
    })
    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(wt_path, run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (True, wt_path, False)


def test_scan_skips_dead_wrapper_pid_with_fresh_heartbeat(worktree_env, make_args):
    """回归（review round 2 CRITICAL）：owner_pid 是已死的短命包装 shell、但心跳新鲜
    → 视为存活，MUST NOT 进候选池。

    真实部署里 npc 经 Bash 工具的 zsh -c 调用，os.getppid() 记录的 shell 在命令
    结束后数秒内即死；若 pid 死亡即判死，活跃 run 在任意两次子命令之间都会被
    并发 init 抢走——即原始并发踩踏缺陷原样复现。
    """
    repo, home = worktree_env
    run_ts = "2026-05-01-1000"
    wt_path = _setup_wt_with_state(home, "ts_wrapper", run_ts, {
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "in-progress",
        "progress": [],
        "owner_pid": _dead_pid(),
        "owner_heartbeat_at": _fresh_heartbeat(),
    })
    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(wt_path, run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (False, None, False)


def test_scan_takeover_bypasses_alive_owner_gate(worktree_env, make_args):
    """--takeover：owner 判定存活的 in-progress 候选也进候选池（显式手动接管）。"""
    repo, home = worktree_env
    run_ts = "2026-05-01-1000"
    wt_path = _setup_wt_with_state(home, "ts_alive_tk", run_ts, {
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "in-progress",
        "progress": [],
        "owner_pid": os.getpid(),
        "owner_heartbeat_at": _fresh_heartbeat(),
    })
    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(wt_path, run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner, takeover=True
    )
    assert (needs_resume, wt, is_init) == (True, wt_path, False)


def test_scan_initializing_owner_gate(worktree_env, make_args):
    """initializing 候选同样过 owner 门槛：存活跳过，已死命中。"""
    repo, home = worktree_env
    run_ts = "2026-05-01-1000"

    # owner 存活 → 不进候选池
    wt_alive = _setup_wt_with_state(home, "ts_alive", run_ts, {
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "initializing",
        "worktree_root": "placeholder",
        "progress": [],
        "owner_pid": os.getpid(),
        "owner_heartbeat_at": _fresh_heartbeat(),
    })
    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(wt_alive, run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (False, None, False)

    # owner 已死 → 进候选池（崩溃恢复）
    wt_dead = _setup_wt_with_state(home, "ts_dead", run_ts, {
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "initializing",
        "worktree_root": "placeholder",
        "progress": [],
        "owner_pid": _dead_pid(),
        "owner_heartbeat_at": _stale_heartbeat(),
    })
    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(wt_dead, run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (True, wt_dead, True)


def test_owner_alive_for_state_file_corrupt_is_dead(tmp_path):
    """state 文件损坏（JSONDecodeError）→ owner 判定保守退化为不存活（允许进候选池）。"""
    bad = tmp_path / "bad-plan-state.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _init._owner_alive_for_state_file(bad) is False
    missing = tmp_path / "missing-plan-state.json"
    assert _init._owner_alive_for_state_file(missing) is False


# ---- 3.6：并发场景集成测试 ----


def test_init_concurrent_second_run_creates_own_worktree(worktree_env, capsys, make_args):
    """两个连续 run()（模拟两个并发 npc init）：第二次 MUST NOT 抢走第一次的 worktree。"""
    repo, home = worktree_env

    # 第一次：无既有 worktree → 新建 worktree A（骨架 owner 为当前进程父 pid，存活）
    first_runner = _make_mock_runner(
        worktree_list_output="", worktree_add_rc=0, current_branch="main"
    )
    args = make_args(auto=False, fresh=False, shell_exports=False)
    _init.run(args, runner=first_runner)
    payload1 = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    wt_a = payload1["worktree_root"]
    run_ts_a = payload1["run_ts"]
    assert payload1["needs_resume"] is False

    # 第二次：git worktree list 里已有 A → A 的骨架 owner 存活，不得被接管
    second_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(Path(wt_a), run_ts_a),
        worktree_add_rc=0,
        current_branch="main",
    )
    _init.run(args, runner=second_runner)
    payload2 = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert payload2["needs_resume"] is False, (
        "owner 存活的 worktree A 不应被第二次 init 当作悬空 run 抢走"
    )
    assert payload2["worktree_root"] is not None
    assert payload2["worktree_root"] != wt_a
    assert payload2["run_ts"] != run_ts_a


# ---- 3.7 / 3.8：--no-worktree 路径 owner 门槛 ----


def test_init_no_worktree_owner_alive_no_resume(init_env, capsys, make_args):
    """--no-worktree：in-progress state owner 存活 → needs_resume=False + 全新 run_ts。"""
    repo, home = init_env
    proj_key = "-" + str(repo).lstrip("/").replace("/", "-")
    task_log = home / "task_log" / proj_key
    task_log.mkdir(parents=True)
    old_run_ts = "2026-05-01-1000"
    (task_log / f"{old_run_ts}-plan-state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "run_ts": old_run_ts,
            "status": "in-progress",
            "progress": [],
            "owner_pid": os.getpid(),
            "owner_heartbeat_at": _fresh_heartbeat(),
        })
    )

    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is False
    assert payload["resume_state_json"] is None
    assert payload["run_ts"] != old_run_ts


def test_init_no_worktree_owner_dead_resumes(init_env, capsys, make_args):
    """--no-worktree：in-progress state owner 已死 → needs_resume=True，复用旧 run_ts。"""
    repo, home = init_env
    proj_key = "-" + str(repo).lstrip("/").replace("/", "-")
    task_log = home / "task_log" / proj_key
    task_log.mkdir(parents=True)
    old_run_ts = "2026-05-01-1000"
    (task_log / f"{old_run_ts}-plan-state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "run_ts": old_run_ts,
            "status": "in-progress",
            "progress": [],
            "owner_pid": _dead_pid(),
            "owner_heartbeat_at": _stale_heartbeat(),
        })
    )

    args = make_args(auto=False, fresh=False, shell_exports=False, no_worktree=True)
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is True
    assert payload["run_ts"] == old_run_ts


def test_cli_fresh_and_takeover_mutually_exclusive(capsys):
    """npc init --fresh --takeover → argparse 拒绝（语义互斥：弃旧 vs 抢旧）。"""
    from npc import cli as _cli

    with pytest.raises(SystemExit) as exc_info:
        _cli._build_parser().parse_args(["init", "--fresh", "--takeover"])
    assert exc_info.value.code == 2


def test_init_no_worktree_takeover_resumes_alive_owner(init_env, capsys, make_args):
    """--no-worktree --takeover：owner 存活的 in-progress state 也被显式接管。"""
    repo, home = init_env
    proj_key = "-" + str(repo).lstrip("/").replace("/", "-")
    task_log = home / "task_log" / proj_key
    task_log.mkdir(parents=True)
    old_run_ts = "2026-05-01-1000"
    (task_log / f"{old_run_ts}-plan-state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "run_ts": old_run_ts,
            "status": "in-progress",
            "progress": [],
            "owner_pid": os.getpid(),
            "owner_heartbeat_at": _fresh_heartbeat(),
        })
    )

    args = make_args(
        auto=False, fresh=False, takeover=True, shell_exports=False, no_worktree=True
    )
    _init.run(args)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is True
    assert payload["run_ts"] == old_run_ts
    assert payload["takeover"] is True


def test_reverse_scan_orphan_mark_still_gated_under_takeover(worktree_env, make_args):
    """--takeover 不豁免孤儿标记的 owner 门槛：接管是续跑语义，
    不是把他人活跃骨架判残骸的许可。"""
    repo, home = worktree_env
    run_ts = "2026-05-02-1300"
    skeleton_path = _initializing_skeleton(home, "ts_tk", run_ts, owner_pid=os.getpid())

    mock_runner = _make_mock_runner(worktree_list_output="", current_branch="main")
    _init._scan_spine_worktrees_for_resume(repo, home, runner=mock_runner, takeover=True)
    data = json.loads(skeleton_path.read_text())
    assert data["status"] == "initializing", (
        f"takeover 下 owner 存活的骨架也不应被标孤儿，实际 status={data['status']!r}"
    )


# ============================================================
# Review round-1 F2：孤儿标记 owner 门槛（竞态）
# ============================================================


def _initializing_skeleton(
    home: Path, name: str, run_ts: str, *, owner_pid: int, heartbeat: str | None = None
) -> Path:
    """写一个 worktree_root 指向不存在目录的 initializing 骨架（不建 worktree），返回骨架路径。

    heartbeat 缺省为新鲜心跳；模拟真死 owner 时传 ``_stale_heartbeat()``。
    """
    from npc import paths as _paths

    wt_path = home / ".spine" / "worktrees" / "p" / name
    wt_proj_key = _paths.proj_key_for(wt_path)
    wt_task_log = home / "task_log" / wt_proj_key
    wt_task_log.mkdir(parents=True)
    skeleton_path = wt_task_log / f"{run_ts}-plan-state.json"
    skeleton_path.write_text(json.dumps({
        "schema_version": 2,
        "run_ts": run_ts,
        "status": "initializing",
        "worktree_root": str(wt_path),
        "spine_branch": f"spine/{run_ts}",
        "base_branch": "main",
        "plan_order": [],
        "progress": [],
        "owner_pid": owner_pid,
        "owner_heartbeat_at": heartbeat or _fresh_heartbeat(),
    }))
    return skeleton_path


def test_reverse_scan_orphan_mark_skips_alive_owner(worktree_env, make_args):
    """反向扫描：worktree 缺失的 initializing 骨架 owner 存活 → MUST NOT 标 orphan。"""
    repo, home = worktree_env
    run_ts = "2026-05-02-1000"
    skeleton_path = _initializing_skeleton(home, "ts_alive", run_ts, owner_pid=os.getpid())

    mock_runner = _make_mock_runner(worktree_list_output="", current_branch="main")
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (False, None, False)
    data = json.loads(skeleton_path.read_text())
    assert data["status"] == "initializing", (
        f"owner 存活的骨架不应被标孤儿，实际 status={data['status']!r}"
    )


def test_reverse_scan_orphan_mark_marks_dead_owner(worktree_env, make_args):
    """反向扫描：worktree 缺失的 initializing 骨架 owner 已死 → 仍标 orphan（既有行为）。"""
    repo, home = worktree_env
    run_ts = "2026-05-02-1100"
    skeleton_path = _initializing_skeleton(
        home, "ts_dead", run_ts, owner_pid=_dead_pid(), heartbeat=_stale_heartbeat()
    )

    mock_runner = _make_mock_runner(worktree_list_output="", current_branch="main")
    _init._scan_spine_worktrees_for_resume(repo, home, runner=mock_runner)
    data = json.loads(skeleton_path.read_text())
    assert data["status"] == "orphan", (
        f"owner 已死且 worktree 缺失的骨架应被标孤儿，实际 status={data['status']!r}"
    )


def test_forward_scan_missing_dir_orphan_mark_skips_alive_owner(worktree_env, make_args):
    """正向扫描：worktree 在 git list 但目录缺失，骨架 owner 存活 → MUST NOT 标 orphan。"""
    repo, home = worktree_env
    run_ts = "2026-05-02-1200"
    skeleton_path = _initializing_skeleton(home, "ts_listed", run_ts, owner_pid=os.getpid())
    # 骨架的 worktree_root 目录不存在，但出现在 git worktree list 里
    wt_root = json.loads(skeleton_path.read_text())["worktree_root"]

    mock_runner = _make_mock_runner(
        worktree_list_output=_wt_list_output(Path(wt_root), run_ts),
        current_branch="main",
    )
    needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
        repo, home, runner=mock_runner
    )
    assert (needs_resume, wt, is_init) == (False, None, False)
    data = json.loads(skeleton_path.read_text())
    assert data["status"] == "initializing", (
        f"owner 存活的骨架不应被标孤儿，实际 status={data['status']!r}"
    )


def test_init_concurrent_scan_does_not_orphan_live_skeleton(worktree_env, capsys, make_args):
    """真实竞态回归（round-1 F2）：session A 骨架已落盘、add_worktree 未完成时，
    session B 的扫描 MUST NOT 把 A 的活跃骨架标为 orphan。

    测试方法：在真实 run() 路径上用 runner 把 git worktree add 卡住（threading.Event），
    主线程轮询到 initializing 骨架出现后，以「git list 尚无该 worktree」的视角跑第二次
    真实 _scan_spine_worktrees_for_resume，断言骨架 status 保持 initializing；
    随后放行 add，断言 init 正常完成。不 mock 被修复路径本身。
    """
    repo, home = worktree_env
    add_gate = threading.Event()
    add_entered = threading.Event()

    base_runner = _make_mock_runner(
        worktree_list_output="", worktree_add_rc=0, current_branch="main"
    )

    def blocking_runner(cmd, cwd=None, capture_output=False, text=False, env=None, **kwargs):
        if "worktree" in cmd and "add" in cmd:
            add_entered.set()
            # 模拟慢速 worktree add：在主线程放行前一直阻塞（超时兜底防死等）
            assert add_gate.wait(timeout=30), "测试未放行 worktree add"
        return base_runner(cmd, cwd=cwd, capture_output=capture_output, text=text, env=env, **kwargs)

    args = make_args(auto=False, fresh=False, shell_exports=False)
    run_errors: list[BaseException] = []

    def _session_a():
        try:
            _init.run(args, runner=blocking_runner)
        except BaseException as e:  # noqa: BLE001 — 透传到主线程断言
            run_errors.append(e)

    thread = threading.Thread(target=_session_a)
    thread.start()

    try:
        # 等待 session A 骨架落盘并抵达被卡住的 add_worktree
        deadline = time.monotonic() + 30
        skeleton_path = None
        while time.monotonic() < deadline:
            candidates = list(home.glob("task_log/**/*-plan-state.json"))
            for cand in candidates:
                try:
                    if json.loads(cand.read_text()).get("status") == "initializing":
                        skeleton_path = cand
                        break
                except (OSError, json.JSONDecodeError):
                    continue
            if skeleton_path is not None and add_entered.is_set():
                break
            time.sleep(0.01)
        assert skeleton_path is not None, "session A 的 initializing 骨架未落盘"
        assert add_entered.is_set(), "session A 未抵达 worktree add（竞态窗口未构造成功）"

        # session B：此刻 git worktree list 里还没有 A 的 worktree（add 未完成），
        # 目录也不存在 → 走反向扫描分支。owner（本进程父 pid）存活 → 不得标孤儿。
        scan_runner = _make_mock_runner(worktree_list_output="", current_branch="main")
        needs_resume, wt, is_init = _init._scan_spine_worktrees_for_resume(
            repo, home, runner=scan_runner
        )
        assert (needs_resume, wt, is_init) == (False, None, False)
        data = json.loads(skeleton_path.read_text())
        assert data["status"] == "initializing", (
            "竞态窗口内 session B 不得把 session A 的活跃骨架标为 orphan，"
            f"实际 status={data['status']!r}"
        )
    finally:
        add_gate.set()
        thread.join(timeout=30)

    assert not thread.is_alive(), "session A 的 run() 未在放行后完成"
    assert not run_errors, f"session A 的 run() 抛异常：{run_errors}"
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["needs_resume"] is False
    assert Path(payload["worktree_root"]).is_dir()
    # 骨架已被 init-run 正常升级（不再是 initializing / orphan 残骸）
    final = json.loads(skeleton_path.read_text())
    assert final["status"] != "orphan"
