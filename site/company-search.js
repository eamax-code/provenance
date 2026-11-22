/* Find a company by name, ticker, former name or CIK (keyless /v1/public/companies/search).
   Any form with data-company-search gets live results in its [data-results] list; Enter opens the
   first. Showcase companies open their public page; others open the same address, which explains
   that a free key opens every company. Text goes in through textContent only. */
(function () {
  'use strict';
  var el = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] == null) return; if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  document.querySelectorAll('form[data-company-search]').forEach(function (form) {
    var input = form.querySelector('input'), list = form.parentNode.querySelector('[data-results]'), timer = null, seq = 0, first = null;
    if (!input || !list) return;
    var render = function (rows, q) {
      first = rows[0] ? '/companies/' + parseInt(rows[0].cik, 10) : null;
      if (!rows.length) { list.replaceChildren(el('li', { class: 'cs-empty', text: 'No company matches "' + q + '". Try a ticker, a former name or the CIK.' })); return; }
      list.replaceChildren.apply(list, rows.map(function (r) {
        var cik = String(parseInt(r.cik, 10));
        return el('li', {}, [
          el('a', { href: '/companies/' + cik }, [
            el('b', { text: r.display_name }),
            el('span', { class: 'cs-meta', text: [r.ticker, r.exchange, 'CIK ' + cik].filter(Boolean).join(' · ') + (r.matched_former_name ? (r.match_type === 'former_ticker' ? ' · formerly traded as ' : ' · formerly ') + r.matched_former_name : '') }),
            el('span', { class: 'cs-tag', text: r.is_public_page ? 'Public page' : 'With a free key' })
          ])
        ]);
      }));
    };
    var search = function () {
      var q = input.value.trim(), mine = ++seq;
      if (q.length < 2) { list.replaceChildren(); first = null; return; }
      fetch('/v1/public/companies/search?q=' + encodeURIComponent(q), { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : { data: [] }; })
        .then(function (d) { if (mine === seq) render(d.data || [], q); })
        .catch(function () { if (mine === seq) list.replaceChildren(el('li', { class: 'cs-empty', text: 'Search is unavailable right now.' })); });
    };
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(search, 220); });
    form.addEventListener('submit', function (e) { e.preventDefault(); if (first) location.href = first; else search(); });
  });
})();
