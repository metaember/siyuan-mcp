"""FastMCP server exposing SiYuan as English, ergonomic MCP tools.

Transport: streamable-HTTP on 0.0.0.0:8000 at /mcp. Configure with env vars
``SIYUAN_API_URL`` (e.g. http://siyuan:6806) and ``SIYUAN_API_TOKEN``.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .client import SiyuanClient
from .service import SiyuanService

SERVER_INSTRUCTIONS = """\
This server drives a SiYuan notebook (notebooks -> documents -> blocks).

Key facts that prevent the most common mistakes:
- A document's TITLE comes from the `title` parameter (the last path segment),
  NOT from YAML frontmatter or a leading `# heading`. SiYuan does not parse
  frontmatter; a leading `---` block just becomes a horizontal rule plus text.
- Attach metadata (status, source, tags) with `set_block_attributes`
  (`custom-*` attributes), not frontmatter.
- Block IDs look like `20260619181928-palr67f`. Get them from `list_notebooks`,
  `find_documents`, `search_blocks`, `query_sql`, or a write tool's return value.
- `query_sql` is read-only (SELECT). Use the block tools to change content.

Typical flow: `list_notebooks` -> `create_document(title=..., notebook_id=...)`
-> capture the returned `id` -> `append_block`/`set_block_attributes` using it.
"""

mcp = FastMCP(
    "siyuan",
    instructions=SERVER_INSTRUCTIONS,
    host="0.0.0.0",
    port=8000,
    streamable_http_path="/mcp",
    # CRITICAL: the airlock gateway forwards a `Host: siyuan-mcp:8000` header that
    # the MCP SDK's DNS-rebinding protection would reject ("Invalid Host header").
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_service: SiyuanService | None = None


def service() -> SiyuanService:
    """Lazily build the service from env vars on first use."""
    global _service
    if _service is None:
        _service = SiyuanService(SiyuanClient.from_env())
    return _service


# ===================================================================== reads


@mcp.tool()
def list_notebooks(name_filter: str | None = None) -> list[dict[str, Any]]:
    """List SiYuan notebooks (the top-level containers for documents).

    Call this first to get a notebook `id` to pass to `create_document` and other
    tools. Optionally filter by a case-insensitive substring of the notebook name.

    Returns a list of {id, name, closed, icon}.
    """
    return service().list_notebooks(name_filter=name_filter)


@mcp.tool()
def find_documents(
    notebook_id: str | None = None,
    title_contains: str | None = None,
    path_prefix: str | None = None,
    created_after: str | None = None,
    updated_after: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Find documents (whole notes), optionally filtered.

    Filters: `notebook_id` (restrict to one notebook), `title_contains`
    (substring of the document title), `path_prefix` (human path prefix such as
    '/99 Archive'), `created_after` / `updated_after` (timestamps formatted
    YYYYMMDDHHMMSS). Results are newest-updated first.

    Returns a list of {id, title, hpath, notebook_id, created, updated}.
    """
    return service().find_documents(
        notebook_id=notebook_id,
        title_contains=title_contains,
        path_prefix=path_prefix,
        created_after=created_after,
        updated_after=updated_after,
        limit=limit,
    )


@mcp.tool()
def search_blocks(
    query: str,
    notebook_id: str | None = None,
    block_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Full-text search for blocks whose content contains `query`.

    This is the main way to locate blocks (and their IDs) to read or edit.
    Optionally restrict to a `notebook_id` or a `block_type` (e.g. 'p' paragraph,
    'h' heading, 'l' list, 'd' document, 'c' code, 't' table).

    Returns a list of {id, content, type, subtype, hpath, root_id}.
    """
    return service().search_blocks(query=query, notebook_id=notebook_id, block_type=block_type, limit=limit)


@mcp.tool()
def get_block_markdown(block_id: str) -> dict[str, Any]:
    """Get the full kramdown (SiYuan-flavored markdown) of a single block.

    Returns {id, kramdown}. The kramdown includes SiYuan attribute markers like
    `{: id="..."}`.
    """
    return service().get_block_markdown(block_id)


@mcp.tool()
def get_blocks_markdown(block_ids: list[str]) -> list[dict[str, Any]]:
    """Get kramdown for several blocks at once.

    Returns a list of {id, kramdown}; entries that fail return {id, error}
    instead of aborting the whole batch.
    """
    return service().get_blocks_markdown(block_ids)


@mcp.tool()
def get_block_children(block_id: str) -> list[dict[str, Any]]:
    """List the direct child blocks of a block (e.g. blocks inside a document).

    Useful to discover the IDs of blocks under a document or heading before
    editing. Returns the children as SiYuan returns them (includes id, type,
    subtype).
    """
    return service().get_block_children(block_id)


@mcp.tool()
def get_block_attributes(block_id: str) -> dict[str, Any]:
    """Get all attributes of a block, including any `custom-*` metadata.

    This is how you read back metadata set via `set_block_attributes`. Returns a
    dict of {attribute_name: value} (plus built-ins like id/type/updated).
    """
    return service().get_block_attributes(block_id)


@mcp.tool()
def query_sql(query: str) -> list[dict[str, Any]]:
    """Run a read-only SQL SELECT against SiYuan's SQLite index.

    SELECT/WITH only - write statements are rejected (use the block tools to
    mutate). Always include an explicit LIMIT (the kernel otherwise caps results
    at a small default).

    Main table `blocks` columns: id, content (plain text), markdown, type,
    subtype, root_id (containing doc id), box (notebook id), hpath (human path),
    name, tag (space-joined `#tag#` tokens), ial, created, updated.

    Other useful tables: `attributes(block_id, name, value)` - the reliable way
    to query custom metadata; `refs(block_id, def_block_id, content)` - block
    references / backlinks.

    Examples:
      SELECT id, content, hpath FROM blocks WHERE type='d' AND content LIKE '%review%' ORDER BY updated DESC LIMIT 10
      SELECT b.* FROM blocks b JOIN attributes a ON a.block_id=b.id WHERE a.name='custom-status' AND a.value='draft' LIMIT 50
      SELECT * FROM blocks WHERE tag LIKE '%#meeting#%' LIMIT 50
    """
    return service().query_sql(query)


@mcp.tool()
def list_files(path: str) -> list[dict[str, Any]]:
    """List files/folders under a SiYuan workspace path (read-only).

    Example paths: '/data', '/data/assets'. Returns directory entries.
    """
    return service().list_files(path)


@mcp.tool()
def read_file(path: str) -> dict[str, Any]:
    """Read a file from the SiYuan workspace as UTF-8 text (read-only).

    Returns {path, content, binary}. For non-text files, `binary` is true and
    `content` is null.
    """
    return service().read_file(path)


# ==================================================================== writes


@mcp.tool()
def create_document(
    notebook_id: str,
    title: str,
    markdown: str = "",
    parent_path: str = "/",
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new document with an explicit title.

    The title is set from the `title` parameter (placed as the last path
    segment). Do NOT put a title in YAML frontmatter or rely on the path - pass
    `title` directly. `parent_path` is the folder to create it under (e.g.
    '/99 Archive'); default is the notebook root. `markdown` is the document
    BODY only (no title heading needed).

    Metadata: pass `attributes` like {"status": "draft", "source": "TickTick"};
    they are stored as `custom-*` block attributes (the frontmatter replacement).

    Frontmatter handling: if `markdown` begins with a `---` YAML block it is
    stripped (SiYuan does not parse it) and its keys are converted to custom
    attributes; the conversion is reported in the returned `warnings`.

    Returns {id, notebook_id, title, path, attributes, warnings}. Capture `id`
    to chain follow-up writes (append_block, set_block_attributes, ...).
    """
    return service().create_document(
        notebook_id=notebook_id,
        title=title,
        markdown=markdown,
        parent_path=parent_path,
        attributes=attributes,
    )


@mcp.tool()
def insert_block(
    markdown: str,
    previous_id: str | None = None,
    next_id: str | None = None,
    parent_id: str | None = None,
    data_type: str = "markdown",
) -> dict[str, Any]:
    """Insert a new block relative to an anchor block.

    Provide exactly one anchor: `previous_id` (insert AFTER it), `next_id`
    (insert BEFORE it), or `parent_id` (insert as a child). If you just want to
    add content under a document or heading, prefer `append_block` /
    `prepend_block` (more predictable parent/child placement).

    Returns {id, ids} - the new block ID(s).
    """
    return service().insert_block(
        markdown=markdown,
        previous_id=previous_id,
        next_id=next_id,
        parent_id=parent_id,
        data_type=data_type,
    )


@mcp.tool()
def prepend_block(parent_id: str, markdown: str, data_type: str = "markdown") -> dict[str, Any]:
    """Insert a block as the FIRST child of `parent_id`.

    `parent_id` is usually a document ID (to add at the top of a note) or a
    heading ID. Returns {id, ids, parent_id}.
    """
    return service().prepend_block(parent_id=parent_id, markdown=markdown, data_type=data_type)


@mcp.tool()
def append_block(parent_id: str, markdown: str, data_type: str = "markdown") -> dict[str, Any]:
    """Insert a block as the LAST child of `parent_id`.

    The most common way to add content to a document: pass the document ID as
    `parent_id`. Returns {id, ids, parent_id}.
    """
    return service().append_block(parent_id=parent_id, markdown=markdown, data_type=data_type)


@mcp.tool()
def update_block(block_id: str, markdown: str, data_type: str = "markdown") -> dict[str, Any]:
    """Replace the entire content of a block with new markdown.

    This is a full replacement, not a patch. Returns {id, updated}.
    """
    return service().update_block(block_id=block_id, markdown=markdown, data_type=data_type)


@mcp.tool()
def move_block(block_id: str, parent_id: str | None = None, previous_id: str | None = None) -> dict[str, Any]:
    """Move a block to a new position.

    Provide a destination: `previous_id` (place it right after that block) and/or
    `parent_id` (place it under that parent). Returns {id, moved, ...}.
    """
    return service().move_block(block_id=block_id, parent_id=parent_id, previous_id=previous_id)


@mcp.tool()
def delete_block(block_id: str) -> dict[str, Any]:
    """Delete a single block.

    Refuses to delete whole documents (type 'd') - delete those manually in
    SiYuan. Returns {id, deleted}.
    """
    return service().delete_block(block_id)


@mcp.tool()
def set_block_attributes(block_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
    """Attach metadata to a block as custom attributes (the frontmatter replacement).

    Pass {"status": "draft", "source": "TickTick"}. Names without a `custom-`
    prefix get one automatically (so `status` is stored as `custom-status`).
    Read them back with `get_block_attributes`.

    Built-in names are kept as-is: `tags` (comma-separated) sets real SiYuan
    document tags; `alias`, `bookmark`, `memo`, `name` are the other built-ins.
    For inline tags inside body text, write `#tag#` (a hash on BOTH sides).

    Returns {id, attributes, notes}.
    """
    return service().set_block_attributes(block_id=block_id, attributes=attributes)


@mcp.tool()
def notify(message: str) -> dict[str, Any]:
    """Show a one-off message toast in the SiYuan UI (English only).

    Optional and never fired automatically - only when you explicitly call it.
    Returns {shown, message}.
    """
    return service().notify(message)


def main() -> None:
    """Entry point: serve over streamable-HTTP."""
    # Allow overriding bind host/port via env without code changes.
    mcp.settings.host = os.getenv("SIYUAN_MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.getenv("SIYUAN_MCP_PORT", "8000"))
    mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
