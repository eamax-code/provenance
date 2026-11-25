/* The provenance card (plan-explorer-chat §2.2), shared by the Explorer and chat: one figure's period,
   filing (sec.gov/Archives only), accession, tag, mapping version, quality, derivation and as-of date,
   with the page's own actions. Text goes in through textContent; links are filings or our pages. */
(function () {
  'use strict';
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; }
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function money(v, cur) {
    if (v == null) return ''; var a = Math.abs(v), p = (v < 0 ? '−' : '') + (!cur || cur === 'USD' ? '$' : cur + ' ');
    return a >= 1e12 ? p + (a / 1e12).toFixed(1) + 'T' : a >= 1e9 ? p + (a / 1e9).toFixed(1) + 'B' : a >= 1e6 ? p + (a / 1e6).toFixed(1) + 'M' : p + a.toLocaleString('en-US');
  }
  var cfg = { asOf: function () { return null; }, actions: function () { return []; } };
  var card = null, cardFor = null;
  function open(b) {
    close(); cardFor = b; var i = b._prov || {};
    var rows = [];
    var kv = function (k, v) { if (v != null && v !== '') rows.push(el('dt', { text: k }), el('dd', {}, [v])); };
    kv('Period', [i.fiscal_label, i.period_end ? 'ended ' + day(i.period_end) : null].filter(Boolean).join(', '));
    if (i.source_url && ARCHIVE.test(i.source_url)) kv('Filing', el('a', { href: i.source_url, target: '_blank', rel: 'noopener', text: (i.form_type || 'Filing') + (i.filed_date ? ' filed ' + day(i.filed_date) : '') + ' ↗' }));
    kv('Accession', i.accession_number);
    kv('Tag', i.source_tag);
    kv('Mapping', i.mapping_version);
    // a mark's row links its entry on /docs/flags/ ("What this means"); the quality note itself is said here too
    var why = function (id) { return el('a', { class: 'prov-why', href: '/docs/flags/#' + id, text: 'What this means' }); };
    var bad = i.quality_status && i.quality_status !== 'ok';
    if (bad || i.quality_note) kv('Quality', el('span', {}, [(bad ? String(i.quality_status).replace(/_/g, ' ') + (i.quality_note ? ': ' : '') : '') + (i.quality_note || '') + ' ', why(i.quality_status === 'unit_doubtful' || /about 100 times/.test(i.quality_note || '') ? 'unit-doubtful' : 'quality')]));
    if (i.derived) kv('Derived', el('span', {}, [(i.formula || 'worked out here from reported figures') + (i.inputs && i.inputs.length ? ': ' + i.inputs.map(function (x) { return String(x.metric || x.name || '').replace(/_/g, ' ') + ' ' + money(x.value, i.currency); }).join(', ') : ''), ' ', why('derived')]));
    if (i.derived && i.inputs && i.inputs.some(function (x) { return x.source_url && ARCHIVE.test(x.source_url); })) kv('Inputs', el('span', { class: 'prov-in' }, i.inputs.map(function (x) {
      return ARCHIVE.test(x.source_url || '') ? el('a', { href: x.source_url, target: '_blank', rel: 'noopener', text: String(x.metric || '').replace(/_/g, ' ') + ' · ' + (x.form_type || 'filing') + (x.filed_date ? ' filed ' + day(x.filed_date) : '') + ' ↗' }) : null;
    })));
    if (i.adj) kv('Split-adjusted', el('span', {}, ['put on today’s share basis here ', why('split-adjusted')]));
    if (i.predecessor) kv('Registrant', i.registrant_label || 'Reported by the predecessor registrant (CIK ' + i.registrant_cik + ')');
    var asOf = cfg.asOf(); kv('As known on', asOf ? day(asOf) : 'latest');
    card = el('div', { class: 'prov-card', role: 'dialog', 'aria-label': 'Where this figure comes from', tabindex: '-1' }, [
      el('p', { class: 'prov-v' }, [el('b', { text: b.textContent, 'data-t': b.textContent }), i.label ? ' ' + i.label : '']),
      el('dl', {}, rows), el('div', { class: 'prov-act' }, cfg.actions(i, close) || [])
    ]);
    document.body.appendChild(card);
    var r = b.getBoundingClientRect(), w = Math.min(340, window.innerWidth - 24), left = Math.max(12, Math.min(r.left + window.scrollX, window.scrollX + window.innerWidth - w - 12));
    card.style.width = w + 'px'; card.style.left = left + 'px'; card.style.top = (r.bottom + window.scrollY + 6) + 'px';
    b.setAttribute('aria-expanded', 'true'); lead(card); card.focus({ preventScroll: true });
    // the card reads as if it sat right after its figure: Tab past its last link closes it and moves on
    // to whatever follows the figure, Shift+Tab before its first goes back to the figure
    card.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab') return;
      var f = card.querySelectorAll('a[href], button:not([disabled])'), first = f[0], last = f[f.length - 1], a = document.activeElement;
      if (e.shiftKey && (a === card || a === first)) { e.preventDefault(); var d = close(); if (d) d.focus(); }
      else if (!e.shiftKey && (a === last || !f.length)) { e.preventDefault(); var from = close(); if (from) after(from); }
    });
  }
  // the leader (brand, B-4): from the figure in the card, down its left gutter, to a dot at the filing row
  function lead(c) {
    var a = c.querySelector('dd a[href^="https://www.sec.gov/Archives/"]'), v = c.querySelector('.prov-v b');
    if (!a || !v) return;
    var cr = c.getBoundingClientRect(), ox = cr.left + c.clientLeft, oy = cr.top + c.clientTop, vr = v.getBoundingClientRect(), dr = a.parentNode.previousElementSibling.getBoundingClientRect();
    var y1 = Math.round(vr.top + vr.height / 2 - oy), y2 = Math.round(dr.top + dr.height / 2 - oy), x2 = Math.round(dr.left - ox);
    var NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg'), p = document.createElementNS(NS, 'path'), d = document.createElementNS(NS, 'circle');
    s.setAttribute('class', 'prov-lead'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('width', c.clientWidth); s.setAttribute('height', c.clientHeight);
    p.setAttribute('d', 'M' + Math.round(vr.left - ox) + ',' + y1 + 'H12V' + y2 + 'H' + (x2 - 9)); p.setAttribute('pathLength', '1');
    d.setAttribute('cx', x2 - 7); d.setAttribute('cy', y2); d.setAttribute('r', '3.5');
    s.appendChild(p); s.appendChild(d); c.appendChild(s);
  }
  function close() { if (card) { card.remove(); card = null; } if (cardFor) { cardFor.setAttribute('aria-expanded', 'false'); var f = cardFor; cardFor = null; return f; } }
  function after(node) {
    var all = Array.prototype.filter.call(document.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'), function (x) { return x.offsetParent !== null || x === node; });
    var nx = all[all.indexOf(node) + 1]; (nx || node).focus();
  }
  function door(text, info, cls) {
    var b = el('button', { type: 'button', class: 'door' + (cls ? ' ' + cls : ''), text: text, 'aria-haspopup': 'dialog', 'data-t': text });
    b._prov = info;
    b.addEventListener('click', function (e) { e.stopPropagation(); if (cardFor === b) close(); else open(b); });
    return b;
  }
  document.addEventListener('click', function (e) { if (card && !card.contains(e.target)) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && card) { var f = close(); if (f) f.focus(); } });
  window.ProvCard = { door: door, open: open, close: close, configure: function (c) { Object.assign(cfg, c || {}); } };
})();
