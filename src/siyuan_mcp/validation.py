"""Pure, dependency-free helpers shared by the SiYuan MCP tools.

Everything here is side-effect free so it can be unit tested without a running
SiYuan kernel. The functions raise ``ValueError`` with *actionable* English
messages - the message should tell the calling LLM how to fix the call, not
merely that something went wrong.
"""

from __future__ import annotations

import json
import re
from typing import Any

# A SiYuan block ID is a 14-digit timestamp (YYYYMMDDHHMMSS), a hyphen, then a
# short random suffix, e.g. ``20260619181928-palr67f``.
BLOCK_ID_RE = re.compile(r"^\d{14}-[a-z0-9]+$", re.IGNORECASE)
BLOCK_ID_EXAMPLE = "20260619181928-palr67f"
BLOCK_ID_HINT = (
    f"Block IDs look like `{BLOCK_ID_EXAMPLE}` (a 14-digit timestamp, a hyphen, "
    "then a short suffix). Get a real one from `search_blocks`, `find_documents`, "
    "`query_sql`, or the `id` returned by a write tool."
)

# YAML-style frontmatter: a leading `---` fence ... `---` at the very top of the
# document. Allow an optional BOM and surrounding whitespace before the fence.
_FRONTMATTER_RE = re.compile(
    "^\ufeff?" + r"[ \t]*\r?\n?[ \t]*---[ \t]*\r?\n(?P<body>.*?)\r?\n[ \t]*---[ \t]*(?:\r?\n|$)",
    re.DOTALL,
)

# Built-in (non custom-*) block attributes that SiYuan understands directly.
# Anything else gets a ``custom-`` prefix so it shows up as user metadata.
#   - ``tags`` is the document-level tag attribute (comma-separated); setting it
#     registers real SiYuan tags, so we must NOT rewrite it to ``custom-tags``.
#   - ``name``/``alias``/``memo``/``bookmark`` are the other recognised built-ins.
BUILTIN_ATTRS = frozenset({"alias", "bookmark", "memo", "name", "tags"})

SQL_READONLY_HINT = (
    "`query_sql` is read-only - it only accepts a single SELECT (or WITH ... SELECT) "
    "statement. To change content use the block tools: `create_document`, "
    "`insert_block`, `append_block`, `prepend_block`, `update_block`, `move_block`, "
    "`delete_block`, or `set_block_attributes`."
)


def is_block_id(value: Any) -> bool:
    """Return True if *value* looks like a SiYuan block ID."""
    return isinstance(value, str) and bool(BLOCK_ID_RE.match(value.strip()))


def require_block_id(value: Any, param: str = "block_id") -> str:
    """Validate and normalise a block ID, or raise with guidance."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{param}` is required and must be a non-empty string. {BLOCK_ID_HINT}")
    cleaned = value.strip()
    if not BLOCK_ID_RE.match(cleaned):
        raise ValueError(f"`{param}` is not a valid SiYuan block ID (got {value!r}). {BLOCK_ID_HINT}")
    return cleaned


def detect_frontmatter(markdown: str) -> tuple[str | None, str]:
    """Split leading YAML frontmatter from a markdown body.

    Returns ``(frontmatter_text_or_None, body_without_frontmatter)``. SiYuan does
    **not** parse YAML frontmatter - a leading ``---`` fence becomes a thematic
    break and the ``key: value`` lines become literal body text - so callers
    should route metadata through block attributes instead.
    """
    if not isinstance(markdown, str) or "---" not in markdown:
        return None, markdown
    match = _FRONTMATTER_RE.match(markdown)
    if not match:
        return None, markdown
    body = markdown[match.end():]
    return match.group("body"), body.lstrip("\n")


def parse_frontmatter(frontmatter_text: str) -> dict[str, str]:
    """Best-effort parse of simple ``key: value`` YAML frontmatter.

    This is intentionally minimal (no external YAML dependency). Each ``key:
    value`` line becomes one entry; quotes are stripped and inline ``[a, b]``
    lists are flattened to a comma-separated string. Lines it cannot interpret
    are ignored - nothing is silently merged into a value.
    """
    attrs: dict[str, str] = {}
    for raw_line in frontmatter_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Strip surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        # Flatten an inline list like ``[a, b, c]`` to ``a, b, c``.
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            items = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
            value = ", ".join(items)
        attrs[key] = value
    return attrs


def _attr_value_to_str(value: Any) -> str:
    """Coerce an attribute value to the string SiYuan stores."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # Lists/dicts/None get a JSON representation so nothing is lost.
    return json.dumps(value, ensure_ascii=False)


def normalize_attributes(attrs: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Normalise an attributes dict for ``/api/attr/setBlockAttrs``.

    Keys are lower-cased and whitespace/underscores collapse to ``-``. Any key
    that is not already ``custom-*`` and not a known built-in attribute gets a
    ``custom-`` prefix (so ``status`` becomes ``custom-status``). Returns the
    normalised dict plus human-readable notes describing every rename.
    """
    if not isinstance(attrs, dict):
        raise ValueError("`attributes` must be an object/dict of {name: value}.")
    normalized: dict[str, str] = {}
    notes: list[str] = []
    for raw_key, raw_value in attrs.items():
        key = re.sub(r"[\s_]+", "-", str(raw_key).strip().lower())
        if not key:
            continue
        if key.startswith("custom-") or key in BUILTIN_ATTRS:
            final_key = key
        else:
            final_key = f"custom-{key}"
            notes.append(f"renamed attribute {raw_key!r} to {final_key!r} (custom attributes need a `custom-` prefix)")
        normalized[final_key] = _attr_value_to_str(raw_value)
    if not normalized:
        raise ValueError("`attributes` is empty. Pass at least one {name: value} pair, e.g. {\"status\": \"draft\"}.")
    return normalized, notes


def ensure_select_only(query: str) -> str:
    """Validate that *query* is a single read-only SELECT/WITH statement.

    Returns the original query if it is safe, otherwise raises with guidance.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("`query` is required and must be a non-empty SQL SELECT statement.")
    # Drop trailing semicolons/whitespace, then strip leading SQL comments.
    trimmed = query.strip().rstrip(";").strip()
    without_comments = re.sub(r"^(?:--[^\n]*\n|/\*.*?\*/|\s)+", "", trimmed, flags=re.DOTALL)
    first_word = re.match(r"[a-zA-Z]+", without_comments)
    if not first_word or first_word.group(0).lower() not in {"select", "with"}:
        raise ValueError(SQL_READONLY_HINT)
    # Reject stacked statements such as ``SELECT 1; DROP TABLE blocks``.
    if ";" in trimmed:
        raise ValueError("Only a single SQL statement is allowed (found more than one). " + SQL_READONLY_HINT)
    return query


def normalize_parent_path(parent_path: str | None) -> str:
    """Normalise a parent folder path to a leading-slash, no-trailing-slash form.

    ``None``, ``""``, ``"/"`` all mean the notebook root (``"/"``).
    """
    if not parent_path:
        return "/"
    cleaned = "/" + parent_path.strip().strip("/")
    return cleaned if cleaned != "/" else "/"


def build_doc_path(title: str, parent_path: str | None = "/") -> str:
    """Build the SiYuan hpath for a new document from an explicit title.

    SiYuan derives a document's title from the **last segment of its path**, not
    from YAML frontmatter or the first markdown heading. So we place *title* as
    the final path segment under *parent_path*.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError(
            "`title` is required and cannot be empty. SiYuan takes the document "
            "title from the last path segment, so pass it explicitly, e.g. "
            "create_document(notebook_id=..., title='Weekly Review', markdown=...)."
        )
    clean_title = title.strip()
    if "/" in clean_title:
        raise ValueError(
            "`title` cannot contain '/': SiYuan treats '/' as a document path "
            "separator. Put the folder in `parent_path` instead, e.g. "
            "parent_path='/99 Archive', title='TickTick Reference Lists Raw Dump'."
        )
    parent = normalize_parent_path(parent_path)
    if parent == "/":
        return f"/{clean_title}"
    return f"{parent}/{clean_title}"


def sql_escape(value: str) -> str:
    """Escape a single-quoted SQL string literal."""
    return value.replace("'", "''")
