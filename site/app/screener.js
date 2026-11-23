/* Explorer screener (plan-explorer-chat X-08): rank every company by one reported metric for a
   calendar year (/v1/facts/screen), add columns, filter, sort, export, and open any row in the
   workspace. The whole screen lives in the URL (#screener with ?sm, sy, so, sc, sf, sx). Margins
   are worked out here only when both figures come from the same filing. */
(function () {
  'use strict';
  var X = window.ProvenanceExplorer, $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var M = { revenue: 'Revenue', gross_profit: 'Gross profit', operating_income: 'Operating income', net_income: 'Net income', eps_diluted: 'EPS, diluted', operating_cash_flow: 'Operating cash flow', capex: 'Capital expenditure', total_assets: 'Total assets', total_liabilities: 'Total liabilities', stockholders_equity: 'Stockholders’ equity', cash_and_equivalents: 'Cash and equivalents', long_term_debt: 'Long-term debt', r_and_d: 'Research and development', sga: 'SG&A', dividends_paid: 'Dividends paid', share_repurchases: 'Share repurchases', sbc: 'Stock-based compensation', shares_outstanding: 'Shares outstanding', public_float: 'Public float' };
  // derived here from two reported columns of the same filing
  var D = { gross_margin: ['Gross margin', 'gross_profit', 'revenue'], operating_margin: ['Operating margin', 'operating_income', 'revenue'], net_margin: ['Net margin', 'net_income', 'revenue'] };
  var thisYear = new Date().getFullYear();
  var S = { sm: 'revenue', sy: thisYear - 1, so: 'desc', sc: ['operating_income', 'operating_margin', 'net_income'], sf: [], sx: '' };

  function money(v, unit) {
    if (v == null) return '—';
    if (unit === '%') return (v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%';
    if (/shares$/.test(unit || '') && !/\//.test(unit)) { var a0 = Math.abs(v); return a0 >= 1e9 ? (v / 1e9).toFixed(2) + 'B' : a0 >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : Math.round(v).toLocaleString('en-US'); }
    var per = /\/shares$/.test(unit || ''), cur = (unit || 'USD').split('/')[0], p = (v < 0 ? '−' : '') + (cur === 'USD' ? '$' : cur + ' '), a = Math.abs(v);
    if (per) return p + a.toFixed(2);
    return a >= 1e12 ? p + (a / 1e12).toFixed(1) + 'T' : a >= 1e9 ? p + (a / 1e9).toFixed(1) + 'B' : a >= 1e6 ? p + (a / 1e6).toFixed(1) + 'M' : p + Math.round(a).toLocaleString('en-US');
  }
  // "1B", "250m", "20%", "-5" → a number in the metric's own units (percent for margins)
  function parseVal(t) { var m = /^\s*(-?[\d.]+)\s*([kmbt%]?)\s*$/i.exec(t || ''); if (!m) return null; var n = parseFloat(m[1]), u = m[2].toLowerCase(); return n * ({ k: 1e3, m: 1e6, b: 1e9, t: 1e12 }[u] || 1); }
  function label(m) { return M[m] || (D[m] && D[m][0]) || m; }

  /* ---- the URL ---- */
  function read() {
    var q = new URLSearchParams(location.search);
    if (M[q.get('sm')]) S.sm = q.get('sm');
    var y = parseInt(q.get('sy'), 10); if (y >= 2009 && y <= thisYear) S.sy = y;
    S.so = q.get('so') === 'asc' ? 'asc' : 'desc';
    if (q.get('sc') != null) S.sc = q.get('sc').split(',').filter(function (c) { return (M[c] || D[c]) && c !== S.sm; }).slice(0, 5);
    S.sf = (q.get('sf') || '').split(';').map(function (f) { var m = /^([a-z_]+)(>=|<=)(-?[\d.e+]+)$/.exec(f); return m && (M[m[1]] || D[m[1]]) ? { m: m[1], op: m[2], v: parseFloat(m[3]) } : null; }).filter(Boolean).slice(0, 6);
    S.sx = /^[A-Za-z ]{0,20}$/.test(q.get('sx') || '') ? (q.get('sx') || '') : '';
  }
  function write() {
    var q = new URLSearchParams();
    q.set('sm', S.sm); q.set('sy', String(S.sy)); if (S.so === 'asc') q.set('so', 'asc');
    q.set('sc', S.sc.join(','));
    if (S.sf.length) q.set('sf', S.sf.map(function (f) { return f.m + f.op + f.v; }).join(';'));
    if (S.sx) q.set('sx', S.sx);
    try { history.replaceState(null, '', location.pathname + '?' + q.toString() + '#screener'); } catch (e) {}
  }

  /* ---- data: the ranked metric, then each column for the same calendar year ---- */
  var cache = {}, seq = 0;
  function screen(metric, order, limit) {
    var k = [metric, S.sy, order, limit, X.hasKey() ? 'k' : 'd'].join('|');
    if (!cache[k]) cache[k] = X.raw('/v1/facts/screen?metric=' + metric + '&year=' + S.sy + '&period=annual&order=' + order + '&limit=' + limit, X.hasKey() ? null : 'demo').then(function (r) { return r.ok ? r.body : { error: r.status, body: r.body }; });
    return cache[k];
  }
  function load() {
    var my = ++seq, keyed = X.hasKey(), lim = keyed ? 200 : 10;
    $('scr-out').replaceChildren(el('p', { class: 'muted', text: 'Ranking every company that filed ' + label(S.sm).toLowerCase() + ' for ' + S.sy + '…' }));
    var need = []; S.sc.concat(S.sf.map(function (f) { return f.m; })).forEach(function (c) { (D[c] ? [D[c][1], D[c][2]] : [c]).forEach(function (m) { if (m !== S.sm && need.indexOf(m) < 0) need.push(m); }); });
    Promise.all([screen(S.sm, S.so, lim)].concat(need.map(function (m) { return screen(m, 'desc', lim); }))).then(function (res) {
      if (my !== seq) return;
      var main = res[0];
      if (!main || main.error) {
        var dm = !X.hasKey() && main && main.body && main.body.error ? main.body.error.message || '' : '', demoOut = /demo key daily limit/i.test(dm), demoBusy = /demo key is busy/i.test(dm);
        $('scr-out').replaceChildren(el('p', { class: 'muted' }, demoBusy ? ['Without a key the screener runs on the shared demo key, which is busy right now. Try again in a minute, or ', el('a', { href: '/account/', text: 'connect a free key' }), '.'] : demoOut ? ['Without a key the screener runs on the shared demo key, which has reached today\u2019s limit. ', el('a', { href: '/account/', text: 'Connect a free key' }), ' to rank every company.'] : [main && main.error === 429 ? 'Too many requests just now. Try again in a minute.' : 'The screen is unavailable right now.']));
        return;
      }
      var by = {}; need.forEach(function (m, i) { var b = res[i + 1]; by[m] = {}; ((b && b.data) || []).forEach(function (r) { by[m][r.cik] = r; }); });
      var rows = (main.data || []).map(function (r) {
        var cells = {}; cells[S.sm] = r;
        need.forEach(function (m) { cells[m] = by[m][r.cik] || null; });
        Object.keys(D).forEach(function (d) { var a = cells[D[d][1]] || (D[d][1] === S.sm ? r : null), b = cells[D[d][2]] || (D[d][2] === S.sm ? r : null); cells[d] = a && b && b.value > 0 && a.accession_number === b.accession_number && a.unit === b.unit ? { value: 100 * a.value / b.value, unit: '%', derived: true, accession_number: a.accession_number, source_url: a.source_url, form_type: a.form_type, filed_date: a.filed_date, period_end: a.period_end } : null; });
        return { r: r, cells: cells };
      });
      var shown = rows.filter(function (x) {
        if (S.sx && (x.r.exchange || '').toLowerCase() !== S.sx.toLowerCase()) return false;
        return S.sf.every(function (f) { var c = x.cells[f.m]; if (!c || c.value == null) return false; var v = c.unit === '%' ? c.value : c.value; return f.op === '>=' ? v >= f.v : v <= f.v; });
      });
      render(main, rows, shown, keyed, lim);
    });
  }

  /* ---- the screen ---- */
  function render(main, rows, shown, keyed, lim) {
    // lim: how many rows each column's ranking returns
    var cols = [S.sm].concat(S.sc);
    var head = el('tr', {}, [el('th', { scope: 'col', class: 'n', text: '#' }), el('th', { scope: 'col', text: 'Company' }), el('th', { scope: 'col', text: 'Exchange' })].concat(cols.map(function (c, i) {
      return el('th', { scope: 'col', class: 'n' }, [label(c), D[c] ? el('span', { class: 'tag', title: D[c][0] + ' = ' + label(D[c][1]).toLowerCase() + ' ÷ ' + label(D[c][2]).toLowerCase() + ', same filing', text: 'derived' }) : null, i === 0 ? el('span', { class: 'muted', text: S.so === 'desc' ? ' ↓' : ' ↑' }) : null]);
    })).concat([el('th', { scope: 'col', text: 'Filing' })]));
    var body = shown.map(function (x, i) {
      var r = x.r, name = window.Workspace && window.Workspace.orgName ? window.Workspace.orgName(r.display_name || r.legal_name) : r.display_name || r.legal_name, cik = String(parseInt(r.cik, 10));
      return el('tr', {}, [el('td', { class: 'n muted', text: String(i + 1) }),
        el('th', { scope: 'row' }, [el('a', { href: '/app/?c=' + cik, text: name, on: { click: function (e) { if (window.Workspace && !e.metaKey && !e.ctrlKey) { e.preventDefault(); window.ProvenanceExplorer.showExplore(); window.Workspace.open(cik); } } } })]),
        el('td', { class: 'muted', text: [r.ticker, r.exchange].filter(Boolean).join(' · ') })].concat(cols.map(function (c) {
          var v = x.cells[c];
          if (!v || v.value == null) return el('td', { class: 'n muted', title: D[c] ? 'Needs both figures from the same filing' : 'Not among the top ' + lim + ' companies ranked by ' + label(c).toLowerCase() + '; open the company for its figure', text: '—' });
          var info = { label: label(c), metric: D[c] ? null : c, currency: (v.unit || '').split('/')[0], fiscal_label: v.fiscal_year ? 'FY' + v.fiscal_year : null, period_end: v.period_end, form_type: v.form_type, filed_date: v.filed_date, source_url: v.source_url, accession_number: v.accession_number, source_tag: v.source_tag, mapping_version: v.mapping_version, quality_status: v.quality_status, derived: v.derived, formula: D[c] ? label(D[c][1]).toLowerCase() + ' ÷ ' + label(D[c][2]).toLowerCase() : null };
          return el('td', { class: 'n' }, [window.ProvCard ? window.ProvCard.door(money(v.value, v.unit), info) : money(v.value, v.unit)]);
        })).concat([el('td', {}, [ARCHIVE.test(r.source_url || '') ? el('a', { href: r.source_url, target: '_blank', rel: 'noopener', text: (r.form_type || '') + ' ↗' }) : null])]));
    });
    var m = main.meta || {};
    var gaps = shown.some(function (x) { return S.sc.some(function (c) { return !D[c] && !x.cells[c]; }); });
    var note = 'Showing ' + shown.length + ' of the top ' + rows.length + (m.total_matched ? ' among ' + Number(m.total_matched).toLocaleString('en-US') + ' companies' : '') + ' with ' + label(S.sm).toLowerCase() + ' for calendar ' + S.sy + ', ranked by the API. Columns and filters apply to those rows' + (keyed ? '' : '; the demo key ranks the top ten, a free key the top ' + 200) + '. Currencies are as filed and never converted.' + (gaps ? ' A "—" in a column means the company isn\u2019t in that column\u2019s top ' + lim + ', not that it reported nothing.' : '');
    $('scr-out').replaceChildren.apply($('scr-out'), [el('p', { class: 'muted small', text: note }),
      el('div', { class: 'tw st-wrap' }, [el('table', { class: 'st-table scr-table' }, [el('thead', {}, [head]), el('tbody', {}, body)])]),
      shown.length ? null : el('p', { class: 'muted', text: 'No company in these rows passes every filter.' })].filter(Boolean));
    $('scr-csv').onclick = function () {
      var lines = [['rank', 'cik', 'company', 'ticker', 'exchange'].concat(cols).join(',')].concat(shown.map(function (x, i) { return [i + 1, x.r.cik, '"' + String(x.r.display_name || x.r.legal_name).replace(/"/g, '""') + '"', x.r.ticker || '', x.r.exchange || ''].concat(cols.map(function (c) { var v = x.cells[c]; return v && v.value != null ? v.value : ''; })).join(','); }));
      var a = el('a', { href: URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' })), download: 'screen-' + S.sm + '-' + S.sy + '.csv' }); document.body.appendChild(a); a.click(); a.remove();
    };
  }

  function controls() {
    var opts = function (sel, list, cur) { list.forEach(function (k) { var o = el('option', { value: k, text: label(k) }); if (k === cur) o.selected = true; sel.appendChild(o); }); return sel; };
    var sm = opts(el('select', { id: 'scr-sm', on: { change: function (e) { S.sm = e.target.value; S.sc = S.sc.filter(function (c) { return c !== S.sm; }); go(); } } }), Object.keys(M), S.sm);
    var sy = el('select', { id: 'scr-sy', on: { change: function (e) { S.sy = parseInt(e.target.value, 10); go(); } } }); for (var y = thisYear; y >= 2009; y--) { var o = el('option', { value: String(y), text: String(y) }); if (y === S.sy) o.selected = true; sy.appendChild(o); }
    var so = el('div', { class: 'seg-btns', role: 'group', 'aria-label': 'Order' }, [['desc', 'Largest first'], ['asc', 'Smallest first']].map(function (v) { return el('button', { type: 'button', 'aria-pressed': String(S.so === v[0]), text: v[1], on: { click: function () { S.so = v[0]; go(); } } }); }));
    var colChips = el('span', { class: 'ch-series' }, S.sc.map(function (c, i) { return el('span', { class: 'chip' }, [label(c), el('button', { type: 'button', class: 'x', 'aria-label': 'Remove column ' + label(c), text: '×', on: { click: function () { S.sc.splice(i, 1); go(); } } })]); }));
    var addCol = opts(el('select', { 'aria-label': 'Add a column', on: { change: function (e) { if (e.target.value) { S.sc.push(e.target.value); go(); } } } }, [el('option', { value: '', text: S.sc.length < 5 ? '+ Column' : 'Five columns at most' })]), Object.keys(M).concat(Object.keys(D)).filter(function (c) { return c !== S.sm && S.sc.indexOf(c) < 0; }), null);
    if (S.sc.length >= 5) addCol.disabled = true;
    var fChips = el('span', { class: 'ch-series' }, S.sf.map(function (f, i) { return el('span', { class: 'chip' }, [label(f.m) + ' ' + (f.op === '>=' ? '≥' : '≤') + ' ' + money(f.v, D[f.m] ? '%' : (f.m === 'eps_diluted' ? 'USD/shares' : f.m === 'shares_outstanding' ? 'shares' : 'USD')), el('button', { type: 'button', class: 'x', 'aria-label': 'Remove filter', text: '×', on: { click: function () { S.sf.splice(i, 1); go(); } } })]); }));
    var fm = opts(el('select', { 'aria-label': 'Filter metric' }), [S.sm].concat(S.sc).concat(Object.keys(D).filter(function (d) { return S.sc.indexOf(d) < 0; })), S.sm);
    var fo = el('select', { 'aria-label': 'Comparison' }, [el('option', { value: '>=', text: '≥' }), el('option', { value: '<=', text: '≤' })]);
    var fv = el('input', { type: 'text', size: '7', placeholder: '1B or 20%', 'aria-label': 'Value, e.g. 1B or 20%' });
    var fadd = el('button', { type: 'button', class: 'btn small', text: 'Add filter', on: { click: function () { var v = parseVal(fv.value); if (v == null || S.sf.length >= 6) { fv.focus(); return; } S.sf.push({ m: fm.value, op: fo.value, v: v }); if (D[fm.value] && S.sc.indexOf(fm.value) < 0 && S.sc.length < 5) S.sc.push(fm.value); go(); } } });
    var sx = el('select', { 'aria-label': 'Exchange', on: { change: function (e) { S.sx = e.target.value; go(); } } }, ['', 'Nasdaq', 'NYSE', 'NYSE American', 'Cboe BZX', 'OTC'].map(function (x) { var o = el('option', { value: x, text: x || 'Any exchange' }); if (x === S.sx) o.selected = true; return o; }));
    var copy = el('button', { type: 'button', class: 'btn small', text: 'Copy link', on: { click: function () { try { navigator.clipboard.writeText(location.href); copy.textContent = 'Copied'; } catch (e) {} } } });
    return el('div', { class: 'scr-ctl' }, [
      el('div', { class: 'ch-bar' }, [el('label', { class: 'scr-l' }, ['Rank by ', sm]), el('label', { class: 'scr-l' }, ['Calendar year ', sy]), so, sx, el('span', { class: 'ch-acts' }, [copy, el('button', { type: 'button', class: 'btn small', id: 'scr-csv', text: 'CSV' })])]),
      el('div', { class: 'ch-bar' }, [el('span', { class: 'muted small', text: 'Columns' }), colChips, addCol]),
      el('div', { class: 'ch-bar' }, [el('span', { class: 'muted small', text: 'Filters' }), fChips, fm, fo, fv, fadd])]);
  }
  function go() { write(); $('scr-ctl').replaceChildren(controls()); load(); }
  window.ProvenanceScreener = { load: function () { var sv = new URLSearchParams(location.search); read(); go(); if (window.ProvenanceRaises) window.ProvenanceRaises.mode(sv); } };
  // opened straight from a link (#screener) before this file loaded
  if (!$('screener').hidden) window.ProvenanceScreener.load();
})();
