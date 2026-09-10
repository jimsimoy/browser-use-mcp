#!/usr/bin/env python3
"""
browser-use-mcp — a browser automation MCP server built on Playwright.

Deliberately has NO LLM inside it and needs NO API key. Every published
browser-automation MCP puts a model in the server so it can accept instructions
like "find the login form and sign in". When the caller is already an agent,
that model is redundant: it adds a key to manage, a per-call cost, and a layer
of guesswork between the agent and the page. These tools are all deterministic.

Transport is stdio.

Usage:
  python3 server.py

Registering it:
  claude mcp add browser-use --scope user -- /path/to/run.sh
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

from browser_session import BrowserManager, MAX_INLINE_CHARS
from page_inspect import FONT_AUDIT_JS, COMPUTED_STYLE_JS

manager = BrowserManager()
server = Server("browser-use")


# ── Helpers ────────────────────────────────────────────────────────────────


def ok(payload) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]


def clip(text: str, max_chars: int, save_to: str | None) -> dict:
    """Return text within budget, or write it out and return a pointer.

    A tool result that blows the token limit is worse than useless: the content
    is lost and the call has to be repeated differently. Saving to a file keeps
    the payload addressable without spending the context on it.
    """
    if save_to:
        path = os.path.abspath(os.path.expanduser(save_to))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return {"saved_to": path, "chars": len(text), "preview": text[:1000]}

    budget = min(max_chars, MAX_INLINE_CHARS)
    if len(text) <= budget:
        return {"chars": len(text), "content": text}

    return {
        "chars": len(text),
        "truncated": True,
        "returned_chars": budget,
        "content": text[:budget],
        "hint": "Output truncated. Re-run with a narrower `selector`, or pass "
                "`save_to` to write the whole document to a file.",
    }


SESSION_ARG = {
    "session_id": {
        "type": "string",
        "description": "Session id returned by browser_open.",
    }
}


# ── Tool catalogue ─────────────────────────────────────────────────────────


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="browser_open",
            description=(
                "Open a browser session, optionally navigating to a URL. Returns a "
                "session_id used by every other tool. HTTPS certificate errors are "
                "ignored by default, so local development sites with self-signed "
                "certificates load without an interstitial."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open immediately (optional)."},
                    "headless": {"type": "boolean", "default": True},
                    "viewport_width": {"type": "integer", "default": 1440},
                    "viewport_height": {"type": "integer", "default": 900},
                    "ignore_https_errors": {"type": "boolean", "default": True},
                    "user_agent": {"type": "string", "description": "Override the User-Agent."},
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                        "default": "load",
                    },
                },
            },
        ),
        Tool(
            name="browser_goto",
            description="Navigate an existing session to a URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "url": {"type": "string"},
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                        "default": "load",
                    },
                },
                "required": ["session_id", "url"],
            },
        ),
        Tool(
            name="browser_sessions",
            description="List open sessions with their URL, title and error counts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="browser_close",
            description="Close one session, or every session when session_id is omitted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Omit to close all."}
                },
            },
        ),
        Tool(
            name="browser_click",
            description=(
                "Click an element by CSS selector, or at viewport coordinates when x and y "
                "are given instead. Coordinates are the fallback for canvas and for "
                "browser-chrome interstitials that no selector reaches."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "selector": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "timeout_ms": {"type": "integer", "default": 15000},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="browser_type",
            description="Type text into the element matching a selector.",
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "clear_first": {"type": "boolean", "default": True},
                    "press_enter": {"type": "boolean", "default": False},
                },
                "required": ["session_id", "selector", "text"],
            },
        ),
        Tool(
            name="browser_scroll",
            description="Scroll the page by a pixel amount, or to an element.",
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "pixels": {"type": "integer", "description": "Positive scrolls down."},
                    "to_selector": {"type": "string", "description": "Scroll this into view."},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="browser_screenshot",
            description=(
                "Capture the viewport, the full page, or a single element. Prefer a "
                "selector on long pages: full-page captures of very tall documents can "
                "render blank past a few thousand pixels."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "selector": {"type": "string", "description": "Capture just this element."},
                    "full_page": {"type": "boolean", "default": False},
                    "save_to": {
                        "type": "string",
                        "description": "Write a PNG here instead of returning the image inline.",
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="browser_html",
            description=(
                "Get rendered HTML after JavaScript has run. Scope it with a selector "
                "wherever possible; whole documents are frequently large enough to "
                "exhaust the result budget."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "selector": {"type": "string", "description": "Limit to this element."},
                    "max_chars": {"type": "integer", "default": 20000},
                    "save_to": {"type": "string", "description": "Write the full HTML here."},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="browser_text",
            description="Get visible text content, optionally scoped to a selector.",
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "selector": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 20000},
                    "save_to": {"type": "string"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="browser_eval",
            description=(
                "Evaluate a JavaScript expression in the page and return the JSON result. "
                "The expression must be a function, e.g. `() => document.title`."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "expression": {"type": "string"},
                },
                "required": ["session_id", "expression"],
            },
        ),
        Tool(
            name="browser_computed_style",
            description=(
                "Return getComputedStyle values for elements matching a selector — what "
                "the browser actually resolved, not what the stylesheet says. Use it to "
                "settle questions that source-reading cannot, such as which rule won a "
                "specificity contest or what a font stack fell back to."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "selector": {"type": "string"},
                    "properties": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CSS property names. Defaults to a typography/layout set.",
                    },
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["session_id", "selector"],
            },
        ),
        Tool(
            name="browser_fonts",
            description=(
                "Audit the fonts a page actually uses. Reports every computed font stack "
                "with how many elements use it, which webfonts genuinely loaded, "
                "@font-face rules, external font hosts, and — the part source grep cannot "
                "determine — which requested families FAIL to resolve and are silently "
                "falling back. Availability is measured by text metrics, not guessed."
            ),
            inputSchema={
                "type": "object",
                "properties": {**SESSION_ARG},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="browser_console",
            description=(
                "Return console messages, uncaught page errors and failed network "
                "requests collected since the session opened."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **SESSION_ARG,
                    "errors_only": {"type": "boolean", "default": False},
                },
                "required": ["session_id"],
            },
        ),
    ]


# ── Dispatch ───────────────────────────────────────────────────────────────


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    args = arguments or {}

    if name == "browser_open":
        session = await manager.open(
            url=args.get("url"),
            headless=args.get("headless", True),
            viewport={
                "width": args.get("viewport_width", 1440),
                "height": args.get("viewport_height", 900),
            },
            ignore_https_errors=args.get("ignore_https_errors", True),
            user_agent=args.get("user_agent"),
            wait_until=args.get("wait_until", "load"),
        )
        info = {"session_id": session.id, "url": session.page.url}
        if args.get("url"):
            info["title"] = await session.page.title()
        return ok(info)

    if name == "browser_goto":
        return ok(
            await manager.goto(
                args["session_id"], args["url"], wait_until=args.get("wait_until", "load")
            )
        )

    if name == "browser_sessions":
        return ok({"sessions": await manager.list_sessions()})

    if name == "browser_close":
        if args.get("session_id"):
            await manager.close(args["session_id"])
            return ok({"closed": args["session_id"]})
        return ok({"closed_sessions": await manager.close_all()})

    if name == "browser_click":
        page = manager.get(args["session_id"]).page
        if args.get("selector"):
            await page.click(args["selector"], timeout=args.get("timeout_ms", 15000))
            target = args["selector"]
        elif args.get("x") is not None and args.get("y") is not None:
            await page.mouse.click(args["x"], args["y"])
            target = f"({args['x']}, {args['y']})"
        else:
            raise ValueError("Provide either `selector`, or both `x` and `y`.")
        await page.wait_for_timeout(300)
        return ok({"clicked": target, "url": page.url})

    if name == "browser_type":
        page = manager.get(args["session_id"]).page
        if args.get("clear_first", True):
            await page.fill(args["selector"], "")
        await page.type(args["selector"], args["text"])
        if args.get("press_enter"):
            await page.press(args["selector"], "Enter")
            await page.wait_for_timeout(500)
        return ok({"typed_into": args["selector"], "url": page.url})

    if name == "browser_scroll":
        page = manager.get(args["session_id"]).page
        if args.get("to_selector"):
            await page.locator(args["to_selector"]).first.scroll_into_view_if_needed()
            where = f"to {args['to_selector']}"
        else:
            await page.mouse.wheel(0, args.get("pixels", 600))
            where = f"{args.get('pixels', 600)}px"
        await page.wait_for_timeout(300)
        return ok({"scrolled": where})

    if name == "browser_screenshot":
        result = await manager.screenshot(
            args["session_id"],
            selector=args.get("selector"),
            full_page=args.get("full_page", False),
            path=args.get("save_to"),
        )
        if result["base64"]:
            return [ImageContent(type="image", data=result["base64"], mimeType="image/png")]
        return ok({"saved_to": result["path"], "bytes": result["bytes"]})

    if name == "browser_html":
        page = manager.get(args["session_id"]).page
        if args.get("selector"):
            element = await page.query_selector(args["selector"])
            if element is None:
                raise ValueError(f"No element matches {args['selector']!r}")
            html = await element.inner_html()
        else:
            html = await page.content()
        return ok(clip(html, args.get("max_chars", 20000), args.get("save_to")))

    if name == "browser_text":
        page = manager.get(args["session_id"]).page
        selector = args.get("selector") or "body"
        element = await page.query_selector(selector)
        if element is None:
            raise ValueError(f"No element matches {selector!r}")
        text = await element.inner_text()
        return ok(clip(text, args.get("max_chars", 20000), args.get("save_to")))

    if name == "browser_eval":
        page = manager.get(args["session_id"]).page
        return ok({"result": await page.evaluate(args["expression"])})

    if name == "browser_computed_style":
        page = manager.get(args["session_id"]).page
        return ok(
            await page.evaluate(
                COMPUTED_STYLE_JS,
                {
                    "selector": args["selector"],
                    "properties": args.get("properties") or [],
                    "limit": args.get("limit", 10),
                },
            )
        )

    if name == "browser_fonts":
        page = manager.get(args["session_id"]).page
        # Webfonts paint after first render; without this the audit can report a
        # family as unresolved purely because it had not finished loading.
        try:
            await page.evaluate("() => document.fonts && document.fonts.ready")
        except Exception:
            pass
        await page.wait_for_timeout(600)
        return ok(await page.evaluate(FONT_AUDIT_JS))

    if name == "browser_console":
        session = manager.get(args["session_id"])
        console = session.console
        if args.get("errors_only"):
            console = [c for c in console if c["type"] in ("error", "warning")]
        return ok(
            {
                "console": console[-100:],
                "page_errors": session.page_errors[-50:],
                "failed_requests": session.failed_requests[-50:],
            }
        )

    raise ValueError(f"Unknown tool: {name}")


# ── Entry point ────────────────────────────────────────────────────────────


async def main() -> None:
    argparse.ArgumentParser(description="browser-use-mcp").parse_args()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        # Leaked Chrome processes accumulate fast across restarts.
        await manager.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
