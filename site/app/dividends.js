/* Dividends (Q-04, docs/contracts/dividends.md), shared by the Explorer and the company page, loaded only when shown.
   block(): per share by period under the income statement, aligned to its columns, as reported or split-adjusted,
   its basis named, with the payout ratio (annual, derived) and the cash paid; line(): one sentence for the overview.
   The company's own currency, never converted; each value opens its filing on sec.gov/Archives. A large quarter is
   flagged as possibly special, never called special. No yield. */
(function () {
  'use strict';
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//, cache = {};
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  if (!document.getElementById('dv-css')) { var st = document.createElement('style'); st.id = 'dv-css'; st.textContent = '.dv-h{margin:22px 0 4px;font-size:1.05rem}.dv-table{width:100%;border-collapse:collapse;font-size:.9rem;font-variant-numeric:tabular-nums}.dv-table th,.dv-table td{padding:6px 8px;border-bottom:1px solid var(--line-soft);white-space:nowrap}.dv-table thead th{font-size:.78rem;color:var(--soft);font-weight:600;text-align:right}.dv-table th[scope=row],.dv-table thead th:first-child{text-align:left;font-weight:600;position:sticky;left:0;z-index:1;background:var(--bg)}.dv-table .n{text-align:right}.dv-table td.pre{background:color-mix(in srgb,var(--warn) 8%,transparent)}.dv-der{font-style:italic}.dv-v{color:var(--ink);text-decoration-line:underline;text-decoration-color:var(--link-line)}.dv-table th span[title]{text-decoration:underline dotted;cursor:help}.dv-flags{margin:6px 0;padding-left:18px;font-size:.85rem}.dv-flag{display:inline-block;padding:0 6px;border:1px solid var(--line);border-radius:4px;background:var(--surface-2);font-size:.78rem;font-weight:600;cursor:help}.ov-div,.co-div{margin:10px 0 0;font-size:.92rem}'; document.head.appendChild(st); }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var cur = function (unit) { return String(unit || 'USD').split('/')[0]; };
  // a per-share amount in its own currency: $0.27, JPY 45.00; never converted
  var dps = function (v, unit) { if (v == null) return '—'; var c = cur(unit), s = Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 }); return c === 'USD' ? '$' + s : c + ' ' + s; };
  var total = function (v, unit) { if (v == null) return '—'; var c = cur(unit), a = Math.abs(v), s = a >= 1e9 ? (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : Math.round(v).toLocaleString('en-US'); return c === 'USD' ? '$' + s : c + ' ' + s; };
  var cite = function (text, f, title, cls) { return f && ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', class: cls, title: title || ((f.form || 'Filing') + ' filed ' + (f.filed_date || '')), text: text }) : el('span', { class: cls, title: title, text: text }); };

  function load(cik, o) {
    o = o || {};
    var url = '/v1/companies/' + parseInt(cik, 10) + '/dividends?period=' + (o.period || 'annual') + '&periods=' + (o.period === 'quarterly' ? 20 : 12) + (o.asOf ? '&as_of=' + o.asOf : '');
    return cache[url] || (cache[url] = fetch(url, { headers: { Accept: 'application/json', 'X-API-Key': key() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); })
      .catch(function () { delete cache[url]; return { ok: false, status: 0, b: {} }; }));
  }
  var empty = 'No dividends declared in the filings we hold.';
  // each row's basis (Q-04c): declared, cash paid, recognised in the period (IFRS), distributions per unit
  var basis = function (d) { return d.basis || d.basis_tag || 'declared'; };
  var unitRow = function (b) { return /per unit/.test(b); };
  var payable = function (b) { return b === 'declared' || /^recognised/.test(b); }; // payout is given only on these
  var NOPAY = 'Payout is shown for declared or recognised dividends only';
  // the row label names the basis when every row shares one other than declared
  function label(data) {
    var bs = data.map(basis).filter(function (b, i, a) { return a.indexOf(b) === i; }), b = bs.length === 1 ? bs[0] : '';
    return b === 'declared' ? 'Declared per share' : unitRow(b) ? 'Distributions per unit' : b === 'cash paid' ? 'Dividends per share (cash paid)' : /^recognised/.test(b) ? 'Dividends per share (recognised in the period, IFRS)' : 'Dividends per share';
  }

  // block(host, response, {cols: [period labels in display order], basis: 'as_reported' | 'split_adjusted', period})
  function block(host, r, o) {
    o = o || {}; var adj = o.basis === 'split_adjusted', q = o.period === 'quarterly';
    var head = el('h3', { class: 'dv-h', text: 'Dividends' });
    // 404: the endpoint is not on this server yet (or the company is not here): show nothing rather than an error
    if (r.status === 404) { host.hidden = true; return; }
    if (!r.ok) { host.replaceChildren(head, el('p', { class: 'muted small', text: r.status === 403 ? 'Dividends for this company need a free key (the demo key covers the showcase companies).' : r.status === 429 ? 'Too many requests this minute; dividends will load on the next view.' : 'Dividends are unavailable right now.' })); return; }
    var b = r.b || {}, data = b.data || [], by = {};
    if (!data.length) { host.replaceChildren.apply(host, [head, el('p', { class: 'muted', text: empty }), (b.notes || []).length ? el('p', { class: 'muted small', text: b.notes.join(' ') }) : null].filter(Boolean)); return; }
    data.forEach(function (d) { by[d.period_label] = d; });
    var cols = (o.cols && o.cols.length ? o.cols : data.map(function (d) { return d.period_label; })), flags = [];
    var row = function (label, tip, cell) { return el('tr', {}, [el('th', { scope: 'row' }, [tip ? el('span', { title: tip, text: label }) : label])].concat(cols.map(function (c) { var d = by[c]; return d ? cell(d, c) : el('td', { class: 'n muted', title: 'not reported', text: '—' }); }))); };
    var rows = [row(label(data), adj ? 'Split-adjusted: each value put on today’s share basis with the reviewed splits listed below (derived)' : 'As reported: each value on the share basis of the filing it cites', function (d, c) {
      var sa = d.split_adjusted, v = adj ? sa && sa.value : d.declared_per_share, pre = !adj && sa && sa.factor > 1, f = d.filing || {};
      if (d.special && d.special.likely) flags.push(el('li', {}, [c + ': ', el('span', { class: 'dv-flag', title: d.special.basis || '', text: 'Unusually large: possibly special' })]));
      var tip = (d.derived ? 'Derived: the fiscal year less its first three quarters. ' : '') + (adj && sa && sa.factor > 1 ? 'Split-adjusted (derived): ' + dps(d.declared_per_share, d.unit) + ' as reported, divided by ' + sa.factor + '. ' : '') + (basis(d) !== 'declared' ? 'Basis: ' + basis(d) + '. ' : '') + (f.form || 'Filing') + ' filed ' + (f.filed_date || '');
      if (adj && !sa) return el('td', { class: 'n muted', title: 'Not adjusted: the split is dated only to the month around this filing', text: '—' });
      return el('td', { class: 'n' + (pre ? ' pre' : '') + (d.derived || (adj && sa && sa.factor > 1) ? ' dv-der' : '') }, [cite(dps(v, d.unit) + (d.special && d.special.likely ? '*' : ''), d.derived && d.inputs && d.inputs[0] ? d.inputs[0] : f, tip, 'dv-v')]);
    })];
    if (!q) rows.push(row('Payout ratio', 'Derived: declared dividends per share over diluted EPS for the same fiscal year, both as reported', function (d) {
      var p = d.payout_ratio, e = p && (p.inputs || []).filter(function (x) { return x.metric === 'eps_diluted'; })[0];
      if (!payable(basis(d))) return el('td', { class: 'n muted', title: NOPAY, text: '—' });
      return el('td', { class: 'n dv-der', title: p ? (p.basis || 'declared per share / diluted EPS') + (e ? ': diluted EPS ' + dps(e.value, d.unit) : '') : 'Not worked out: diluted EPS in that filing is missing, zero or negative, or in another currency, or dividends are over 10 times earnings' }, [p && p.value != null ? (Math.round(p.value * 1000) / 10).toFixed(1) + '%' : '—']);
    }));
    rows.push(row('Dividends paid', 'The cash-flow line as stored: all classes, and preferred where the company reports one total; it does not reconcile with per share times shares', function (d) {
      var p = d.dividends_paid; return el('td', { class: 'n' }, [p && p.value != null ? cite(total(p.value, p.unit || cur(d.unit)), p, 'Cash flow statement, ' + (p.accession_number || ''), 'dv-v') : '—']);
    }));
    var t = el('table', { class: 'dv-table' }, [el('caption', { class: 'vh', text: 'Dividends per share, ' + (adj ? 'split-adjusted' : 'as reported') }), el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: adj ? 'Split-adjusted' : 'As reported' })].concat(cols.map(function (c) { return el('th', { scope: 'col', class: 'n', text: c }); })))]), el('tbody', {}, rows)]);
    var mixed = label(data) === 'Dividends per share' ? 'The basis differs by period; each value’s tooltip names it.' : null;
    var splits = (b.splits || []).map(function (s) { var src = s.source || {}; return s.ratio + ' split, ' + s.date + (src.form ? ' (' + src.form + ' filed ' + (src.filed_date || '') + ')' : ''); });
    host.replaceChildren.apply(host, [head,
      el('p', { class: 'muted small', text: (adj ? 'Split-adjusted' : 'As reported') + ' · ' + label(data).replace(/^./, function (c) { return c.toLowerCase(); }) + ' in ' + cur((data[0] || {}).unit) + ', never converted · no yield until prices are loaded' }),
      el('div', { class: 'tw' }, [t]),
      flags.length ? el('ul', { class: 'dv-flags', 'aria-label': 'Flags' }, flags) : null,
      mixed ? el('p', { class: 'muted small', text: mixed }) : null,
      splits.length ? el('p', { class: 'muted small', text: 'Reviewed splits: ' + splits.join('; ') + '.' }) : null,
      el('p', { class: 'muted small', text: [(b.labels || {}).basis_note].concat(b.notes || []).filter(Boolean).join(' ') })].filter(Boolean)); // a null child would print "null"
    if (o.labelWidth) t.querySelectorAll('tr > :first-child').forEach(function (c) { c.style.width = c.style.minWidth = o.labelWidth + 'px'; }); // line the periods up under the statement's
    var w = t.parentNode; if (!o.newestFirst) w.scrollLeft = w.scrollWidth;
  }

  // line(host, response): the latest annual amount, its payout ratio and how far back the data shown goes
  function line(host, r) {
    var d = (r.ok && r.b && r.b.data) || []; host.hidden = !r.ok;
    if (!r.ok) return;
    if (!d.length) { host.replaceChildren(el('b', { text: 'Dividends: ' }), empty); return; }
    var last = d[d.length - 1], first = d[0], p = last.payout_ratio;
    var bs = basis(last), rec = /^recognised/.test(bs);
    var parts = [el('b', { text: unitRow(bs) ? 'Distributions: ' : 'Dividends: ' }), cite(dps(last.declared_per_share, last.unit), last.filing, null, 'dv-v'), (unitRow(bs) ? ' per unit in ' : bs === 'cash paid' ? ' per share paid in ' : rec ? ' per share recognised in ' : ' per share declared in ') + last.period_label + (rec ? ' (IFRS)' : '')];
    if (p && p.value != null && payable(bs)) parts.push(el('span', { class: 'dv-der', title: (p.basis || 'declared per share / diluted EPS') + ' (derived)', text: ' · payout ' + (Math.round(p.value * 1000) / 10).toFixed(1) + '% of diluted EPS' }));
    if (last.special && last.special.likely) parts.push(' · ', el('span', { class: 'dv-flag', title: last.special.basis || '', text: 'Unusually large: possibly special' }));
    parts.push(' · since ' + first.period_label);
    host.replaceChildren.apply(host, parts);
  }
  window.prvDividends = { load: load, block: block, line: line };
})();
