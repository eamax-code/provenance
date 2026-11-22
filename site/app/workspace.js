/* Explorer workspace (plan-explorer-chat X-01, X-10, X-11): one company on one screen, every number a
   door to its filing, the whole view in the URL, a ⌘K palette. Works without a key for the showcase
   companies (the public overview, which never fetches from the SEC); a key opens any company.
   Text goes in through textContent only; links are sec.gov/Archives filings or our own pages. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k]; if (v == null || v === false) return;
      if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v);
    });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var NS = 'http://www.w3.org/2000/svg';
  function sv(tag, attrs, text) { var n = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] != null) n.setAttribute(k, attrs[k]); }); if (text != null) n.textContent = text; return n; }
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  function money(v, cur, d) {
    if (v == null) return '—';
    var a = Math.abs(v), p = (v < 0 ? '−' : '') + (!cur || cur === 'USD' ? '$' : cur + ' '); d = d == null ? 1 : d;
    if (a >= 1e12) return p + (a / 1e12).toFixed(d) + 'T'; if (a >= 1e9) return p + (a / 1e9).toFixed(d) + 'B';
    if (a >= 1e6) return p + (a / 1e6).toFixed(d) + 'M'; if (a >= 1e3) return p + (a / 1e3).toFixed(0) + 'K'; return p + a.toFixed(0);
  }
  function pct(v, sign) { if (v == null || !isFinite(v)) return '—'; var r = Math.abs(v).toFixed(1); return (r === '0.0' ? '' : sign && v > 0 ? '+' : v < 0 ? '−' : '') + r + '%'; }
  function count(v) { var a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(2) + 'B' : a >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : Number(v).toLocaleString('en-US'); }
  /* a value in its row's unit: currency codes as filed, never converted */
  function fmtv(v, unit, cur) {
    if (v == null) return '—';
    if (unit === '%') return pct(v); if (unit === 'x') return Number(v).toFixed(2) + '×'; if (unit === 'shares') return count(v);
    var ps = /^([A-Z]{3})\/shares$/.exec(unit || ''); if (ps) return (v < 0 ? '−' : '') + (ps[1] === 'USD' ? '$' : ps[1] + ' ') + Math.abs(v).toFixed(2);
    return money(v, /^[A-Z]{3}$/.test(unit || '') ? unit : cur);
  }

  var X = window.ProvenanceExplorer;
  var TABS = ['overview', 'statements', 'chart', 'timeline', 'ownership', 'segments', 'compare', 'filings', 'connections', 'freshness', 'facts'];
  var KEYED = { filings: 1, connections: 1, freshness: 1, facts: 1 };
  var S = { cmp: [], cik: null, d: null, tab: 'overview', m: ['revenue', 'operating_margin'], p: 'annual', scale: 'linear', mk: ['8k', 'officer', 'auditor'], st: 'income', show: 'values', as_of: null, asofNote: '' };

  /* ---- one state, one URL (X-10). Every parameter is validated; a key never goes in a URL. ---- */
  var METRIC = /^[a-z_]{2,40}$/;
  function readURL() {
    var q = new URLSearchParams(location.search), o = {};
    var c = q.get('c'); o.cik = c && /^\d{1,10}$/.test(c) ? String(parseInt(c, 10)) : null;
    var t = q.get('tab'); o.tab = TABS.indexOf(t) > -1 ? t : 'overview';
    var m = (q.get('m') || '').split(',').filter(function (x) { return METRIC.test(x); }).slice(0, 3); o.m = m.length ? m : ['revenue', 'operating_margin'];
    o.p = q.get('p') === 'quarterly' ? 'quarterly' : 'annual';
    o.scale = q.get('scale') === 'log' ? 'log' : 'linear';
    var mk = q.get('mk'); o.mk = mk == null ? ['8k', 'officer', 'auditor'] : mk.split(',').filter(function (x) { return ['8k', 'officer', 'auditor'].indexOf(x) > -1; });
    o.cmp = (q.get('cmp') || '').split(',').filter(function (x) { return /^\d{1,10}$/.test(x); }).map(function (x) { return String(parseInt(x, 10)); }).filter(function (x, i, a) { return x !== o.cik && a.indexOf(x) === i; }).slice(0, 4);
    o.st = ['income', 'balance', 'cash_flow', 'ratios'].indexOf(q.get('st')) > -1 ? q.get('st') : 'income';
    o.show = ['values', 'yoy', 'common'].indexOf(q.get('show')) > -1 ? q.get('show') : 'values';
    var a = q.get('as_of'); o.as_of = null; o.asofNote = '';
    if (a) { if (/^\d{4}-\d{2}-\d{2}$/.test(a) && !isNaN(Date.parse(a)) && a >= '1993-01-01' && a <= new Date().toISOString().slice(0, 10)) o.as_of = a; else o.asofNote = 'The date "' + a.slice(0, 20) + '" in the link isn’t a valid past date, so this shows the latest data.'; }
    return o;
  }
  function writeURL(push) {
    var q = new URLSearchParams();
    if (S.cik) q.set('c', S.cik);
    if (S.tab !== 'overview') q.set('tab', S.tab);
    if (S.tab === 'chart') { q.set('m', S.m.join(',')); if (S.scale === 'log') q.set('scale', 'log'); if (S.mk.join(',') !== '8k,officer,auditor') q.set('mk', S.mk.join(',')); }
    if (S.tab === 'compare' && S.cmp.length) q.set('cmp', S.cmp.join(','));
    if (S.tab === 'statements') { if (S.st !== 'income') q.set('st', S.st); if (S.show !== 'values') q.set('show', S.show); }
    if ((S.tab === 'chart' || S.tab === 'statements') && S.p === 'quarterly') q.set('p', 'quarterly');
    if (S.as_of) q.set('as_of', S.as_of);
    var url = location.pathname + (q.toString() ? '?' + q.toString() : '') + (location.hash || '');
    if (url === location.pathname + location.search + location.hash) return;
    try { history[push ? 'pushState' : 'replaceState']({ ws: 1 }, '', url); } catch (e) {}
  }
  window.addEventListener('popstate', function () { apply(readURL(), false); });

  function apply(o, push) {
    var reload = o.cik !== S.cik || o.as_of !== S.as_of;
    Object.assign(S, o);
    if (!S.cik) { showEmpty(); return; }
    if (reload) load(push); else { renderTab(); writeURL(push); }
  }

  /* ---- data: the keyed overview opens any company; without a key, the public showcase overview ---- */
  var seq = 0;
  function load(push) {
    var my = ++seq, cik = S.cik;
    $('explore').hidden = false; $('company').hidden = false; $('ws-empty').hidden = true;
    $('ws-head').replaceChildren(el('p', { class: 'muted', text: 'Loading CIK ' + cik + '…' }));
    var qs = S.as_of ? '?as_of=' + S.as_of : '';
    var keyed = X.hasKey();
    var path = (keyed ? '/v1/companies/' : '/v1/public/companies/') + cik + '/overview' + qs;
    X.raw(path).then(function (r) {
      if (my !== seq) return;
      if (r.status === 404 && keyed) return X.raw('/v1/public/companies/' + cik + '/overview' + qs).then(function (r2) { return done(r2); });
      return done(r);
    }).catch(function () { if (my === seq) $('ws-head').replaceChildren(el('p', { class: 'muted', text: 'Could not load this company. Check the connection and try again.' })); });
    function done(r) {
      if (my !== seq) return;
      if (!r.ok) {
        var msg = r.status === 404 ? (keyed ? 'No company with CIK ' + cik + ' in this deployment.' : 'Without a key the Explorer opens the showcase companies. Connect a key to open CIK ' + cik + '.') : r.status === 429 ? 'Too many requests just now. Try again in a minute.' : 'Could not load this company (HTTP ' + r.status + ').';
        $('ws-head').replaceChildren(el('p', { class: 'muted', text: msg })); showPanes(null); return;
      }
      S.d = r.body; renderHead(); renderTab(); writeURL(push);
      recent({ cik: S.cik, name: r.body.company.display_name || r.body.company.legal_name });
      if (KEYED[S.tab] && X.legacy) X.legacy(cik, S.tab);
    }
  }

  /* ---- the provenance card (§2.2): every number is a door; the card itself is shared with chat ---- */
  function door(text, info, cls) { return window.ProvCard.door(text, info, cls); }
  function closeCard() { return window.ProvCard.close(); }
  window.ProvCard.configure({
    asOf: function () { return S.as_of; },
    actions: function (i, close) {
      return [el('a', { class: 'btn small', href: chatLink((i.label || '') + (i.fiscal_label ? ' ' + i.fiscal_label : '')), text: 'Ask about this' }),
        i.metric ? el('button', { type: 'button', class: 'btn small', text: 'Chart it', on: { click: function () { close(); S.m = [i.metric]; go('chart'); } } }) : null];
    }
  });

  function chatLink(q) {
    var p = new URLSearchParams(); p.set('q', q.trim()); if (S.cik) p.set('cik', S.cik); if (S.as_of) p.set('as_of', S.as_of);
    return '/chat/?' + p.toString();
  }
  function cellInfo(row, c, cur) { return Object.assign({ label: row.label, metric: row.metric, currency: cur, formula: row.formula }, c); }

  /* ---- header: the company, its currency, and (Overview only) its identity strip ---- */
  function renderHead() {
    var d = S.d, c = d.company, cur = c.reporting_currency || 'USD', id = d.identity || {};
    var tick = (c.tickers && c.tickers.length ? c.tickers : [c.ticker]).filter(Boolean).map(function (t, i) { return t + (c.exchanges && c.exchanges[i] ? ' · ' + c.exchanges[i] : ''); });
    var chips = el('p', { class: 'ws-chips' }, tick.map(function (t) { return el('span', { class: 'chip', text: t }); }).concat([
      el('span', { class: 'chip', title: 'Figures are in the currency the company reports in, never converted', text: cur }),
      c.fiscal_year_end_month ? el('span', { class: 'chip', text: 'FY ends ' + c.fiscal_year_end_month }) : null,
      c.filer_category ? el('span', { class: 'chip quiet', text: c.filer_category }) : null,
      S.as_of ? el('span', { class: 'chip asof', text: 'As known on ' + day(S.as_of) }) : null
    ]));
    var acts = el('div', { class: 'ws-acts' }, [
      el('a', { class: 'btn small', href: chatLink('Tell me about ' + (c.display_name || '')), text: 'Ask about ' + (c.ticker || 'this company') }),
      el('button', { type: 'button', class: 'btn small', text: '+ Watchlist', title: 'Add to your watchlist', on: { click: function () { if (window.ProvenanceWatchlists) window.ProvenanceWatchlists.add(c.cik); } } }),
      el('a', { class: 'btn small', href: '/companies/' + parseInt(c.cik, 10) + (S.as_of ? '?as_of=' + S.as_of : ''), text: 'Company page' })
    ]);
    var strip = null;
    if (S.tab === 'overview') {
      var bits = [el('span', { text: 'CIK ' + c.cik })];
      var lei = id.lei || c.lei; if (lei) bits.push(el('span', { title: id.evidence || '', text: 'LEI ' + lei + (id.match_method === 'override' ? ' · checked by hand' : id.confidence === 'medium' ? ' · matched by name' : '') }));
      var inc = c.incorporation; if (inc && inc.code) bits.push(el('span', {}, ['Incorporated ' + (stateName(inc.code) || inc.code), inc.source_url && ARCHIVE.test(inc.source_url) ? el('a', { href: inc.source_url, target: '_blank', rel: 'noopener', text: ' · cover ↗' }) : '']));
      var au = d.auditor && d.auditor.current; if (au) bits.push(el('span', {}, ['Auditor ', au.latest_report && ARCHIVE.test(au.latest_report.source_url) ? el('a', { href: au.latest_report.source_url, target: '_blank', rel: 'noopener', text: au.name }) : au.name, au.since_basis === 'observed_change' && au.since ? ' since FY' + au.since : '']));
      if (c.sic_description) bits.push(el('span', { text: c.sic_description }));
      strip = el('p', { class: 'ws-ident', id: 'ws-ident' }, bits);
    }
    var itog = strip ? el('button', { type: 'button', class: 'linkish ws-ident-t', 'aria-expanded': 'false', 'aria-controls': 'ws-ident', text: 'Identity: CIK, LEI, incorporation, auditor', on: { click: function () { var o = strip.classList.toggle('open'); itog.setAttribute('aria-expanded', String(o)); } } }) : null;
    $('ws-head').replaceChildren.apply($('ws-head'), [el('div', { class: 'ws-title' }, [el('h2', { text: c.display_name || c.legal_name || 'CIK ' + c.cik }), chips, acts]), itog, strip,
      S.asofNote ? el('p', { class: 'ws-note', role: 'status', text: S.asofNote }) : null].filter(Boolean));
    var ai = $('ws-asof'); if (ai) ai.value = S.as_of || ''; var ab = $('ws-asof-btn'); if (ab) ab.lastChild.textContent = S.as_of ? day(S.as_of) : 'latest';
    document.title = (c.display_name || 'Company') + (c.ticker ? ' (' + c.ticker + ')' : '') + ' · Explorer · Provenance';
  }
  var STATES = { DE: 'Delaware', CA: 'California', NY: 'New York', NV: 'Nevada', TX: 'Texas', MD: 'Maryland', PA: 'Pennsylvania', OH: 'Ohio', NJ: 'New Jersey', WA: 'Washington', MA: 'Massachusetts', FL: 'Florida', IL: 'Illinois', VA: 'Virginia', GA: 'Georgia', MN: 'Minnesota', NC: 'North Carolina', MI: 'Michigan', IN: 'Indiana', CO: 'Colorado', MO: 'Missouri', WI: 'Wisconsin', OR: 'Oregon', TN: 'Tennessee', AZ: 'Arizona', UT: 'Utah', CT: 'Connecticut', M0: 'Japan', '2M': 'Germany', F5: 'Taiwan', X0: 'United Kingdom', V8: 'Switzerland', P7: 'Netherlands', L2: 'Ireland', D0: 'Bermuda', E9: 'Cayman Islands', K3: 'Hong Kong', F4: 'China', I0: 'France', A6: 'Ontario, Canada' };
  function stateName(code) { return STATES[code] || null; }

  /* ---- tabs ---- */
  function go(tab, push) { if (TABS.indexOf(tab) < 0) return; S.tab = tab; renderHead(); renderTab(); writeURL(push !== false); if (KEYED[tab] && X.legacy) X.legacy(S.cik, tab); }
  function showPanes(tab) {
    document.querySelectorAll('#ws-tabs .tab').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-tab') === tab)); });
    TABS.forEach(function (t) { var p = $('pane-' + t); if (p) p.hidden = t !== tab; });
  }
  function renderTab() {
    if (!S.d) return;
    showPanes(S.tab);
    if (KEYED[S.tab] && !X.hasKey()) { var p = $('pane-' + S.tab); keyNeeded(p); return; }
    if (S.tab === 'overview') overview(); else if (S.tab === 'chart') chartTab(); else if (S.tab === 'statements') statementsTab(); else if (S.tab === 'timeline') timelineTab(); else if (S.tab === 'ownership') ownershipTab(); else if (S.tab === 'segments') segmentsTab(); else if (S.tab === 'compare') compareTab();
  }
  function keyNeeded(p) {
    if (!p) return; var n = p.querySelector('.ws-keyneeded');
    if (!n) p.prepend(el('p', { class: 'ws-keyneeded muted', text: 'This tab reads the keyed API. Connect a free key above to use it.' }));
  }

  /* ---- series: ten fiscal years from years[], statement rows for the rest ---- */
  function statementRows() { var out = {}; ((S.d.statements || {}).sections || []).forEach(function (s) { s.rows.forEach(function (r) { out[r.metric] = r; }); }); return out; }
  var YEARLY = { revenue: 'Revenue', operating_income: 'Operating income', net_income: 'Net income', operating_cash_flow: 'Operating cash flow', total_assets: 'Total assets', operating_margin: 'Operating margin' };
  function series(metric) {
    var d = S.d, cur = (d.company || {}).reporting_currency || 'USD', rows = statementRows();
    if (YEARLY[metric]) {
      var key = metric === 'operating_margin' ? 'operating_margin_pct' : metric;
      var pts = (d.years || []).filter(function (y) { return y[key] != null; }).map(function (y) {
        var src = y.sources && y.sources[metric === 'operating_margin' ? 'operating_income' : metric], pv = y.provenance && y.provenance[metric === 'operating_margin' ? 'operating_income' : metric];
        var info = { label: YEARLY[metric], metric: metric, fiscal_label: y.fiscal_label, period_end: y.period_end, currency: cur, source_url: src, predecessor: y.predecessor, registrant_cik: y.registrant_cik };
        if (pv) Object.assign(info, { accession_number: pv.accession_number, source_tag: pv.source_tag, mapping_version: pv.mapping_version, quality_status: pv.quality_status });
        if (metric === 'operating_margin') { info.derived = true; info.formula = 'operating income ÷ revenue'; info.source_tag = null; }
        var srow = rows[metric] && rows[metric].cells.filter(function (c) { return c && c.fiscal_label === y.fiscal_label; })[0];
        if (srow) Object.assign(info, { form_type: srow.form_type, filed_date: srow.filed_date, accession_number: srow.accession_number, quality_status: srow.quality_status, source_tag: srow.source_tag, mapping_version: srow.mapping_version, inputs: srow.inputs });
        return { x: y.fiscal_label, v: y[key], info: info };
      });
      if (pts.length) return { metric: metric, label: YEARLY[metric], unit: metric === 'operating_margin' ? '%' : cur, pts: pts };
    }
    var r = rows[metric]; if (!r) return null;
    var fy = (d.statements || {}).fiscal_years || [];
    return { metric: metric, label: r.label, unit: r.unit === '%' || /margin|return_on/.test(metric) ? '%' : r.unit, pts: r.cells.map(function (c, i) { return c && c.value != null ? { x: fy[i], v: c.value, info: cellInfo(r, c, cur) } : null; }).filter(Boolean) };
  }

  /* ---- X-01 Overview ---- */
  var KEYS = [['revenue', 'Revenue'], ['gross_profit', 'Gross profit'], ['operating_income', 'Operating income'], ['net_income', 'Net income'], ['eps_diluted', 'EPS, diluted'], ['operating_cash_flow', 'Operating cash flow'], ['free_cash_flow', 'Free cash flow'], ['cash_and_equivalents', 'Cash and equivalents'], ['total_assets', 'Total assets'], ['long_term_debt', 'Long-term debt'], ['stockholders_equity', 'Stockholders’ equity'], ['capex', 'Capital expenditure'], ['shares_diluted_weighted', 'Diluted shares'], ['return_on_equity', 'Return on equity']];
  var OPTIONAL = { capex: 1, shares_diluted_weighted: 1 }; // shown only when the company reports them
  var MARGIN = { gross_profit: 1, operating_income: 1, net_income: 1, operating_cash_flow: 1, free_cash_flow: 1 };
  // green and red only where more is plainly more (flows); balance-sheet lines and ratios stay neutral
  var FLOW = { revenue: 1, gross_profit: 1, operating_income: 1, net_income: 1, eps_diluted: 1, operating_cash_flow: 1, free_cash_flow: 1 };
  function tone(metric, v) { return v == null || !FLOW[metric] || Math.abs(v) < 0.05 ? 'muted' : v > 0 ? 'up' : 'down'; }
  function growth(a, b) { return a != null && b != null && b > 0 && a >= 0 ? 100 * (a - b) / b : null; }
  function overview() {
    var d = S.d, cur = (d.company || {}).reporting_currency || 'USD', rows = statementRows(), fy = (d.statements || {}).fiscal_years || [];
    var last = fy.length - 1, rev = rows.revenue;
    // TTM comes with each key figure (key_figures[].ttm), only when four consecutive quarters exist
    var ttm = {}; (d.key_figures || []).forEach(function (k) { if (k.ttm && k.ttm.value != null) ttm[k.metric] = Object.assign({}, k.ttm, { value: Number(k.ttm.value), fiscal_label: 'TTM to ' + day(k.ttm.period_end) }); });
    var hasTTM = KEYS.some(function (k) { return ttm[k[0]]; });
    var head = el('tr', {}, [el('th', { scope: 'col', text: 'Annual, as filed' }), el('th', { scope: 'col', class: 'n', text: fy[last] || 'Latest' }), hasTTM ? el('th', { scope: 'col', class: 'n c-ttm', title: 'Trailing twelve months, from quarterly filings', text: 'TTM' }) : null, el('th', { scope: 'col', class: 'n c-yoy', text: 'YoY' }), el('th', { scope: 'col', class: 'n c-cagr', text: (last > 0 ? last : '') + 'y CAGR' }), el('th', { scope: 'col', class: 'n c-mg', text: 'Margin' }), el('th', { scope: 'col', class: 'spark-h', text: 'Trend' })]);
    var body = KEYS.map(function (k) {
      var r = rows[k[0]];
      if (!r && OPTIONAL[k[0]]) return null;
      if (!r) return el('tr', { class: 'na' }, [el('th', { scope: 'row', text: k[1] }), el('td', { class: 'n muted', colspan: hasTTM ? '6' : '5', title: 'not reported', text: '— not reported' })]);
      var cells = r.cells, c = cells[last], p = cells[last - 1], f = cells.filter(function (x) { return x && x.value != null; })[0];
      var yoy = c && p ? growth(c.value, p.value) : null;
      var n = f ? last - cells.indexOf(f) : 0, cagr = c && f && n > 0 && f.value > 0 && c.value > 0 ? 100 * (Math.pow(c.value / f.value, 1 / n) - 1) : null;
      var mg = MARGIN[k[0]] && c && rev && rev.cells[last] && rev.cells[last].value > 0 ? 100 * c.value / rev.cells[last].value : null;
      var unit = r.unit === '%' || /return_on/.test(k[0]) ? '%' : r.unit;
      var s = series(k[0]);
      return el('tr', {}, [
        el('th', { scope: 'row' }, [r.label || k[1], r.derived ? el('span', { class: 'tag', title: r.formula || 'Worked out here from reported figures', text: 'derived' }) : null]),
        el('td', { class: 'n strong' }, [c && c.value != null ? door(fmtv(c.value, unit, cur), cellInfo(r, c, cur)) : el('span', { class: 'muted', title: 'not reported', text: '—' })]),
        hasTTM ? (ttm[k[0]] && ttm[k[0]].value != null ? el('td', { class: 'n c-ttm' }, [door(fmtv(ttm[k[0]].value, unit, cur), Object.assign({ label: (r.label || k[1]) + ', TTM', metric: k[0], currency: cur }, ttm[k[0]]))]) : el('td', { class: 'n c-ttm muted', title: 'not reported', text: '—' })) : null,
        el('td', { class: 'n c-yoy ' + tone(k[0], unit === '%' ? null : yoy), text: unit === '%' ? '—' : pct(yoy, true) }),
        el('td', { class: 'n c-cagr muted', text: unit === '%' ? '—' : pct(cagr, true) }),
        el('td', { class: 'n c-mg muted', text: mg == null ? '' : pct(mg) }),
        el('td', { class: 'spark-c' }, [s ? spark(s.pts.map(function (x) { return x.v; })) : null])
      ]);
    });
    var figs = el('section', { class: 'ov-figs', 'aria-labelledby': 'ov-figs-h' }, [
      el('h3', { id: 'ov-figs-h', text: 'Key figures' }),
      el('div', { class: 'tw' }, [el('table', { class: 'ov-table' }, [el('thead', {}, [head]), el('tbody', {}, body)])]),
      el('p', { class: 'muted small ov-foot', text: 'In ' + cur + ', as reported. Click any figure for its filing, tag and mapping. Growth only between positive years; green and red only on flows.' })
    ]);
    // events: the API's own labels (a Form 25 says what it is), information, not signals
    var evs = (d.events || []).slice(0, 7);
    var events = el('section', { class: 'ov-ev', 'aria-labelledby': 'ov-ev-h' }, [
      el('div', { class: 'ov-h' }, [el('h3', { id: 'ov-ev-h', text: 'Latest events' }), el('button', { type: 'button', class: 'linkish', text: 'Timeline', on: { click: function () { go('timeline'); } } })]),
      evs.length ? el('ul', { class: 'ov-list' }, evs.map(function (e) { return el('li', {}, [el('time', { datetime: e.date, text: day(e.date) }), el('span', {}, [e.short_label || e.label]), ARCHIVE.test(e.filing_url || '') ? el('a', { href: e.filing_url, target: '_blank', rel: 'noopener', title: e.label, text: e.form_type + ' ↗' }) : null]); })) : el('p', { class: 'muted', text: 'No events in the filings loaded.' }),
      el('p', { class: 'muted small ov-foot', text: 'Information, not signals. Not investment advice.' })
    ]);
    // ownership summary
    var o = d.ownership, own;
    if (o && o.listed === false) own = [el('p', { class: 'muted', text: 'No listed common stock, so no 13F holders.' })];
    else if (o) {
      var adr = (o.classes || []).some(function (x) { return x.held_as === 'adr'; }), f2 = o.flows || {};
      own = [el('p', { class: 'ov-big' }, [o.institutional_pct != null ? door(pct(o.institutional_pct), { label: 'held by institutions (13F)', derived: true, formula: o.institutional_pct_derived && o.institutional_pct_derived.formula }) : el('span', { text: adr ? 'No %' : 'No single %' }), ' institutional · ', el('b', { text: Number(o.holders_count).toLocaleString('en-US') }), ' holders' + (o.holders_count_change != null ? ' (' + (o.holders_count_change >= 0 ? '+' : '−') + Math.abs(o.holders_count_change) + ')' : ''), adr ? el('span', { class: 'tag', text: 'held as ADRs' }) : null]),
        el('ul', { class: 'ov-list' }, (o.top_holders || []).slice(0, 4).map(function (h) { return el('li', {}, [el('span', { text: orgName(h.name) }), el('span', { class: 'n', text: h.pct_of_outstanding != null ? pct(h.pct_of_outstanding) : money(h.value_usd, 'USD') }), ARCHIVE.test(h.filing_url || '') ? el('a', { href: h.filing_url, target: '_blank', rel: 'noopener', text: '13F ↗' }) : null]); })),
        el('p', { class: 'muted small', text: [f2.new, 'new', f2.added, 'added', f2.reduced, 'reduced', f2.exited, 'exited'].reduce(function (a, v, i) { return i % 2 ? a + ' ' + v + (i < 7 ? ' · ' : '') : a + Number(v || 0).toLocaleString('en-US'); }, '') })];
    } else own = [el('p', { class: 'muted', text: S.as_of ? '13F holdings show for the latest quarter only, not for a past date.' : 'No 13F holders matched yet.' })];
    var ownership = el('section', { class: 'ov-own', 'aria-labelledby': 'ov-own-h' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'ov-own-h', text: 'Ownership' + (o && o.quarter ? ' · 13F, ' + qname(o.quarter) : '') }), el('button', { type: 'button', class: 'linkish', text: 'Holders and insiders', on: { click: function () { go('ownership'); } } })])].concat(own));
    // the main chart: revenue bars and operating margin, ten years, with event markers
    var ch = el('section', { class: 'ov-chart', 'aria-labelledby': 'ov-ch-h' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'ov-ch-h', text: 'Revenue and operating margin' }), el('button', { type: 'button', class: 'linkish', text: 'Open in Chart', on: { click: function () { S.m = ['revenue', 'operating_margin']; go('chart'); } } })])]);
    var host = el('div', { class: 'chart-host' }); ch.appendChild(host);
    // segments mini
    var seg = el('section', { class: 'ov-seg', 'aria-labelledby': 'ov-seg-h' }, [el('h3', { id: 'ov-seg-h', text: 'Segments' })]);
    var K = d.segments && (d.segments.kinds || [])[0];
    if (K && K.metrics && K.metrics.revenue) {
      var per = K.periods[0], tot = (K.metrics.revenue.consolidated || {})[per];
      seg.firstChild.textContent = 'Segments · ' + ({ business: 'business', geographic: 'geography', product: 'products' }[K.kind] || K.kind) + ', revenue, year to ' + day(per).replace(/^\d+ /, '');
      seg.appendChild(el('ul', { class: 'seg-bars' }, (K.segments || []).slice(0, 6).map(function (g) {
        var v = ((g.values || {}).revenue || {})[per]; var w = tot > 0 && v != null ? Math.max(1, Math.min(100, 100 * v / tot)) : 0;
        var bar = el('span', { class: 'sb' }); bar.style.width = w + '%';
        return el('li', {}, [el('span', { class: 'sl', text: g.label }), el('span', { class: 'st' }, [bar]), el('span', { class: 'n', text: money(v, cur) })]);
      })));
      if (K.metrics.revenue.status && K.metrics.revenue.status[per] === 'unreconciled') seg.appendChild(el('p', { class: 'muted small', text: 'Unreconciled: these lines don’t add up to the total.' }));
    } else seg.appendChild(el('p', { class: 'muted', text: d.segments && d.segments.hidden_reason ? 'No segment breakdown to show for the latest report.' : 'No segments tagged in the latest annual report.' }));
    if (K) seg.appendChild(el('p', { class: 'ov-foot' }, [el('button', { type: 'button', class: 'linkish', text: 'All breakdowns and years', on: { click: function () { go('segments'); } } })]));
    $('pane-overview').replaceChildren(el('div', { class: 'ov-grid' }, [figs, events, ownership, ch, seg]));
    drawChart(host, { series: [series('revenue'), series('operating_margin')].filter(Boolean), kinds: ['bar', 'line'], height: 200, compact: true });
  }
  var KEEP = { LLC: 1, LP: 1, LLP: 1, PLC: 1, NA: 1, AG: 1, SA: 1, SE: 1, NV: 1, FMR: 1, UBS: 1, BNY: 1, KPMG: 1, II: 1, III: 1, USA: 1, US: 1, ADS: 1, ADR: 1 }, LOWER = { OF: 1, AND: 1, THE: 1, FOR: 1 };
  function orgName(n) {
    n = String(n || '').replace(/\s*\/[A-Za-z]{2,3}\/?\s*$/, '').trim(); if (n !== n.toUpperCase()) return n;
    return n.split(/(\s+|[,.&()-])/).map(function (w, i) { return !/[A-Z]/.test(w) || KEEP[w] ? w : i && LOWER[w] ? w.toLowerCase() : w === 'JPMORGAN' ? 'JPMorgan' : w.charAt(0) + w.slice(1).toLowerCase(); }).join('');
  }
  function qname(iso) { var m = /^(\d{4})-(\d{2})/.exec(iso || ''); return m ? 'Q' + Math.ceil(+m[2] / 3) + ' ' + m[1] : iso; }
  function spark(vals) {
    vals = vals.filter(function (v) { return v != null; }); if (vals.length < 2) return null;
    var w = 84, h = 22, lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), r = hi - lo || 1;
    var pts = vals.map(function (v, i) { return (i * (w - 4) / (vals.length - 1) + 2).toFixed(1) + ',' + (h - 3 - (v - lo) / r * (h - 6)).toFixed(1); });
    var s = sv('svg', { viewBox: '0 0 ' + w + ' ' + h, width: w, height: h, class: 'spark', 'aria-hidden': 'true' });
    s.appendChild(sv('polyline', { points: pts.join(' '), fill: 'none' })); s.appendChild(sv('circle', { cx: pts[pts.length - 1].split(',')[0], cy: pts[pts.length - 1].split(',')[1], r: 2 }));
    return s;
  }

  /* ---- X-11 chart: up to three series, bars or lines, a second axis for ratios, log, event markers ---- */
  var MK = { '8k': { label: '8-K items', test: function (e) { return /^8-K/.test(e.form_type || '') && !/officer|director/i.test(e.short_label || ''); } }, officer: { label: 'Officer changes', test: function (e) { return /officer|director|5\.02/i.test((e.short_label || '') + ' ' + (e.label || '')); } }, auditor: { label: 'Auditor changes', test: function (e) { return /auditor|4\.01/i.test((e.type || '') + ' ' + (e.label || '')); } } };
  function markers() {
    var d = S.d, out = [];
    (d.events || []).forEach(function (e) { S.mk.forEach(function (k) { if (MK[k].test(e)) out.push({ kind: k, date: e.date, label: e.short_label || e.label, url: e.filing_url, form: e.form_type }); }); });
    return out;
  }
  function drawChart(host, cfg) {
    var t0 = performance.now();
    var ser = cfg.series; host.textContent = '';
    if (!ser.length || !ser[0].pts.length) { host.appendChild(el('p', { class: 'muted', text: 'No reported values to chart.' })); return; }
    var xs = []; ser.forEach(function (s) { s.pts.forEach(function (p) { if (xs.indexOf(p.x) < 0) xs.push(p.x); }); }); xs.sort();
    var W = Math.max(320, host.clientWidth || 800), H = cfg.height || 360, narrow = W < 560;
    var padL = 56, padR = ser.some(function (s) { return s.unit === '%'; }) ? 48 : 12, padT = 14, padB = cfg.compact ? 24 : 46;
    var svg = sv('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, class: 'ws-chart', role: 'img' });
    var left = ser.filter(function (s) { return s.unit !== '%'; }), right = ser.filter(function (s) { return s.unit === '%'; });
    var log = S.scale === 'log' && !cfg.compact;
    function scale(list) {
      var vals = []; list.forEach(function (s) { s.pts.forEach(function (p) { vals.push(p.v); }); });
      if (!vals.length) return null;
      var lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
      if (log && lo >= 0) { var mn = Math.min.apply(null, vals.filter(function (v) { return v > 0; })); lo = Math.pow(10, Math.floor(Math.log10(mn || 1))); hi = Math.pow(10, Math.ceil(Math.log10(hi || 1))); return { lo: lo, hi: hi, log: true, y: function (v) { return padT + (H - padT - padB) * (1 - (Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo) || 1)); } }; }
      var raw = (hi - lo || 1) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), u = raw / mag, tick = mag * (u <= 1.2 ? 1 : u <= 2.5 ? 2 : u <= 6 ? 5 : 10);
      hi = Math.ceil(hi / tick) * tick; lo = Math.floor(lo / tick) * tick;
      return { lo: lo, hi: hi, tick: tick, y: function (v) { return padT + (H - padT - padB) * (hi - v) / (hi - lo || 1); } };
    }
    var L = scale(left), R = scale(right), cur = (S.d.company || {}).reporting_currency || 'USD';
    var step = (W - padL - padR) / xs.length, xOf = function (x) { return padL + xs.indexOf(x) * step + step / 2; };
    // faint gridlines from the left axis, labels on both
    [L, R].forEach(function (sc, side) {
      if (!sc) return;
      var ticks = []; if (sc.log) { for (var v = sc.lo; v <= sc.hi * 1.001; v *= 10) ticks.push(v); } else for (var t = sc.lo; t <= sc.hi + sc.tick / 2; t += sc.tick) ticks.push(Math.abs(t) < sc.tick / 2 ? 0 : t);
      ticks.forEach(function (v) {
        var y = sc.y(v);
        if (!side) svg.appendChild(sv('line', { x1: padL, x2: W - padR, y1: y, y2: y, class: v === 0 ? 'zero' : 'grid' }));
        svg.appendChild(sv('text', { x: side ? W - padR + 6 : padL - 6, y: y + 4, 'text-anchor': side ? 'start' : 'end', class: 'axis' }, side ? pct(v) : (v ? money(v, cur, 0) : '0')));
      });
    });
    var nb = ser.filter(function (s, i) { return (cfg.kinds ? cfg.kinds[i] : s.unit === '%' ? 'line' : 'bar') === 'bar'; }).length, bi = 0;
    ser.forEach(function (s, i) {
      var kind = cfg.kinds ? cfg.kinds[i] : s.unit === '%' ? 'line' : 'bar', sc = s.unit === '%' ? R : L; if (!sc) return;
      var cls = 's' + i;
      if (kind === 'bar') {
        var bw = Math.min(40, step * 0.7 / Math.max(1, nb)), off = (bi++ - (nb - 1) / 2) * bw;
        s.pts.forEach(function (p) {
          var x = xOf(p.x) + off - bw / 2, y0 = sc.y(sc.log ? sc.lo : 0), y1 = sc.y(p.v);
          svg.appendChild(sv('rect', { x: x, y: Math.min(y0, y1), width: bw, height: Math.max(1, Math.abs(y0 - y1)), class: 'bar ' + cls + (p.x === xs[xs.length - 1] ? ' latest' : '') + (p.info && p.info.predecessor ? ' pred' : '') }));
        });
      } else {
        var path = s.pts.map(function (p, j) { return (j ? 'L' : 'M') + xOf(p.x).toFixed(1) + ' ' + sc.y(p.v).toFixed(1); }).join(' ');
        svg.appendChild(sv('path', { d: path, class: 'line ' + cls }));
        s.pts.forEach(function (p) { svg.appendChild(sv('circle', { cx: xOf(p.x), cy: sc.y(p.v), r: 3, class: 'pt ' + cls })); });
      }
    });
    // x labels and the event-marker strip: each marker sits in the fiscal year whose period it falls in
    var ends = {}; (S.d.years || []).forEach(function (y) { ends[y.fiscal_label] = y.period_end; });
    var every = Math.ceil(xs.length / (narrow ? 5 : 12));
    xs.forEach(function (x, i) { if (i % every === 0 || i === xs.length - 1) svg.appendChild(sv('text', { x: xOf(x), y: H - (cfg.compact ? 6 : 28), 'text-anchor': 'middle', class: 'axis' }, x.replace(/^FY(\d\d)(\d\d)$/, "'$2").replace(/^FY/, ''))); });
    function bucket(date) { for (var i = 0; i < xs.length; i++) { var e = ends[xs[i]], prev = i ? ends[xs[i - 1]] : null; if (e && date <= e && (!prev || date > prev)) return xs[i]; } return null; }
    var mks = markers(), byYear = {};
    mks.forEach(function (m) { var b = bucket(m.date); if (!b) return; (byYear[b] = byYear[b] || []).push(m); });
    if (!cfg.compact || mks.length) {
      var row = { '8k': 0, officer: 1, auditor: 2 };
      Object.keys(byYear).forEach(function (x) {
        var seen = {}; byYear[x].forEach(function (m) { if (seen[m.kind]) return; seen[m.kind] = 1; var y = H - (cfg.compact ? 18 : 14) + (cfg.compact ? 0 : 0); svg.appendChild(sv('path', { d: shape(m.kind, xOf(x) + (row[m.kind] - 1) * 9, cfg.compact ? padT + 4 : y), class: 'mk mk-' + m.kind })); });
      });
    }
    // hover and keyboard: one column at a time, its values as doors and its events listed
    var hl = sv('rect', { x: 0, y: padT, width: step, height: H - padT - padB, class: 'hl', visibility: 'hidden' }); svg.insertBefore(hl, svg.firstChild);
    var tip = el('div', { class: 'ws-tip', role: 'status', 'aria-live': 'polite' }); tip.hidden = true;
    function show(i) {
      if (i < 0 || i >= xs.length) return; var x = xs[i];
      hl.setAttribute('x', padL + i * step); hl.setAttribute('visibility', 'visible');
      var kids = [el('b', { text: x + (ends[x] ? ' · ended ' + day(ends[x]) : '') })];
      ser.forEach(function (s, k) { var p = s.pts.filter(function (q) { return q.x === x; })[0]; kids.push(el('p', { class: 'tip-s s' + k }, [el('i'), s.label + ' ', p ? door(fmtv(p.v, s.unit, cur), p.info) : el('span', { class: 'muted', text: '—' })])); });
      (byYear[x] || []).slice(0, 5).forEach(function (m) { kids.push(el('p', { class: 'tip-e' }, [shapeIcon(m.kind), day(m.date) + ' ' + m.label + ' ', ARCHIVE.test(m.url || '') ? el('a', { href: m.url, target: '_blank', rel: 'noopener', text: (m.form || '') + ' ↗' }) : null])); });
      tip.replaceChildren.apply(tip, kids); tip.hidden = false;
      var tx = padL + i * step + step + 8; tip.style.left = Math.min(tx, W - 250) + 'px';
    }
    svg.addEventListener('mousemove', function (e) { var r = svg.getBoundingClientRect(), i = Math.floor(((e.clientX - r.left) * W / r.width - padL) / step); show(i); });
    svg.addEventListener('click', function (e) { var r = svg.getBoundingClientRect(), i = Math.floor(((e.clientX - r.left) * W / r.width - padL) / step); show(i); tip.classList.add('pinned'); });
    svg.setAttribute('tabindex', '0');
    var ki = xs.length - 1;
    svg.addEventListener('keydown', function (e) { if (e.key === 'ArrowLeft') { ki = Math.max(0, ki - 1); show(ki); e.preventDefault(); } if (e.key === 'ArrowRight') { ki = Math.min(xs.length - 1, ki + 1); show(ki); e.preventDefault(); } });
    svg.addEventListener('focus', function () { show(ki); });
    host.addEventListener('mouseleave', function () { if (!tip.classList.contains('pinned')) { tip.hidden = true; hl.setAttribute('visibility', 'hidden'); } });
    var lbl = ser.map(function (s) { var a = s.pts[0], b = s.pts[s.pts.length - 1]; return s.label + ' ' + a.x + ' ' + fmtv(a.v, s.unit, cur) + ' to ' + b.x + ' ' + fmtv(b.v, s.unit, cur); }).join('; ');
    svg.setAttribute('aria-label', lbl + '. Use the left and right arrow keys to read each year.');
    host.appendChild(svg); host.appendChild(tip);
    host.dataset.ms = String(Math.round(performance.now() - t0));
  }
  function shape(kind, x, y) { return kind === '8k' ? 'M' + x + ' ' + (y - 4) + 'l4 4-4 4-4-4z' : kind === 'officer' ? 'M' + (x - 3.5) + ' ' + y + 'a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0' : 'M' + x + ' ' + (y - 4) + 'l4 7h-8z'; }
  function shapeIcon(kind) { var s = sv('svg', { viewBox: '0 0 12 12', width: 12, height: 12, class: 'mk-ico', 'aria-hidden': 'true' }); s.appendChild(sv('path', { d: shape(kind, 6, 6), class: 'mk mk-' + kind })); return s; }

  function chartTab() {
    var pane = $('pane-chart'), rows = statementRows(), have = Object.keys(YEARLY).concat(Object.keys(rows).filter(function (m) { return !YEARLY[m]; }));
    S.m = S.m.filter(function (m) { return have.indexOf(m) > -1; }); if (!S.m.length) S.m = ['revenue'];
    var labelOf = function (m) { return YEARLY[m] || (rows[m] && rows[m].label) || m.replace(/_/g, ' '); };
    var chips = el('div', { class: 'ch-series' }, S.m.map(function (m, i) {
      return el('span', { class: 'chip s' + i }, [el('i'), labelOf(m), S.m.length > 1 ? el('button', { type: 'button', class: 'x', 'aria-label': 'Remove ' + labelOf(m), text: '×', on: { click: function () { S.m.splice(i, 1); go('chart'); } } }) : null]);
    }));
    var add = el('select', { 'aria-label': 'Add a metric (up to three)', on: { change: function (e) { if (e.target.value && S.m.length < 3) { S.m.push(e.target.value); go('chart'); } } } }, [el('option', { value: '', text: S.m.length < 3 ? '+ Add a metric' : 'Three series at most' })].concat(have.filter(function (m) { return S.m.indexOf(m) < 0; }).map(function (m) { return el('option', { value: m, text: labelOf(m) }); })));
    if (S.m.length >= 3) add.disabled = true;
    var sc = el('div', { class: 'seg-btns', role: 'group', 'aria-label': 'Scale' }, ['linear', 'log'].map(function (v) { return el('button', { type: 'button', 'aria-pressed': String(S.scale === v), text: v === 'log' ? 'Log' : 'Linear', on: { click: function () { S.scale = v; go('chart'); } } }); }));
    var mk = el('div', { class: 'mk-toggles', role: 'group', 'aria-label': 'Event markers' }, Object.keys(MK).map(function (k) {
      var cb = el('input', { type: 'checkbox', on: { change: function () { S.mk = Object.keys(MK).filter(function (x) { return x === k ? cb.checked : S.mk.indexOf(x) > -1; }); go('chart'); } } }); cb.checked = S.mk.indexOf(k) > -1;
      return el('label', { class: 'check' }, [cb, shapeIcon(k), MK[k].label]);
    }));
    var copy = el('button', { type: 'button', class: 'btn small', text: 'Copy link', on: { click: function () { try { navigator.clipboard.writeText(location.href); copy.textContent = 'Copied'; } catch (e) {} } } });
    var ask = el('a', { class: 'btn small', href: chatLink(S.m.map(labelOf).join(' and ') + ' over time'), text: 'Ask about this chart' });
    var host = el('div', { class: 'chart-host big' });
    pane.replaceChildren(el('div', { class: 'ch-bar' }, [chips, add, sc, mk, el('span', { class: 'ch-acts' }, [ask, copy])]), host,
      el('p', { class: 'muted small', text: 'Annual, as filed. Ten fiscal years where the overview has them, five from the statements otherwise; quarterly and longer histories come with the statements view. Ratios use the right axis. Markers show 8-K items, officer changes and auditor changes from the events loaded. Click a year to pin it.' }));
    drawChart(host, { series: S.m.map(series).filter(Boolean), height: window.innerWidth < 600 ? 280 : 420 });
  }

  /* ---- X-02 statements: the bulk endpoint (one request per statement); the overview's five years otherwise ---- */
  var bulk = {};
  function statementsTab() {
    if (S.st === 'ratios') return statementsFallback();
    var key = [S.cik, S.st, S.p, S.as_of || '', X.hasKey() ? 'k' : 'd'].join('|');
    if (bulk[key] === undefined) {
      bulk[key] = null;
      apiHas('/v1/companies/{cik}/statements/{statement}').then(function (has) { return has ? keyedOrDemo('/v1/companies/' + S.cik + '/statements/' + S.st + '?period=' + S.p + '&periods=' + (S.p === 'quarterly' ? 20 : 12) + (S.as_of ? '&as_of=' + S.as_of : '')) : { ok: false, status: 0 }; }).then(function (r) {
        bulk[key] = r.ok && r.body && r.body.rows ? r.body : (r.status === 404 && r.body && r.body.error && r.body.error.code === 'no_statement_data' ? { empty: true } : false);
        if (S.tab === 'statements') statementsTab();
      }).catch(function () { bulk[key] = false; if (S.tab === 'statements') statementsTab(); });
    }
    var b = bulk[key];
    if (b === null) { $('pane-statements').replaceChildren(el('p', { class: 'muted', text: 'Loading the statement…' })); return; }
    if (b === false) return statementsFallback();
    statementsBulk(b);
  }
  var STN = { income: 'Income statement', balance: 'Balance sheet', cash_flow: 'Cash flow', ratios: 'Ratios' };
  function stControls(cur, note, csvRows, csvName) {
    var tabs = el('div', { class: 'seg-btns', role: 'group', 'aria-label': 'Statement' }, Object.keys(STN).map(function (k) { return el('button', { type: 'button', 'aria-pressed': String(S.st === k), text: STN[k], on: { click: function () { S.st = k; go('statements'); } } }); }));
    var per = el('div', { class: 'seg-btns', role: 'group', 'aria-label': 'Period' }, [['annual', 'Annual'], ['quarterly', 'Quarterly']].map(function (v) { return el('button', { type: 'button', 'aria-pressed': String(S.p === v[0]), disabled: S.st === 'ratios' && v[0] === 'quarterly' ? 'disabled' : null, text: v[1], on: { click: function () { S.p = v[0]; go('statements'); } } }); }));
    var shows = el('div', { class: 'seg-btns', role: 'group', 'aria-label': 'Show' }, [['values', 'Values'], ['yoy', 'YoY %'], ['common', 'Common size']].map(function (v) { return el('button', { type: 'button', 'aria-pressed': String(S.show === v[0]), text: v[1], disabled: v[0] === 'common' && S.st !== 'income' && S.st !== 'balance' ? 'disabled' : null, on: { click: function () { S.show = v[0]; go('statements'); } } }); }));
    var csv = el('button', { type: 'button', class: 'btn small', text: 'CSV', on: { click: function () {
      var a = el('a', { href: URL.createObjectURL(new Blob([csvRows().join('\n')], { type: 'text/csv' })), download: csvName }); document.body.appendChild(a); a.click(); a.remove();
    } } });
    return el('div', { class: 'ch-bar' }, [tabs, per, shows, el('span', { class: 'muted small', text: note }), el('span', { class: 'ch-acts' }, [csv])]);
  }
  function statementsBulk(b) {
    var pane = $('pane-statements'), cur = b.reporting_currency || ((S.d.company || {}).reporting_currency) || 'USD';
    // nothing under this CIK (a new successor whose history the predecessor filed): the overview carries it
    if (b.empty && ((S.d.statements || {}).sections || []).length && S.p === 'annual') return statementsFallback();
    if (b.empty) { pane.replaceChildren(stControls(cur, '', function () { return []; }, 'empty.csv'), el('p', { class: 'muted', text: 'No values for this statement in the filings loaded.' })); return; }
    // columns that share a label (a cover-page date beside the quarter's balance-sheet date) merge into one
    var cols = [], idx = [], rows = b.rows || [], base = S.st === 'balance' ? 'total_assets' : 'revenue';
    (b.columns || []).forEach(function (c, i) { var k = cols.length ? cols.map(function (x) { return x.key; }).lastIndexOf(c.key) : -1; if (k > -1 && k >= cols.length - 2) idx[k].push(i); else { cols.push(c); idx.push([i]); } });
    var baseRow = rows.filter(function (r) { return r.metric === base; })[0];
    // cells align with columns by position (keys can repeat when a filer reuses a period label); values may come as strings
    var at = function (r, j) { var c = null; (idx[j] || []).some(function (i) { var x = (r.cells || [])[i]; if (x && x.value != null) { c = x; return true; } return false; }); return c ? Object.assign({}, c, { value: Number(c.value) }) : null; };
    var head = el('tr', {}, [el('th', { scope: 'col', class: 'stick', text: STN[S.st] })].concat(cols.map(function (c) { return el('th', { scope: 'col', class: 'n', title: c.period_end ? 'ended ' + day(c.period_end) : '', text: c.period_label || c.key }); })));
    var body = rows.map(function (r) {
      var ratio = r.unit_kind === 'ratio' || r.unit_kind === 'percent' || r.unit_kind === 'multiple';
      return el('tr', { class: /^(gross_profit|operating_income|net_income|total_assets|total_liabilities|stockholders_equity|operating_cash_flow|free_cash_flow)$/.test(r.metric) ? 'tot' : '' }, [el('th', { scope: 'row', class: 'stick' }, [r.label, r.derived ? el('span', { class: 'tag', title: r.formula || '', text: 'derived' }) : null])].concat(cols.map(function (col, i) {
        var c = at(r, i); if (!c || !isFinite(c.value)) return el('td', { class: 'n muted', title: 'not reported', text: '—' });
        var txt;
        if (S.show === 'yoy') { var back = S.p === 'quarterly' ? 4 : 1, pc = i >= back ? at(r, i - back) : null; txt = ratio ? '—' : pct(pc ? growth(c.value, pc.value) : null, true); }
        else if (S.show === 'common') { var bc = baseRow && at(baseRow, i); txt = ratio || !bc || !bc.value ? '—' : pct(100 * c.value / bc.value); }
        else txt = c.unit === 'ratio' ? pct(100 * c.value) : fmtv(c.value, c.unit, cur);
        var info = Object.assign({ label: r.label, metric: r.metric, currency: cur, fiscal_label: col.period_label || col.key, formula: r.formula }, c);
        var flag = c.quality_status && c.quality_status !== 'ok';
        return el('td', { class: 'n' + (c.predecessor ? ' pred' : '') }, [door(txt, info, flag ? 'flag' : ''), flag ? el('span', { class: 'qf', title: c.quality_status.replace(/_/g, ' '), text: '!' }) : null]);
      })));
    });
    var csvRows = function () { return [['line_item'].concat(cols.map(function (c) { return c.key; })).join(',')].concat(rows.map(function (r) { return ['"' + r.label.replace(/"/g, '""') + '"'].concat(cols.map(function (c, i) { var x = at(r, i); return x ? x.value : ''; })).join(','); })); };
    var wrap = el('div', { class: 'tw st-wrap' }, [el('table', { class: 'st-table' }, [el('thead', {}, [head]), el('tbody', {}, body)])]);
    pane.replaceChildren(stControls(cur, (S.p === 'quarterly' ? 'Quarterly' : 'Annual') + ' · in ' + cur + ' as filed' + (b.mapping_version ? ' · mapping ' + b.mapping_version : ''), csvRows, ((S.d.company || {}).ticker || S.cik) + '-' + S.st + '-' + S.p + '.csv'),
      wrap,
      el('p', { class: 'muted small', text: 'Click any value for its filing, tag and mapping. "—" means not reported. "!" marks a value whose quality isn\u2019t ok. Derived rows list their inputs; quarterly Q4s derived as the year less nine months are marked.' + (S.show === 'yoy' && S.p === 'quarterly' ? ' Quarterly YoY compares with the same quarter a year earlier.' : '') }),
      (b.notes || []).length ? el('p', { class: 'muted small', text: b.notes.join(' ') }) : null);
    wrap.scrollLeft = wrap.scrollWidth; // open on the latest periods; earlier ones scroll in from the left
  }
  function statementsFallback() {
    var pane = $('pane-statements'), d = S.d, cur = (d.company || {}).reporting_currency || 'USD', st = d.statements || {}, fy = st.fiscal_years || [];
    var KEYS2 = STN;
    var sec = (st.sections || []).filter(function (s) { return s.title === KEYS2[S.st]; })[0] || (st.sections || [])[0];
    var base = S.st === 'balance' ? 'total_assets' : 'revenue', baseRow = statementRows()[base];
    var head = el('tr', {}, [el('th', { scope: 'col', class: 'stick', text: KEYS2[S.st] })].concat(fy.map(function (y) { return el('th', { scope: 'col', class: 'n', text: y }); })));
    if (S.p === 'quarterly') S.p = 'annual';
    var body = (sec ? sec.rows : []).map(function (r) {
      var unit = r.unit === '%' || /margin|return_on/.test(r.metric) ? '%' : r.unit;
      return el('tr', { class: /^(gross_profit|operating_income|net_income|total_assets|total_liabilities|stockholders_equity|operating_cash_flow)$/.test(r.metric) ? 'tot' : '' }, [el('th', { scope: 'row', class: 'stick' }, [r.label, r.derived ? el('span', { class: 'tag', title: r.formula || '', text: 'derived' }) : null])].concat(r.cells.map(function (c, i) {
        if (!c || c.value == null) return el('td', { class: 'n muted', title: 'not reported', text: '—' });
        var txt;
        if (S.show === 'yoy') { var p = r.cells[i - 1]; txt = unit === '%' ? '—' : pct(p ? growth(c.value, p.value) : null, true); }
        else if (S.show === 'common') { var b = baseRow && baseRow.cells[i]; txt = unit === '%' || !b || !b.value ? '—' : pct(100 * c.value / b.value); }
        else txt = fmtv(c.value, unit, cur);
        return el('td', { class: 'n' + (c.predecessor ? ' pred' : '') }, [door(txt, cellInfo(r, c, cur), c.quality_status && c.quality_status !== 'ok' ? 'flag' : ''), c.quality_status && c.quality_status !== 'ok' ? el('span', { class: 'qf', title: c.quality_status.replace(/_/g, ' '), text: '!' }) : null]);
      })));
    });
    var csvRows = function () { return [['line_item'].concat(fy).join(',')].concat((sec ? sec.rows : []).map(function (r) { return ['"' + r.label.replace(/"/g, '""') + '"'].concat(r.cells.map(function (c) { return c && c.value != null ? c.value : ''; })).join(','); })); };
    pane.replaceChildren(stControls(cur, 'Annual · in ' + cur + ' as filed · last five years', csvRows, (d.company.ticker || d.company.cik) + '-' + S.st + '.csv'),
      el('div', { class: 'tw st-wrap' }, [el('table', { class: 'st-table' }, [el('thead', {}, [head]), el('tbody', {}, body)])]),
      el('p', { class: 'muted small', text: 'Click any value for its filing, tag and mapping. "—" means not reported. Shaded cells were reported by a predecessor registrant.' + (S.st === 'ratios' ? ' Ratios are worked out here from reported figures.' : ' Longer histories and quarters load from the statements API when it\u2019s available.') }));
    var fw = pane.querySelector('.st-wrap'); if (fw) fw.scrollLeft = fw.scrollWidth;
  }

  /* ---- X-05 timeline: the timeline endpoint (types, paging); the overview's events and filings otherwise ---- */
  var TLT = [['filing', 'Filings'], ['8k_item', '8-K items'], ['officer_change', 'Officers'], ['auditor_change', 'Auditors'], ['ipo', 'IPO'], ['insider', 'Insider signals'], ['13f_quarter', '13F quarters']];
  var tl = { key: null, items: [], cursor: null, more: false, ok: null, types: TLT.map(function (t) { return t[0]; }).filter(function (t) { return t !== 'filing'; }) };
  function timelineTab() {
    var key = [S.cik, S.as_of || '', tl.types.join(','), X.hasKey() ? 'k' : 'd'].join('|');
    if (tl.key !== key) { tl.key = key; tl.items = []; tl.cursor = null; tl.more = false; tl.ok = null; tlLoad(); }
    if (tl.ok === false) return timelineFallback();
    var pane = $('pane-timeline');
    var chips = el('div', { class: 'mk-toggles', role: 'group', 'aria-label': 'Show on the timeline' }, TLT.map(function (t) {
      var cb = el('input', { type: 'checkbox', on: { change: function () { tl.types = TLT.map(function (x) { return x[0]; }).filter(function (x) { return x === t[0] ? cb.checked : tl.types.indexOf(x) > -1; }); if (!tl.types.length) tl.types = [t[0]]; timelineTab(); } } }); cb.checked = tl.types.indexOf(t[0]) > -1;
      return el('label', { class: 'check' }, [cb, t[1]]);
    }));
    var list = el('ol', { class: 'tl' }, tl.items.map(function (i) {
      // the detail adds only what the title doesn't already say
      var d = i.details || {}, t0 = String(i.title || ''), sub = i.type === 'officer_change' ? (d.change && t0.toLowerCase().indexOf(String(d.change).toLowerCase()) < 0 ? d.change : '') : i.type === 'auditor_change' && !/→| replaces /.test(t0) ? [d.from_firm, d.to_firm].filter(Boolean).join(' → ') : i.type === '13f_quarter' && d.holders_change != null ? (d.holders_change >= 0 ? '+' : '−') + Math.abs(d.holders_change) + ' on the quarter before' : i.type === 'insider' && d.signal ? d.signal.replace(/_/g, ' ') : '';
      var kind = (TLT.filter(function (t) { return t[0] === i.type; })[0] || [0, i.type])[1];
      return el('li', { class: 'tl-' + i.type + (i.upcoming ? ' upcoming' : '') }, [el('time', { datetime: i.date, text: day(i.date) }), el('span', { class: 'tag', text: i.upcoming ? 'upcoming' : kind }),
        el('span', { class: 'tl-t' }, [String(i.title || '').replace(/\b(\d{4}-\d{2}-\d{2})\b/g, function (m) { return day(m); }), sub ? el('span', { class: 'muted small', text: ' · ' + sub }) : null]),
        ARCHIVE.test(i.filing_url || '') ? el('a', { href: i.filing_url, target: '_blank', rel: 'noopener', text: (i.form_type || 'Filing') + ' ↗' }) : el('span')]);
    }));
    var more = tl.more ? el('button', { type: 'button', class: 'btn small', text: 'Load more', on: { click: function () { tlLoad(); } } }) : null;
    pane.replaceChildren(el('div', { class: 'ch-bar' }, [chips]), el('p', { class: 'muted small', text: 'Information, not signals. Not investment advice. Newest first; every item links its filing.' }),
      tl.ok === null && !tl.items.length ? el('p', { class: 'muted', text: 'Loading the timeline…' }) : tl.items.length ? list : el('p', { class: 'muted', text: 'Nothing of these kinds in the filings loaded.' }), more);
  }
  function tlLoad() {
    var key = tl.key, q = '/v1/companies/' + S.cik + '/timeline?limit=' + (X.hasKey() ? 100 : 10) + '&types=' + tl.types.join(',') + (S.as_of ? '&as_of=' + S.as_of : '') + (tl.cursor ? '&cursor=' + encodeURIComponent(tl.cursor) : '');
    apiHas('/v1/companies/{cik}/timeline').then(function (has) { return has ? keyedOrDemo(q) : { ok: false }; }).then(function (r) {
      if (tl.key !== key) return;
      if (!r.ok || !r.body || !Array.isArray(r.body.data)) { if (!tl.items.length) tl.ok = false; }
      else { tl.ok = true; tl.items = tl.items.concat(r.body.data); var m = r.body.meta || {}; tl.cursor = m.next_cursor || null; tl.more = !!(m.has_more && m.next_cursor); }
      if (S.tab === 'timeline') timelineTab();
    }).catch(function () { if (tl.key === key && !tl.items.length) { tl.ok = false; if (S.tab === 'timeline') timelineTab(); } });
  }
  function timelineFallback() {
    var d = S.d, items = [];
    (d.events || []).forEach(function (e) { items.push({ date: e.date, kind: 'Event', title: e.short_label || e.label, detail: e.label, url: e.filing_url, form: e.form_type }); });
    (d.filings || []).forEach(function (f) { items.push({ date: f.filing_date || f.filed_date, kind: 'Filing', title: f.form_label || f.form_type, detail: f.form_type, url: f.source_url || f.filing_url, form: f.form_type }); });
    items.sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    var seen = {}; items = items.filter(function (i) { var k = i.url + i.kind; if (seen[k]) return false; seen[k] = 1; return true; });
    $('pane-timeline').replaceChildren(el('p', { class: 'muted small', text: 'Information, not signals. Not investment advice. Filings and the events read from them, newest first.' }),
      el('ol', { class: 'tl' }, items.slice(0, 60).map(function (i) { return el('li', { class: 'tl-' + i.kind.toLowerCase() }, [el('time', { datetime: i.date, text: day(i.date) }), el('span', { class: 'tag', text: i.kind }), el('span', { class: 'tl-t', title: i.detail, text: i.title }), ARCHIVE.test(i.url || '') ? el('a', { href: i.url, target: '_blank', rel: 'noopener', text: (i.form || '') + ' ↗' }) : null]); })));
  }

  /* ---- the company page's own renderers (13F ownership, segments), so wording and ADR handling match ---- */
  var lowerP = null;
  function companyLower() {
    if (lowerP) return lowerP;
    function load(src) { return new Promise(function (ok, no) { var t = document.createElement('script'); t.src = src; t.onload = ok; t.onerror = no; document.body.appendChild(t); }); }
    lowerP = (window.CompanyPage ? Promise.resolve() : load('/companies/page/page.js')).then(function () {
      var P = window.CompanyPage;
      P.ui = P.ui || { el: P.el, DOT: ' · ', humanDates: P.humanDates, fmt: function (v, unit) { return fmtv(v, unit, P.cur); },
        srcLink: function (text, url, title) { return ARCHIVE.test(url || '') ? el('a', { href: url, target: '_blank', rel: 'noopener', title: title, text: text }) : el('span', { title: title, text: text }); } };
      return window.CompanyLower ? null : load('/companies/page/company-lower.js');
    }).then(function () { return window.CompanyLower; });
    lowerP.catch(function () { lowerP = null; });
    return lowerP;
  }
  // which API routes this deployment has (from /openapi.json, once), so a missing endpoint is never requested
  var specP = null;
  function apiHas(path) {
    specP = specP || fetch('/openapi.json', { headers: { Accept: 'application/json' } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { return j && j.paths ? j.paths : {}; }).catch(function () { return {}; });
    return specP.then(function (paths) { return !!paths[path]; });
  }
  // the keyed endpoints, or the public demo key on a showcase company (no SEC fetch; ten rows)
  function keyedOrDemo(path) { return X.raw(path, X.hasKey() ? null : 'demo'); }

  /* ---- X-04 ownership: 13F, insiders (Forms 3/4/5), 5% holders ---- */
  function ownershipTab() {
    var d = S.d, cik = S.cik, pane = $('pane-ownership'), cur = (d.company || {}).reporting_currency || 'USD';
    var own = el('section', { id: 'ownership', class: 'ws-sec', 'aria-labelledby': 'own-h' }, [
      el('div', { class: 'ov-h' }, [el('h3', { id: 'own-h', text: 'Institutional holders (13F)' })]), el('p', { class: 'muted small', id: 'own-when' }),
      el('div', { class: 'own-nums', id: 'own-nums' }), el('p', { class: 'own-flag', id: 'own-flag', hidden: 'hidden' }),
      el('div', { class: 'tw' }, [el('table', { class: 'own-table', id: 'own-table' })]), el('p', { class: 'muted small', id: 'own-more', hidden: 'hidden' }), el('p', { class: 'notes small muted', id: 'own-notes' })]);
    var ins = el('section', { class: 'ws-sec', 'aria-labelledby': 'ins-h' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'ins-h', text: 'Insider transactions (Forms 3, 4, 5)' })]), el('p', { class: 'muted small', text: 'Information, not signals. Not investment advice.' }), el('p', { class: 'muted', text: 'Loading…' })]);
    var big = el('section', { class: 'ws-sec', 'aria-labelledby': 'big-h' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'big-h', text: 'Holders above 5% (Schedules 13D and 13G)' })]), el('p', { class: 'muted', text: 'Loading…' })]);
    pane.replaceChildren(own, ins, big);
    if (d.ownership) companyLower().then(function (L) {
      if (!L || S.tab !== 'ownership') return;
      window.CompanyPage.cur = cur; L.ownership(d); var more = $('own-more'); if (more) more.hidden = true;
      // ten holders first so insiders and 5% holders show on the first screen; the rest on request
      var trs = [].slice.call(document.querySelectorAll('#own-table tbody tr'));
      if (trs.length > 10) {
        trs.slice(10).forEach(function (r) { r.classList.add('more-row'); r.hidden = true; });
        var b = el('button', { type: 'button', class: 'linkish', text: 'Show all ' + trs.length + ' holders', on: { click: function () { trs.forEach(function (r) { r.hidden = false; }); b.remove(); } } });
        $('own-table').parentNode.after(b);
      }
    });
    else own.replaceChildren(own.firstChild, el('p', { class: 'muted', text: S.as_of ? '13F holdings show for the latest quarter only, not for a past date.' : 'No 13F holders matched yet.' }));
    var asq = S.as_of ? '&as_of=' + S.as_of : '';
    keyedOrDemo('/v1/companies/' + cik + '/insider-transactions?limit=' + (X.hasKey() ? 40 : 10) + asq).then(function (r) {
      if (S.tab !== 'ownership' || S.cik !== cik) return;
      var rows = r.ok && r.body && r.body.data || [];
      var body = rows.map(function (t) {
        var sell = t.acquired_disposed === 'D', open = /open-market/.test(t.trans_code_label || '');
        return el('tr', {}, [el('td', { text: day(t.trans_date) }), el('th', { scope: 'row' }, [t.owner_name, el('span', { class: 'muted small ins-role', title: t.role || '', text: t.role || '' })]),
          el('td', {}, [(t.trans_code_label || t.trans_code || '').replace(/^./, function (c) { return c.toUpperCase(); }), t.is_derivative ? el('span', { class: 'tag', text: 'derivative' }) : null, t.plan_10b5_1 ? el('span', { class: 'tag', title: 'Made under a Rule 10b5-1 trading plan set up in advance', text: '10b5-1 plan' }) : null]),
          el('td', { class: 'n' + (open ? (sell ? ' down' : ' up') : '') }, [(sell ? '−' : '+') + count(t.shares || 0)]), el('td', { class: 'n opt2', text: t.price != null ? money(t.price, 'USD', 2).replace(/\.00$/, '') : '—' }),
          el('td', { class: 'n', text: t.value != null ? money(t.value, 'USD') : '—' }), el('td', { class: 'n muted opt2', text: t.shares_after != null ? count(t.shares_after) : '—' }),
          el('td', {}, [ARCHIVE.test(t.source_url || '') ? el('a', { href: t.source_url, target: '_blank', rel: 'noopener', text: 'Form ' + t.form_type + ' ↗' }) : null])]);
      });
      body.forEach(function (tr, i) { if (i >= 8) { tr.hidden = true; tr.classList.add('more-row'); } });
      var allIns = body.length > 8 ? el('button', { type: 'button', class: 'linkish', text: 'Show all ' + body.length, on: { click: function () { body.forEach(function (tr) { tr.hidden = false; }); allIns.remove(); } } }) : null;
      ins.replaceChildren(ins.firstChild, ins.children[1], rows.length ? el('div', { class: 'tw' }, [el('table', { class: 'ov-table ins-table' }, [el('thead', {}, [el('tr', {}, ['Date', 'Insider', 'Transaction', 'Shares', 'Price', 'Value', 'Held after', 'Filing'].map(function (h, i) { return el('th', { scope: 'col', class: (i >= 3 && i <= 6 ? 'n' : '') + (i === 4 || i === 6 ? ' opt2' : ''), text: h }); }))]), el('tbody', {}, body)])])
        : el('p', { class: 'muted', text: r.ok ? 'No insider transactions in the filings loaded.' : 'Insider transactions are unavailable right now.' }),
        allIns, !X.hasKey() && rows.length ? el('p', { class: 'muted small', text: 'The ten most recent; a free key shows more.' }) : null);
    });
    keyedOrDemo('/v1/companies/' + cik + '/holders?limit=' + (X.hasKey() ? 25 : 10) + asq).then(function (r) {
      if (S.tab !== 'ownership' || S.cik !== cik) return;
      var rows = r.ok && r.body && r.body.data || [];
      big.replaceChildren(big.firstChild, rows.length ? el('div', { class: 'tw' }, [el('table', { class: 'ov-table' }, [el('thead', {}, [el('tr', {}, ['Holder', 'Type', '% of class', 'Shares', 'Schedule', 'As of', 'Filing'].map(function (h, i) { return el('th', { scope: 'col', class: i >= 2 && i <= 3 ? 'n' : '', text: h }); }))]),
        el('tbody', {}, rows.map(function (h) { var f = h.filing || {}; return el('tr', {}, [el('th', { scope: 'row', text: orgName(h.name) }), el('td', { class: 'muted', text: h.holder_type_label || '' }), el('td', { class: 'n', text: h.percent != null ? pct(h.percent) : '—' }), el('td', { class: 'n', text: h.shares != null ? count(h.shares) : '—' }), el('td', { text: h.schedule || '' }), el('td', { text: day(h.event_date) }), el('td', {}, [ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: (f.form_type || 'Filing').replace(/^SCHEDULE /, '') + ' ↗' }) : null])]); }))])])
        : el('p', { class: 'muted', text: r.ok ? 'No 13D or 13G filings above 5% in the filings loaded.' : '5% holders are unavailable right now.' }));
    });
  }

  /* ---- X-03 segments: stacked bars over the report's years, then the company page's table ---- */
  function segmentsTab() {
    var d = S.d, pane = $('pane-segments'), cur = (d.company || {}).reporting_currency || 'USD';
    var stack = el('div', { class: 'chart-host seg-stack' });
    var sec = el('section', { id: 'segments', class: 'ws-sec', 'aria-labelledby': 'seg-h' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'seg-h', text: 'Segments' })]), el('p', { class: 'muted small', id: 'seg-from' }),
      el('div', { class: 'seg-btns', id: 'seg-kinds', role: 'tablist', 'aria-label': 'Segment breakdown' }), el('div', { class: 'seg-btns', id: 'seg-metrics', role: 'group', 'aria-label': 'Figure' }),
      stack, el('div', { class: 'tw fin-wrap', id: 'seg-table' }), el('p', { class: 'notes small muted', id: 'seg-notes' })]);
    pane.replaceChildren(sec);
    if (!d.segments || !(d.segments.kinds || []).length) { sec.replaceChildren(sec.firstChild, el('p', { class: 'muted', text: d.segments && d.segments.hidden_reason ? 'No segment breakdown to show for the latest report.' : 'No segments tagged in the latest annual report.' })); return; }
    companyLower().then(function (L) {
      if (!L || S.tab !== 'segments') return;
      window.CompanyPage.cur = cur; L.segments(d);
      var draw = function () {
        var kb = [].slice.call(document.querySelectorAll('#seg-kinds button')), ki = Math.max(0, kb.findIndex(function (b) { return b.getAttribute('aria-selected') === 'true'; }));
        var mb = [].slice.call(document.querySelectorAll('#seg-metrics button')), mi = mb.findIndex(function (b) { return b.getAttribute('aria-pressed') === 'true'; });
        var K = d.segments.kinds[ki], metrics = Object.keys(K.metrics || {}), m = mi > -1 ? metrics[mi] : (metrics.indexOf('revenue') > -1 ? 'revenue' : metrics[0]);
        stackChart(stack, K, m, cur);
      };
      draw(); new MutationObserver(draw).observe($('seg-table'), { childList: true });
    });
  }
  function stackChart(host, K, m, cur) {
    var per = (K.periods || []).slice().reverse(), segs = (K.segments || []).filter(function (g) { return per.some(function (p) { return (((g.values || {})[m] || {})[p] || 0) > 0; }); });
    host.textContent = ''; if (!per.length || !segs.length) return;
    var W = Math.max(320, host.clientWidth || 700), H = 220, padL = 56, padB = 26, padT = 10, legendW = W < 600 ? 0 : 200;
    var tot = per.map(function (p) { return segs.reduce(function (a, g) { var v = ((g.values || {})[m] || {})[p]; return a + (v > 0 ? v : 0); }, 0); }), hi = Math.max.apply(null, tot) || 1;
    var svg = sv('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, class: 'ws-chart', role: 'img', 'aria-label': 'Segment ' + m.replace(/_/g, ' ') + ' stacked by year' });
    var plotW = W - padL - legendW - 10, step = plotW / per.length, bw = Math.min(64, step * 0.6), y = function (v) { return padT + (H - padT - padB) * (1 - v / hi); };
    [0, .5, 1].forEach(function (f) { svg.appendChild(sv('line', { x1: padL, x2: padL + plotW, y1: y(hi * f), y2: y(hi * f), class: 'grid' })); svg.appendChild(sv('text', { x: padL - 6, y: y(hi * f) + 4, 'text-anchor': 'end', class: 'axis' }, f ? money(hi * f, cur, 0) : '0')); });
    per.forEach(function (p, i) {
      var x = padL + i * step + (step - bw) / 2, acc = 0;
      segs.forEach(function (g, j) { var v = ((g.values || {})[m] || {})[p]; if (!(v > 0)) return; var r = sv('rect', { x: x, y: y(acc + v), width: bw, height: Math.max(1, y(acc) - y(acc + v)), class: 'stk k' + (j % 6) }); r.appendChild(sv('title', {}, g.label + ', year to ' + day(p) + ': ' + money(v, cur))); svg.appendChild(r); acc += v; });
      svg.appendChild(sv('text', { x: x + bw / 2, y: H - 8, 'text-anchor': 'middle', class: 'axis' }, day(p).replace(/^\d+ /, '')));
    });
    if (legendW) segs.slice(0, 8).forEach(function (g, j) { var ly = padT + 4 + j * 22; svg.appendChild(sv('rect', { x: W - legendW, y: ly, width: 10, height: 10, class: 'stk k' + (j % 6) })); svg.appendChild(sv('text', { x: W - legendW + 16, y: ly + 9, class: 'axis lg' }, g.label.length > 28 ? g.label.slice(0, 27) + '…' : g.label)); });
    host.appendChild(svg);
  }

  /* ---- X-06 compare: up to five companies, each in its own currency; growth indexed, never summed ---- */
  var cmpCache = {};
  function overviewOf(cik) {
    var key = cik + '|' + (S.as_of || '') + '|' + (X.hasKey() ? 'k' : 'p');
    if (cmpCache[key]) return cmpCache[key];
    var qs = S.as_of ? '?as_of=' + S.as_of : '';
    cmpCache[key] = X.raw((X.hasKey() ? '/v1/companies/' : '/v1/public/companies/') + cik + '/overview' + qs).then(function (r) { return r.ok ? r.body : (X.hasKey() ? X.raw('/v1/public/companies/' + cik + '/overview' + qs).then(function (r2) { return r2.ok ? r2.body : null; }) : null); });
    return cmpCache[key];
  }
  var CMP = [['revenue', 'Revenue', 'v'], ['revenue', 'Revenue growth, latest year', 'yoy'], ['revenue', 'Revenue CAGR', 'cagr'], ['operating_income', 'Operating income', 'v'], ['operating_margin', 'Operating margin', 'r'], ['net_income', 'Net income', 'v'], ['net_margin', 'Net margin', 'r'], ['free_cash_flow', 'Free cash flow', 'v'], ['total_assets', 'Total assets', 'v'], ['return_on_equity', 'Return on equity', 'r']];
  function compareTab() {
    var pane = $('pane-compare'), ciks = [S.cik].concat(S.cmp), my = ++seq2;
    var add = el('button', { type: 'button', class: 'btn small', text: ciks.length < 5 ? '+ Add a company' : 'Five companies at most', on: { click: function () { palette('compare'); } } }); if (ciks.length >= 5) add.disabled = true;
    pane.replaceChildren(el('div', { class: 'ch-bar' }, [el('span', { class: 'muted small', text: 'Up to five companies, each in the currency it reports in.' }), el('span', { class: 'ch-acts' }, [add, el('button', { type: 'button', class: 'btn small', text: 'Copy link', on: { click: function (e) { try { navigator.clipboard.writeText(location.href); e.target.textContent = 'Copied'; } catch (x) {} } } })])]), el('p', { class: 'muted', text: 'Loading…' }));
    Promise.all(ciks.map(overviewOf)).then(function (list) {
      if (my !== seq2 || S.tab !== 'compare') return;
      var cos = list.map(function (d, i) { return { cik: ciks[i], d: d }; });
      var curs = cos.filter(function (c) { return c.d; }).map(function (c) { return c.d.company.reporting_currency || 'USD'; }), mixed = curs.some(function (c) { return c !== curs[0]; });
      var head = el('tr', {}, [el('th', { scope: 'col', text: '' })].concat(cos.map(function (c, i) {
        var nm = c.d ? (c.d.company.display_name || c.d.company.legal_name) : 'CIK ' + c.cik + ' (not available' + (X.hasKey() ? ')' : ' without a key)');
        var fye = c.d && c.d.company.fiscal_year_end_month ? 'FY ends ' + String(c.d.company.fiscal_year_end_month).slice(0, 3) : null;
        return el('th', { scope: 'col', class: 'n cmp-h' }, [el('a', { href: '/app/?c=' + c.cik, text: c.d && c.d.company.ticker || nm, title: nm }), c.d ? el('span', { class: 'chip', text: c.d.company.reporting_currency || 'USD' }) : null,
          i ? el('button', { type: 'button', class: 'x', 'aria-label': 'Remove ' + nm, text: '×', on: { click: function () { S.cmp = S.cmp.filter(function (x) { return x !== c.cik; }); go('compare'); } } }) : null, fye ? el('span', { class: 'muted small cmp-fye', text: fye }) : null]);
      })));
      var body = CMP.map(function (row) {
        return el('tr', {}, [el('th', { scope: 'row', text: row[1] })].concat(cos.map(function (c) {
          if (!c.d) return el('td', { class: 'n muted', text: '—' });
          var saved = S.d; S.d = c.d; var sr = series(row[0]); S.d = saved;
          var cur = c.d.company.reporting_currency || 'USD';
          if (!sr || !sr.pts.length) return el('td', { class: 'n muted', title: 'not reported', text: '—' });
          var a = sr.pts[sr.pts.length - 1], b = sr.pts[sr.pts.length - 2], f = sr.pts[0], n = sr.pts.length - 1;
          if (row[2] === 'yoy') return el('td', { class: 'n ' + tone('revenue', b ? growth(a.v, b.v) : null), text: pct(b ? growth(a.v, b.v) : null, true) });
          if (row[2] === 'cagr') return el('td', { class: 'n muted', text: n > 0 && f.v > 0 && a.v > 0 ? pct(100 * (Math.pow(a.v / f.v, 1 / n) - 1), true) + ' (' + n + 'y)' : '—' });
          return el('td', { class: 'n' }, [door(fmtv(a.v, sr.unit, cur), a.info), el('span', { class: 'muted small', text: ' ' + a.x })]);
        })));
      });
      var table = el('div', { class: 'tw' }, [el('table', { class: 'ov-table cmp-table' }, [el('thead', {}, [head]), el('tbody', {}, body)])]);
      var g = el('div', { class: 'chart-host' }), m = el('div', { class: 'chart-host' });
      pane.replaceChildren(pane.firstChild,
        mixed ? el('p', { class: 'ws-note cmp-banner', role: 'note', text: 'These companies report in different currencies (' + curs.filter(function (c, i, a) { return a.indexOf(c) === i; }).join(', ') + '). Each figure is in its company’s own currency; only growth and margins are compared, and nothing is summed or converted.' }) : null,
        table, el('div', { class: 'cmp-charts' }, [el('section', { class: 'ws-sec' }, [el('h3', { text: 'Revenue, indexed to 100 at the first year shown' }), g]), el('section', { class: 'ws-sec' }, [el('h3', { text: 'Operating margin' }), m])]),
        el('p', { class: 'muted small', text: 'Fiscal years as each company defines them, aligned by fiscal-year number. Click any figure for its filing.' + fyGap(cos) }));
      multiLine(g, cos, 'revenue', true); multiLine(m, cos, 'operating_margin', false);
    });
  }
  var seq2 = 0;
  // when fiscal years end more than three months apart, say so with the real nearest example
  function fyGap(cos) {
    var ends = cos.filter(function (c) { return c.d && (c.d.years || []).length; }).map(function (c) { var y = c.d.years[c.d.years.length - 1]; return { c: c, y: y, m: +String(y.period_end).slice(5, 7) }; });
    if (ends.length < 2) return '';
    var base = ends[0], far = null, gap = 0;
    ends.slice(1).forEach(function (e) { var d = Math.abs(e.m - base.m); d = Math.min(d, 12 - d); if (d > gap) { gap = d; far = e; } });
    if (!far || gap <= 3) return '';
    var nm = far.c.d.company.display_name || far.c.d.company.legal_name;
    return ' Fiscal years end in different months: ' + nm + '\u2019s ' + far.y.fiscal_label + ' ended ' + day(far.y.period_end).replace(/^\d+ /, '') + ', ' + (base.c.d.company.display_name || '') + '\u2019s ' + base.y.fiscal_label + ' ended ' + day(base.y.period_end).replace(/^\d+ /, '') + '.';
  }
  function multiLine(host, cos, metric, indexed) {
    var lines = cos.filter(function (c) { return c.d; }).map(function (c, i) {
      var saved = S.d; S.d = c.d; var sr = series(metric); S.d = saved; if (!sr || !sr.pts.length) return null;
      var pts = sr.pts.map(function (p) { return { fy: parseInt(String(p.x).replace(/\D/g, ''), 10), v: p.v }; }).filter(function (p) { return isFinite(p.fy); });
      if (indexed) { var b = pts.filter(function (p) { return p.v > 0; })[0]; if (!b) return null; pts = pts.filter(function (p) { return p.fy >= b.fy; }).map(function (p) { return { fy: p.fy, v: 100 * p.v / b.v }; }); }
      return { label: c.d.company.ticker || c.d.company.display_name, pts: pts, k: i };
    }).filter(Boolean);
    host.textContent = ''; if (!lines.length) { host.appendChild(el('p', { class: 'muted', text: 'Nothing to chart.' })); return; }
    var fys = []; lines.forEach(function (l) { l.pts.forEach(function (p) { if (fys.indexOf(p.fy) < 0) fys.push(p.fy); }); }); fys.sort();
    var vals = []; lines.forEach(function (l) { l.pts.forEach(function (p) { vals.push(p.v); }); });
    var lo = Math.min(indexed ? 100 : 0, Math.min.apply(null, vals)), hi = Math.max.apply(null, vals); if (hi === lo) hi = lo + 1;
    var W = Math.max(300, host.clientWidth || 600), H = 220, padL = 44, padR = 60, padT = 10, padB = 22;
    var x = function (fy) { return padL + (fys.length < 2 ? 0 : (fys.indexOf(fy)) * (W - padL - padR) / (fys.length - 1)); }, y = function (v) { return padT + (H - padT - padB) * (hi - v) / (hi - lo); };
    var svg = sv('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, class: 'ws-chart', role: 'img', 'aria-label': (indexed ? 'Revenue indexed to 100' : 'Operating margin') + ': ' + lines.map(function (l) { var e = l.pts[l.pts.length - 1]; return l.label + ' ' + (indexed ? Math.round(e.v) : pct(e.v)) + ' in FY' + e.fy; }).join('; ') });
    [lo, (lo + hi) / 2, hi].forEach(function (v) { svg.appendChild(sv('line', { x1: padL, x2: W - padR, y1: y(v), y2: y(v), class: 'grid' })); svg.appendChild(sv('text', { x: padL - 6, y: y(v) + 4, 'text-anchor': 'end', class: 'axis' }, indexed ? String(Math.round(v)) : pct(v))); });
    fys.forEach(function (fy, i) { if (i % Math.ceil(fys.length / 6) === 0 || i === fys.length - 1) svg.appendChild(sv('text', { x: x(fy), y: H - 6, 'text-anchor': 'middle', class: 'axis' }, "'" + String(fy).slice(2))); });
    var ends = [];
    lines.forEach(function (l) {
      svg.appendChild(sv('path', { d: l.pts.map(function (p, j) { return (j ? 'L' : 'M') + x(p.fy).toFixed(1) + ' ' + y(p.v).toFixed(1); }).join(' '), class: 'line c' + l.k }));
      var e = l.pts[l.pts.length - 1]; ends.push({ l: l, x: x(e.fy) + 6, y: y(e.v) + 4 });
    });
    // end labels never overlap: keep at least 12px between them, in order down the chart
    ends.sort(function (a, b) { return a.y - b.y; }).forEach(function (e, i, a) { if (i && e.y - a[i - 1].y < 12) e.y = a[i - 1].y + 12; svg.appendChild(sv('text', { x: e.x, y: e.y, class: 'axis lg c' + e.l.k }, e.l.label)); });
    host.appendChild(svg);
  }

  /* ---- empty state: the showcase companies, opened in the workspace ---- */
  function showEmpty() {
    $('company').hidden = true; $('ws-empty').hidden = false; S.d = null;
    document.title = 'Explorer · Provenance';
    landing();
  }
  /* the landing: showcase companies with live figures, recent companies, the screener's top three */
  var RKEY = 'prv_ws_recent';
  function recent(add) {
    var list = []; try { list = JSON.parse(localStorage.getItem(RKEY) || '[]').filter(function (r) { return r && /^\d{1,10}$/.test(r.cik); }); } catch (e) {}
    if (add) { list = [add].concat(list.filter(function (r) { return r.cik !== add.cik; })).slice(0, 8); try { localStorage.setItem(RKEY, JSON.stringify(list)); } catch (e) {} }
    return list;
  }
  var landed = false;
  function landing() {
    var host = $('ws-landing'); if (!host || landed || $('explore').hidden) return; landed = true; // only when Explore is showing
    var cards = el('ul', { class: 'land-cards' }), rec = recent();
    host.replaceChildren.apply(host, [
      el('p', { class: 'land-k' }, [el('kbd', { text: '⌘K' }), ' or ', el('kbd', { text: '/' }), ' jumps to any company, tab, metric or date. Every figure opens its filing.']),
      el('section', { 'aria-labelledby': 'land-sc' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'land-sc', text: 'Showcase companies' }), el('span', { class: 'muted small', text: X.hasKey() ? '' : 'Open with no key' })]), cards]),
      rec.length ? el('section', { 'aria-labelledby': 'land-rec' }, [el('h3', { id: 'land-rec', text: 'Recent' }), el('p', { class: 'land-rec' }, rec.map(function (r) { return el('a', { class: 'chip', href: '/app/?c=' + r.cik, text: r.name, on: { click: function (e) { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); window.Workspace.open(r.cik); } } } }); }))]) : null,
      el('section', { 'aria-labelledby': 'land-top', class: 'land-top' }, [el('div', { class: 'ov-h' }, [el('h3', { id: 'land-top', text: 'Largest by revenue, ' + (new Date().getFullYear() - 1) }), el('a', { class: 'linkish', href: '/app/?sm=revenue&sy=' + (new Date().getFullYear() - 1) + '#screener', text: 'Open the screener' })]), el('p', { class: 'muted', text: 'Loading…' })])].filter(Boolean));
    X.raw('/v1/public/companies').then(function (r) {
      var cos = r.ok && r.body && r.body.data || [];
      cos.slice(0, 8).forEach(function (c) {
        var cik = String(parseInt(c.cik, 10)), li = el('li', {}, [el('a', { class: 'land-card', href: '/app/?c=' + cik, on: { click: function (e) { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); window.Workspace.open(cik); } } } }, [el('b', { text: c.display_name || orgName(c.legal_name) }), el('span', { class: 'muted small', text: [c.ticker, c.exchange].filter(Boolean).join(' · ') })])]);
        cards.appendChild(li);
        X.raw('/v1/public/companies/' + cik + '/overview').then(function (o) {
          if (!o.ok) return; var d = o.body; if (d.company.display_name) li.querySelector('b').textContent = d.company.display_name; var y = (d.years || []).filter(function (x) { return x.revenue != null; }), last = y[y.length - 1], prev = y[y.length - 2], cur = d.company.reporting_currency || 'USD';
          if (!last) return;
          var yoy = prev && prev.revenue > 0 ? 100 * (last.revenue - prev.revenue) / prev.revenue : null;
          li.appendChild(el('p', { class: 'land-fig' }, [el('span', { class: 'muted small', text: 'Revenue ' + last.fiscal_label }), el('b', { text: money(last.revenue, cur) }), el('span', { class: 'small ' + tone('revenue', yoy), text: pct(yoy, true) }), last.operating_margin_pct != null ? el('span', { class: 'muted small', text: 'Op. margin ' + pct(last.operating_margin_pct) }) : null]));
          var sp = spark(y.map(function (x) { return x.revenue; })); if (sp) li.appendChild(sp);
        });
      });
    });
    X.raw('/v1/facts/screen?metric=revenue&year=' + (new Date().getFullYear() - 1) + '&limit=3', X.hasKey() ? null : 'demo').then(function (r) {
      var box = host.querySelector('.land-top'); if (!box) return;
      var rows = r.ok && r.body && r.body.data || [];
      box.replaceChild(rows.length ? el('ol', { class: 'ov-list land-list' }, rows.map(function (x) { var cik = String(parseInt(x.cik, 10)); return el('li', {}, [el('a', { href: '/app/?c=' + cik, text: x.display_name || orgName(x.legal_name), on: { click: function (e) { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); window.Workspace.open(cik); } } } }), el('span', { class: 'muted small', text: x.ticker || '' }), door(money(x.value, (x.unit || 'USD').split('/')[0]), { label: 'Revenue', metric: 'revenue', period_end: x.period_end, form_type: x.form_type, filed_date: x.filed_date, source_url: x.source_url, accession_number: x.accession_number, source_tag: x.source_tag, mapping_version: x.mapping_version, quality_status: x.quality_status })]); })) : el('p', { class: 'muted', text: !X.hasKey() && r.status === 429 ? 'The shared demo key has reached today\u2019s limit; a free key shows the ranking.' : 'The screen is unavailable right now.' }), box.lastChild);
    });
  }

  /* ---- ⌘K palette (X-10): companies, tabs, metrics, as-of ---- */
  var pal = null;
  var palMode = null;
  function palette(mode) {
    palMode = mode === 'compare' ? 'compare' : null;
    if (pal) { pal.querySelector('input').focus(); return; }
    var input = el('input', { type: 'search', 'aria-label': 'Jump to a company, tab, metric or date', placeholder: 'Company, ticker or CIK · a tab · a metric · "as of 2024-06-30"', autocomplete: 'off', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'pal-list' });
    var list = el('ul', { id: 'pal-list', role: 'listbox' }), items = [], sel = 0, timer;
    pal = el('div', { class: 'pal-back', on: { click: function (e) { if (e.target === pal) closePal(); } } }, [el('div', { class: 'pal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Command palette' }, [input, list, el('p', { class: 'muted small', text: '↑ ↓ to choose · Enter to open · Esc to close' })])]);
    document.body.appendChild(pal); input.focus();
    function render() {
      list.replaceChildren.apply(list, items.map(function (it, i) { var li = el('li', { role: 'option', id: 'pal-' + i, 'aria-selected': String(i === sel) }, [el('span', { text: it.label }), el('span', { class: 'muted small', text: it.hint || '' })]); li.addEventListener('click', function () { sel = i; run(); }); return li; }));
      input.setAttribute('aria-activedescendant', items.length ? 'pal-' + sel : '');
    }
    function local(q) {
      var out = [], ql = q.toLowerCase();
      var a = /^(?:as of\s*)?(\d{4}-\d{2}-\d{2})$/i.exec(q.trim()); if (a) out.push({ label: 'As known on ' + day(a[1]), hint: 'set the workspace date', fn: function () { var o = readURL(); o.cik = S.cik; o.as_of = a[1]; apply(Object.assign({}, S, { as_of: a[1] }), true); } });
      if (/^latest|as of latest/.test(ql) && S.as_of) out.push({ label: 'Latest data', hint: 'clear the workspace date', fn: function () { apply(Object.assign({}, S, { as_of: null }), true); } });
      if (S.d) {
        TABS.forEach(function (t) { var n = t === 'facts' ? 'observations' : t; if (q && n.indexOf(ql) === 0) out.push({ label: 'Go to ' + n.charAt(0).toUpperCase() + n.slice(1), hint: 'tab', fn: function () { go(t); } }); });
        var rows = statementRows(); Object.keys(YEARLY).concat(Object.keys(rows)).forEach(function (m) { var lab = YEARLY[m] || rows[m].label; if (q.length > 1 && lab.toLowerCase().indexOf(ql) > -1 && !out.some(function (o) { return o.m === m; })) out.push({ m: m, label: 'Chart ' + lab, hint: 'metric', fn: function () { S.m = S.m.indexOf(m) > -1 ? S.m : [m].concat(S.m).slice(0, 3); go('chart'); } }); });
      }
      return out.slice(0, 6);
    }
    function search(q) {
      items = local(q); sel = 0; render();
      clearTimeout(timer); if (q.trim().length < 1 || /^\d{4}-/.test(q)) return;
      timer = setTimeout(function () {
        var path = (X.hasKey() ? '/v1/companies/search?limit=8&q=' : '/v1/public/companies/search?q=') + encodeURIComponent(q.trim());
        X.raw(path).then(function (r) {
          if (!r.ok || input.value !== q) return;
          var cos = (r.body.data || []).filter(function (c) { return X.hasKey() || c.is_public_page !== false; }).slice(0, 8).map(function (c) { return { label: c.display_name || c.legal_name || 'CIK ' + c.cik, hint: [c.ticker, c.exchange, 'CIK ' + parseInt(c.cik, 10)].filter(Boolean).join(' · ') + (c.matched_former_name ? ' · formerly ' + c.matched_former_name : ''), fn: function () { var ck = String(parseInt(c.cik, 10)); if (palMode === 'compare') { if (ck !== S.cik && S.cmp.indexOf(ck) < 0 && S.cmp.length < 4) S.cmp.push(ck); go('compare'); return; } apply(Object.assign({}, S, { cik: ck, tab: 'overview', as_of: S.as_of }), true); } }; });
          if (!X.hasKey() && !cos.length && /\S/.test(q)) cos.push({ label: 'Connect a key to search every company', hint: 'without a key the Explorer opens the showcase', fn: function () { var k = $('key-input'); if (k) k.focus(); } });
          items = cos.concat(local(q)); sel = 0; render();
        });
      }, 140);
    }
    function run() { var it = items[sel]; if (!it) return; closePal(); it.fn(); }
    input.addEventListener('input', function () { search(input.value); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel = Math.min(items.length - 1, sel + 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
      else if (e.key === 'Enter') { run(); e.preventDefault(); }
      else if (e.key === 'Escape') { closePal(); }
    });
    search('');
  }
  function closePal() { if (pal) { pal.remove(); pal = null; var b = $('ws-k'); if (b) b.focus(); } }
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); palette(); }
    else if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '') && !pal) { e.preventDefault(); palette(); }
  });

  /* ---- wiring ---- */
  function init() {
    var k = $('ws-k'); if (k) k.addEventListener('click', palette);
    document.querySelectorAll('#ws-tabs .tab').forEach(function (b) { b.addEventListener('click', function () { go(b.getAttribute('data-tab')); }); });
    var asof = $('ws-asof'), clear = $('ws-asof-clear'), btn = $('ws-asof-btn'), pop = $('ws-asof-pop');
    if (asof) {
      asof.max = new Date().toISOString().slice(0, 10);
      btn.addEventListener('click', function () { pop.hidden = !pop.hidden; btn.setAttribute('aria-expanded', String(!pop.hidden)); if (!pop.hidden) asof.focus(); });
      $('ws-asof-go').addEventListener('click', function () { var v = asof.value; pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); if (S.cik && /^\d{4}-\d{2}-\d{2}$/.test(v)) apply(Object.assign({}, S, { as_of: v, asofNote: '' }), true); });
      clear.addEventListener('click', function () { asof.value = ''; pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); if (S.cik) apply(Object.assign({}, S, { as_of: null, asofNote: '' }), true); });
      document.addEventListener('click', function (e) { if (!pop.hidden && !e.target.closest('.ws-asof')) { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); } });
    }
    var o = readURL(); if (asof && o.as_of) asof.value = o.as_of;
    apply(o, false);
  }
  window.Workspace = { landing: function () { if (!S.cik) landing(); }, orgName: function (n) { return orgName(n); }, open: function (cik) { apply(Object.assign({}, S, { cik: String(parseInt(cik, 10)), tab: 'overview' }), true); }, palette: palette, state: S, reload: function () { if (S.cik) { S.cik = null; apply(readURL(), false); } } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
