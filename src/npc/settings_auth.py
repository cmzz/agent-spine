"""auto 模式授权：`npc init --auto` 时给项目 `<repo>/.claude/settings.json` 授足够权限，
让 harness 无人值守跑时不被 Claude Code 的工具授权弹窗打断。

设计纪律：
- **只在 --auto 时调用**（交互档保留人确认）。
- **项目级、可逆**：只动 `<repo>/.claude/settings.json`。
- **合并不覆盖**：保留既有所有键；尤其 **deny 原样不动**（密钥保护不破）。
- **幂等**：重复 init 不重复追加 allow 项、不改已是 acceptEdits 的 mode。
- **坏 JSON 不覆盖**：既有文件无法解析时跳过并报告，绝不 clobber 用户配置。
- 失败不阻塞 init（调用方 swallow，warn 到 stderr）。
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path


def auto_local_dirs(home: Path | None = None) -> list[str]:
    """--auto 无人值守所需的 cwd 外受信目录（机器专属绝对路径）。

    这些路径在当前 checkout（cwd）之外，``defaultMode=acceptEdits`` 覆盖不到；
    必须显式列入 ``permissions.additionalDirectories`` 才不会在 worktree 内
    读/改文件时弹窗。因含 ``$HOME`` 绝对路径（机器专属），写入 gitignore 的
    ``settings.local.json`` 而非可共享的 ``settings.json``。

    - ``~/.spine/worktrees``：所有 spine per-run worktree 的根（coder 在此写代码）。
    - ``~/task_log``：run state / summary.md 等 pointer 落盘处。
    """
    h = home or Path.home()
    return [
        str(h / ".spine" / "worktrees"),
        str(h / "task_log"),
    ]


# harness 工具链 Bash 白名单（与用户级 settings 同口径）。acceptEdits 已覆盖
# 写文件类工具；这里放行 harness 真正会用的 Bash 命令，避免逐次授权弹窗。
_HARNESS_BINS = (
    "npc", "git", "openspec", "codex", "claude",
    "python3", "python", "pytest", "uv", "jq",
    "node", "npm", "pnpm", "yarn", "make", "cargo", "go",
)
HARNESS_BASH_ALLOW = tuple(f"Bash({c} *)" for c in _HARNESS_BINS)

# harness 破坏性操作 deny 底线（写入 settings.local.json）。
# 这些规则属 settings 层（非 context 层），compaction 后仍恒定生效。
AUTO_DENY_RULES: tuple[str, ...] = (
    "Bash(git push --force*)",
    "Bash(git reset --hard*)",
    "Edit(.git/**)",
)

AUTO_MODE = "acceptEdits"


def merge_auto_permissions(existing: dict) -> tuple[dict, dict]:
    """把 auto 授权合并进既有 settings dict。纯函数。

    返回 ``(new_settings, summary)``。``summary`` 含 ``defaultMode_set``（是否设了）
    与 ``added_allow``（新增的 allow 项；幂等：已存在的不重复）。
    既有 ``permissions.deny`` 与其它键原样保留。
    """
    new = deepcopy(existing) if isinstance(existing, dict) else {}
    perms = dict(new.get("permissions") or {})

    summary: dict = {"defaultMode_set": False, "added_allow": []}

    if perms.get("defaultMode") != AUTO_MODE:
        perms["defaultMode"] = AUTO_MODE
        summary["defaultMode_set"] = True

    allow = list(perms.get("allow") or [])
    for item in HARNESS_BASH_ALLOW:
        if item not in allow:
            allow.append(item)
            summary["added_allow"].append(item)
    perms["allow"] = allow

    new["permissions"] = perms
    return new, summary


def merge_additional_dirs(existing: dict, dirs: list[str]) -> tuple[dict, dict]:
    """把机器专属受信目录合并进 ``permissions.additionalDirectories``。纯函数。

    幂等：已存在的目录不重复追加。既有 additionalDirectories 与其它键原样保留。
    返回 ``(new_settings, summary)``，``summary`` 含 ``added_dirs``。
    """
    new = deepcopy(existing) if isinstance(existing, dict) else {}
    perms = dict(new.get("permissions") or {})

    current = list(perms.get("additionalDirectories") or [])
    added: list[str] = []
    for d in dirs:
        if d not in current:
            current.append(d)
            added.append(d)
    perms["additionalDirectories"] = current

    new["permissions"] = perms
    return new, {"added_dirs": added}


def merge_auto_deny(existing: dict) -> tuple[dict, dict]:
    """把 auto deny 底线合并进既有 settings dict。纯函数。

    返回 ``(new_settings, summary)``。``summary`` 含 ``added_deny``
    （新追加的条目；已存在的不重复，幂等）。
    既有 deny 条目原样保留（不删不改）。
    """
    new = deepcopy(existing) if isinstance(existing, dict) else {}
    perms = dict(new.get("permissions") or {})

    deny = list(perms.get("deny") or [])
    added: list[str] = []
    for item in AUTO_DENY_RULES:
        if item not in deny:
            deny.append(item)
            added.append(item)
    perms["deny"] = deny

    new["permissions"] = perms
    return new, {"added_deny": added}


def grant_auto_local_dirs(repo_root: Path, home: Path | None = None) -> dict:
    """把 --auto 所需的 cwd 外受信目录和破坏性操作 deny 底线写入 settings.local.json。

    ``settings.local.json`` 是 gitignore 的本地配置——机器专属绝对路径写这里，
    绝不污染可共享/可提交的 ``settings.json``。合并、幂等、坏 JSON 不覆盖，与
    ``grant_auto_permissions`` 同纪律。

    同时写入 deny 底线（AUTO_DENY_RULES）：force push / hard reset / .git 直改。
    deny 属 settings 层、不进 context，compaction 后仍恒定生效。

    返回 ``{ok, path, created, added_dirs, added_deny, skipped?}``。
    """
    settings_path = repo_root / ".claude" / "settings.local.json"
    existed = settings_path.is_file()

    existing: dict = {}
    if existed:
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                return {"ok": False, "path": str(settings_path), "skipped": "not-an-object"}
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "path": str(settings_path), "skipped": "unparseable"}

    new, dir_summary = merge_additional_dirs(existing, auto_local_dirs(home))
    new, deny_summary = merge_auto_deny(new)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, settings_path)

    return {
        "ok": True,
        "path": str(settings_path),
        "created": not existed,
        "added_dirs": dir_summary["added_dirs"],
        "added_deny": deny_summary["added_deny"],
    }


def grant_auto_permissions(repo_root: Path) -> dict:
    """读 `<repo>/.claude/settings.json`，合并 auto 授权，原子写回。

    返回结果 dict：``{ok, path, created, defaultMode_set, added_allow, skipped?}``。
    既有文件不可解析 → ``{ok: False, skipped: "unparseable", path}``，不写。
    """
    settings_path = repo_root / ".claude" / "settings.json"
    existed = settings_path.is_file()

    existing: dict = {}
    if existed:
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                return {"ok": False, "path": str(settings_path), "skipped": "not-an-object"}
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "path": str(settings_path), "skipped": "unparseable"}

    new, summary = merge_auto_permissions(existing)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, settings_path)

    return {
        "ok": True,
        "path": str(settings_path),
        "created": not existed,
        "defaultMode_set": summary["defaultMode_set"],
        "added_allow": summary["added_allow"],
    }
