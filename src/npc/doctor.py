"""npc doctor：环境前置体检（基石工具）。

把"跑 npc 之前需要满足的一切前置条件"汇成一份结构化体检报告：

- 必备/可选可执行文件是否在 PATH（git / openspec / codex / claude / jq /
  portable-timeout）；
- 跨项目共享的 review schema 是否已自举；
- 成本路由 ``mimo.env`` 是否就绪（缺失只降级 warn，不视为 missing）；
- npc 配置是否能正常加载（失败降级 warn，不阻塞）；
- 工程级 ``docs/principles.md`` 是否在（warn 级）；
- 共读上下文 ``openspec/project.md`` 的结构性健康（存在/非空/含约定段落，warn 级）。

设计成"纯函数核 + 薄 handler"：:func:`gather_checks` 不做任何 I/O 输出、可注入
``which`` / ``home`` / ``repo_root``，便于单测；:func:`run` 只负责探测 repo_root、
调核、emit JSON、按 required 缺失决定退出码。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from . import _io, config as _config, paths as _paths


# (name, required) —— 在 PATH 中可执行文件的体检清单
_BIN_CHECKS: tuple[tuple[str, bool], ...] = (
    ("git", True),
    ("openspec", False),
    ("codex", False),
    ("claude", False),
    ("jq", False),
)

# 可执行文件状态：required 缺失记 "missing"，可选缺失记 "warn"
def _bin_status(found: bool, required: bool) -> str:
    if found:
        return "ok"
    return "missing" if required else "warn"


def _check_bin(name: str, *, required: bool, which) -> dict:
    """通用 PATH 可执行文件检查。"""
    resolved = which(name)
    found = resolved is not None
    status = _bin_status(found, required)
    detail = f"已找到：{resolved}" if found else f"未在 PATH 中找到 {name}"
    return {"name": name, "status": status, "detail": detail, "required": required}


def _check_portable_timeout(*, home: Path, which) -> dict:
    """portable-timeout：先查 PATH，再查 ~/.local/bin/portable-timeout。"""
    resolved = which("portable-timeout")
    if resolved is not None:
        return {
            "name": "portable-timeout",
            "status": "ok",
            "detail": f"已找到（PATH）：{resolved}",
            "required": False,
        }
    fallback = home / ".local" / "bin" / "portable-timeout"
    if fallback.is_file():
        if os.access(fallback, os.X_OK):
            return {
                "name": "portable-timeout",
                "status": "ok",
                "detail": f"已找到（自举位置）：{fallback}",
                "required": False,
            }
        return {
            "name": "portable-timeout",
            "status": "warn",
            "detail": f"portable-timeout 存在但不可执行（缺执行位）：{fallback}；运行 chmod +x 或 npc init 修复",
            "required": False,
        }
    return {
        "name": "portable-timeout",
        "status": "warn",
        "detail": "未找到 portable-timeout（PATH 与 ~/.local/bin 均无）；运行 npc init 自举",
        "required": False,
    }


def _check_schema(*, home: Path) -> dict:
    """review schema 文件是否已落盘。"""
    schema_path = home / "task_log" / _paths.SCHEMA_FILENAME
    if schema_path.is_file():
        if not os.access(schema_path, os.R_OK):
            return {
                "name": "schema",
                "status": "warn",
                "detail": f"review schema 存在但不可读：{schema_path}；检查文件权限",
                "required": False,
            }
        try:
            json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {
                "name": "schema",
                "status": "warn",
                "detail": f"review schema 存在但非法（JSON 解析失败）：{schema_path}：{e}",
                "required": False,
            }
        return {
            "name": "schema",
            "status": "ok",
            "detail": f"已存在：{schema_path}",
            "required": False,
        }
    return {
        "name": "schema",
        "status": "warn",
        "detail": f"review schema 缺失：{schema_path}；运行 npc init 自举",
        "required": False,
    }


def _check_mimo_env(*, home: Path) -> dict:
    """成本路由 mimo.env：存在则 ok 并标注成本路由可用，缺失为 warn（非 missing）。"""
    mimo_env = home / ".config" / "npc" / "mimo.env"
    if mimo_env.is_file():
        if not os.access(mimo_env, os.R_OK):
            return {
                "name": "mimo.env",
                "status": "warn",
                "detail": f"成本路由 mimo.env 存在但不可读：{mimo_env}；检查文件权限",
                "required": False,
            }
        return {
            "name": "mimo.env",
            "status": "ok",
            "detail": f"成本路由可用：{mimo_env}",
            "required": False,
        }
    return {
        "name": "mimo.env",
        "status": "warn",
        "detail": f"成本路由 mimo.env 缺失：{mimo_env}；coder 将走默认 premium 层",
        "required": False,
    }


def _check_config(*, home: Path, repo_root: Path) -> dict:
    """npc config 可加载性；加载失败降级 warn，不阻塞。"""
    try:
        cfg = _config.load_config(repo_root, home=home)
    except (_config.ConfigError, OSError, Exception) as e:
        return {
            "name": "config",
            "status": "warn",
            "detail": f"配置加载失败（将用内置默认）：[{type(e).__name__}] {e}",
            "required": False,
        }
    if cfg.source == "<default>":
        detail = "使用内置默认配置（未找到配置文件）"
    else:
        detail = f"配置可加载：{cfg.source}"
    return {
        "name": "config",
        "status": "ok",
        "detail": detail,
        "required": False,
    }


def _check_principles(*, repo_root: Path | None) -> dict:
    """工程级 docs/principles.md 是否在（warn 级）。"""
    if repo_root is None:
        return {
            "name": "principles.md",
            "status": "warn",
            "detail": "无法定位 repo_root，跳过 docs/principles.md 检查",
            "required": False,
        }
    principles = repo_root / "docs" / "principles.md"
    if principles.is_file():
        return {
            "name": "principles.md",
            "status": "ok",
            "detail": f"已存在：{principles}",
            "required": False,
        }
    return {
        "name": "principles.md",
        "status": "warn",
        "detail": f"docs/principles.md 缺失：{principles}",
        "required": False,
    }


# 约定类段落标题词表：标题文本含任一子串（大小写不敏感）即命中。
# 中文 "约定" 大小写无关；英文 "convention" 覆盖 Convention/Conventions。
_CONVENTION_TITLE_SUBSTRINGS: tuple[str, ...] = ("约定", "convention")


def _has_convention_heading(text: str) -> bool:
    """扫描 1~2 级 Markdown 标题行，任一标题文本含约定类子串即命中。

    仅匹配 ``#`` / ``##`` 起始的整行标题（3 级及以下、正文行不计入），
    子串大小写不敏感。
    """
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # 仅 1~2 级标题：# 或 ## 后跟空白与标题文本；### 及以上被排除
        if not (line.startswith("# ") or line.startswith("## ")):
            continue
        title = line.lstrip("#").strip().lower()
        if any(sub in title for sub in _CONVENTION_TITLE_SUBSTRINGS):
            return True
    return False


def _check_shared_context(*, repo_root: Path | None) -> dict:
    """共读上下文文档 openspec/project.md 的结构性体检（warn 级，永不阻断）。

    三层结构检查：存在性 / 非空 / 含约定类段落标题。任一不满足 → warn。
    仅做结构判断，MUST NOT 校验业务内容质量。读取抛 OSError 时降级 warn，
    绝不抛未捕获异常。``required`` 恒为 ``False``。
    """
    name = "openspec/project.md"
    if repo_root is None:
        return {
            "name": name,
            "status": "warn",
            "detail": "无法定位 repo_root，跳过 openspec/project.md 检查",
            "required": False,
        }
    project_md = repo_root / "openspec" / "project.md"
    try:
        if not project_md.is_file():
            return {
                "name": name,
                "status": "warn",
                "detail": (
                    f"共读上下文文档缺失：{project_md}；"
                    "建议补一份项目级技术约定文档，供所有 worker 共读"
                ),
                "required": False,
            }
        text = project_md.read_text(encoding="utf-8")
    except OSError as e:
        return {
            "name": name,
            "status": "warn",
            "detail": f"读取 openspec/project.md 失败（降级 warn，不阻断）：[{type(e).__name__}] {e}",
            "required": False,
        }
    if not text.strip():
        return {
            "name": name,
            "status": "warn",
            "detail": f"共读上下文文档为空：{project_md}；补充项目级技术约定内容",
            "required": False,
        }
    if not _has_convention_heading(text):
        return {
            "name": name,
            "status": "warn",
            "detail": (
                f"共读上下文文档 {project_md} 未含约定类段落标题"
                "（1~2 级标题含「约定」或 Convention/Conventions）；"
                "建议补一个专门的约定段落"
            ),
            "required": False,
        }
    return {
        "name": name,
        "status": "ok",
        "detail": f"已存在且含约定段落：{project_md}",
        "required": False,
    }


def gather_checks(
    *,
    home: Path,
    repo_root: Path | None,
    which=shutil.which,
) -> list[dict]:
    """纯函数核：返回全部体检项。

    每项形如 ``{"name", "status", "detail", "required"}``，
    其中 ``status`` ∈ {"ok", "missing", "warn"}。不做任何输出，便于单测。

    config 检查需要 repo_root；缺省时回退到 cwd（由调用方在 run 中探测后传入）。
    """
    checks: list[dict] = []
    for name, required in _BIN_CHECKS:
        checks.append(_check_bin(name, required=required, which=which))
    checks.append(_check_portable_timeout(home=home, which=which))
    checks.append(_check_schema(home=home))
    checks.append(_check_mimo_env(home=home))
    cfg_root = repo_root if repo_root is not None else Path.cwd()
    checks.append(_check_config(home=home, repo_root=cfg_root))
    checks.append(_check_principles(repo_root=repo_root))
    checks.append(_check_shared_context(repo_root=repo_root))
    return checks


def summarize(checks: list[dict]) -> dict:
    """把 checks 聚合为 summary：各状态计数 + 缺失的 required 名单。"""
    ok = sum(1 for c in checks if c["status"] == "ok")
    warn = sum(1 for c in checks if c["status"] == "warn")
    missing = sum(1 for c in checks if c["status"] == "missing")
    missing_required = [
        c["name"] for c in checks if c["required"] and c["status"] == "missing"
    ]
    return {
        "ok": ok,
        "warn": warn,
        "missing": missing,
        "missing_required": missing_required,
    }


def build_report(checks: list[dict]) -> dict:
    """组装最终 JSON 报告。ok 当且仅当无 required 缺失。"""
    summary = summarize(checks)
    return {
        "ok": not summary["missing_required"],
        "checks": checks,
        "summary": summary,
    }


def run(args: argparse.Namespace) -> None:
    """doctor 主入口：探测 repo_root → 体检 → emit JSON → 按 required 决定退出码。

    任一 required 项缺失：仍把完整报告 emit 出去（调用方据此知道缺哪个），
    随后以 ``dependency_missing`` / exit 3 退出。
    """
    home = Path.home()

    # repo_root 探测失败不致命：principles/config 降级处理
    try:
        repo_root: Path | None = _paths.detect_repo_root()
    except _paths.PathsError:
        repo_root = None

    checks = gather_checks(home=home, repo_root=repo_root, which=shutil.which)
    report = build_report(checks)
    _io.emit(report)

    missing_required = report["summary"]["missing_required"]
    if missing_required:
        _io.emit_error(
            "dependency_missing",
            f"缺少必备前置：{', '.join(missing_required)}",
            exit_code=3,
        )
