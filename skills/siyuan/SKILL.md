---
name: siyuan
description: Drive a SiYuan notebook through the siyuan-mcp server - create and edit notes, search, and attach metadata. Use whenever you read from or write to SiYuan (notebooks, documents, blocks) via tools like list_notebooks, create_document, search_blocks, append_block, query_sql, or set_block_attributes. Read this FIRST so you create correctly-titled documents on the first try and don't lose metadata to YAML frontmatter.
---

# Driving SiYuan via siyuan-mcp

SiYuan is a block-based notebook. This skill teaches you to read and write it
correctly through the `siyuan-mcp` server. The single biggest source of mistakes
is **titles and frontmatter** - read that section before any write.

## Data model

```
notebook  (e.g. "Inbox")   id: 20260101090000-abc1234
  └─ document  (a whole note; block type "d")   id: 20260619181928-palr67f
       └─ block  (paragraph, heading, list, code, table, ...)   id: 2026...-xxxxxxx
            └─ child block (list item, nested content)
```

- **Everything is a block**, including the document itself (the document is the
  "root" block, type `d`).
- **Block IDs** look like `20260619181928-palr67f`: a 14-digit timestamp
  (`YYYYMMDDHHMMSS`), a hyphen, then a short suffix. Notebook IDs share the same
  shape. You never invent IDs - you get them from `list_notebooks`,
  `find_documents`, `search_blocks`, `query_sql`, or the `id` a write tool
  returns.
- **Content is kramdown** (SiYuan-flavored Markdown). Standard Markdown works,
  plus SiYuan extensions: tags `#tag#`, block references `((id "anchor"))`,
  highlight `==x==`, and block attribute markers `{: id="..." custom-status="draft"}`.
  See **Writing content** below for the full syntax and its gotchas.

## Titles & paths - the #1 gotcha

**A document's title comes from the `title` parameter** (which the server places
as the last segment of the document's path). It does **NOT** come from YAML
frontmatter and **NOT** from a leading `# heading`. SiYuan does not parse YAML
frontmatter at all.

### Wrong - DO NOT do this

```yaml
notebook_id: 20260619181928-palr67f
path: /99 Archive/TickTick Reference Lists Raw Dump
markdown: |
  ---
  title: TickTick Reference Lists Raw Dump
  status: raw-dump
  source: TickTick
  scope: [Cuisines, Cooking, To Watch]
  ---
  ...content...
```

What actually happens with frontmatter in SiYuan: the `---` becomes a horizontal
rule, the `title:`/`status:`/... lines become **literal body text**, and the
document title is taken from the path. Earlier this produced documents titled
`《—》` (an empty/dash title). The metadata is lost as plain text.

### Right - DO this

```
create_document(
  notebook_id = "20260101090000-abc1234",     # from list_notebooks
  title       = "TickTick Reference Lists Raw Dump",
  parent_path = "/99 Archive",                 # the folder; default "/" = root
  markdown    = "## Cuisines\n\n- ...\n\n## Cooking\n\n- ...",   # BODY only
  attributes  = {"status": "raw-dump", "source": "TickTick",
                 "scope": "Cuisines, Cooking, To Watch"},
)
```

- Pass `title` explicitly. Don't encode it in a `path`, and don't add a
  `# Title` heading to `markdown` (the title is separate from the body).
- Put the folder in `parent_path`, not in the title. A `title` containing `/`
  is rejected (SiYuan treats `/` as a path separator).
- The tool **returns the new document `id`** - capture it to add more blocks.
- If you do pass frontmatter in `markdown` anyway, the server strips it, converts
  its keys to `custom-*` attributes, and tells you so in the returned
  `warnings`. Don't rely on this - prefer `attributes`.

## Metadata - use block attributes, not frontmatter

Attach machine-readable metadata (status, source, project, ...) as **custom
attributes**:

```
set_block_attributes(block_id="20260619181928-palr67f",
                     attributes={"status": "published", "source": "TickTick"})
# stored as custom-status, custom-source
get_block_attributes(block_id="20260619181928-palr67f")
```

- Names without a `custom-` prefix get one automatically (`status` ->
  `custom-status`). Attributes can be set on any block, not just documents.
- **Built-in names are kept as-is** (not prefixed): `tags`, `alias`, `bookmark`,
  `memo`, `name`.
- **`tags` is special**: `set_block_attributes(doc_id, {"tags": "project, urgent"})`
  sets real SiYuan document tags (comma-separated), browsable in the Tag panel.
  That's different from inline `#tag#` you write in body text - see
  **Writing content**.
- Query custom attributes via the dedicated `attributes` table (reliable), not by
  `LIKE`-matching the `ial` blob:
  `SELECT b.* FROM blocks b JOIN attributes a ON a.block_id=b.id WHERE a.name='custom-status' AND a.value='published' LIMIT 50`.

Use a small set of **consistent attribute keys** across the vault (e.g.
`custom-status`, `custom-source`, `custom-project`) so queries stay simple.

## Writing content: kramdown syntax

Block content you send to `create_document` / `append_block` / `insert_block` /
`update_block` is **kramdown**. Standard Markdown blocks work: headings
(`#`..`######`), lists (`-`, `1.`), task lists (`- [ ]` / `- [x]`), code fences
(```` ``` ````), tables, blockquotes (`>`), and a math block (`$$ ... $$`). A bare
`---` line is a **thematic break** (horizontal rule), *not* frontmatter.

### Inline formatting

| Effect | Syntax | Example |
| --- | --- | --- |
| bold / italic | `**x**` / `*x*` | `**done**` |
| strikethrough | `~~x~~` | `~~old~~` |
| highlight / mark | `==x==` | `==important==` |
| superscript | `^x^` | `x^2^` |
| subscript | `~x~` | `H~2~O` |
| inline code | `` `x` `` | `` `npm i` `` |
| inline math | `$x$` | `$E = mc^2$` |
| underline | `<u>x</u>` | (no ASCII shorthand) |
| keyboard | `<kbd>x</kbd>` | `<kbd>Ctrl</kbd>` |
| tag | `#x#` | `#project/alpha#` |

**Overloading gotchas:** `~x~` is subscript but `~~x~~` is strikethrough; `^x^`
is superscript; `$...$` is math. Literal `~`, `^`, or `$` (currency like `$5`,
globs, regex) can render unexpectedly - wrap them in inline code `` `...` `` or
escape with `\`.

### Tags

- **Inline tag** (in body text): `#tag#` - a hash on **BOTH** sides (unlike
  Obsidian/Logseq's single leading `#`). Hierarchical: `#area/subarea#`. No spaces
  inside the inline form.
- **Document tags:** set the `tags` attribute (comma-separated) with
  `set_block_attributes(doc_id, {"tags": "project, urgent"})`.
- Both populate the queryable `blocks.tag` column:
  `SELECT id, content FROM blocks WHERE tag LIKE '%#project#%' LIMIT 50`.

### Links, references & embeds

- **Plain link:** `[text](https://example.com)`. Link to a block internally with
  `[text](siyuan://blocks/20260619181928-palr67f)`.
- **Block reference** (a refactor-safe pointer; the recommended way to link
  notes): `((20260619181928-palr67f "anchor text"))`. Double quotes = a *static*
  anchor (fixed text); single quotes `(('...'))` = a *dynamic* anchor that
  follows the target block's name.
- **Block embed** (render the target's content inline, e.g. for an index/MOC
  page): a query-embed block `{{select * from blocks where id='20260619181928-palr67f'}}`.
  This is what SiYuan emits for "Copy block embed". (The `!((id))` shorthand is
  recognised mainly on import; prefer the `{{ }}` form for reliable rendering.)
- **`[[wikilinks]]` are NOT supported** at runtime (import-conversion only). Use
  `((id "anchor"))` instead.

### kramdown gotchas

- **You can't pre-assign a block's id.** Writing `{: id="..." }` in markdown does
  *not* set the id - SiYuan mints a fresh one. Capture the id a write tool
  returns; don't reference an id you invented.
- **Headings own their section** (the blocks beneath them up to the next
  same-or-higher heading). Use a heading's `id` as `parent_id` to append into it.
- **One markdown string can create multiple blocks.** Blank-line-separated
  paragraphs each become a block; write tools return all created ids in `ids`
  (first in `id`).
- **`update_block` replaces the whole block**, it is not a patch.
- Attribute markers `{: id="..." custom-status="draft"}` are emitted by SiYuan;
  set attributes via `set_block_attributes`, not by hand-writing IAL.

## Task -> tool map

| Goal | Tool(s) |
| --- | --- |
| See notebooks / get a notebook id | `list_notebooks` |
| Find a whole note | `find_documents` (by title/path/time) |
| Find any block by content | `search_blocks` (then use the returned `id`) |
| Advanced/cross-field lookup | `query_sql` (SELECT only) |
| Read a block's markdown | `get_block_markdown` / `get_blocks_markdown` |
| See what's inside a doc/heading | `get_block_children` |
| Read metadata | `get_block_attributes` |
| **Create a note** | `create_document` (capture the returned `id`) |
| Add content to the END of a doc/heading | `append_block(parent_id=<doc/heading id>)` |
| Add content to the START | `prepend_block(parent_id=...)` |
| Insert next to a specific block | `insert_block(previous_id=... or next_id=...)` |
| Replace a block's content | `update_block(block_id=...)` |
| Reorder / reparent a block | `move_block(block_id=..., previous_id/parent_id=...)` |
| Delete a block | `delete_block` (refuses whole documents) |
| Attach metadata / tags | `set_block_attributes` |
| Link / embed a block | write `((id "anchor"))` or `{{select * from blocks where id='...'}}` in the markdown |
| Find backlinks to a block | `query_sql` on the `refs` table (see below) |

**Canonical create-and-fill flow:**
1. `list_notebooks` -> pick a notebook `id`.
2. `create_document(notebook_id, title, markdown, attributes)` -> capture `id`.
3. `append_block(parent_id=id, markdown="...")` for more sections, or
   `set_block_attributes(block_id=id, ...)` for metadata.

**append vs insert:** `append_block`/`prepend_block` are *parent-first* - they
reliably place content as the last/first child of `parent_id`. `insert_block` is
*anchor-first* - it positions relative to a sibling (`previous_id`/`next_id`).
When in doubt (e.g. "add this under that document/heading"), use `append_block`.

## query_sql

Read-only: only a single `SELECT` (or `WITH ... SELECT`) statement runs; writes
are rejected. It queries SiYuan's SQLite index. The main table is `blocks`;
`attributes` and `refs` are useful for metadata and backlinks.

Key `blocks` columns:

| Column | Meaning |
| --- | --- |
| `id` | block id |
| `content` | text with Markdown markers removed (for a document, this is its **title**) |
| `markdown` | full kramdown of the block |
| `type` | `d` doc, `h` heading, `p` paragraph, `l` list, `i` list item, `c` code, `t` table, `b` quote, `s` super block, `m` math, `tb` divider, `av` database, `html`, `query_embed`, `iframe`, `widget`, `video`, `audio` (newer builds also `callout`) |
| `subtype` | `h1`-`h6` for headings; `o`/`u`/`t` for ordered/unordered/task lists |
| `root_id` | id of the containing document (every block in a doc shares this) |
| `box` | notebook id |
| `hpath` | human-readable path (ends with the document title) |
| `name`, `tag` | block name; space-joined `#tag#` tokens (inline + document tags) |
| `created`, `updated` | `YYYYMMDDHHMMSS` strings (lexical order = chronological) |
| `ial` | raw attribute blob (prefer the `attributes` table to query it) |

Other tables: `attributes(block_id, name, value)` - one row per attribute;
`refs(block_id, def_block_id, content)` - a reference edge from the block
containing the link (`block_id`) to the block being linked (`def_block_id`).

Examples:

```sql
-- Find documents by title
SELECT id, content, hpath FROM blocks
WHERE type='d' AND content LIKE '%Weekly Review%' LIMIT 10;

-- Most recently edited blocks in one notebook
SELECT id, content, type, updated FROM blocks
WHERE box='20260101090000-abc1234' ORDER BY updated DESC LIMIT 20;

-- All blocks in one document, in order
SELECT id, content, type FROM blocks
WHERE root_id='20260619181928-palr67f' ORDER BY sort LIMIT 999999;

-- Find by custom attribute (preferred over LIKE-matching ial)
SELECT b.id, b.content FROM blocks b
JOIN attributes a ON a.block_id = b.id
WHERE a.name='custom-status' AND a.value='draft' LIMIT 50;

-- Blocks carrying a tag
SELECT id, content FROM blocks WHERE tag LIKE '%#meeting#%' LIMIT 50;

-- Backlinks: blocks that reference a given block
SELECT b.id, b.content FROM blocks b
JOIN refs r ON r.block_id = b.id
WHERE r.def_block_id='20260619181928-palr67f' LIMIT 50;
```

**Always add an explicit `LIMIT`** - without one the kernel caps results at a
small default (historically 64; fewer in current builds). Use a large explicit
limit (e.g. `LIMIT 999999`) when you truly want everything.

## Common failures & how to fix them

The server returns actionable English errors; here's the model up front:

| Symptom / error | Fix |
| --- | --- |
| "`notebook_id` is required / not valid" | Call `list_notebooks` and pass a real `id`. |
| Document titled `—` or wrong title | Don't put the title in frontmatter or rely on `path`; pass `title=`. |
| Metadata showing up as body text | It was frontmatter. Use `attributes` / `set_block_attributes` instead. |
| "not a valid SiYuan block ID" | IDs look like `20260619181928-palr67f`; get one from `search_blocks`/`query_sql`. |
| "`query_sql` is read-only" | It's SELECT-only; use the block tools (`update_block`, `insert_block`, ...) to mutate. |
| "title cannot contain '/'" | Put the folder in `parent_path`, keep `/` out of `title`. |
| `insert_block` "needs an anchor" | Pass one of `previous_id`/`next_id`/`parent_id`, or use `append_block`. |
| Wanted content "under a heading" but it landed elsewhere | Use `append_block(parent_id=<heading id>)`, not `insert_block` with a sibling anchor. |
| `delete_block` refused | It won't delete whole documents (type `d`); delete those in SiYuan manually. |
| A tag isn't recognised | Inline tags need a hash on BOTH sides: `#tag#`, not `#tag`. For document tags use the `tags` attribute. |
| `[[wikilink]]` didn't link | Wikilinks aren't supported at runtime; use `((id "anchor"))`. |
| `$`, `~`, or `^` rendered as math/sub/superscript | Wrap literal text in inline code `` `...` `` or escape with `\`. |
| Referenced an id you wrote in markdown and it failed | You can't pre-assign ids; capture the `id` the write tool returns. |

## Beyond this server (native SiYuan features)

This server covers documents, blocks, attributes, and search. SiYuan also has
features this server does **not** expose - if you need them, do it in the SiYuan
app or extend the server:

- **Daily notes** (per-notebook journaling with a date-path template) and
  **templates** (`data/templates/`, Go `text/template` + Sprig). For journaling
  via this server, just `create_document` at a dated path like
  `/daily note/2026/06/2026-06-20`.
- **Databases / attribute views** (block type `av`): structured table/kanban
  views. For machine-readable structured data via this server, prefer
  `custom-*` attributes + `query_sql`.
