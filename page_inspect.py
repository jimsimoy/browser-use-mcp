#!/usr/bin/env python3
"""
Page inspection payloads for browser-use-mcp.

These are the tools a screenshot cannot give you: what the browser actually
computed, rather than what the source says or what a picture suggests.

The font audit here exists because that job kept being done by hand — grepping
a theme for `font-family`, then separately working out which of those families
the browser could actually resolve. Source grep cannot tell you that a stack
like `"Some Commercial Font", Georgia, serif` is silently rendering as Georgia
because nothing ever loaded the first family. Measuring in the page can.
"""

from __future__ import annotations

# ── Font audit ─────────────────────────────────────────────────────────────
#
# Availability is decided by measurement, not by document.fonts.check(), which
# is unreliable for locally-installed families. The classic approach: render a
# sample string in `<family>, <fallback>` and in `<fallback>` alone. If the two
# widths match across two very different fallbacks, the family never applied.

FONT_AUDIT_JS = r"""
() => {
  const SAMPLE = 'mmmwwwiiilll0123456789MMMWWW';
  const PROBES = ['monospace', 'serif'];

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');

  function widthWith(stack) {
    ctx.font = '72px ' + stack;
    return ctx.measureText(SAMPLE).width;
  }

  // A family "resolves" if adding it in front of a probe changes the metrics
  // for at least one probe. Generic keywords always resolve by definition.
  const GENERIC = new Set([
    'serif','sans-serif','monospace','cursive','fantasy','system-ui',
    'ui-serif','ui-sans-serif','ui-monospace','ui-rounded','math','emoji','fangsong',
    '-apple-system','blinkmacsystemfont','inherit','initial','unset','revert'
  ]);

  function resolves(family) {
    const clean = family.trim().replace(/^["']|["']$/g, '');
    if (!clean) return { family: clean, resolves: true, generic: true };
    if (GENERIC.has(clean.toLowerCase())) return { family: clean, resolves: true, generic: true };

    const quoted = '"' + clean.replace(/"/g, '\\"') + '"';
    let changed = false;
    for (const probe of PROBES) {
      if (Math.abs(widthWith(quoted + ',' + probe) - widthWith(probe)) > 0.5) {
        changed = true;
        break;
      }
    }
    return { family: clean, resolves: changed, generic: false };
  }

  // --- what the browser actually applied, across visible text -------------
  const stacks = new Map();
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
  let el = walker.currentNode;
  let scanned = 0;

  while (el && scanned < 6000) {
    scanned++;
    // Only elements that actually carry visible text of their own.
    const ownText = Array.from(el.childNodes)
      .filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim())
      .join('');

    if (ownText) {
      const cs = getComputedStyle(el);
      if (cs.display !== 'none' && cs.visibility !== 'hidden') {
        const stack = cs.fontFamily;
        if (!stacks.has(stack)) {
          stacks.set(stack, {
            stack,
            count: 0,
            weights: new Set(),
            sample_text: ownText.slice(0, 60),
            sample_selector: el.tagName.toLowerCase() +
              (el.id ? '#' + el.id : '') +
              (el.className && typeof el.className === 'string'
                ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.')
                : '')
          });
        }
        const rec = stacks.get(stack);
        rec.count++;
        rec.weights.add(cs.fontWeight);
      }
    }
    el = walker.nextNode();
  }

  // --- webfonts the page genuinely loaded ---------------------------------
  const loaded = [];
  const loadedFamilies = new Set();
  try {
    document.fonts.forEach(f => {
      loaded.push({ family: f.family, style: f.style, weight: f.weight, status: f.status });
      // Any declared face counts as "the page ships this family". A face still
      // 'unloaded' is simply one the browser has not needed yet; it would load
      // on demand, so it is not evidence the family is missing.
      loadedFamilies.add(f.family.replace(/^["']|["']$/g, '').toLowerCase());
    });
  } catch (e) { /* FontFaceSet unavailable */ }

  const families_in_use = Array.from(stacks.values())
    .sort((a, b) => b.count - a.count)
    .map(r => {
      const first = r.stack.split(',')[0];
      const verdict = resolves(first);
      const shipped = loadedFamilies.has(verdict.family.toLowerCase());

      // The distinction that makes this audit trustworthy on a designer's
      // machine. A family can render perfectly here and still be invisible to
      // every visitor, because it is installed locally (an Adobe Fonts desktop
      // sync, say) rather than served by the site. Measuring "does it render"
      // alone reports that as fine, which is how a fallback like this survives
      // review for years.
      let source;
      if (verdict.generic)      source = 'generic';
      else if (!verdict.resolves) source = 'fallback';       // nothing has it
      else if (shipped)           source = 'webfont';        // site serves it
      else                        source = 'local_only';     // THIS MACHINE ONLY

      return {
        stack: r.stack,
        elements: r.count,
        weights: Array.from(r.weights).sort(),
        requested_family: verdict.family,
        actually_renders: verdict.resolves,
        source,
        served_by_site: shipped,
        sample_selector: r.sample_selector,
        sample_text: r.sample_text
      };
    });

  // --- @font-face rules and stylesheet origins ----------------------------
  const face_rules = [];
  const sheets = [];

  for (const sheet of Array.from(document.styleSheets)) {
    const origin = { href: sheet.href || '(inline)', cross_origin_blocked: false };
    let rules = null;
    try {
      rules = sheet.cssRules;
    } catch (e) {
      // Reading cssRules of a cross-origin sheet throws. Record it rather than
      // skipping silently: an unreadable sheet may still carry @font-face, so
      // "no @font-face found" is only trustworthy when nothing was blocked.
      origin.cross_origin_blocked = true;
    }
    sheets.push(origin);

    if (!rules) continue;

    for (const rule of Array.from(rules)) {
      if (rule.constructor && rule.constructor.name === 'CSSFontFaceRule') {
        face_rules.push({
          family: (rule.style.getPropertyValue('font-family') || '').trim(),
          weight: (rule.style.getPropertyValue('font-weight') || '').trim(),
          src: (rule.style.getPropertyValue('src') || '').slice(0, 400),
          sheet: sheet.href || '(inline)'
        });
      }
    }
  }

  // --- external font hosts referenced by the document ---------------------
  const HOSTS = ['fonts.googleapis.com','fonts.gstatic.com','use.typekit.net','p.typekit.net',
                 'fonts.adobe.com','fonts.bunny.net','cdn.jsdelivr.net','fast.fonts.net',
                 'cloud.typography.com','use.fontawesome.com'];
  const external = new Set();
  for (const link of Array.from(document.querySelectorAll('link[href]'))) {
    for (const h of HOSTS) if (link.href.includes(h)) external.add(link.href);
  }

  const flag = (f) => ({
    requested_family: f.requested_family,
    stack: f.stack,
    elements: f.elements,
    sample_selector: f.sample_selector
  });

  return {
    url: location.href,
    families_in_use,

    // Named in CSS, available to nobody — always falling back.
    unresolved_families: families_in_use.filter(f => f.source === 'fallback').map(flag),

    // Named in CSS, rendering HERE only because the machine has the font
    // installed. The site does not serve it, so visitors get the next entry in
    // the stack. This is the one a screenshot on a designer's machine hides.
    local_only_families: families_in_use.filter(f => f.source === 'local_only').map(flag),
    loaded_webfonts: loaded,
    font_face_rules: face_rules,
    external_font_urls: Array.from(external),
    stylesheets: sheets,
    elements_scanned: scanned
  };
}
"""


COMPUTED_STYLE_JS = r"""
(args) => {
  const { selector, properties, limit } = args;
  const nodes = Array.from(document.querySelectorAll(selector)).slice(0, limit);

  if (!nodes.length) return { matched: 0, elements: [] };

  return {
    matched: document.querySelectorAll(selector).length,
    returned: nodes.length,
    elements: nodes.map(el => {
      const cs = getComputedStyle(el);
      const out = {};
      // No property list means "everything set on this element", which is far
      // too much; fall back to the properties that actually get asked about.
      const props = (properties && properties.length) ? properties : [
        'font-family','font-size','font-weight','line-height','color',
        'background-color','display','position','margin','padding'
      ];
      for (const p of props) out[p] = cs.getPropertyValue(p).trim();

      const rect = el.getBoundingClientRect();
      return {
        selector: el.tagName.toLowerCase() +
          (el.id ? '#' + el.id : '') +
          (el.className && typeof el.className === 'string'
            ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.')
            : ''),
        text: (el.textContent || '').trim().slice(0, 80),
        box: { x: Math.round(rect.x), y: Math.round(rect.y),
               w: Math.round(rect.width), h: Math.round(rect.height) },
        styles: out
      };
    })
  };
}
"""
