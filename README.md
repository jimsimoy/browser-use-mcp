# Browser Use MCP — Deterministic Browser Control for AI Clients

<div align="center">

<img src="https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square" alt="Python 3.10+">
<a href="https://github.com/jimsimoy/browser-use-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License: MIT"></a>
<a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-compatible-green.svg?style=flat-square" alt="MCP Compatible"></a>
<img src="https://img.shields.io/badge/tools-14-brightgreen.svg?style=flat-square" alt="14 Tools">
<img src="https://img.shields.io/badge/API%20key-not%20required-success.svg?style=flat-square" alt="No API key required">
<img src="https://img.shields.io/badge/dependencies-2-lightgrey.svg?style=flat-square" alt="2 runtime dependencies">

**Real browser control as 14 deterministic MCP tools — navigate, click, type, screenshot, and read what the browser actually computed. No LLM inside the server, no API key, no per-call cost.**

For Claude Desktop, Claude Code, and any MCP client.

by [Jan Ivan Simoy](https://github.com/jimsimoy)

</div>

---

## What is this?

Browser Use MCP is a [Model Context Protocol](https://modelcontextprotocol.io) server that gives AI assistants a real [Playwright](https://playwright.dev/)-driven browser — page navigation, interaction, screenshots, rendered HTML, computed styles, console diagnostics and a font audit.

Three things make it different from the other browser MCP servers:

**There is no model inside it.** Most browser MCP servers embed an LLM so they can accept instructions like *"find the login form and sign in"*. When the caller is already an AI agent, that second model is redundant — it adds an API key to manage, a per-call cost, and a layer of guesswork between the agent and the page. Every tool here is deterministic and takes explicit arguments. Nothing is inferred, and there is no key to configure.

**It tells you what the browser resolved, not what the source says.** `browser_computed_style` returns real `getComputedStyle` values and box geometry, which settles questions that reading CSS cannot — which rule won a specificity contest, what a font stack actually fell back to, whether an element is where you think it is. See [Inspection tools](#inspection-tools).

**It respects your context budget.** A rendered page is frequently hundreds of kilobytes. Returning that into a tool result wastes the window or overruns it outright, and the content is lost either way. Every text tool takes a `selector` to scope it, a `max_chars` budget, and a `save_to` that writes the full document to disk and returns a pointer instead.

**Supported platform:** any MCP client on macOS, Linux, or Windows with Python 3.10+.

---

## Tools

**14 tools**, in four groups.

| Category | Tools | What you can do |
|---|---|---|
| **Session** | 4 | Open and close browsers, navigate, list what is open |
| **Interaction** | 3 | Click by selector or coordinates, type, scroll |
| **Inspection** | 5 | Rendered HTML, visible text, computed styles, font audit, arbitrary JS |
| **Diagnostics** | 2 | Screenshots, console and network errors |

<details>
<summary>Full tool reference</summary>

| Tool | Description |
|---|---|
| `browser_open` | Open a session, optionally navigating to a URL — **start here**. Returns a `session_id` every other tool needs. |
| `browser_goto` | Navigate an existing session to a URL |
| `browser_sessions` | List open sessions with URL, title, age and error counts |
| `browser_close` | Close one session, or every session when `session_id` is omitted |
| `browser_click` | Click by CSS selector, or at viewport coordinates |
| `browser_type` | Type into an element, optionally clearing first or pressing Enter |
| `browser_scroll` | Scroll by a pixel amount, or bring an element into view |
| `browser_screenshot` | Capture the viewport, the full page, or a single element |
| `browser_html` | Rendered HTML after JavaScript, selector-scoped and budget-aware |
| `browser_text` | Visible text content, selector-scoped and budget-aware |
| `browser_eval` | Run a JavaScript function in the page, get JSON back |
| `browser_computed_style` | Resolved CSS values plus box geometry for matching elements |
| `browser_fonts` | Full font audit — see [The font audit](#the-font-audit) |
| `browser_console` | Console messages, uncaught page errors and failed network requests |

</details>

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10 or later |
| Google Chrome | any recent version (optional — see below) |

Runtime dependencies are deliberately minimal — `mcp` and `playwright`, both pinned. There is no LLM SDK, no API client, and no key to supply.

By default the server drives your **system Google Chrome** via Playwright's `channel="chrome"`. That means no ~150MB browser download to keep in sync, and testing happens in the browser your visitors actually use. If Chrome is not installed, `setup.sh` installs bundled Chromium and the server falls back to it automatically.

---

## Installation

```bash
git clone git@github.com:jimsimoy/browser-use-mcp.git
cd browser-use-mcp
./setup.sh
```

Verify before wiring up a client:

```bash
.venv/bin/python selftest.py                    # against example.com
.venv/bin/python selftest.py https://your.site/ # against your own
```

`selftest.py` spawns the server over stdio exactly as an MCP client would and exercises all 14 tools, printing a pass/fail line for each.

---

## Configuration

There is no configuration file and no API key. Behaviour is set per call, on `browser_open`:

| Argument | Default | Purpose |
|---|---|---|
| `url` | — | Navigate immediately on open |
| `headless` | `true` | Set `false` to watch the browser work |
| `viewport_width` / `viewport_height` | `1440` / `900` | Explicit, so layouts render as intended |
| `ignore_https_errors` | `true` | Load sites with self-signed certificates — see [Local development sites](#local-development-sites) |
| `user_agent` | — | Override the User-Agent |
| `wait_until` | `load` | `load`, `domcontentloaded`, `networkidle` or `commit` |

One environment variable, read by `setup.sh` and `run.sh`:

| Variable | Default | Purpose |
|---|---|---|
| `BROWSER_USE_MCP_VENV` | `./.venv` | Put the virtualenv somewhere other than the checkout |

---

## Client Setup

```json
{
  "mcpServers": {
    "browser-use": {
      "command": "/path/to/browser-use-mcp/run.sh"
    }
  }
}
```

Or invoke the interpreter directly, skipping the launcher:

```json
{
  "mcpServers": {
    "browser-use": {
      "command": "/path/to/browser-use-mcp/.venv/bin/python",
      "args": ["/path/to/browser-use-mcp/server.py"]
    }
  }
}
```

With Claude Code:

```bash
claude mcp add browser-use --scope user -- /path/to/browser-use-mcp/run.sh
```

Restart your MCP client after saving.

---

## Inspection tools

### Local development sites

`ignore_https_errors` defaults to `true`. Local development environments — Local by Flywheel, Valet, DDEV, Docker with a self-signed cert — serve HTTPS that no browser trusts. Without this, the browser stops on an interstitial that has to be clicked through by coordinate, which is fragile and a common cause of crashes in browser automation tooling.

Set it to `false` when you specifically want certificate validation enforced.

### Computed styles

```
browser_computed_style(session_id, selector, properties?, limit?)
```

Returns real `getComputedStyle` values plus a bounding box for each matching element. Omit `properties` for a sensible typography and layout default set.

This answers what source-reading cannot. A stylesheet says an element *should* be 24px Inter; only the browser knows whether a later rule, a specificity contest, or a missing font changed that.

### Budget-aware extraction

`browser_html` and `browser_text` both take:

- `selector` — scope to one element instead of the whole document
- `max_chars` — truncate with an explicit notice rather than overrunning
- `save_to` — write the full content to a file and return a path plus a preview

Reach for `selector` first. `save_to` is for when you genuinely need the whole document.

---

## The font audit

`browser_fonts` reports every computed font stack on the page with how many elements use it, which webfonts loaded, `@font-face` rules, external font hosts, and the weights in use.

The part that makes it worth having is that it classifies each stack by **where the font actually came from**:

| Source | Meaning |
|---|---|
| `webfont` | The site serves this font. Working as intended. |
| **`local_only`** | **It renders on this machine because the font is installed here — the site does not serve it. Visitors get the next entry in the stack.** |
| `fallback` | Nothing has this font. Always falling back. |
| `generic` | A generic keyword such as `serif`. |

`local_only` is the case that hides from every other method. A designer with a commercial font installed — through an Adobe Fonts desktop sync, say — sees the intended typeface on their own machine and in every screenshot they take, while the site never serves it and visitors have always seen the fallback. Source grep cannot detect it, because the CSS is present and correct. A screenshot cannot detect it, because the screenshot looks right.

Two results are surfaced directly for that reason:

- `local_only_families` — renders for you, not for visitors
- `unresolved_families` — renders for nobody

### On measurement

Availability is decided by **canvas text metrics**: render a sample string in `<family>, <probe>` and in `<probe>` alone, across two dissimilar probes, and compare widths. If nothing changes, the family never applied.

`document.fonts.check()` is not used, because it is unreliable for this — it returns `true` for font families that do not exist at all.

### Caveat

Reading `cssRules` on a cross-origin stylesheet throws a `SecurityError`. Those sheets are reported in `stylesheets[]` with `cross_origin_blocked: true` rather than skipped silently, so *"no `@font-face` found"* is only trustworthy when that count is zero.

---

## Usage Examples

**Check what a page really loaded**

```
browser_open(url="https://example.com/")
browser_console(session_id)          → JS errors, failed requests
browser_fonts(session_id)            → what is served vs. faked locally
```

**Settle a CSS question**

```
browser_computed_style(session_id, selector="h1", properties=["font-family","font-size","color"])
```

**Read a large page without burning the context window**

```
browser_html(session_id, selector="main .article-body", max_chars=8000)
browser_html(session_id, save_to="/tmp/page.html")     → full document to disk
```

**Fill and submit a form**

```
browser_type(session_id, selector="#email", text="someone@example.com")
browser_click(session_id, selector="button[type=submit]")
browser_text(session_id, selector=".confirmation")
```

---

## Security

This server drives a real browser as the user running it, with that user's network access. It has no sandbox of its own.

- **`browser_eval` executes arbitrary JavaScript** in the page. It is as powerful as the browser console.
- **`browser_screenshot` and `browser_html` capture whatever is on screen**, including anything behind a login you are signed into.
- **`ignore_https_errors` is on by default**, which is right for local development and wrong for verifying a production certificate. Set it to `false` when validation is the point.
- Sessions start with a clean profile and no stored credentials. Nothing is persisted between runs.

---

## Project Structure

```
browser-use-mcp/
├── server.py            # MCP server: tool schemas and dispatch
├── browser_session.py   # Playwright lifecycle, sessions, diagnostics
├── page_inspect.py      # Injected JS for the font audit and computed styles
├── selftest.py          # End-to-end test over real stdio
├── setup.sh             # Creates the venv, installs pinned deps
├── run.sh               # Launcher used by the MCP client
├── requirements.txt
└── CHANGELOG.md         # Includes an honest known-limitations list
```

---

## Development

The design rule is: **when you hit a limitation, extend the tool rather than working around it.** A workaround solves the problem once and leaves the gap for next time.

1. Edit the source.
2. Run `selftest.py` — it exercises the real stdio path, not a mock.
3. Add a case for whatever you changed, so it cannot regress.
4. Note it in [CHANGELOG.md](./CHANGELOG.md).
5. Restart your MCP client — servers load at client start.

[CHANGELOG.md](./CHANGELOG.md) carries a deliberately honest **Known limitations** list — no cookie persistence, no download handling, no iframe traversal, no full network log. Read it before assuming something is missing by accident.

---

## License

[MIT](./LICENSE) — free to use, modify, and distribute. Provided "as is", without warranty of any kind.

---

<div align="center">

[Report a Bug](https://github.com/jimsimoy/browser-use-mcp/issues) · [Request a Feature](https://github.com/jimsimoy/browser-use-mcp/issues)

</div>
