#!/usr/bin/env node
// Transfer size and Largest Contentful Paint for the heavy pages, at phone width on a throttled
// profile (Fast 3G: 150 ms latency, 1.6 Mbit/s down, 750 kbit/s up; CPU 4x slower), cold cache.
//
//   node scripts/ui_checks/perf.mjs [--base http://127.0.0.1:8771] [--json]
//
// Budgets are in perf-budgets.json, set just above the numbers measured when they were added; a page
// over its budget fails (exit 1). Transfer counts every response the page loads in its first 8 s
// after the load event, compressed as sent.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf('--' + n); return i === -1 ? d : args[i + 1]; };
const base = opt('base', process.env.UI_BASE || 'http://127.0.0.1:8771').replace(/\/$/, '');
const asJson = args.includes('--json');
const budgets = JSON.parse(readFileSync(join(here, 'perf-budgets.json'), 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const CHROME = [process.env.CHROME_PATH, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find((p) => p && existsSync(p));
if (!CHROME) { console.error('No Chrome found; set CHROME_PATH.'); process.exit(2); }

const profile = mkdtempSync(join(tmpdir(), 'prv-perf-'));
const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--hide-scrollbars', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
process.on('exit', () => { try { proc.kill('SIGKILL'); } catch {} try { rmSync(profile, { recursive: true, force: true }); } catch {} });
const wsUrl = await new Promise((resolve, reject) => {
  let buf = ''; const t = setTimeout(() => reject(new Error('Chrome did not start')), 20000);
  proc.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]); } });
});
const ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let nextId = 1; const pending = new Map(), listeners = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); }
  else if (m.method) for (const l of listeners) if (l.s === m.sessionId && l.m === m.method) l.fn(m.params);
};
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = nextId++; pending.set(id, { resolve, reject });
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
});

const results = []; let failures = 0;
for (const [path, budget] of Object.entries(budgets.pages)) {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  for (const d of ['Page', 'Runtime', 'Network']) await send(d + '.enable', {}, sessionId);
  await send('Network.setCacheDisabled', { cacheDisabled: true }, sessionId);
  await send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1.6e6 / 8, uploadThroughput: 750e3 / 8 }, sessionId);
  await send('Emulation.setCPUThrottlingRate', { rate: 4 }, sessionId);
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, sessionId);
  await send('Page.addScriptToEvaluateOnNewDocument', { source: "window.__lcp=0;try{new PerformanceObserver(function(l){l.getEntries().forEach(function(e){window.__lcp=e.startTime})}).observe({type:'largest-contentful-paint',buffered:true})}catch(e){}" }, sessionId);
  let bytes = 0, requests = 0;
  listeners.push({ s: sessionId, m: 'Network.loadingFinished', fn: (p) => { bytes += p.encodedDataLength || 0; requests++; } });
  const loaded = new Promise((r) => listeners.push({ s: sessionId, m: 'Page.loadEventFired', fn: r }));
  await send('Page.navigate', { url: base + path }, sessionId);
  await Promise.race([loaded, sleep(60000)]);
  await sleep(8000);
  const r = await send('Runtime.evaluate', { expression: 'window.__lcp', returnByValue: true }, sessionId);
  const lcp = Math.round(r.result?.value || 0);
  await send('Target.closeTarget', { targetId });
  const kb = Math.round(bytes / 1024);
  const over = [kb > budget.transfer_kb && `transfer ${kb} KB > ${budget.transfer_kb} KB`, lcp > budget.lcp_ms && `LCP ${lcp} ms > ${budget.lcp_ms} ms`].filter(Boolean);
  if (over.length) failures++;
  results.push({ path, transfer_kb: kb, requests, lcp_ms: lcp, budget, ok: !over.length });
  if (!asJson) console.log(`${over.length ? 'FAIL' : 'ok  '} ${path}  ${kb} KB in ${requests} requests · LCP ${(lcp / 1000).toFixed(2)} s${over.length ? '  ✗ ' + over.join('; ') : ''}`);
}
if (asJson) console.log(JSON.stringify(results, null, 2));
ws.close();
process.exit(failures ? 1 : 0);
