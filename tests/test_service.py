"""Tests for SiyuanService using a fake client (no running kernel)."""

from __future__ import annotations

import pytest

from siyuan_mcp.client import SiyuanError
from siyuan_mcp.service import SiyuanService


class FakeClient:
    """Records calls and returns canned responses keyed by endpoint."""

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict | None]] = []

    def post(self, endpoint, payload=None):
        self.calls.append((endpoint, payload))
        value = self.responses.get(endpoint, None)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(payload)
        return value

    def post_raw_bytes(self, endpoint, payload=None):
        self.calls.append((endpoint, payload))
        return self.responses.get(endpoint, b"")

    def payloads_for(self, endpoint):
        return [p for (e, p) in self.calls if e == endpoint]


# An insert/append-style transaction with a fresh block id.
def _txn(new_id: str):
    return [{"doOperations": [{"action": "insert", "id": new_id}], "undoOperations": None}]


NOTEBOOK_ID = "20260101090000-abc1234"
NEW_DOC_ID = "20260619181928-palr67f"


# ----------------------------------------------------- create_document


def test_create_document_sets_title_via_path_and_returns_id():
    client = FakeClient({"/api/filetree/createDocWithMd": NEW_DOC_ID})
    svc = SiyuanService(client)

    result = svc.create_document(
        notebook_id=NOTEBOOK_ID,
        title="TickTick Reference Lists Raw Dump",
        markdown="Some body content",
        parent_path="/99 Archive",
    )

    assert result["id"] == NEW_DOC_ID
    assert result["title"] == "TickTick Reference Lists Raw Dump"
    assert result["path"] == "/99 Archive/TickTick Reference Lists Raw Dump"

    # The kernel got the title via the path, and the raw body unchanged.
    payload = client.payloads_for("/api/filetree/createDocWithMd")[0]
    assert payload["path"] == "/99 Archive/TickTick Reference Lists Raw Dump"
    assert payload["notebook"] == NOTEBOOK_ID
    assert payload["markdown"] == "Some body content"


def test_create_document_strips_frontmatter_and_converts_to_attributes():
    client = FakeClient(
        {
            "/api/filetree/createDocWithMd": NEW_DOC_ID,
            "/api/attr/setBlockAttrs": None,
        }
    )
    svc = SiyuanService(client)

    md = (
        "---\n"
        "title: TickTick Reference Lists Raw Dump\n"
        "status: raw-dump\n"
        "source: TickTick\n"
        "scope: [Cuisines, Cooking, To Watch]\n"
        "---\n\n"
        "## Real content\n\nbody"
    )
    result = svc.create_document(notebook_id=NOTEBOOK_ID, title="TickTick Dump", markdown=md)

    # Frontmatter removed from the body that reaches SiYuan.
    body = client.payloads_for("/api/filetree/createDocWithMd")[0]["markdown"]
    assert "---" not in body
    assert body.startswith("## Real content")

    # Frontmatter keys became custom-* attributes.
    attrs = client.payloads_for("/api/attr/setBlockAttrs")[0]["attrs"]
    assert attrs["custom-status"] == "raw-dump"
    assert attrs["custom-source"] == "TickTick"
    assert attrs["custom-scope"] == "Cuisines, Cooking, To Watch"

    # The agent is told what happened.
    assert any("frontmatter" in w.lower() for w in result["warnings"])
    assert result["id"] == NEW_DOC_ID


def test_create_document_explicit_attributes_override_frontmatter():
    client = FakeClient(
        {"/api/filetree/createDocWithMd": NEW_DOC_ID, "/api/attr/setBlockAttrs": None}
    )
    svc = SiyuanService(client)
    md = "---\nstatus: raw-dump\n---\nbody"
    svc.create_document(
        notebook_id=NOTEBOOK_ID,
        title="X",
        markdown=md,
        attributes={"status": "published"},
    )
    attrs = client.payloads_for("/api/attr/setBlockAttrs")[0]["attrs"]
    assert attrs["custom-status"] == "published"


def test_create_document_missing_notebook_guidance():
    svc = SiyuanService(FakeClient())
    with pytest.raises(ValueError) as exc:
        svc.create_document(notebook_id="", title="X")
    assert "list_notebooks" in str(exc.value)


def test_create_document_title_in_path_not_required():
    # Title with a slash should be rejected with guidance toward parent_path.
    svc = SiyuanService(FakeClient())
    with pytest.raises(ValueError) as exc:
        svc.create_document(notebook_id=NOTEBOOK_ID, title="a/b")
    assert "parent_path" in str(exc.value)


# ----------------------------------------------------- block writes return ids


def test_append_block_returns_new_id():
    client = FakeClient({"/api/block/appendBlock": _txn(NEW_DOC_ID)})
    svc = SiyuanService(client)
    result = svc.append_block(parent_id=NOTEBOOK_ID, markdown="hello")
    assert result["id"] == NEW_DOC_ID
    assert result["ids"] == [NEW_DOC_ID]


def test_insert_block_requires_anchor():
    svc = SiyuanService(FakeClient())
    with pytest.raises(ValueError) as exc:
        svc.insert_block(markdown="x")
    assert "previous_id" in str(exc.value) and "parent_id" in str(exc.value)


def test_insert_block_returns_id():
    client = FakeClient({"/api/block/insertBlock": _txn(NEW_DOC_ID)})
    svc = SiyuanService(client)
    result = svc.insert_block(markdown="x", previous_id=NOTEBOOK_ID)
    assert result["id"] == NEW_DOC_ID


# ----------------------------------------------------- query_sql guard


def test_query_sql_rejects_writes_with_guidance():
    svc = SiyuanService(FakeClient())
    with pytest.raises(ValueError) as exc:
        svc.query_sql("DELETE FROM blocks")
    assert "block tools" in str(exc.value)


def test_query_sql_allows_select():
    client = FakeClient({"/api/query/sql": [{"id": "1"}]})
    svc = SiyuanService(client)
    assert svc.query_sql("SELECT id FROM blocks LIMIT 1") == [{"id": "1"}]


# ----------------------------------------------------- error message quality


def test_bad_block_id_message_quality():
    svc = SiyuanService(FakeClient())
    with pytest.raises(ValueError) as exc:
        svc.get_block_markdown("garbage")
    msg = str(exc.value)
    assert "20260619181928-palr67f" in msg


def test_delete_block_refuses_documents():
    client = FakeClient({"/api/query/sql": [{"type": "d"}]})
    svc = SiyuanService(client)
    with pytest.raises(ValueError) as exc:
        svc.delete_block(NEW_DOC_ID)
    assert "document" in str(exc.value).lower()
    # It must not have called deleteBlock.
    assert client.payloads_for("/api/block/deleteBlock") == []


def test_set_block_attributes_prefixes_and_calls_api():
    client = FakeClient({"/api/attr/setBlockAttrs": None})
    svc = SiyuanService(client)
    result = svc.set_block_attributes(NEW_DOC_ID, {"status": "draft"})
    assert result["attributes"] == {"custom-status": "draft"}
    sent = client.payloads_for("/api/attr/setBlockAttrs")[0]
    assert sent["attrs"] == {"custom-status": "draft"}


def test_find_documents_filters_on_title_content():
    captured = {}

    def capture(payload):
        captured["stmt"] = payload["stmt"]
        return [{"id": "1", "content": "My Title", "hpath": "/x", "box": NOTEBOOK_ID}]

    client = FakeClient({"/api/query/sql": capture})
    svc = SiyuanService(client)
    rows = svc.find_documents(title_contains="Title")
    # Filters on the title column (content), not the block `name`.
    assert "content LIKE" in captured["stmt"]
    assert "type = 'd'" in captured["stmt"]
    assert rows[0]["title"] == "My Title"


def test_client_error_propagates_as_message():
    client = FakeClient({"/api/notebook/lsNotebooks": SiyuanError("kernel down")})
    svc = SiyuanService(client)
    with pytest.raises(SiyuanError) as exc:
        svc.list_notebooks()
    assert "kernel down" in str(exc.value)
