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
// a figure drawn in the brand's marker yellow (it may only sit behind a figure as the highlight).
// WARN: skipped heading levels, touch targets under 24px, text under 12px.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
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
  if (yellow.length) fail.push(`figure in the marker yellow (only the highlight may be yellow): ${yellow.join('; ')}`);

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
    const errors = []; let status = 0;
    listeners.push({ session: sessionId, method: 'Runtime.exceptionThrown', fn: (p) => errors.push('JS: ' + (p.exceptionDetails.exception?.description || p.exceptionDetails.text).split('\n')[0]) });
    listeners.push({ session: sessionId, method: 'Log.entryAdded', fn: (p) => { if (p.entry.level === 'error') errors.push((/Content Security Policy/.test(p.entry.text) ? 'CSP: ' : 'console: ') + p.entry.text.slice(0, 200)); } });
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
    const r = await send('Runtime.evaluate', { expression: `(${audit})()`, returnByValue: true }, sessionId);
    const res = r.result?.value || { fail: ['audit crashed: ' + (r.exceptionDetails?.exception?.description || '?')], warn: [] };
    const want = page.status || 200;
    if (status !== want) res.fail.unshift(`HTTP ${status} (want ${want})`);
    const allowed = (page.allowConsole || []).map((p) => new RegExp(p));
    res.fail.push(...[...new Set(errors)].filter((e) => !(want === 404 && /404/.test(e)) && !allowed.some((re) => re.test(e))));
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
// ---- run ----
const results = [];
let failures = 0;
for (const page of config.pages) {
  if (only && !only.has(page.path)) continue;
  for (const theme of page.themes || [null]) {
    for (const width of widths) {
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
