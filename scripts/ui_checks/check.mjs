#!/usr/bin/env node
// Browser checks for the site's pages: accessibility basics, CSP, overflow and forbidden source links.
//
//   node scripts/ui_checks/check.mjs [--base http://127.0.0.1:8771] [--only /,/chat/] [--widths 1440,390]
//                                    [--out DIR] [--json]
//
// Drives an installed Chrome headless over the DevTools protocol (Node 22+, no npm install).
// Each page in pages.json is opened at every width, and in every reader theme it lists. Exit code 1
// when any FAIL is found. WARNs are printed but do not fail the run. Screenshots go to --out if given.
//
// FAIL: page errors or CSP violations, wrong HTTP status, no <main> or more than one, no skip link to
// it, no or several h1, missing html lang, images without alt, controls or links without an accessible
// name, duplicate ids, a stray "null", "undefined" or "NaN" printed as text, text under WCAG AA contrast, horizontal page overflow, forbidden source URLs or
// fields in the page (data.sec.gov, efts, GLEIF API, FIRDS files, first_detected_at, source_updated_at),
// a figure link without a visible underline (every number is a door, on every theme), a figure or data mark
// (chart label, SVG shape, HTML bar, Chart.js dataset) drawn in the brand's marker
// yellow (it may only sit behind a figure as the highlight), chart series too alike to tell apart (normal or
// colour-blind vision) or under 3:1 against the chart, a link to /docs/flags/#x with no such entry on that page, and, for an entry with sweepAt, light text under
// the marker while the provenance highlight sweeps (pixels read from a PNG of the figure at that moment).
// A page's documented API errors (a 403 demo scope, a 404 not read) are excused only by allowHttp [{status, url, code}]:
// the failed request's status, URL and JSON error.code must all match; every other failed request fails.
// WARN: skipped heading levels, touch targets under 24px, text under 12px.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { inflateSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf('--' + name); return i === -1 ? def : args[i + 1]; };
const flag = (name) => args.includes('--' + name);
const config = JSON.parse(readFileSync(join(here, 'pages.json'), 'utf8'));
const base = (opt('base', process.env.UI_BASE || 'http://127.0.0.1:8771')).replace(/\/$/, '');
const widths = opt('widths', '') ? opt('widths').split(',').map(Number) : config.widths;
const only = opt('only', '') ? new Set(opt('only').split(',')) : null;
const out = opt('out', '');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CHROME = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].find((p) => p && existsSync(p));
if (!CHROME) { console.error('No Chrome found; set CHROME_PATH.'); process.exit(2); }
if (typeof WebSocket === 'undefined') { console.error('Node 22+ is required.'); process.exit(2); }

// ---- a tiny CDP client ----
const profile = mkdtempSync(join(tmpdir(), 'prv-ui-'));
const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--force-color-profile=srgb', 'about:blank'],
  { stdio: ['ignore', 'ignore', 'pipe'] });
const cleanup = () => { try { proc.kill('SIGKILL'); } catch {} try { rmSync(profile, { recursive: true, force: true }); } catch {} };
process.on('exit', cleanup);
const wsUrl = await new Promise((resolve, reject) => {
  let buf = ''; const t = setTimeout(() => reject(new Error('Chrome did not start')), 20000);
  proc.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
});
const ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let nextId = 1; const pending = new Map(); const listeners = [];
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result); }
  else if (msg.method) for (const l of listeners) if (l.session === msg.sessionId && l.method === msg.method) l.fn(msg.params);
};
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = nextId++; pending.set(id, { resolve, reject });
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error('timeout ' + method)); } }, 30000);
});

// ---- the in-page audit (runs in the browser) ----
function audit() {
  const fail = [], warn = [];
  const vis = (el) => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const name = (el) => (el.getAttribute('aria-label') || (el.getAttribute('aria-labelledby') || '').split(' ').map((id) => document.getElementById(id)?.textContent || '').join(' ') || el.textContent || el.getAttribute('title') || el.querySelector('img[alt]')?.alt || el.value || '').trim();
  const desc = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');

  if (!document.documentElement.lang) fail.push('html has no lang');
  const mains = document.querySelectorAll('main, [role=main]');
  if (mains.length !== 1) fail.push(`${mains.length} main landmarks (want 1)`);
  const skip = [...document.querySelectorAll('a[href^="#"]')].find((a) => /skip/i.test(a.textContent));
  if (!skip) fail.push('no skip link');
  else if (!document.getElementById(skip.getAttribute('href').slice(1))) fail.push(`skip link target ${skip.getAttribute('href')} missing`);
  const h1s = [...document.querySelectorAll('h1')].filter(vis);
  if (h1s.length !== 1) fail.push(`${h1s.length} visible h1 (want 1)`);
  let last = 0;
  for (const h of [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(vis)) {
    const n = +h.tagName[1]; if (last && n > last + 1) warn.push(`heading skips h${last}→h${n}: "${h.textContent.trim().slice(0, 40)}"`); last = n;
  }
  for (const img of document.querySelectorAll('img')) if (!img.hasAttribute('alt')) fail.push(`img without alt: ${img.src.slice(-50)}`);
  for (const img of document.querySelectorAll('img')) if (img.complete && img.naturalWidth === 0 && vis(img)) fail.push(`broken image: ${img.src.slice(-60)}`);
  const targets = [];
  for (const el of document.querySelectorAll('a[href], button, [role=button], [role=tab], [role=link]')) {
    if (!vis(el)) continue;
    if (!name(el)) fail.push(`no accessible name: ${desc(el)}`);
    targets.push(el);
  }
  // WCAG 2.5.8: a target under 24px passes when a 24px circle on its centre touches no other target.
  const centre = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }; };
  const cs = targets.map(centre);
  cs.forEach((c, i) => {
    if (c.w >= 24 && c.h >= 24) return;
    if (getComputedStyle(targets[i]).display === 'inline' || targets[i].closest('p, td, dd, figcaption, small')) return;
    const crowded = cs.some((o, j) => j !== i && Math.hypot(o.x - c.x, o.y - c.y) < 24);
    if (crowded) warn.push(`target ${Math.round(c.w)}×${Math.round(c.h)}px crowded: ${desc(targets[i])} "${name(targets[i]).slice(0, 30)}"`);
  });
  for (const el of document.querySelectorAll('input:not([type=hidden]), select, textarea')) {
    if (!vis(el)) continue;
    const labelled = el.labels?.length || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title');
    if (!labelled) fail.push(`form control without label: ${desc(el)}${el.placeholder ? ' (placeholder is not a label)' : ''}`);
  }
  const ids = {}; for (const el of document.querySelectorAll('[id]')) ids[el.id] = (ids[el.id] || 0) + 1;
  for (const [id, n] of Object.entries(ids)) if (n > 1) fail.push(`duplicate id "${id}" ×${n}`);

  // contrast of every visible text node's element against its painted background
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 }; };
  const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const blend = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  const bgOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage !== 'none' && !/gradient/.test(s.backgroundImage)) return null; // a picture: can't judge
      const c = parse(s.backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    for (const c of layers.reverse()) bg = blend(c, bg);
    return bg;
  };
  const seen = new Set(); let low = 0; const lowSamples = [];
  // brand (Trace): the marker yellow is never a figure's own colour, as text or as a chart label; it
  // may only sit behind a figure as the highlight, with --marker-ink on it. Up and down stay green and red.
  const hex = (v) => { const m = /^#([0-9a-f]{6})$/i.exec((v || '').trim()); return m ? { r: parseInt(m[1].slice(0, 2), 16), g: parseInt(m[1].slice(2, 4), 16), b: parseInt(m[1].slice(4), 16), a: 1 } : null; };
  const marker = hex(getComputedStyle(document.documentElement).getPropertyValue('--marker'));
  const near = (c, m) => c && m && Math.abs(c.r - m.r) + Math.abs(c.g - m.g) + Math.abs(c.b - m.b) < 24;
  const FIGURE = /^[(−+\-]?\s?[$€£¥]?\s?\d[\d,.]*\s?(%|[KMBT]|bn|pp)?\)?$/;
  const yellow = [];
  for (const t of document.querySelectorAll('svg text')) if (FIGURE.test(t.textContent.trim()) && near(parse(getComputedStyle(t).fill), marker)) yellow.push(`chart label "${t.textContent.trim()}"`);
  // data marks are figures too: SVG chart shapes, empty HTML bars, and Chart.js datasets (canvas)
  const mark = (c) => near(parse(c) || hex(c), marker);
  for (const g of document.querySelectorAll('svg[role=img], svg.spark, svg[class*=chart]')) {
    for (const sh of g.querySelectorAll('rect, circle, ellipse, path, polyline, polygon, line')) {
      const cs = getComputedStyle(sh); if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      if ((mark(cs.fill) || mark(cs.stroke)) && yellow.length < 6) yellow.push(`chart mark ${sh.tagName}.${sh.getAttribute('class') || ''} in svg.${g.getAttribute('class') || ''}`);
    }
  }
  for (const el of document.querySelectorAll('main *')) {
    if (!/(^|\s)(bar|bar-h|col|last|latest|hot|dot)(\s|$)/.test(typeof el.className === 'string' ? el.className : '') || el.textContent.trim() || el.closest('svg, .theme-pick') || /^(INPUT|SELECT|TEXTAREA|IMG|CANVAS)$/.test(el.tagName) || !vis(el)) continue;
    const cs = getComputedStyle(el); if (cs.maskImage && cs.maskImage !== 'none') continue; // the logo, drawn as a mask
    if (mark(cs.backgroundColor) && yellow.length < 6) yellow.push(`data mark ${desc(el)}`);
  }
  // the logo (a mask of mark.svg painted in --mark) must stand out from what it sits on: 3:1, as for any graphic
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el); if (!/mark\.svg/.test(cs.maskImage || cs.webkitMaskImage || '') || !vis(el)) continue;
    const c = parse(cs.backgroundColor), bg = el.parentElement && bgOf(el.parentElement); if (!c || !bg) continue;
    const L1 = lum(blend(c, bg)), L2 = lum(bg), r = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    if (r < 3) fail.push(`logo mark at ${r.toFixed(2)}:1 against its background (${desc(el)})`);
  }
  // a legend's key stands for a series, so it is a data mark too: an empty swatch inside a legend or key
  for (const el of document.querySelectorAll('main [class*=legend] *, main [class*=key] *')) {
    if (el.textContent.trim() || el.children.length || el.closest('svg') || !vis(el)) continue;
    const r = el.getBoundingClientRect(); if (r.width > 24 || r.height > 24) continue;
    const cs = getComputedStyle(el);
    if ((mark(cs.backgroundColor) || mark(cs.borderTopColor) && parseFloat(cs.borderTopWidth) >= 2) && yellow.length < 6) yellow.push(`legend swatch ${desc(el)}`);
  }
  // categorical series (a chart with 2+ series): neighbours must be told apart with normal vision (OKLab ΔE×100 >= 15)
  // and under protan, deutan and tritan simulation (>= 6, Machado 2009 at full severity), and each series must hold
  // 3:1 against the chart's background. Pairs: adjacent slots, plus all pairs among the first three (the palette's design).
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const CVDM = { protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
    tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]] };
  const okl = (c, kind) => {
    let v = [lin(c.r), lin(c.g), lin(c.b)];
    if (kind) { const M = CVDM[kind]; v = M.map((row) => Math.min(1, Math.max(0, row[0] * v[0] + row[1] * v[1] + row[2] * v[2]))); }
    const l = Math.cbrt(0.4122214708 * v[0] + 0.5363325363 * v[1] + 0.0514459929 * v[2]), m = Math.cbrt(0.2119034982 * v[0] + 0.6806995451 * v[1] + 0.1073969566 * v[2]), q = Math.cbrt(0.0883024619 * v[0] + 0.2817188376 * v[1] + 0.6299787005 * v[2]);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * q, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * q, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * q];
  };
  const dE = (x, y, kind) => { const a = okl(x, kind), b = okl(y, kind); return 100 * Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); };
  const series = [];
  // computed colours can come back as color(srgb r g b / a) from color-mix()
  const anyc = (v) => { const m = /color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/.exec(v || ''); return m ? { r: m[1] * 255, g: m[2] * 255, b: m[3] * 255, a: m[4] == null ? 1 : +m[4] } : (parse(v || '') || hex(v)); };
  const judge = (name, cols, bg) => {
    const slots = Object.keys(cols).map(Number).sort((x, y) => x - y); if (slots.length < 2) return;
    const pairs = [];
    slots.forEach((k, i) => { if (i) pairs.push([slots[i - 1], k]); });
    slots.filter((k) => k < 3).forEach((k, i, f) => f.slice(i + 1).forEach((j) => { if (!pairs.some((p) => p[0] === k && p[1] === j)) pairs.push([k, j]); }));
    for (const [i, j] of pairs) {
      const n = dE(cols[i], cols[j]), cvd = Math.min(...['protan', 'deutan', 'tritan'].map((k) => dE(cols[i], cols[j], k)));
      if ((n < 15 || cvd < 6) && series.length < 6) series.push(`${name}: series ${i + 1} and ${j + 1} too alike (ΔE ${n.toFixed(1)} normal, ${cvd.toFixed(1)} colour-blind)`);
    }
    if (bg) for (const k of slots) { const c = blend(cols[k], bg), L1 = lum(c), L2 = lum(bg), r = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05); if (r < 3 && series.length < 6) series.push(`${name}: series ${k + 1} is ${r.toFixed(2)}:1 against its background`); }
  };
  for (const g of document.querySelectorAll('svg[role=img], svg[class*=chart]')) {
    if (!vis(g)) continue;
    const bg = bgOf(g), cols = {};
    for (const sh of g.querySelectorAll('[class]')) {
      const cl = typeof sh.className === 'string' ? sh.className : sh.className.baseVal, m = /\b(?:k|c)([0-7])\b/.exec(cl) || (g.classList.contains('multi') && /\bs([0-7])\b/.exec(cl));
      if (!m || cols[+m[1]]) continue;
      const cs = getComputedStyle(sh), paint = cs.fill && cs.fill !== 'none' && !/url/.test(cs.fill) ? cs.fill : cs.stroke;
      const c = anyc(paint); if (c && c.a > 0) cols[+m[1]] = bg ? blend(c, bg) : c;
    }
    judge('chart ' + (g.getAttribute('aria-label') || g.getAttribute('class') || '').slice(0, 40), cols, bg);
  }
  if (window.Chart && window.Chart.instances) for (const c of Object.values(window.Chart.instances)) {
    // datasets drawn in one exact colour (a low-to-high range as two lines) are one series
    const cols = {}, seenc = []; c.data.datasets.forEach((d, i) => { const v = [].concat(d.borderColor || [], d.backgroundColor || []).find((x) => typeof x === 'string'); const p = v && anyc(v); if (p && seenc.indexOf(v) < 0) { seenc.push(v); cols[i] = p; } });
    judge('chat chart', cols, bgOf(c.canvas));
  }
  if (window.Chart && window.Chart.instances) for (const c of Object.values(window.Chart.instances)) for (const d of c.data.datasets) {
    for (const k of ['backgroundColor', 'borderColor', 'pointBackgroundColor', 'pointBorderColor']) for (const v of [].concat(d[k] || [])) if (typeof v === 'string' && mark(v) && yellow.length < 6) yellow.push(`chart dataset "${d.label}" ${k}`);
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: (n) => n.textContent.trim() ? 1 : 2 });
  const stray = [];
  while (walker.nextNode()) {
    // a null or undefined child handed to the DOM prints itself: "null" on the page is always a bug
    const raw = walker.currentNode.textContent.trim(), pe = walker.currentNode.parentElement;
    if (/^(null|undefined|NaN)$/.test(raw) && pe && !pe.closest('pre, code') && stray.length < 4) stray.push(`"${raw}" in ${desc(pe)}`);
    const el = walker.currentNode.parentElement; if (!el || seen.has(el) || !vis(el)) continue; seen.add(el);
    if (FIGURE.test(raw) && near(parse(getComputedStyle(el).color), marker) && yellow.length < 6) yellow.push(`"${raw}" in ${desc(el)}`);
    if (el.closest('[aria-hidden=true], .sr-only, .visually-hidden, svg')) continue;
    const s = getComputedStyle(el); if (+s.opacity === 0) continue;
    const fg = parse(s.color); const bg = bgOf(el); if (!fg || !bg) continue;
    const c = blend(fg, bg); const L1 = lum(c), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(s.fontSize), bold = +s.fontWeight >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const disabled = el.closest('[disabled], [aria-disabled=true]');
    if (ratio < need && !disabled) { low++; if (lowSamples.length < 6) lowSamples.push(`${ratio.toFixed(2)}:1 "${el.textContent.trim().slice(0, 32)}" (${desc(el)})`); }
    if (size < 12 && !el.closest('pre, code')) warn.push(`text ${size}px: "${el.textContent.trim().slice(0, 30)}"`);
  }
  if (low) fail.push(`${low} text element(s) under AA contrast, e.g. ${lowSamples.join('; ')}`);
  if (stray.length) fail.push(`stray text: ${stray.join('; ')}`);
  // every number is a door, on every theme: a figure that links (an <a> or a provenance door) shows its underline
  const bare = [];
  for (const a of document.querySelectorAll('a[href], button.door')) {
    const t = a.textContent.trim(); if (!FIGURE.test(t) || !vis(a) || a.closest('svg')) continue;
    const cs = getComputedStyle(a), dc = anyc(cs.textDecorationColor);
    if (!/underline/.test(cs.textDecorationLine) || (dc && dc.a === 0)) { if (bare.length < 4) bare.push(`"${t}" (${desc(a)})`); }
  }
  if (bare.length) fail.push(`figure link without a visible underline: ${bare.join('; ')}`);
  if (yellow.length) fail.push(`figure in the marker yellow (only the highlight may be yellow): ${yellow.join('; ')}`);
  if (series.length) fail.push(`chart series hard to tell apart: ${series.join('; ')}`);

  if (document.documentElement.scrollWidth > innerWidth + 1) {
    const wide = [...document.querySelectorAll('body *')].filter((e) => { const r = e.getBoundingClientRect(); return r.right > innerWidth + 1 && vis(e) && !e.closest('[data-scroll-x], pre, table, .table-scroll'); }).slice(0, 3).map(desc);
    fail.push(`page scrolls sideways (${document.documentElement.scrollWidth}px > ${innerWidth}px): ${wide.join(', ')}`);
  }

  const html = document.documentElement.outerHTML;
  for (const bad of ['data.sec.gov', 'efts.sec.gov', 'api.gleif.org', 'registers.esma.europa.eu', 'fca-firds', 'first_detected_at', 'source_updated_at']) {
    if (html.includes(bad)) fail.push(`forbidden source reference in page: ${bad}`);
  }
  return { fail, warn: [...new Set(warn)].slice(0, 12), title: document.title };
}

async function view(page, theme, width) {
    // every page view gets its own browser context, so storage set by one check never leaks into the next
    const { browserContextId } = await send('Target.createBrowserContext', {});
    const { targetId } = await send('Target.createTarget', { url: 'about:blank', browserContextId });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    const errors = [], netErr = new Map(); let status = 0; // netErr: a resource-load error line -> its request (url, id)
    listeners.push({ session: sessionId, method: 'Runtime.exceptionThrown', fn: (p) => errors.push('JS: ' + (p.exceptionDetails.exception?.description || p.exceptionDetails.text).split('\n')[0]) });
    listeners.push({ session: sessionId, method: 'Log.entryAdded', fn: (p) => { if (p.entry.level !== 'error') return; const t = (/Content Security Policy/.test(p.entry.text) ? 'CSP: ' : 'console: ') + p.entry.text.slice(0, 200) + (p.entry.source === 'network' && p.entry.url ? ' [' + p.entry.url.replace(/^https?:\/\/[^/]+/, '') + ']' : ''); errors.push(t); if (p.entry.source === 'network') netErr.set(t, { url: p.entry.url || '', id: p.entry.networkRequestId }); } });
    listeners.push({ session: sessionId, method: 'Runtime.consoleAPICalled', fn: (p) => { if (p.type === 'error') errors.push('console.error: ' + p.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 200)); } });
    listeners.push({ session: sessionId, method: 'Network.responseReceived', fn: (p) => { if (p.type === 'Document') status = p.response.status; } });
    for (const d of ['Page', 'Runtime', 'Log', 'Network']) await send(d + '.enable', {}, sessionId);
    const mobile = width < 600;
    await send('Emulation.setDeviceMetricsOverride', { width, height: mobile ? 844 : 900, deviceScaleFactor: 1, mobile }, sessionId);
    if (theme) await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{localStorage.setItem('prv-theme',${JSON.stringify(theme)})}catch(e){}` }, sessionId);
    // a page may preset browser storage and stub API responses, to check states without writing data
    if (page.storage) await send('Page.addScriptToEvaluateOnNewDocument', { source: `try{${Object.entries(page.storage).map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)},${JSON.stringify(v)})`).join(';')}}catch(e){}` }, sessionId);
    if (page.stubs) {
      // a stub either replaces a response (body) or adds fields to the real one (merge, at the response stage)
      await send('Fetch.enable', { patterns: [{ urlPattern: '*/v1/*', requestStage: 'Request' }, { urlPattern: '*/v1/*', requestStage: 'Response' }, { urlPattern: '*/openapi.json*', requestStage: 'Request' }, { urlPattern: '*/openapi.json*', requestStage: 'Response' }] }, sessionId);
      listeners.push({ session: sessionId, method: 'Fetch.requestPaused', fn: async (ev) => {
        const stub = page.stubs.find((st) => new RegExp(st.match).test(ev.request.url));
        const atResponse = ev.responseStatusCode !== undefined;
        const late = stub && (stub.merge || stub.transform);
        if (!stub || (late ? !atResponse : atResponse)) { send('Fetch.continueRequest', { requestId: ev.requestId }, sessionId).catch(() => {}); return; }
        let payload = stub.body;
        if (late) {
          try {
            const got = await send('Fetch.getResponseBody', { requestId: ev.requestId }, sessionId);
            payload = JSON.parse(got.base64Encoded ? Buffer.from(got.body, 'base64').toString() : got.body);
            if (stub.merge) payload = Object.assign(payload, stub.merge);
            // transform: the body of a function of the parsed response (b) that returns it; from pages.json only
            if (stub.transform) payload = new Function('b', stub.transform)(payload);
          } catch { send('Fetch.continueRequest', { requestId: ev.requestId }, sessionId).catch(() => {}); return; }
        }
        const body = Buffer.from(JSON.stringify(payload)).toString('base64');
        send('Fetch.fulfillRequest', { requestId: ev.requestId, responseCode: stub.status || (late ? ev.responseStatusCode : 200), responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body }, sessionId).catch(() => {});
      } });
    }
    const loaded = new Promise((r) => listeners.push({ session: sessionId, method: 'Page.loadEventFired', fn: r }));
    await send('Page.navigate', { url: base + page.path }, sessionId);
    await Promise.race([loaded, sleep(20000)]);
    // live fetches and reveals: wait until a visible h1 is on the page (up to 8 s), then settle
    for (let t = 0; t < 32; t++) {
      const r0 = await send('Runtime.evaluate', { expression: `[...document.querySelectorAll('h1')].some(h => h.getBoundingClientRect().height > 0 && getComputedStyle(h).visibility !== 'hidden')`, returnByValue: true }, sessionId);
      if (r0.result?.value) break;
      await sleep(250);
    }
    await sleep(900);
    // waitFor: content drawn late (a chart behind a lazy script) is audited once it is there, up to 8 s more
    if (page.waitFor) for (let t = 0; t < 32; t++) { const w = await send('Runtime.evaluate', { expression: page.waitFor, returnByValue: true }, sessionId).catch(() => null); if (w && w.result && w.result.value) break; await sleep(250); }
    const r = await send('Runtime.evaluate', { expression: `(${audit})()`, returnByValue: true }, sessionId);
    const res = r.result?.value || { fail: ['audit crashed: ' + (r.exceptionDetails?.exception?.description || '?')], warn: [] };
    const want = page.status || 200;
    if (status !== want) res.fail.unshift(`HTTP ${status} (want ${want})`);
    const allowed = (page.allowConsole || []).map((p) => new RegExp(p));
    // allowHttp: [{status, url, code}] excuses Chrome's resource-load line for one documented API answer only: the
    // line's status, the request's URL and its JSON body's error.code must all match (e.g. 404 on /changes with
    // changes_not_available); any other failed request on the page still fails. allowConsole is not for status lines.
    const excused = new Set();
    for (const [line, req] of netErr) {
      const st = +((/status of (\d{3})/.exec(line) || [])[1]);
      const rules = (page.allowHttp || []).filter((a) => a.status === st && new RegExp(a.url).test(req.url));
      if (!rules.length || !req.id) continue;
      const got = await send('Network.getResponseBody', { requestId: req.id }, sessionId).catch(() => null);
      let code = null; try { code = JSON.parse(got.base64Encoded ? Buffer.from(got.body, 'base64').toString() : got.body).error.code; } catch {}
      if (rules.some((a) => a.code === code)) excused.add(line);
    }
    res.fail.push(...[...new Set(errors)].filter((e) => !excused.has(e) && !(want === 404 && /404/.test(e)) && !allowed.some((re) => re.test(e))));
    // a mark that explains itself must land on its entry: /docs/flags/#x with x an id on that page
    const fl = await send('Runtime.evaluate', { expression: `[...document.querySelectorAll('a[href^="/docs/flags/#"]')].map((a) => a.getAttribute('href').slice(13))`, returnByValue: true }, sessionId).catch(() => null);
    for (const id of new Set((fl && fl.result && fl.result.value) || [])) if (!flagIds.has(id)) res.fail.push('link to /docs/flags/#' + id + ': no such entry');
    // page-specific expectations: each a JS expression that must be true once the page has settled
    for (const ex of page.expect || []) {
      let okEx = false;
      for (let t = 0; t < 20 && !okEx; t++) {
        const r1 = await send('Runtime.evaluate', { expression: ex.js, returnByValue: true }, sessionId).catch(() => null);
        okEx = !!(r1 && r1.result && r1.result.value);
        if (!okEx) await sleep(250);
      }
      if (!okEx) res.fail.push('expectation failed: ' + ex.label);
    }
    // sweepAt (brand B-4): open the first figure's provenance card, hold every animation at that many ms, and
    // read the figure's pixels: in the columns the marker already covers, no pixel may be light text (blue > 150)
    if (page.sweepAt != null) {
      const r2 = await send('Runtime.evaluate', { returnByValue: true, expression: `(() => { const d = document.querySelector('${page.sweepDoor || '#pane-overview .ov-table .door'}'); if (!d) return null;
        d.scrollIntoView({ block: 'center' }); d.click(); document.getAnimations().forEach((a) => { a.pause(); a.currentTime = ${+page.sweepAt}; });
        const r = d.getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height, scale: 2 }; })()` }, sessionId);
      const clip = r2.result && r2.result.value;
      if (!clip) res.fail.push('sweep: no figure door to open');
      else {
        // let the held frame paint before the capture (two animation frames)
        await send('Runtime.evaluate', { awaitPromise: true, expression: 'new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))' }, sessionId);
        await sleep(120);
        const shot = await send('Page.captureScreenshot', { format: 'png', clip }, sessionId);
        const im = decodePng(Buffer.from(shot.data, 'base64')), yellow = (c) => c[0] > 200 && c[1] > 180 && c[2] < 130;
        let cols = 0, light = 0;
        for (let x = 8; x < im.w - 2; x++) { // from x = 8: the highlight's rounded corners show the page through
          const half = (cx) => { let n = 0; for (let y = 0; y < im.h; y++) if (yellow(im.at(cx, y))) n++; return n >= im.h * 0.5; };
          if (!half(x) || !half(x + 2)) continue; // a covered column away from the clip's moving edge
          cols++; for (let y = 0; y < im.h; y++) if (im.at(x, y)[2] > 150) light++;
        }
        if (cols < 5) res.fail.push(`sweep at ${page.sweepAt} ms: the marker covers ${cols} columns, too few to judge`);
        else if (light) res.fail.push(`sweep at ${page.sweepAt} ms: ${light} light pixels under the marker (the figure must be ink wherever the marker is)`);
      }
    }
    if (out) {
      mkdirSync(out, { recursive: true });
      const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 70 }, sessionId);
      const slug = (page.path.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'home') + (theme ? '-' + theme : '') + '-' + width;
      writeFileSync(join(out, slug + '.jpg'), Buffer.from(shot.data, 'base64'));
    }
    await send('Target.closeTarget', { targetId });
    await send('Target.disposeBrowserContext', { browserContextId }).catch(() => {});
  return res;
}
// a PNG from Page.captureScreenshot (8-bit RGB or RGBA, not interlaced), for the sweep check
function decodePng(b) {
  let p = 8, w = 0, h = 0, ct = 2; const idat = [];
  while (p < b.length) {
    const len = b.readUInt32BE(p), type = b.toString('ascii', p + 4, p + 8), d = b.subarray(p + 8, p + 8 + len);
    if (type === 'IHDR') { w = d.readUInt32BE(0); h = d.readUInt32BE(4); ct = d[9]; } else if (type === 'IDAT') idat.push(d);
    p += 12 + len;
  }
  const bpp = ct === 6 ? 4 : 3, st = w * bpp, raw = inflateSync(Buffer.concat(idat)), px = Buffer.alloc(w * h * bpp);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (st + 1)], row = y * (st + 1) + 1;
    for (let x = 0; x < st; x++) {
      const a = x >= bpp ? px[y * st + x - bpp] : 0, u = y ? px[(y - 1) * st + x] : 0, c = x >= bpp && y ? px[(y - 1) * st + x - bpp] : 0;
      let pr = 0;
      if (f === 1) pr = a; else if (f === 2) pr = u; else if (f === 3) pr = (a + u) >> 1;
      else if (f === 4) { const q = a + u - c, pa = Math.abs(q - a), pb = Math.abs(q - u), pc = Math.abs(q - c); pr = pa <= pb && pa <= pc ? a : pb <= pc ? u : c; }
      px[y * st + x] = (raw[row + x] + pr) & 255;
    }
  }
  return { w, h, at: (x, y) => { const i = (y * w + x) * bpp; return [px[i], px[i + 1], px[i + 2]]; } };
}
// ---- run ----
// the anchors /docs/flags/ offers (its element ids), read once: every link to /docs/flags/#x on any view must name one
const flagIds = await fetch(base + '/docs/flags/').then((r) => (r.ok ? r.text() : '')).then((t) => new Set([...t.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]))).catch(() => new Set());
const results = [];
let failures = 0;
for (const page of config.pages) {
  if (only && !only.has(page.path)) continue;
  for (const theme of page.themes || [null]) {
    for (const width of page.widths || widths) {
      // the public per-IP limit can answer 429 when views run back to back: wait and look again
      let res;
      for (let attempt = 0; attempt < 3; attempt++) {
        res = await view(page, theme, width);
        if (!res.fail.some((f) => / 429 /.test(f))) break;
        await sleep(30000);
      }
      failures += res.fail.length;
      results.push({ path: page.path, theme, width, ...res });
      if (!flag('json')) {
        const label = `${page.path}${theme ? ' [' + theme + ']' : ''} @${width}`;
        console.log(`${res.fail.length ? 'FAIL' : 'ok  '} ${label}`);
        for (const f of res.fail) console.log('     ✗ ' + f);
        for (const w of res.warn) console.log('     · ' + w);
      }
    }
  }
}
if (flag('json')) console.log(JSON.stringify(results, null, 2));
else console.log(`\n${results.length} page views, ${failures} failure(s).`);
ws.close(); cleanup();
process.exit(failures ? 1 : 0);
