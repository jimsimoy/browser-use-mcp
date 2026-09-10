#!/usr/bin/env python3
"""
End-to-end self test: spawns server.py over stdio exactly as an MCP client
would, and exercises every tool against a real page.

    python3 selftest.py [url]

Pass a URL to test against your own site. A local development site served over
HTTPS with a self-signed certificate is the most valuable thing to point it at,
since that path is the one most likely to regress.
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
URL = sys.argv[1] if len(sys.argv) > 1 else "https://example.com/"

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))
    print(f"  [{PASS if condition else FAIL}] {name}{' — ' + detail if detail else ''}")


def payload(result):
    """Unwrap the first text block of a tool result as JSON."""
    return json.loads(result.content[0].text)


async def main() -> int:
    params = StdioServerParameters(
        command=os.path.join(HERE, "run.sh"),
        args=[],
        env={**os.environ},
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"\nServer exposes {len(names)} tools:\n  {', '.join(names)}\n")

            print("Session + navigation")
            opened = payload(await session.call_tool("browser_open", {"url": URL}))
            sid = opened["session_id"]
            # Certificate errors are ignored by default, so pointing this at a
            # self-signed local site is the more demanding version of this check.
            record(f"browser_open reaches {URL}", bool(opened.get("title")),
                   opened.get("title", "")[:60])

            listed = payload(await session.call_tool("browser_sessions", {}))
            record("browser_sessions lists the open page", len(listed["sessions"]) == 1)

            print("\nInspection")
            style = payload(await session.call_tool(
                "browser_computed_style",
                {"session_id": sid, "selector": "body", "properties": ["font-family", "font-size"]},
            ))
            body_font = style["elements"][0]["styles"]["font-family"]
            record("browser_computed_style returns resolved values", bool(body_font), body_font[:60])

            fonts = payload(await session.call_tool("browser_fonts", {"session_id": sid}))
            record("browser_fonts finds font stacks in use", len(fonts["families_in_use"]) > 0,
                   f"{len(fonts['families_in_use'])} stacks, "
                   f"{fonts['elements_scanned']} elements scanned")
            record("browser_fonts reports loaded webfonts", "loaded_webfonts" in fonts,
                   f"{len(fonts['loaded_webfonts'])} faces loaded")

            record("browser_fonts classifies every stack by source",
                   all("source" in f for f in fonts["families_in_use"]),
                   ", ".join(sorted({f["source"] for f in fonts["families_in_use"]})))

            for label, key in (("falling back (nobody has it)", "unresolved_families"),
                               ("LOCAL-ONLY (renders here, not for visitors)", "local_only_families")):
                for u in fonts.get(key, [])[:5]:
                    print(f"       {label}: {u['requested_family']!r} on "
                          f"{u['elements']} els ({u['sample_selector']})")

            html = payload(await session.call_tool(
                "browser_html", {"session_id": sid, "selector": "head", "max_chars": 3000}))
            record("browser_html scoped by selector", html["chars"] > 0, f"{html['chars']} chars")

            big = payload(await session.call_tool(
                "browser_html", {"session_id": sid, "max_chars": 500}))
            record("browser_html truncates instead of blowing the budget",
                   big.get("truncated") is True and len(big["content"]) <= 500)

            text = payload(await session.call_tool(
                "browser_text", {"session_id": sid, "selector": "body", "max_chars": 2000}))
            record("browser_text extracts visible copy", text["chars"] > 0)

            ev = payload(await session.call_tool(
                "browser_eval", {"session_id": sid, "expression": "() => document.title"}))
            record("browser_eval runs JS", isinstance(ev["result"], str))

            console = payload(await session.call_tool("browser_console", {"session_id": sid}))
            record("browser_console collects diagnostics", "console" in console,
                   f"{len(console['console'])} msgs, "
                   f"{len(console['page_errors'])} page errors, "
                   f"{len(console['failed_requests'])} failed requests")

            print("\nCapture")
            shot_path = "/tmp/browser-use-selftest.png"
            shot = payload(await session.call_tool(
                "browser_screenshot", {"session_id": sid, "save_to": shot_path}))
            record("browser_screenshot writes a PNG",
                   os.path.exists(shot_path) and shot["bytes"] > 5000, f"{shot['bytes']} bytes")

            print("\nTeardown")
            closed = payload(await session.call_tool("browser_close", {"session_id": sid}))
            record("browser_close releases the session", closed.get("closed") == sid)

    failed = [r for r in results if r[0] == FAIL]
    print(f"\n{'=' * 60}")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    for _, name, _ in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
