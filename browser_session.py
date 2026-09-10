#!/usr/bin/env python3
"""
Playwright session management for browser-use-mcp.

One BrowserManager holds any number of named sessions. A session owns a
Playwright browser, a context and a page, plus the diagnostic buffers
(console messages, page errors, failed requests) collected since it opened.

Design notes
------------
* Chrome, not bundled Chromium. `channel="chrome"` reuses the system Google
  Chrome install, so there is no ~150MB browser download to keep in sync and
  what we test is the browser real visitors use. Falls back to bundled
  Chromium only if Chrome is genuinely absent.

* `ignore_https_errors` defaults to True. Every Local by Flywheel site is
  served over HTTPS with an untrusted certificate. Without this the browser
  stops on an interstitial that has to be clicked through, which is exactly
  where the stock browser-use MCP kept dying.

* Diagnostics are collected passively from the moment a session opens, so
  `browser_console` can report what happened during load rather than only
  what happens after you think to ask.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

# Default viewport. Wide enough that desktop layouts render as intended, and a
# deliberate, explicit value: headless Chrome's own default is small enough to
# trigger mobile breakpoints and produce misleading "responsive bug" findings.
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}

# Hard ceiling on any single text payload handed back through MCP. Large pages
# blow the tool-result token limit, so callers get a truncation notice and are
# pointed at `save_to` instead of a silently cut-off document.
MAX_INLINE_CHARS = 60_000


@dataclass
class Session:
    """One open browser page plus everything observed on it."""

    id: str
    browser: Browser
    context: BrowserContext
    page: Page
    created_at: float = field(default_factory=time.time)
    console: list[dict] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_requests: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "session_id": self.id,
            "url": self.page.url,
            "title": "",  # filled in by callers that can await
            "age_seconds": round(time.time() - self.created_at, 1),
            "console_errors": sum(1 for c in self.console if c["type"] == "error"),
            "page_errors": len(self.page_errors),
            "failed_requests": len(self.failed_requests),
        }


class BrowserManager:
    """Owns the Playwright driver and every open session."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def _playwright(self) -> Playwright:
        if self._pw is None:
            self._pw = await async_playwright().start()
        return self._pw

    async def open(
        self,
        url: str | None = None,
        *,
        headless: bool = True,
        viewport: dict | None = None,
        ignore_https_errors: bool = True,
        user_agent: str | None = None,
        wait_until: str = "load",
        timeout_ms: int = 45_000,
    ) -> Session:
        """Open a new session, optionally navigating straight to `url`."""
        pw = await self._playwright()

        try:
            browser = await pw.chromium.launch(channel="chrome", headless=headless)
        except Exception:
            # Chrome absent or unusable — bundled Chromium still lets the tool work.
            browser = await pw.chromium.launch(headless=headless)

        context = await browser.new_context(
            viewport=viewport or DEFAULT_VIEWPORT,
            ignore_https_errors=ignore_https_errors,
            user_agent=user_agent,
        )
        page = await context.new_page()

        session = Session(id=uuid.uuid4().hex[:8], browser=browser, context=context, page=page)
        self._wire_diagnostics(session)

        async with self._lock:
            self._sessions[session.id] = session

        if url:
            await self.goto(session.id, url, wait_until=wait_until, timeout_ms=timeout_ms)

        return session

    def _wire_diagnostics(self, session: Session) -> None:
        """Attach passive listeners before any navigation happens."""

        def on_console(msg) -> None:
            session.console.append(
                {
                    "type": msg.type,
                    "text": msg.text[:500],
                    "location": (msg.location or {}).get("url", ""),
                }
            )

        def on_page_error(err) -> None:
            session.page_errors.append(str(err)[:500])

        def on_request_failed(req) -> None:
            session.failed_requests.append(
                {
                    "url": req.url[:300],
                    "method": req.method,
                    "resource_type": req.resource_type,
                    "failure": (req.failure or ""),
                }
            )

        session.page.on("console", on_console)
        session.page.on("pageerror", on_page_error)
        session.page.on("requestfailed", on_request_failed)

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            known = ", ".join(self._sessions) or "none open"
            raise KeyError(f"No session {session_id!r}. Open sessions: {known}")
        return self._sessions[session_id]

    async def goto(
        self,
        session_id: str,
        url: str,
        *,
        wait_until: str = "load",
        timeout_ms: int = 45_000,
    ) -> dict:
        session = self.get(session_id)
        response = await session.page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        return {
            "url": session.page.url,
            "title": await session.page.title(),
            "status": response.status if response else None,
        }

    async def close(self, session_id: str) -> None:
        session = self.get(session_id)
        try:
            await session.context.close()
            await session.browser.close()
        finally:
            async with self._lock:
                self._sessions.pop(session_id, None)

    async def close_all(self) -> int:
        count = 0
        for sid in list(self._sessions):
            try:
                await self.close(sid)
                count += 1
            except Exception:
                pass
        return count

    async def list_sessions(self) -> list[dict]:
        out = []
        for session in self._sessions.values():
            info = session.summary()
            try:
                info["title"] = await session.page.title()
            except Exception:
                info["title"] = "<unavailable>"
            out.append(info)
        return out

    async def shutdown(self) -> None:
        await self.close_all()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    # ── Screenshots ────────────────────────────────────────────────────────

    async def screenshot(
        self,
        session_id: str,
        *,
        selector: str | None = None,
        full_page: bool = False,
        path: str | None = None,
    ) -> dict:
        """Capture the viewport, the full page, or a single element.

        Element screenshots matter for tall pages: headless Chrome renders
        black past roughly 1500px on a full-page capture, so framing the
        element you care about is more reliable than cropping afterwards.
        """
        session = self.get(session_id)
        target: Any = session.page

        if selector:
            element = await session.page.query_selector(selector)
            if element is None:
                raise ValueError(f"No element matches {selector!r}")
            target = element
            data = await target.screenshot(path=path)
        else:
            data = await target.screenshot(path=path, full_page=full_page)

        return {
            "bytes": len(data),
            "path": path,
            "base64": None if path else base64.b64encode(data).decode(),
        }
