/**
 * Provenance for Google Sheets (GH #30): reported figures in a cell, each with its SEC filing.
 *
 *   =PROVENANCE("AAPL", "revenue")                 latest annual revenue
 *   =PROVENANCE("AAPL", "revenue", "FY2024")       a fiscal year
 *   =PROVENANCE("320193", "net_income", "Q2 FY2026")  a fiscal quarter
 *   =PROVENANCE("MSFT", "operating_income", "CY2025")  a calendar year (companies line up)
 *   =PROVENANCE_SOURCE("AAPL", "revenue", "FY2024")    the filing on sec.gov behind that value
 *
 * The API key lives in the script's properties (Extensions > Apps Script > Project settings >
 * Script properties): PROVENANCE_API_KEY, and PROVENANCE_BASE_URL for the server address.
 * Values are cached for six hours; a missing value returns "not reported", never 0.
 */

var DEFAULT_BASE_URL = 'https://api.provenance.example'; // replaced by PROVENANCE_BASE_URL until the domain is chosen
var CACHE_SECONDS = 6 * 60 * 60;

/**
 * A reported figure for a company, as filed with the SEC.
 *
 * @param {string} company Ticker, CIK or company name, e.g. "AAPL" or "320193".
 * @param {string} metric Metric, e.g. "revenue", "net_income", "total_assets", "gross_margin".
 * @param {string} period Optional: "latest" (default), "latest quarter", "FY2024", "Q2 FY2026", "CY2025" or "CY2025Q4".
 * @return The value in its unit (USD, shares, %, ×), or "not reported".
 * @customfunction
 */
function PROVENANCE(company, metric, period) {
  var fact = provenanceFact_(company, metric, period);
  return fact ? fact.value : 'not reported';
}

/**
 * The SEC filing behind a figure: the link to the filing index on sec.gov.
 *
 * @param {string} company Ticker, CIK or company name.
 * @param {string} metric Metric, e.g. "revenue".
 * @param {string} period Optional: "latest" (default), "FY2024", "Q2 FY2026", "CY2025".
 * @return The sec.gov filing URL, or "not reported".
 * @customfunction
 */
function PROVENANCE_SOURCE(company, metric, period) {
  var fact = provenanceFact_(company, metric, period);
  return fact ? fact.source_url : 'not reported';
}

/* ---- internals ---- */

function provenanceSettings_() {
  var props = PropertiesService.getScriptProperties();
  var key = props.getProperty('PROVENANCE_API_KEY');
  if (!key) throw new Error('Set PROVENANCE_API_KEY in the script properties (Extensions > Apps Script > Project settings).');
  var base = (props.getProperty('PROVENANCE_BASE_URL') || DEFAULT_BASE_URL).replace(/\/+$/, '');
  return { key: key, base: base };
}

function provenanceGet_(path) {
  var s = provenanceSettings_();
  var cache = CacheService.getScriptCache();
  var hit = cache.get(path);
  if (hit) return JSON.parse(hit);
  var res = UrlFetchApp.fetch(s.base + path, { headers: { 'X-API-Key': s.key, Accept: 'application/json' }, muteHttpExceptions: true });
  var code = res.getResponseCode(), text = res.getContentText();
  var body = null; try { body = JSON.parse(text); } catch (e) {}
  if (code === 404) return null;
  if (code === 429) throw new Error('Provenance rate limit reached; try again in a minute.');
  if (code < 200 || code >= 300) throw new Error((body && body.error && body.error.message) || ('Provenance returned ' + code));
  try { cache.put(path, text, CACHE_SECONDS); } catch (e) { /* responses over 100 KB are not cached */ }
  return body;
}

/** Ticker, CIK or name to a CIK without leading zeros. */
function provenanceCik_(company) {
  var q = String(company == null ? '' : company).trim();
  if (!q) throw new Error('Give a ticker, CIK or company name.');
  if (/^\d{1,10}$/.test(q)) return String(parseInt(q, 10));
  var found = provenanceGet_('/v1/companies/search?q=' + encodeURIComponent(q) + '&limit=5');
  var rows = (found && found.data) || [];
  var exact = rows.filter(function (r) { return (r.ticker || '').toUpperCase() === q.toUpperCase(); })[0] || rows[0];
  if (!exact) throw new Error('No company matches "' + q + '".');
  return String(parseInt(exact.cik, 10));
}

/** "FY 2024" -> "FY2024", "q2 fy2026" -> "Q2 FY2026", "2024" -> "FY2024". */
function provenancePeriod_(period) {
  var p = String(period == null ? '' : period).trim().toUpperCase().replace(/\s+/g, ' ');
  if (!p || p === 'LATEST') return { kind: 'annual', latest: true };
  if (p === 'LATEST QUARTER' || p === 'LATEST Q') return { kind: 'quarterly', latest: true };
  if (/^\d{4}$/.test(p)) p = 'FY' + p;
  p = p.replace(/^FY (\d{4})$/, 'FY$1').replace(/^CY (\d{4})/, 'CY$1').replace(/^(Q[1-4]) ?FY ?(\d{4})$/, '$1 FY$2').replace(/^FY ?(\d{4}) ?(Q[1-4])$/, '$2 FY$1');
  var quarterly = /^Q[1-4] FY\d{4}$/.test(p) || /^CY\d{4}Q[1-4]$/.test(p);
  if (!/^(FY\d{4}|Q[1-4] FY\d{4}|CY\d{4}|CY\d{4}Q[1-4])$/.test(p)) throw new Error('Period "' + period + '" is not one of: latest, latest quarter, FY2024, Q2 FY2026, CY2025, CY2025Q4.');
  return { kind: quarterly ? 'quarterly' : 'annual', label: p, calendar: p.indexOf('CY') === 0 };
}

function provenanceFact_(company, metric, period) {
  var m = String(metric == null ? '' : metric).trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (!m) throw new Error('Give a metric, e.g. "revenue".');
  var cik = provenanceCik_(company), want = provenancePeriod_(period);
  var body = provenanceGet_('/v1/companies/' + cik + '/facts?metric=' + encodeURIComponent(m) + '&period=' + want.kind + '&limit=100');
  var rows = (body && body.data) || [];
  if (!rows.length) return null;
  if (want.latest) {
    rows.sort(function (a, b) { return a.period_end < b.period_end ? 1 : -1; });
    return rows[0];
  }
  var match = rows.filter(function (r) {
    var label = String((want.calendar ? r.calendar_period : r.period_label) || '').toUpperCase();
    if (label === want.label) return true;
    // balance-sheet values are instants: CY2025Q4I is the year-end balance for CY2025
    return want.calendar && (label === want.label + 'I' || (want.label.length === 6 && label === want.label + 'Q4I'));
  });
  match.sort(function (a, b) { return a.filed_date < b.filed_date ? 1 : -1; }); // the latest filed value for that period
  if (!match.length && want.calendar && want.kind === 'annual') {
    // a calendar-year balance for a company whose fiscal year ends mid-year sits in a quarterly report
    var q = provenanceGet_('/v1/companies/' + cik + '/facts?metric=' + encodeURIComponent(m) + '&period=quarterly&limit=100');
    match = ((q && q.data) || []).filter(function (r) { return String(r.calendar_period || '').toUpperCase() === want.label + 'Q4I'; });
    match.sort(function (a, b) { return a.filed_date < b.filed_date ? 1 : -1; });
  }
  return match[0] || null;
}
