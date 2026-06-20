"""SiYuan operations, expressed as plain methods on :class:`SiyuanService`.

This layer has no dependency on MCP. It takes a :class:`SiyuanClient` (real or
fake) and returns plain Python data, raising ``ValueError`` / ``SiyuanError``
with actionable English guidance. ``server.py`` wraps each method in a thin
``@mcp.tool()`` so the logic stays unit-testable without a running kernel.
"""

from __future__ import annotations

from typing import Any

from .client import SiyuanClient, SiyuanError
from .validation import (
    BLOCK_ID_RE,
    build_doc_path,
    detect_frontmatter,
    ensure_select_only,
    is_block_id,
    normalize_attributes,
    parse_frontmatter,
    require_block_id,
    sql_escape,
)

_VALID_DATA_TYPES = {"markdown", "dom"}


def _ensure_data_type(data_type: str) -> str:
    if data_type not in _VALID_DATA_TYPES:
        raise ValueError(
            f"`data_type` must be 'markdown' or 'dom' (got {data_type!r}). "
            "Use 'markdown' for normal text/kramdown content."
        )
    return data_type


def _require_notebook_id(notebook_id: str) -> str:
    if not isinstance(notebook_id, str) or not notebook_id.strip():
        raise ValueError(
            "`notebook_id` is required. Call `list_notebooks` first and pass the "
            "`id` of the notebook you want to write to."
        )
    cleaned = notebook_id.strip()
    if not BLOCK_ID_RE.match(cleaned):
        raise ValueError(
            f"`notebook_id` {notebook_id!r} is not a valid notebook ID. Call "
            "`list_notebooks` and use the `id` field (looks like 20210817205410-2kvfpfn)."
        )
    return cleaned


def _extract_inserted_ids(transactions: Any) -> list[str]:
    """Pull the new block IDs out of an insert/append/prepend transaction list."""
    ids: list[str] = []
    if isinstance(transactions, list):
        for txn in transactions:
            if not isinstance(txn, dict):
                continue
            for op in txn.get("doOperations") or []:
                if isinstance(op, dict):
                    op_id = op.get("id")
                    if isinstance(op_id, str) and op_id:
                        ids.append(op_id)
    return ids


class SiyuanService:
    def __init__(self, client: SiyuanClient) -> None:
        self.client = client

    # ------------------------------------------------------------------ reads

    def list_notebooks(self, name_filter: str | None = None) -> list[dict[str, Any]]:
        data = self.client.post("/api/notebook/lsNotebooks")
        notebooks = data.get("notebooks", []) if isinstance(data, dict) else []
        if name_filter:
            needle = name_filter.lower()
            notebooks = [nb for nb in notebooks if needle in str(nb.get("name", "")).lower()]
        return [
            {
                "id": nb.get("id"),
                "name": nb.get("name"),
                "closed": nb.get("closed", False),
                "icon": nb.get("icon", ""),
            }
            for nb in notebooks
            if isinstance(nb, dict)
        ]

    def find_documents(
        self,
        notebook_id: str | None = None,
        title_contains: str | None = None,
        path_prefix: str | None = None,
        created_after: str | None = None,
        updated_after: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conditions = ["type = 'd'"]
        if notebook_id:
            conditions.append(f"box = '{sql_escape(notebook_id.strip())}'")
        if title_contains:
            conditions.append(f"content LIKE '%{sql_escape(title_contains)}%'")
        if path_prefix:
            conditions.append(f"hpath LIKE '{sql_escape(path_prefix)}%'")
        if created_after:
            conditions.append(f"created > '{sql_escape(created_after)}'")
        if updated_after:
            conditions.append(f"updated > '{sql_escape(updated_after)}'")
        query = (
            "SELECT id, content, hpath, box, created, updated FROM blocks WHERE "
            + " AND ".join(conditions)
            + f" ORDER BY updated DESC LIMIT {int(limit)}"
        )
        rows = self.client.post("/api/query/sql", {"stmt": query})
        return [
            {
                "id": row.get("id"),
                "title": row.get("content"),
                "hpath": row.get("hpath"),
                "notebook_id": row.get("box"),
                "created": row.get("created"),
                "updated": row.get("updated"),
            }
            for row in (rows or [])
            if isinstance(row, dict)
        ]

    def search_blocks(
        self,
        query: str,
        notebook_id: str | None = None,
        block_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("`query` is required: a substring to look for in block content.")
        conditions = [f"content LIKE '%{sql_escape(query)}%'"]
        if notebook_id:
            conditions.append(f"box = '{sql_escape(notebook_id.strip())}'")
        if block_type:
            conditions.append(f"type = '{sql_escape(block_type)}'")
        sql = (
            "SELECT id, content, type, subtype, hpath, root_id FROM blocks WHERE "
            + " AND ".join(conditions)
            + f" LIMIT {int(limit)}"
        )
        rows = self.client.post("/api/query/sql", {"stmt": sql})
        return [row for row in (rows or []) if isinstance(row, dict)]

    def get_block_markdown(self, block_id: str) -> dict[str, Any]:
        block_id = require_block_id(block_id)
        result = self.client.post("/api/block/getBlockKramdown", {"id": block_id})
        if not isinstance(result, dict):
            raise SiyuanError(f"Unexpected response reading block {block_id}.")
        return {"id": block_id, "kramdown": result.get("kramdown", "")}

    def get_blocks_markdown(self, block_ids: list[str]) -> list[dict[str, Any]]:
        if not isinstance(block_ids, list) or not block_ids:
            raise ValueError("`block_ids` must be a non-empty list of block IDs.")
        results: list[dict[str, Any]] = []
        for raw_id in block_ids:
            if not is_block_id(raw_id):
                results.append({"id": raw_id, "error": "Not a valid block ID; skipped."})
                continue
            try:
                result = self.client.post("/api/block/getBlockKramdown", {"id": raw_id.strip()})
                results.append({"id": raw_id.strip(), "kramdown": (result or {}).get("kramdown", "")})
            except SiyuanError as exc:
                results.append({"id": raw_id.strip(), "error": str(exc)})
        return results

    def get_block_children(self, block_id: str) -> list[dict[str, Any]]:
        block_id = require_block_id(block_id)
        result = self.client.post("/api/block/getChildBlocks", {"id": block_id})
        return [row for row in (result or []) if isinstance(row, dict)]

    def get_block_attributes(self, block_id: str) -> dict[str, Any]:
        block_id = require_block_id(block_id)
        result = self.client.post("/api/attr/getBlockAttrs", {"id": block_id})
        return result if isinstance(result, dict) else {}

    def query_sql(self, query: str) -> list[dict[str, Any]]:
        ensure_select_only(query)
        result = self.client.post("/api/query/sql", {"stmt": query})
        return [row for row in (result or []) if isinstance(row, dict)]

    def list_files(self, path: str) -> list[dict[str, Any]]:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("`path` is required, e.g. '/data' or '/data/assets'.")
        result = self.client.post("/api/file/readDir", {"path": path})
        return [row for row in (result or []) if isinstance(row, dict)]

    def read_file(self, path: str) -> dict[str, Any]:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("`path` is required, e.g. '/data/assets/note.txt'.")
        raw = self.client.post_raw_bytes("/api/file/getFile", {"path": path})
        try:
            return {"path": path, "content": raw.decode("utf-8"), "binary": False}
        except UnicodeDecodeError:
            return {
                "path": path,
                "content": None,
                "binary": True,
                "note": "File is not UTF-8 text; cannot return as a string.",
            }

    # ----------------------------------------------------------------- writes

    def create_document(
        self,
        notebook_id: str,
        title: str,
        markdown: str = "",
        parent_path: str = "/",
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        notebook_id = _require_notebook_id(notebook_id)
        path = build_doc_path(title, parent_path)

        warnings: list[str] = []
        body = markdown or ""
        merged_attrs: dict[str, Any] = {}

        frontmatter_text, stripped_body = detect_frontmatter(body)
        if frontmatter_text is not None:
            parsed = parse_frontmatter(frontmatter_text)
            merged_attrs.update(parsed)
            body = stripped_body
            if parsed:
                warnings.append(
                    "Stripped YAML frontmatter from `markdown` (SiYuan does not parse it) "
                    f"and converted these keys to custom block attributes: {', '.join(parsed)}."
                )
            else:
                warnings.append(
                    "Stripped an empty/unparsable YAML frontmatter block from `markdown` "
                    "(SiYuan does not parse frontmatter)."
                )

        # Explicit attributes win over anything pulled from frontmatter.
        if attributes:
            merged_attrs.update(attributes)

        doc_id = self.client.post(
            "/api/filetree/createDocWithMd",
            {"notebook": notebook_id, "path": path, "markdown": body},
        )
        if not isinstance(doc_id, str) or not doc_id:
            raise SiyuanError("SiYuan did not return a document ID for the created document.")

        applied: dict[str, str] = {}
        if merged_attrs:
            applied, attr_notes = normalize_attributes(merged_attrs)
            self.client.post("/api/attr/setBlockAttrs", {"id": doc_id, "attrs": applied})
            warnings.extend(attr_notes)

        return {
            "id": doc_id,
            "notebook_id": notebook_id,
            "title": title.strip(),
            "path": path,
            "attributes": applied,
            "warnings": warnings,
        }

    def insert_block(
        self,
        markdown: str,
        previous_id: str | None = None,
        next_id: str | None = None,
        parent_id: str | None = None,
        data_type: str = "markdown",
    ) -> dict[str, Any]:
        _ensure_data_type(data_type)
        if not (previous_id or next_id or parent_id):
            raise ValueError(
                "insert_block needs an anchor: pass one of `previous_id` (insert after it), "
                "`next_id` (insert before it), or `parent_id` (insert as a child). For a "
                "stable parent/child relationship prefer `append_block` or `prepend_block`."
            )
        payload = {
            "dataType": data_type,
            "data": markdown,
            "previousID": require_block_id(previous_id, "previous_id") if previous_id else "",
            "nextID": require_block_id(next_id, "next_id") if next_id else "",
            "parentID": require_block_id(parent_id, "parent_id") if parent_id else "",
        }
        result = self.client.post("/api/block/insertBlock", payload)
        ids = _extract_inserted_ids(result)
        return {"id": ids[0] if ids else None, "ids": ids}

    def prepend_block(self, parent_id: str, markdown: str, data_type: str = "markdown") -> dict[str, Any]:
        parent_id = require_block_id(parent_id, "parent_id")
        _ensure_data_type(data_type)
        result = self.client.post(
            "/api/block/prependBlock",
            {"parentID": parent_id, "data": markdown, "dataType": data_type},
        )
        ids = _extract_inserted_ids(result)
        return {"id": ids[0] if ids else None, "ids": ids, "parent_id": parent_id}

    def append_block(self, parent_id: str, markdown: str, data_type: str = "markdown") -> dict[str, Any]:
        parent_id = require_block_id(parent_id, "parent_id")
        _ensure_data_type(data_type)
        result = self.client.post(
            "/api/block/appendBlock",
            {"parentID": parent_id, "data": markdown, "dataType": data_type},
        )
        ids = _extract_inserted_ids(result)
        return {"id": ids[0] if ids else None, "ids": ids, "parent_id": parent_id}

    def update_block(self, block_id: str, markdown: str, data_type: str = "markdown") -> dict[str, Any]:
        block_id = require_block_id(block_id)
        _ensure_data_type(data_type)
        if not isinstance(markdown, str):
            raise ValueError("`markdown` must be a string (the full replacement content for the block).")
        self.client.post(
            "/api/block/updateBlock",
            {"id": block_id, "data": markdown, "dataType": data_type},
        )
        return {"id": block_id, "updated": True}

    def move_block(self, block_id: str, parent_id: str | None = None, previous_id: str | None = None) -> dict[str, Any]:
        block_id = require_block_id(block_id)
        if not (parent_id or previous_id):
            raise ValueError(
                "move_block needs a destination: pass `previous_id` (move after that block) "
                "and/or `parent_id` (move under that parent)."
            )
        payload: dict[str, str] = {"id": block_id}
        if previous_id:
            payload["previousID"] = require_block_id(previous_id, "previous_id")
        if parent_id:
            payload["parentID"] = require_block_id(parent_id, "parent_id")
        self.client.post("/api/block/moveBlock", payload)
        return {"id": block_id, "moved": True, "parent_id": parent_id, "previous_id": previous_id}

    def delete_block(self, block_id: str) -> dict[str, Any]:
        block_id = require_block_id(block_id)
        rows = self.client.post(
            "/api/query/sql",
            {"stmt": f"SELECT type FROM blocks WHERE id = '{sql_escape(block_id)}' LIMIT 1"},
        )
        if rows and isinstance(rows[0], dict) and rows[0].get("type") == "d":
            raise ValueError(
                f"{block_id} is a document block. delete_block refuses to delete whole "
                "documents (it is destructive and not reversible via this server). Delete "
                "the document manually in SiYuan if you really intend to."
            )
        self.client.post("/api/block/deleteBlock", {"id": block_id})
        return {"id": block_id, "deleted": True}

    def set_block_attributes(self, block_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
        block_id = require_block_id(block_id)
        normalized, notes = normalize_attributes(attributes)
        self.client.post("/api/attr/setBlockAttrs", {"id": block_id, "attrs": normalized})
        return {"id": block_id, "attributes": normalized, "notes": notes}

    def notify(self, message: str) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("`message` must be a non-empty string.")
        self.client.post("/api/notification/pushMsg", {"msg": message, "timeout": 7000})
        return {"shown": True, "message": message}
