"""Unit tests for the pure validation/helpers layer."""

from __future__ import annotations

import pytest

from siyuan_mcp.validation import (
    build_doc_path,
    detect_frontmatter,
    ensure_select_only,
    is_block_id,
    normalize_attributes,
    parse_frontmatter,
    require_block_id,
)


# --------------------------------------------------------------- block IDs


@pytest.mark.parametrize(
    "value,expected",
    [
        ("20260619181928-palr67f", True),
        ("20260619181928-PALR67F", True),
        ("not-an-id", False),
        ("2026-palr67f", False),
        ("20260619181928palr67f", False),
        ("", False),
        (None, False),
    ],
)
def test_is_block_id(value, expected):
    assert is_block_id(value) is expected


def test_require_block_id_message_is_actionable():
    with pytest.raises(ValueError) as exc:
        require_block_id("oops")
    msg = str(exc.value)
    assert "20260619181928-palr67f" in msg
    assert "search_blocks" in msg


# ------------------------------------------------------------- doc paths


def test_build_doc_path_root():
    assert build_doc_path("Weekly Review") == "/Weekly Review"


def test_build_doc_path_with_parent():
    assert build_doc_path("My Doc", "/99 Archive") == "/99 Archive/My Doc"


def test_build_doc_path_normalizes_parent_slashes():
    assert build_doc_path("My Doc", "99 Archive/") == "/99 Archive/My Doc"


def test_build_doc_path_empty_title_rejected():
    with pytest.raises(ValueError) as exc:
        build_doc_path("   ")
    assert "title" in str(exc.value).lower()


def test_build_doc_path_title_with_slash_rejected_with_guidance():
    with pytest.raises(ValueError) as exc:
        build_doc_path("a/b")
    msg = str(exc.value)
    assert "parent_path" in msg
    assert "/" in msg


# ----------------------------------------------------------- frontmatter


def test_detect_frontmatter_none():
    fm, body = detect_frontmatter("# Title\n\nplain body")
    assert fm is None
    assert body == "# Title\n\nplain body"


def test_detect_frontmatter_strips_block():
    md = "---\ntitle: X\nstatus: raw-dump\n---\n\nReal content here"
    fm, body = detect_frontmatter(md)
    assert fm is not None
    assert "status: raw-dump" in fm
    assert body == "Real content here"


def test_detect_frontmatter_requires_leading_fence():
    md = "Some intro\n\n---\nnot frontmatter\n---\n"
    fm, body = detect_frontmatter(md)
    assert fm is None
    assert body == md


def test_parse_frontmatter_scalars_and_lists():
    fm = "title: TickTick Dump\nstatus: raw-dump\nscope: [Cuisines, Cooking, To Watch]"
    parsed = parse_frontmatter(fm)
    assert parsed["status"] == "raw-dump"
    assert parsed["scope"] == "Cuisines, Cooking, To Watch"


# ------------------------------------------------------------- attributes


def test_normalize_attributes_prefixes_custom():
    normalized, notes = normalize_attributes({"status": "draft", "source": "TickTick"})
    assert normalized == {"custom-status": "draft", "custom-source": "TickTick"}
    assert len(notes) == 2


def test_normalize_attributes_keeps_existing_prefix_and_builtins():
    normalized, _ = normalize_attributes({"custom-x": "1", "alias": "foo"})
    assert normalized == {"custom-x": "1", "alias": "foo"}


def test_normalize_attributes_tags_is_builtin_not_prefixed():
    # `tags` sets real SiYuan document tags; it must NOT become `custom-tags`.
    normalized, notes = normalize_attributes({"tags": "project, urgent"})
    assert normalized == {"tags": "project, urgent"}
    assert notes == []


def test_normalize_attributes_coerces_values():
    normalized, _ = normalize_attributes({"count": 3, "topics": ["a", "b"], "done": True})
    assert normalized["custom-count"] == "3"
    assert normalized["custom-done"] == "true"
    assert normalized["custom-topics"] == '["a", "b"]'


def test_normalize_attributes_empty_rejected():
    with pytest.raises(ValueError):
        normalize_attributes({})


# ------------------------------------------------------------- SQL guard


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM blocks LIMIT 1",
        "  select id from blocks ",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT * FROM blocks LIMIT 1;",
    ],
)
def test_ensure_select_only_accepts_reads(query):
    assert ensure_select_only(query) == query


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM blocks",
        "UPDATE blocks SET content='x'",
        "DROP TABLE blocks",
        "INSERT INTO blocks VALUES (1)",
        "SELECT 1; DROP TABLE blocks",
    ],
)
def test_ensure_select_only_rejects_writes(query):
    with pytest.raises(ValueError) as exc:
        ensure_select_only(query)
    assert "read-only" in str(exc.value) or "single SQL statement" in str(exc.value)
