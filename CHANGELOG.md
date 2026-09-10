# Changelog & limitations log

This tool is meant to get better through use. The rule is: **when you hit friction, fix
the tool rather than working around it in the session.** A one-off workaround solves it
once; a fix solves it every time, and the next person never meets the problem.

Working around something and not recording it here is the failure mode to avoid — that is
how a tool stays permanently half-finished while everyone quietly keeps their own scripts.

## How to change it

1. Edit the source here.
2. Run `python3 selftest.py` — it spawns the server over stdio exactly as a client does.
3. Add a case to `selftest.py` for whatever you fixed, so it cannot regress.
4. Note it below.
5. Restart the session to pick up the new build (MCP servers load at session start).

---

## Unreleased

Nothing yet.

## 1.0.0 — 2026-09-10

First release. Every item below came from a concrete failure hit while using an
existing LLM-backed browser MCP for real work, rather than from a feature wishlist:

- **Untrusted local certificates.** `ignore_https_errors=True` by default. Local
  development sites are served over HTTPS that no browser trusts; the previous tooling
  stopped on Chrome's interstitial and crashed twice trying to get past it
  (`Connection closed`, then `Browser process exited before CDP became available`).
- **`browser_computed_style`.** Returning HTML and screenshots but never what the browser
  resolved meant CSS questions kept dropping out of the MCP into hand-rolled Playwright.
- **Budget-aware text tools.** A single `get_html` call returned 315KB and overran the
  tool-result limit, losing the content. `browser_html` / `browser_text` take `selector`,
  `max_chars` and `save_to`.
- **`browser_fonts`**, including `local_only` detection — see README. On its first run it
  corrected a wrong conclusion reached by the manual audit process it was built to replace.
- **No LLM, no API key.** All tools deterministic.
- **Pinned dependencies.** The tooling it replaces was installed unpinned and silently
  resolved to whatever was newest.

---

## Known limitations

Honest list. Add to it rather than rediscovering these.

- **No cookie/profile persistence.** Every session starts clean, so anything behind a login
  must be logged into each time. A `storage_state` load/save pair would fix it.
- **No download handling.** Files a page tries to download are not captured.
- **No iframe traversal.** Selectors only reach the top document. Playwright supports
  `frame_locator`; nothing here exposes it yet.
- **No network log.** `browser_console` reports *failed* requests only. A full request
  list — status, type, size — would answer "what did this page actually load", which is
  most of a performance or third-party-script audit.
- **`browser_fonts` scans a 6000-element cap** and only elements holding their own text
  nodes. Fine for normal pages; a very large DOM could be sampled incompletely
  (`elements_scanned` in the result tells you).
- **Cross-origin stylesheets cannot be read** for `@font-face`. Reported as
  `cross_origin_blocked` rather than skipped, so treat "no @font-face found" as
  provisional whenever that count is above zero.
- **One page per session.** Popups and new tabs are not tracked.
- **`browser_screenshot` full-page on very tall documents** can render blank past a few
  thousand pixels — a headless Chrome trait, not something this wraps around yet. Use a
  `selector` for anything below the fold.
