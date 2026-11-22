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
    kv('Quality', i.quality_status ? String(i.quality_status).replace(/_/g, ' ') : null);
    if (i.derived) kv('Derived', (i.formula || 'worked out here from reported figures') + (i.inputs && i.inputs.length ? ': ' + i.inputs.map(function (x) { return String(x.metric || x.name || '').replace(/_/g, ' ') + ' ' + money(x.value, i.currency); }).join(', ') : ''));
    if (i.predecessor) kv('Registrant', i.registrant_label || 'Reported by the predecessor registrant (CIK ' + i.registrant_cik + ')');
    var asOf = cfg.asOf(); kv('As known on', asOf ? day(asOf) : 'latest');
    card = el('div', { class: 'prov-card', role: 'dialog', 'aria-label': 'Where this figure comes from', tabindex: '-1' }, [
      el('p', { class: 'prov-v' }, [el('b', { text: b.textContent }), i.label ? ' ' + i.label : '']),
      el('dl', {}, rows), el('div', { class: 'prov-act' }, cfg.actions(i, close) || [])
    ]);
    document.body.appendChild(card);
    var r = b.getBoundingClientRect(), w = Math.min(340, window.innerWidth - 24), left = Math.max(12, Math.min(r.left + window.scrollX, window.scrollX + window.innerWidth - w - 12));
    card.style.width = w + 'px'; card.style.left = left + 'px'; card.style.top = (r.bottom + window.scrollY + 6) + 'px';
    b.setAttribute('aria-expanded', 'true'); card.focus({ preventScroll: true });
  }
  function close() { if (card) { card.remove(); card = null; } if (cardFor) { cardFor.setAttribute('aria-expanded', 'false'); var f = cardFor; cardFor = null; return f; } }
  function door(text, info, cls) {
    var b = el('button', { type: 'button', class: 'door' + (cls ? ' ' + cls : ''), text: text, 'aria-haspopup': 'dialog' });
    b._prov = info;
    b.addEventListener('click', function (e) { e.stopPropagation(); if (cardFor === b) close(); else open(b); });
    return b;
  }
  document.addEventListener('click', function (e) { if (card && !card.contains(e.target)) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && card) { var f = close(); if (f) f.focus(); } });
  window.ProvCard = { door: door, close: close, configure: function (c) { Object.assign(cfg, c || {}); } };
})();
