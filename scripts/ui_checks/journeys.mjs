#!/usr/bin/env node
// The three conversion paths, clicked through in a real browser at desktop and phone width, each
// step asserted, with the time from opening the home page to the first value a visitor gets.
//
//   node scripts/ui_checks/journeys.mjs [--base http://127.0.0.1:8771] [--json]
//
//   key:        home → Get a free key → /account/ → the first request on that page runs (demo key)
//   playground: home → Try a call → /playground/ → a response with its sec.gov citation on screen
//   mcp:        home → the MCP line → /developers/#mcp → the install line visible with a Copy button
//
// Exit code 1 when a step fails. Chrome headless over the DevTools protocol; Node 22+, no npm.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf('--' + n); return i === -1 ? d : args[i + 1]; };
const base = opt('base', process.env.UI_BASE || 'http://127.0.0.1:8771').replace(/\/$/, '');
const asJson = args.includes('--json');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const CHROME = [process.env.CHROME_PATH, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find((p) => p && existsSync(p));
if (!CHROME) { console.error('No Chrome found; set CHROME_PATH.'); process.exit(2); }

const profile = mkdtempSync(join(tmpdir(), 'prv-journey-'));
const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--hide-scrollbars', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
process.on('exit', () => { try { proc.kill('SIGKILL'); } catch {} try { rmSync(profile, { recursive: true, force: true }); } catch {} });
const wsUrl = await new Promise((resolve, reject) => {
  let buf = ''; const t = setTimeout(() => reject(new Error('Chrome did not start')), 20000);
  proc.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
});
const ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let nextId = 1; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); } };
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = nextId++; pending.set(id, { resolve, reject });
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
});

async function page(width) {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  await send('Page.enable', {}, sessionId); await send('Runtime.enable', {}, sessionId);
  const mobile = width < 600;
  await send('Emulation.setDeviceMetricsOverride', { width, height: mobile ? 844 : 900, deviceScaleFactor: 1, mobile }, sessionId);
  if (mobile) await send('Emulation.setTouchEmulationEnabled', { enabled: true }, sessionId);
  const evalIn = async (fn, arg) => {
    const r = await send('Runtime.evaluate', { expression: `(${fn})(${arg === undefined ? '' : JSON.stringify(arg)})`, awaitPromise: true, returnByValue: true }, sessionId);
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result?.value;
  };
  const waitFor = async (fn, arg, ms = 30000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) { try { const v = await evalIn(fn, arg); if (v) return v; } catch {} await sleep(150); }
    return null;
  };
  return { targetId, evalIn, waitFor, go: (url) => send('Page.navigate', { url }, sessionId), close: () => send('Target.closeTarget', { targetId }) };
}

// a visible element matching a selector, optionally containing some text
const visible = ({ sel, text }) => [...document.querySelectorAll(sel)].find((e) => {
  const r = e.getBoundingClientRect(), s = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('[hidden]') && (!text || e.textContent.includes(text));
}) ? true : false;
const clickLink = ({ sel, text }) => {
  const a = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().includes(text) && e.getBoundingClientRect().height > 0);
  if (!a) return false;
  a.scrollIntoView({ block: 'center' }); a.click(); return a.getAttribute('href');
};

const JOURNEYS = {
  key: async (p, step) => {
    await step('open home', () => p.waitFor(visible, { sel: 'h1', text: 'cites its filing' }));
    await step('click Get a free key', () => p.evalIn(clickLink, { sel: '.hero a.button', text: 'Get a free key' }));
    await step('land on /account/', () => p.waitFor(() => location.pathname === '/account/'));
    await step('first request shown', () => p.waitFor(visible, { sel: '#first-call', text: '/v1/companies/' }));
    return step('first request runs', () => p.waitFor(async () => {
      const m = /"(https?:[^"]+)"/.exec(document.getElementById('first-call').textContent);
      if (!m) return false;
      const r = await fetch(m[1], { headers: { 'X-API-Key': 'demo', Accept: 'application/json' } });
      const b = await r.json();
      return r.ok && b.data && b.data[0] && /^https:\/\/www\.sec\.gov\/Archives\//.test(b.data[0].source_url);
    }), true);
  },
  playground: async (p, step) => {
    await step('open home', () => p.waitFor(visible, { sel: 'h1', text: 'cites its filing' }));
    await step('click Try a call', () => p.evalIn(clickLink, { sel: '.hero a.button', text: 'Try a call' }));
    await step('land on /playground/', () => p.waitFor(() => location.pathname === '/playground/'));
    return step('response with its citation', () => p.waitFor(visible, { sel: '#pg-cite', text: 'open it on sec.gov' }), true);
  },
  mcp: async (p, step) => {
    await step('open home', () => p.waitFor(visible, { sel: 'h1', text: 'cites its filing' }));
    await step('click the MCP line', () => p.evalIn(clickLink, { sel: '.hero-note a', text: 'one line' }));
    await step('land on /developers/#mcp', () => p.waitFor(() => location.pathname === '/developers/' && location.hash === '#mcp'));
    await step('install line visible', () => p.waitFor(visible, { sel: '#mcp pre', text: 'claude mcp add' }));
    return step('copy button on it', () => p.waitFor(() => !!document.querySelector('#mcp .code .copy')), true);
  },
};

const results = []; let failures = 0;
for (const width of [1440, 390]) {
  for (const [name, run] of Object.entries(JOURNEYS)) {
    const p = await page(width), steps = []; let t0 = 0, ttfv = null, ok = true;
    const step = async (label, fn, isValue) => {
      if (!ok) return;
      const v = await fn();
      steps.push({ label, ok: !!v });
      if (!v) { ok = false; return; }
      if (isValue) ttfv = Date.now() - t0;
    };
    t0 = Date.now();
    await p.go(base + '/');
    try { await run(p, step); } catch (e) { ok = false; steps.push({ label: 'error: ' + e.message, ok: false }); }
    await p.close();
    if (!ok) failures++;
    results.push({ journey: name, width, ok, time_to_first_value_ms: ttfv, steps });
    if (!asJson) {
      console.log(`${ok ? 'ok  ' : 'FAIL'} ${name} @${width}${ttfv != null ? `  first value in ${(ttfv / 1000).toFixed(1)} s` : ''}`);
      for (const s of steps) console.log(`     ${s.ok ? '✓' : '✗'} ${s.label}`);
    }
  }
}
if (asJson) console.log(JSON.stringify(results, null, 2));
ws.close();
process.exit(failures ? 1 : 0);
