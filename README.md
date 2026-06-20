# siyuan-mcp

An English, ergonomic [MCP](https://modelcontextprotocol.io) server for the
[SiYuan](https://github.com/siyuan-note/siyuan) note kernel. It is a clean,
owned replacement for `leolulu/siyuan-mcp-server` that fixes three problems:

1. **English everywhere.** Every tool name, description, parameter doc, and
   error message is clear English — no Chinese.
2. **No unsolicited UI toasts.** Writes never push a notification into the
   SiYuan UI. A single optional `notify` tool exists for when you actually want
   to show a message.
3. **Sane writes.** `create_document` takes an explicit `title`, builds the
   SiYuan path correctly, and strips/auto-converts YAML frontmatter (which
   SiYuan does **not** parse) into `custom-*` block attributes. Every write
   returns the new block ID so you can chain follow-ups.

## How SiYuan models data (the things that bite you)

- **Notebooks -> documents -> blocks.** Block IDs look like
  `20260619181928-palr67f` (a 14-digit timestamp, a hyphen, a short suffix).
- **A document's title comes from the last path segment**, set here via the
  `title` parameter — never from YAML frontmatter and never from a leading
  `# heading`. SiYuan does not parse frontmatter: a leading `---` block renders
  as a horizontal rule and the `key: value` lines become literal text.
- **Metadata is stored as `custom-*` block attributes**, not frontmatter. Use
  `set_block_attributes` / `get_block_attributes`.
- **`query_sql` is read-only** (SELECT/WITH). Use the block tools to mutate.

See `skills/siyuan/SKILL.md` for a full driving guide aimed at an LLM.

## Tools

**Reads:** `list_notebooks`, `find_documents`, `search_blocks`,
`get_block_markdown`, `get_blocks_markdown`, `get_block_children`, `query_sql`,
`get_block_attributes`, `list_files`, `read_file`.

**Writes:** `create_document`, `insert_block`, `prepend_block`, `append_block`,
`update_block`, `move_block`, `delete_block`, `set_block_attributes`.

**Misc:** `notify` (optional, English-only, never auto-fired).

## Configuration

| Env var             | Required | Default                  | Meaning                              |
| ------------------- | -------- | ------------------------ | ------------------------------------ |
| `SIYUAN_API_URL`    | no       | `http://127.0.0.1:6806`  | SiYuan kernel base URL               |
| `SIYUAN_API_TOKEN`  | yes      | —                        | SiYuan API token (Settings -> About) |
| `SIYUAN_MCP_HOST`   | no       | `0.0.0.0`                | Bind host                            |
| `SIYUAN_MCP_PORT`   | no       | `8000`                   | Bind port                            |

Transport is **streamable-HTTP**, served at `/mcp`. DNS-rebinding protection is
disabled so a gateway can forward an arbitrary `Host` header (the MCP SDK would
otherwise reject `Host: siyuan-mcp:8000` with "Invalid Host header").

## Run

```bash
git clone https://github.com/metaember/siyuan-mcp.git
cd siyuan-mcp

uv run siyuan-mcp                      # local dev (reads env)
# or
pip install . && siyuan-mcp
```

## Docker

```bash
docker build -t siyuan-mcp .
docker run --rm -p 8000:8000 \
  -e SIYUAN_API_URL=http://siyuan:6806 \
  -e SIYUAN_API_TOKEN=your-token \
  siyuan-mcp
```

The image runs as `nobody` and exposes `8000`. It drops into the airlock compose
as a replacement for the `siyuan-mcp` image (same env + `/mcp` endpoint); see
`docker-compose.example.yml`.

## Tests

```bash
uv run pytest          # or: pip install -e '.[dev]' && pytest
```

The suite covers create-with-title, frontmatter handling, IDs returned by
writes, the SELECT-only SQL guard, and error-message quality — all without a
running SiYuan kernel (the kernel client is faked). An opt-in end-to-end test
(mock kernel + real server over HTTP) lives in `tests/integration`:

```bash
RUN_INTEGRATION=1 pytest tests/integration -q
```

## Acknowledgements

API surface and endpoint shapes were learned from
[`leolulu/siyuan-mcp-server`](https://github.com/leolulu/siyuan-mcp-server)
(MIT) and the [official SiYuan kernel API](https://github.com/siyuan-note/siyuan/blob/master/API.md).
This is an independent, English-first reimplementation.

## License

MIT — see [LICENSE](LICENSE).
