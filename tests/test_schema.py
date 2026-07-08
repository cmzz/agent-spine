"""schema 模块测试。"""

from __future__ import annotations

import json

import jsonschema
import pytest

from npc import schema as _schema


def test_ensure_schema_creates_when_missing(tmp_path):
    target = tmp_path / "sub" / "schema.json"
    created = _schema.ensure_schema(target)
    assert created is True
    assert target.exists()
    # 父目录被一并创建
    assert target.parent.is_dir()
    data = json.loads(target.read_text())
    assert data == _schema.REVIEW_SCHEMA
    assert "findings" in data["properties"]
    # 关键 enum 存在
    assert "approve" in data["properties"]["verdict"]["enum"]
    assert "critical" in data["properties"]["findings"]["items"]["properties"]["severity"]["enum"]


def test_ensure_schema_rewrites_stale_content(tmp_path):
    """schema_path 存在但内容缺 spec_attribution → 被重写为 REVIEW_SCHEMA（修 write-once 缺陷）。"""
    target = tmp_path / "schema.json"
    stale = json.loads(json.dumps(_schema.REVIEW_SCHEMA))
    del stale["properties"]["findings"]["items"]["properties"]["spec_attribution"]
    stale["properties"]["findings"]["items"]["required"].remove("spec_attribution")
    target.write_text(json.dumps(stale), encoding="utf-8")

    created = _schema.ensure_schema(target)

    assert created is True
    assert json.loads(target.read_text(encoding="utf-8")) == _schema.REVIEW_SCHEMA


def test_ensure_schema_idempotent_same_content(tmp_path):
    """内容已等于 REVIEW_SCHEMA 时连续两次调用 → 第二次不重写（mtime 不变）。"""
    target = tmp_path / "schema.json"
    _schema.ensure_schema(target)
    t0 = target.stat().st_mtime_ns

    created_again = _schema.ensure_schema(target)

    assert created_again is False
    assert target.stat().st_mtime_ns == t0


def test_ensure_schema_indent_and_key_order_do_not_trigger_rewrite(tmp_path):
    """键序/缩进差异（语义相等）不触发重写。"""
    target = tmp_path / "schema.json"
    # 用不同缩进（0）+ 顶层键反序写入语义相同的内容
    reordered = dict(reversed(list(_schema.REVIEW_SCHEMA.items())))
    target.write_text(json.dumps(reordered, indent=0, ensure_ascii=False), encoding="utf-8")
    t0_written = target.stat().st_mtime_ns

    created = _schema.ensure_schema(target)

    assert created is False
    assert target.stat().st_mtime_ns == t0_written


def test_ensure_schema_corrupt_json_is_rewritten(tmp_path):
    """损坏的 JSON 视为不等，触发重写。"""
    target = tmp_path / "schema.json"
    target.write_text("not-json{{{", encoding="utf-8")

    created = _schema.ensure_schema(target)

    assert created is True
    assert json.loads(target.read_text(encoding="utf-8")) == _schema.REVIEW_SCHEMA


def test_review_schema_structure_is_strict():
    s = _schema.REVIEW_SCHEMA
    finding = s["properties"]["findings"]["items"]
    assert finding["additionalProperties"] is False
    for key in (
        "id",
        "severity",
        "category",
        "title",
        "file",
        "line_range",
        "detail",
        "recommendation",
        "in_scope",
        "spec_attribution",
    ):
        assert key in finding["required"]


def test_review_schema_spec_attribution_enum():
    s = _schema.REVIEW_SCHEMA
    finding = s["properties"]["findings"]["items"]
    assert finding["properties"]["spec_attribution"]["enum"] == [
        "spec-silent",
        "spec-ambiguous",
        "spec-contradicted",
        "impl-deviation",
    ]
    assert "spec_attribution" in finding["required"]
    assert finding["additionalProperties"] is False


def test_review_schema_rejects_invalid_spec_attribution():
    finding = {
        "id": "F1",
        "severity": "critical",
        "category": "validation",
        "title": "x",
        "file": "-",
        "line_range": "-",
        "detail": "d",
        "recommendation": "r",
        "in_scope": True,
        "spec_attribution": "maybe-spec",
    }
    payload = {"verdict": "changes-requested", "findings": [finding]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _schema.REVIEW_SCHEMA)
