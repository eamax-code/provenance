/* Fails to deliver (Q-06, docs/contracts/fails-to-deliver.md), the Explorer's Ownership tab, loaded only when the tab
   draws it. The balance of shares still outstanding after failing to settle, per settlement date, as the SEC
   publishes it: a running balance, never "new fails", never a measure of short selling. One sub-table per symbol and
   class, never summed across them; one series of bars in the neutral --data-hi; the price as filed; the value derived;
   the SEC file named as text (it is not an EDGAR Archives document, so it has no link). Text nodes only. */
(function () {
  'use strict';
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function sv(tag, attrs, kids) { var n = document.createElementNS(NS, tag); Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); }); (kids || []).forEach(function (c) { n.appendChild(c); }); return n; }
  if (!document.getElementById('ftd-css')) { var st = document.createElement('style'); st.id = 'ftd-css'; st.textContent = '#pane-ownership #ftd{grid-column:1/-1}#ftd .ftd-cap{margin:0 0 6px;font-size:.8rem;color:var(--soft)}#ftd .ftd-lede{margin:0;max-width:80ch;color:var(--soft);font-size:.9rem}#ftd .ftd-sum{margin:6px 0 0}#ftd .ftd-disc{margin:0;font-weight:600}#ftd .ftd-h4{margin:14px 0 2px;font-size:.95rem}#ftd .ftd-h4 span{color:var(--soft);font-weight:400}#ftd .ftd-chart{display:block;width:100%;max-width:760px;height:110px;margin:8px 0 2px}#ftd .ftd-bar{fill:var(--data-hi)}#ftd .ftd-ax{font:11px var(--face);fill:var(--soft)}#ftd .ftd-base{stroke:var(--line)}#ftd table{border-collapse:collapse;font-size:.9rem;font-variant-numeric:tabular-nums}#ftd th,#ftd td{padding:6px 12px 6px 0;border-bottom:1px solid var(--line-soft);text-align:left;white-space:nowrap}#ftd thead th{font-size:.78rem;color:var(--soft);font-weight:600}#ftd .n{text-align:right}#ftd .der{font-style:italic}#ftd th span[title]{text-decoration:underline dotted;cursor:help}#ftd .ftd-note{margin:6px 0 0;font-size:.85rem;color:var(--soft);max-width:90ch}@media (max-width:600px){#ftd .ftd-src{display:none}#ftd table{min-width:0}#ftd th,#ftd td{padding:5px 8px 5px 0;white-space:normal}}'; document.head.appendChild(st); }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var dmy = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; };
  var int = function (v) { return v == null ? '—' : Math.round(v).toLocaleString('en-US'); };
  var usd = function (v, d) { if (v == null) return '—'; var a = Math.abs(v); return a >= 1e9 ? '$' + (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? '$' + (v / 1e6).toFixed(1) + 'M' : '$' + v.toLocaleString('en-US', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); };
  var day = function (iso) { return Date.parse(iso) / 864e5; };
  var QTY = 'The balance of shares that had failed to settle and were still outstanding on that settlement date, across all clearing members (NSCC), as the SEC publishes it. It is a running balance, not the day’s new fails, and it does not show how old the fails are.';
  var RANGES = [['3m', '3 months', 91], ['6m', '6 months', 182], ['1y', '1 year', 365]];

  function load(cik, o) {
    o = o || {};
    var q = '/v1/companies/' + parseInt(cik, 10) + '/fails-to-deliver' + (o.since ? '?since=' + o.since : '') + (o.asOf ? (o.since ? '&' : '?') + 'as_of=' + o.asOf : '');
    return fetch(q, { headers: { Accept: 'application/json', 'X-API-Key': key() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); })
      .catch(function () { return { ok: false, status: 0, b: {} }; });
  }

  // one series of bars over the range: a bar per settlement date with a balance; a date with no row stays empty
  function chart(rows, from, to) {
    var W = 760, H = 120, L = 0, B = 2, max = Math.max.apply(null, rows.map(function (r) { return r.quantity || 0; }).concat([1])), span = Math.max(1, to - from), bw = Math.max(2, Math.min(10, (W - L) / (span * 5 / 7) - 1));
    var x = function (d) { return L + (W - L - bw) * (day(d) - from) / span; }, y = function (v) { return (H - B) * (1 - v / max); };
    var bars = rows.map(function (r) {
      var t = sv('title', {}); t.textContent = dmy(r.settlement_date) + ': ' + int(r.quantity) + ' shares outstanding' + (r.price != null ? ' · price ' + usd(r.price, 2) + ' as filed' : '') + ' · ' + ((r.source || {}).file || '');
      return sv('rect', { class: 'ftd-bar', x: x(r.settlement_date).toFixed(1), y: y(r.quantity).toFixed(1), width: bw.toFixed(1), height: Math.max(1, H - B - y(r.quantity)).toFixed(1), rx: 1 }, [t]);
    });
    var fd = new Date(from * 864e5).toISOString().slice(0, 10), td = new Date(to * 864e5).toISOString().slice(0, 10);
    // the labels are HTML under the bars, so they stay readable at any width
    return [sv('svg', { class: 'ftd-chart', viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Shares outstanding after failing to settle, by settlement date, ' + dmy(fd) + ' to ' + dmy(td) + '; the table below lists each value' }, [sv('line', { class: 'ftd-base', x1: 0, x2: W, y1: H - B, y2: H - B })].concat(bars)),
      el('p', { class: 'ftd-cap', text: dmy(fd) + ' to ' + dmy(td) + ' · tallest bar ' + int(max) + ' shares' })];
  }

  function table(rows) {
    var th = function (t, n, tip) { return el('th', { scope: 'col', class: n ? 'n' : null }, [tip ? el('span', { title: tip, text: t }) : t]); };
    var body = rows.slice().reverse().map(function (r, i) {
      var v = r.value || {};
      return el('tr', { hidden: i >= 10 ? 'hidden' : null }, [el('td', { text: dmy(r.settlement_date) }), el('td', { class: 'n', text: int(r.quantity) }),
        el('td', { class: 'n', title: r.price == null ? 'Not available or under a penny in the SEC file' : null, text: r.price == null ? '—' : usd(r.price, 2) }),
        el('td', { class: 'n der', title: v.value == null ? 'Not worked out: no price in the SEC file' : 'Derived: shares outstanding × the price in the SEC file (the previous day’s close as filed, not licensed market data)', text: usd(v.value) }),
        el('td', { class: 'ftd-src', text: 'SEC fails-to-deliver file ' + String((r.source || {}).file || '').replace(/\.zip$/, '') })]);
    });
    var t = el('table', {}, [el('caption', { class: 'vh', text: 'Shares outstanding after failing to settle, newest first' }),
      el('thead', {}, [el('tr', {}, [th('Settlement date'), th('Shares outstanding', 1, QTY), th('Price as filed', 1, 'The previous day’s close, as the SEC file gives it'), th('Value', 1, 'Derived: shares × price as filed'), el('th', { scope: 'col', class: 'ftd-src' }, ['Source'])])]), el('tbody', {}, body)]);
    var out = [el('div', { class: 'tw' }, [t])];
    // a missing price is said once under the table, with its entry, rather than on a dash too small to tap
    if (rows.some(function (r) { return r.price == null; })) out.push(el('p', { class: 'ftd-note' }, ['— in Price: no price in the SEC file, or one under a penny; the dash is not a zero. ', el('a', { href: '/docs/flags/#ftd-price', text: 'What this means' })]));
    if (body.length > 10) { var b = el('button', { type: 'button', class: 'linkish', text: 'Show all ' + body.length + ' dates' }); b.addEventListener('click', function () { body.forEach(function (tr) { tr.hidden = false; }); b.remove(); }); out.push(b); }
    return out;
  }

  // block(host, response, {head, range, onRange(range)})
  function block(host, r, o) {
    o = o || {}; host.hidden = false;
    if (r.status === 404) { host.hidden = true; return; } // the endpoint is not on this server yet, or no such company
    var b = r.b || {}, kids = [o.head, el('p', { class: 'ftd-lede' }, ['The balance of shares that had failed to settle and were still outstanding on each settlement date, across all clearing members, as the SEC publishes it. It is a running balance, not the day’s new fails; a fail has many causes and it is not a measure of short selling. ', el('a', { href: '/docs/flags/#ftd-balance', text: 'What this means' })]), el('p', { class: 'ftd-disc', text: 'Information, not signals. Not investment advice.' })];
    if (!r.ok) { kids.push(el('p', { class: 'muted', text: r.status === 403 ? 'Fails to deliver for this company need a free key (the demo key covers the showcase companies).' : r.status === 429 ? 'Too many requests this minute; this will load on the next view.' : 'Fails to deliver are unavailable right now.' })); host.replaceChildren.apply(host, kids); return; }
    var seg = el('div', { class: 'seg-btns', role: 'group', 'aria-label': 'Settlement dates shown' }, RANGES.map(function (x) { var bt = el('button', { type: 'button', 'aria-pressed': String(x[0] === o.range), text: x[1] }); bt.addEventListener('click', function () { if (o.onRange && x[0] !== o.range) o.onRange(x[0]); }); return bt; }));
    kids.push(seg);
    var groups = (b.data || []).filter(function (g) { return (g.rows || []).length; }), all = [].concat.apply([], groups.map(function (g) { return g.rows; }));
    // notes this section already says (the disclaimer, the quantity and price labels, missing dates) are not repeated
    var notes = (b.notes || []).filter(function (n) { return !/^(Information, not signals|quantity:|price:|A date with no row)/.test(n); }), nocusip = notes.filter(function (n) { return /CUSIP/.test(n); })[0];
    var last = all.map(function (x) { return x.settlement_date; }).sort().pop(), span = (RANGES.filter(function (x) { return x[0] === o.range; })[0] || RANGES[0])[2];
    // a company whose shares are not matched is coverage, never a zero balance
    if (!groups.length) kids.push(el('p', { class: 'muted', text: nocusip || 'No fails balance in the SEC’s files for these dates.' }));
    groups.forEach(function (g) {
      var to = day(last), from = to - span, rows = g.rows.filter(function (x) { return day(x.settlement_date) >= from; }).sort(function (a, c) { return a.settlement_date < c.settlement_date ? -1 : 1; });
      if (groups.length > 1) kids.push(el('h4', { class: 'ftd-h4' }, [g.symbol || g.description || 'Class', g.class_label ? el('span', { text: ' · ' + g.class_label }) : null]));
      if (!rows.length) { kids.push(el('p', { class: 'muted', text: 'No fails balance on any settlement date shown.' })); return; }
      var big = rows.reduce(function (m, x) { return x.quantity > m.quantity ? x : m; }), lt = rows[rows.length - 1];
      kids.push(el('p', { class: 'ftd-sum' }, [el('b', { text: 'Latest: ' + int(lt.quantity) + ' shares outstanding on ' + dmy(lt.settlement_date) }), ' · a balance on ' + rows.length + ' settlement date' + (rows.length === 1 ? '' : 's') + ' shown · largest ' + int(big.quantity) + ' on ' + dmy(big.settlement_date)]));
      kids.push.apply(kids, chart(rows, from, to)); kids.push.apply(kids, table(rows));
    });
    var cv = b.coverage || {}, m = /^(\d{4})-(\d{2})/.exec(cv.from || '');
    kids.push(el('p', { class: 'ftd-note', text: 'A date with no row had no fails balance, or its file is not yet published. From the SEC’s fails-to-deliver files, ' + (m ? MONTHS[+m[2] - 1] + ' ' + m[1] : 'July 2009') + ' to ' + (dmy(cv.through) || 'the latest') + (cv.latest_file ? '; the latest is ' + cv.latest_file.replace(/\.zip$/, '') : '') + '. The SEC publishes them twice a month, about two weeks after each half-month ends.' + (o.asOf ? ' As published by ' + dmy(o.asOf) + '.' : '') }));
    notes = notes.filter(function (n) { return n !== nocusip || groups.length; });
    if (notes.length) kids.push(el('p', { class: 'ftd-note', text: notes.join(' ') }));
    host.replaceChildren.apply(host, kids.filter(Boolean));
  }
  window.prvFtd = { load: load, block: block };
})();
