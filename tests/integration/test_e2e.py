"""Opt-in end-to-end test: mock SiYuan kernel + the real MCP server over HTTP.

Spawns the server as a subprocess and a mock kernel, then drives `create_document`
through a real MCP client. Skipped by default (it binds ports and spawns a process);
run it with:

    RUN_INTEGRATION=1 pytest tests/integration -q
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

if os.getenv("RUN_INTEGRATION") != "1":
    pytest.skip("integration test (set RUN_INTEGRATION=1 to run)", allow_module_level=True)

KERNEL_PORT = 16806
MCP_PORT = 18078
NEW_DOC_ID = "20260619181928-palr67f"
NOTEBOOK_ID = "20260101090000-abc1234"


def _make_kernel(recorded: list):
    class Kernel(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            recorded.append((self.path, body))
            if self.path == "/api/filetree/createDocWithMd":
                data = NEW_DOC_ID
            elif self.path == "/api/notebook/lsNotebooks":
                data = {"notebooks": [{"id": NOTEBOOK_ID, "name": "Inbox", "closed": False, "icon": ""}]}
            else:
                data = None
            payload = json.dumps({"code": 0, "msg": "", "data": data}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Kernel


def test_create_document_end_to_end():
    recorded: list = []
    kernel = ThreadingHTTPServer(("127.0.0.1", KERNEL_PORT), _make_kernel(recorded))
    threading.Thread(target=kernel.serve_forever, daemon=True).start()

    env = dict(
        os.environ,
        SIYUAN_API_URL=f"http://127.0.0.1:{KERNEL_PORT}",
        SIYUAN_API_TOKEN="test-token",
        SIYUAN_MCP_PORT=str(MCP_PORT),
        PYTHONPATH="src",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "siyuan_mcp.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def drive():
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        last_err = None
        for _ in range(40):
            try:
                async with streamablehttp_client(f"http://127.0.0.1:{MCP_PORT}/mcp") as (r, w, _):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        md = "---\nstatus: raw-dump\nsource: TickTick\n---\n\n## Body\n\ntext"
                        res = await session.call_tool(
                            "create_document",
                            {
                                "notebook_id": NOTEBOOK_ID,
                                "title": "TickTick Reference Lists Raw Dump",
                                "parent_path": "/99 Archive",
                                "markdown": md,
                            },
                        )
                        return json.loads(res.content[0].text)
            except Exception as exc:  # server not up yet / transient
                last_err = exc
                time.sleep(0.25)
        raise AssertionError(f"could not reach MCP server: {last_err}")

    try:
        out = asyncio.run(drive())
    finally:
        proc.terminate()
        kernel.shutdown()

    # The title was set via the path, and the returned id is usable for chaining.
    assert out["id"] == NEW_DOC_ID
    assert out["path"] == "/99 Archive/TickTick Reference Lists Raw Dump"

    create = next(b for (p, b) in recorded if p == "/api/filetree/createDocWithMd")
    assert create["path"] == "/99 Archive/TickTick Reference Lists Raw Dump"
    assert "---" not in create["markdown"]  # frontmatter stripped from the body
    assert create["markdown"].startswith("## Body")

    attrs = next(b for (p, b) in recorded if p == "/api/attr/setBlockAttrs")
    assert attrs["attrs"]["custom-status"] == "raw-dump"
    assert attrs["attrs"]["custom-source"] == "TickTick"
