"""settings_auth 测试：auto 授权的合并纯函数 + 落盘行为。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc import settings_auth as sa


# ============================================================
# merge_auto_permissions 纯函数
# ============================================================


def test_merge_empty_sets_mode_and_allow():
    new, summary = sa.merge_auto_permissions({})
    assert new["permissions"]["defaultMode"] == "acceptEdits"
    assert summary["defaultMode_set"] is True
    # 全部 harness 白名单都被加入
    assert set(sa.HARNESS_BASH_ALLOW).issubset(set(new["permissions"]["allow"]))
    assert summary["added_allow"] == list(sa.HARNESS_BASH_ALLOW)


def test_merge_preserves_existing_deny_and_other_keys():
    existing = {
        "permissions": {"deny": ["Read(.env)", "Read(.secrets)"], "allow": ["Bash(ls *)"]},
        "enabledPlugins": {"foo": True},
    }
    new, _ = sa.merge_auto_permissions(existing)
    # deny 原样保留
    assert new["permissions"]["deny"] == ["Read(.env)", "Read(.secrets)"]
    # 其它顶层键保留
    assert new["enabledPlugins"] == {"foo": True}
    # 既有 allow 项保留 + harness 项追加
    assert "Bash(ls *)" in new["permissions"]["allow"]
    assert "Bash(npc *)" in new["permissions"]["allow"]


def test_merge_idempotent():
    new1, s1 = sa.merge_auto_permissions({})
    new2, s2 = sa.merge_auto_permissions(new1)
    # 第二次不再改 mode、不再加 allow
    assert s2["defaultMode_set"] is False
    assert s2["added_allow"] == []
    assert new2["permissions"]["allow"] == new1["permissions"]["allow"]


def test_merge_does_not_mutate_input():
    existing = {"permissions": {"allow": ["Bash(ls *)"]}}
    sa.merge_auto_permissions(existing)
    # 原对象不被改
    assert existing == {"permissions": {"allow": ["Bash(ls *)"]}}


def test_merge_respects_existing_acceptedits_mode():
    existing = {"permissions": {"defaultMode": "acceptEdits"}}
    _, summary = sa.merge_auto_permissions(existing)
    assert summary["defaultMode_set"] is False


# ============================================================
# grant_auto_permissions 落盘
# ============================================================


def test_grant_creates_settings(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    res = sa.grant_auto_permissions(repo)
    assert res["ok"] is True
    assert res["created"] is True
    sp = repo / ".claude" / "settings.json"
    assert sp.is_file()
    data = json.loads(sp.read_text())
    assert data["permissions"]["defaultMode"] == "acceptEdits"
    assert "Bash(npc *)" in data["permissions"]["allow"]


def test_grant_merges_existing_preserves_deny(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    sp = repo / ".claude" / "settings.json"
    sp.write_text(json.dumps({"permissions": {"deny": ["Read(.env)"]}, "hooks": {"x": 1}}))
    res = sa.grant_auto_permissions(repo)
    assert res["ok"] is True
    assert res["created"] is False
    data = json.loads(sp.read_text())
    assert data["permissions"]["deny"] == ["Read(.env)"]
    assert data["hooks"] == {"x": 1}
    assert data["permissions"]["defaultMode"] == "acceptEdits"


def test_grant_idempotent_on_disk(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sa.grant_auto_permissions(repo)
    res2 = sa.grant_auto_permissions(repo)
    assert res2["ok"] is True
    assert res2["defaultMode_set"] is False
    assert res2["added_allow"] == []


def test_grant_skips_unparseable_without_clobber(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    sp = repo / ".claude" / "settings.json"
    sp.write_text("{ this is not json")
    res = sa.grant_auto_permissions(repo)
    assert res["ok"] is False
    assert res["skipped"] == "unparseable"
    # 原文件未被覆盖
    assert sp.read_text() == "{ this is not json"


def test_grant_skips_non_object(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    sp = repo / ".claude" / "settings.json"
    sp.write_text("[1, 2, 3]")
    res = sa.grant_auto_permissions(repo)
    assert res["ok"] is False
    assert res["skipped"] == "not-an-object"


# ============================================================
# additionalDirectories：merge 纯函数
# ============================================================


def test_merge_dirs_empty_adds_all():
    new, summary = sa.merge_additional_dirs({}, ["/a", "/b"])
    assert new["permissions"]["additionalDirectories"] == ["/a", "/b"]
    assert summary["added_dirs"] == ["/a", "/b"]


def test_merge_dirs_idempotent_and_preserves():
    existing = {"permissions": {"additionalDirectories": ["/a"], "deny": ["Read(.env)"]}}
    new, summary = sa.merge_additional_dirs(existing, ["/a", "/b"])
    # 已存在的不重复；deny 原样保留
    assert new["permissions"]["additionalDirectories"] == ["/a", "/b"]
    assert summary["added_dirs"] == ["/b"]
    assert new["permissions"]["deny"] == ["Read(.env)"]


def test_merge_dirs_does_not_mutate_input():
    existing = {"permissions": {"additionalDirectories": ["/a"]}}
    sa.merge_additional_dirs(existing, ["/b"])
    assert existing == {"permissions": {"additionalDirectories": ["/a"]}}


def test_auto_local_dirs_uses_home():
    dirs = sa.auto_local_dirs(home=Path("/home/x"))
    assert "/home/x/.spine/worktrees" in dirs
    assert "/home/x/task_log" in dirs


# ============================================================
# grant_auto_local_dirs：落 settings.local.json
# ============================================================


def test_grant_local_dirs_creates_local_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    res = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res["ok"] is True
    assert res["created"] is True
    # 只写 settings.local.json，绝不碰 settings.json
    lp = repo / ".claude" / "settings.local.json"
    assert lp.is_file()
    assert not (repo / ".claude" / "settings.json").exists()
    data = json.loads(lp.read_text())
    assert "/home/x/.spine/worktrees" in data["permissions"]["additionalDirectories"]


def test_grant_local_dirs_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    res2 = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res2["ok"] is True
    assert res2["added_dirs"] == []
    data = json.loads((repo / ".claude" / "settings.local.json").read_text())
    # 不重复累加
    assert data["permissions"]["additionalDirectories"].count("/home/x/task_log") == 1


def test_grant_local_dirs_merges_existing_allow(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    lp = repo / ".claude" / "settings.local.json"
    lp.write_text(json.dumps({"permissions": {"allow": ["Bash(ls *)"]}}))
    res = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res["ok"] is True
    data = json.loads(lp.read_text())
    # 既有 allow 保留 + additionalDirectories 追加
    assert data["permissions"]["allow"] == ["Bash(ls *)"]
    assert "/home/x/.spine/worktrees" in data["permissions"]["additionalDirectories"]


def test_grant_local_dirs_skips_unparseable(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    lp = repo / ".claude" / "settings.local.json"
    lp.write_text("{ not json")
    res = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res["ok"] is False
    assert res["skipped"] == "unparseable"
    assert lp.read_text() == "{ not json"


# ============================================================
# merge_auto_deny 纯函数（deny 底线）
# ============================================================


def test_merge_deny_empty_adds_all_rules():
    new, summary = sa.merge_auto_deny({})
    assert set(sa.AUTO_DENY_RULES).issubset(set(new["permissions"]["deny"]))
    assert summary["added_deny"] == list(sa.AUTO_DENY_RULES)


def test_merge_deny_preserves_existing_user_deny():
    existing = {"permissions": {"deny": ["Read(.env)", "Read(.secrets)"]}}
    new, summary = sa.merge_auto_deny(existing)
    # 用户条目原样保留
    assert "Read(.env)" in new["permissions"]["deny"]
    assert "Read(.secrets)" in new["permissions"]["deny"]
    # harness deny 追加
    assert "Bash(git push --force*)" in new["permissions"]["deny"]
    assert "Bash(git reset --hard*)" in new["permissions"]["deny"]
    assert "Edit(.git/**)" in new["permissions"]["deny"]


def test_merge_deny_idempotent():
    new1, s1 = sa.merge_auto_deny({})
    new2, s2 = sa.merge_auto_deny(new1)
    # 第二次不再追加
    assert s2["added_deny"] == []
    assert new2["permissions"]["deny"] == new1["permissions"]["deny"]


def test_merge_deny_does_not_mutate_input():
    existing = {"permissions": {"deny": ["Read(.env)"]}}
    sa.merge_auto_deny(existing)
    assert existing == {"permissions": {"deny": ["Read(.env)"]}}


# ============================================================
# grant_auto_local_dirs：verify deny rules written
# ============================================================


def test_grant_local_dirs_writes_deny_rules(tmp_path):
    """Task 3.1：空 settings.local.json → 三条 deny 写入。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    res = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res["ok"] is True
    lp = repo / ".claude" / "settings.local.json"
    data = json.loads(lp.read_text())
    deny = data["permissions"]["deny"]
    assert "Bash(git push --force*)" in deny
    assert "Bash(git reset --hard*)" in deny
    assert "Edit(.git/**)" in deny
    assert set(sa.AUTO_DENY_RULES).issubset(set(deny))
    assert res["added_deny"] == list(sa.AUTO_DENY_RULES)


def test_grant_local_dirs_preserves_user_deny(tmp_path):
    """Task 3.2：用户已有 deny → 并集保留用户条目。"""
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    lp = repo / ".claude" / "settings.local.json"
    lp.write_text(json.dumps({"permissions": {"deny": ["Read(.env)", "Read(.secrets)"]}}))
    res = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res["ok"] is True
    data = json.loads(lp.read_text())
    deny = data["permissions"]["deny"]
    # 用户条目保留
    assert "Read(.env)" in deny
    assert "Read(.secrets)" in deny
    # harness deny 追加
    assert "Bash(git push --force*)" in deny
    assert "Bash(git reset --hard*)" in deny
    assert "Edit(.git/**)" in deny


def test_grant_local_dirs_deny_idempotent(tmp_path):
    """Task 3.3：重复运行 init --auto → deny 无重复条目。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    res2 = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res2["ok"] is True
    assert res2["added_deny"] == []
    data = json.loads((repo / ".claude" / "settings.local.json").read_text())
    deny = data["permissions"]["deny"]
    # 无重复
    assert deny.count("Bash(git push --force*)") == 1
    assert deny.count("Bash(git reset --hard*)") == 1
    assert deny.count("Edit(.git/**)") == 1


def test_grant_local_dirs_bad_json_not_overwritten(tmp_path):
    """Task 3.4：坏 JSON → 不覆盖、init 不失败（返回 ok=False）。"""
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    lp = repo / ".claude" / "settings.local.json"
    lp.write_text("{ this is not valid json")
    res = sa.grant_auto_local_dirs(repo, home=Path("/home/x"))
    assert res["ok"] is False
    assert res["skipped"] == "unparseable"
    # 原文件未被覆盖
    assert lp.read_text() == "{ this is not valid json"
