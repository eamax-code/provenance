// Runs Code.gs outside Google: Apps Script's PropertiesService, CacheService and UrlFetchApp are
// stood in for (UrlFetchApp is synchronous, so curl does the request). Against a local server:
//   PROVENANCE_BASE_URL=http://127.0.0.1:8771 PROVENANCE_API_KEY=... node clients/sheets/test/run.mjs
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const code = readFileSync(fileURLToPath(new URL('../Code.gs', import.meta.url)), 'utf8');
const props = { PROVENANCE_API_KEY: process.env.PROVENANCE_API_KEY, PROVENANCE_BASE_URL: process.env.PROVENANCE_BASE_URL };
const cache = new Map();
const sandbox = {
  PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => props[k] || null }) },
  CacheService: { getScriptCache: () => ({ get: (k) => cache.get(k) || null, put: (k, v) => cache.set(k, v) }) },
  UrlFetchApp: {
    fetch: (url, opts) => {
      const out = execFileSync('curl', ['-s', '-m', '120', '-w', '\n%{http_code}', ...Object.entries(opts.headers).flatMap(([k, v]) => ['-H', `${k}: ${v}`]), url], { encoding: 'utf8' });
      const i = out.lastIndexOf('\n');
      return { getResponseCode: () => +out.slice(i + 1), getContentText: () => out.slice(0, i) };
    },
  },
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const cases = [
  ['AAPL', 'revenue', ''], ['AAPL', 'revenue', 'FY2024'], ['aapl', 'revenue', 'fy 2024'], ['320193', 'net_income', 'Q2 FY2026'],
  ['MSFT', 'operating_income', 'CY2025'], ['AAPL', 'total_assets', 'CY2025'], ['AAPL', 'gross_margin', 'FY2025'], ['AAPL', 'revenue', 'latest quarter'],
  ['AAPL', 'revenue', 'FY1990'],
];
let failed = 0;
for (const [c, m, p] of cases) {
  try {
    const v = sandbox.PROVENANCE(c, m, p), src = sandbox.PROVENANCE_SOURCE(c, m, p);
    const ok = v === 'not reported' ? src === 'not reported' : typeof v === 'number' && /^https:\/\/www\.sec\.gov\/Archives\//.test(src);
    if (!ok) failed++;
    console.log(ok ? 'ok  ' : 'FAIL', `=PROVENANCE("${c}", "${m}", "${p}")`, '→', v, '·', src);
  } catch (e) { failed++; console.log('FAIL', c, m, p, e.message); }
}
for (const bad of [['AAPL', 'revenue', 'next year'], ['', 'revenue', '']]) {
  try { sandbox.PROVENANCE(...bad); failed++; console.log('FAIL no error for', bad); } catch (e) { console.log('ok   error for', JSON.stringify(bad), '→', e.message); }
}
process.exit(failed ? 1 : 0);
