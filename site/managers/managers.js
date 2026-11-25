/* Fund managers (Q-02, docs/contracts/managers.md): find a manager, and the companies funds bought or sold most in a
   quarter (net managers buying). State in the URL. Holdings are as of the quarter end and filed up to 45 days later:
   said next to the quarter on every view. Text nodes only; links go to sec.gov/Archives or into the site. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var dmy = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; };
  var int = function (v) { return v == null ? '—' : Math.round(v).toLocaleString('en-US'); };
  var big = function (v) { if (v == null) return '—'; var a = Math.abs(v); return a >= 1e12 ? '$' + (v / 1e12).toFixed(2) + 'T' : a >= 1e9 ? '$' + (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? '$' + (v / 1e6).toFixed(1) + 'M' : '$' + Math.round(v).toLocaleString('en-US'); };
  var signed = function (v) { return v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toLocaleString('en-US'); };
  var pct = function (v) { return v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%'; };
  var common = function (c) { return !c || /^common stock$/i.test(String(c).trim()); };
  var get = function (url) { return fetch(url, { headers: { Accept: 'application/json', 'X-API-Key': key() } }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); }); };
  var why = function (r, what) { var e = (r.b && r.b.error) || {}; return r.status === 422 || r.status === 404 ? (e.message || what + ' could not be found.') : r.status === 429 ? 'Too many requests this minute. Try again in a moment.' : what + ' could not load. Check the connection and try again.'; };
  // the quarter ends before q, newest first (n of them)
  function quarters(q, n) { var out = [], m = /^(\d{4})-(\d{2})/.exec(q || ''); if (!m) return out; var y = +m[1], mo = +m[2]; for (var i = 0; i < n; i++) { out.push(y + '-' + ('0' + mo).slice(-2) + '-' + (mo === 3 || mo === 12 ? '31' : '30')); mo -= 3; if (mo < 3) { mo = 12; y--; } } return out; }

  var st = { q: '', dir: 'bought', min: '20', quarter: '' };
  (function () { var u = new URLSearchParams(location.search); st.q = (u.get('q') || '').slice(0, 100); st.dir = u.get('direction') === 'sold' ? 'sold' : 'bought'; st.min = /^(20|50|100|250)$/.test(u.get('min_holders') || '') ? u.get('min_holders') : '20'; st.quarter = /^\d{4}-\d{2}-\d{2}$/.test(u.get('quarter') || '') ? u.get('quarter') : ''; })();
  function syncUrl() { var u = new URLSearchParams(); if (st.q) u.set('q', st.q); if (st.dir !== 'bought') u.set('direction', st.dir); if (st.min !== '20') u.set('min_holders', st.min); if (st.quarter) u.set('quarter', st.quarter); var s = u.toString(); history.replaceState(null, '', '/managers/' + (s ? '?' + s : '')); }

  // ---- search ----
  $('mg-qin').value = st.q;
  function search() {
    var box = $('mg-found'); syncUrl();
    if (st.q.length < 2) { box.textContent = ''; return; }
    box.replaceChildren(el('li', { class: 'muted', text: 'Looking…' }));
    get('/v1/managers?q=' + encodeURIComponent(st.q) + '&limit=20').then(function (r) {
      if (!r.ok) { box.replaceChildren(el('li', { text: why(r, 'The managers') })); return; }
      var d = r.b.data || [];
      box.replaceChildren.apply(box, d.length ? d.map(function (m) {
        return el('li', {}, [el('a', { href: '/managers/' + parseInt(m.cik, 10) + '/', text: m.name }),
          el('span', { class: 'mg-found-meta', text: ' · ' + int(m.positions) + ' positions, ' + big(m.value_usd) + ' at ' + dmy(m.latest_quarter) }),
          m.company_cik ? el('a', { class: 'mg-co', href: '/companies/' + parseInt(m.company_cik, 10), text: 'Company page' }) : null]);
      }) : [el('li', { text: 'No manager with a stored 13F matches “' + st.q + '”.' })]);
    });
  }
  $('mg-search').addEventListener('submit', function (e) { e.preventDefault(); st.q = $('mg-qin').value.trim().slice(0, 100); search(); });

  // ---- funds bought / sold ----
  var tabs = [$('mg-t-bought'), $('mg-t-sold')], seq = 0;
  tabs.forEach(function (t) { t.addEventListener('click', function () { st.dir = t.getAttribute('data-dir'); activity(); }); });
  $('mg-min').value = st.min; $('mg-min').addEventListener('change', function () { st.min = this.value; activity(); });
  $('mg-quarter').addEventListener('change', function () { st.quarter = this.value; activity(); });
  function activity() {
    syncUrl(); tabs.forEach(function (t) { t.setAttribute('aria-selected', String(t.getAttribute('data-dir') === st.dir)); });
    var my = ++seq, tbl = $('mg-act-table'); $('mg-sum').textContent = 'Loading…'; tbl.textContent = '';
    get('/v1/managers/activity?direction=' + st.dir + '&min_holders=' + st.min + (st.quarter ? '&quarter=' + st.quarter : '') + '&limit=50').then(function (r) {
      if (my !== seq) return;
      if (!r.ok) { $('mg-sum').textContent = why(r, 'The fund activity'); return; }
      var b = r.b, d = b.data || [];
      if (b.labels && b.labels.disclaimer) $('mg-disc').textContent = b.labels.disclaimer;
      $('mg-q').textContent = 'Quarter ending ' + dmy(b.quarter);
      var sel = $('mg-quarter'); if (!sel.options.length) { quarters(st.quarter || b.quarter, 4).forEach(function (q) { sel.appendChild(el('option', { value: q, text: dmy(q) })); }); } sel.value = b.quarter;
      $('mg-sum').textContent = d.length + ' compan' + (d.length === 1 ? 'y' : 'ies') + ' ' + (st.dir === 'bought' ? 'most bought' : 'most sold') + ' by funds, ' + dmy(b.previous_quarter) + ' to ' + dmy(b.quarter) + ', held by at least ' + st.min + ' managers · ranked by net managers ' + (st.dir === 'bought' ? 'buying' : 'selling') + '.';
      var th = function (t, n, tip) { return el('th', { scope: 'col', class: n ? 'n' : null }, [tip ? el('span', { title: tip, text: t }) : t]); };
      tbl.replaceChildren(el('thead', {}, [el('tr', {}, [th('Company'), th('Net managers', 1, 'New and added, minus reduced and sold out'), th('New', 1), th('Added', 1), th('Reduced', 1), th('Sold out', 1), th('Holders', 1, 'Managers holding it now (the quarter before)'), th('Shares held, change', 1, 'All managers’ 13F shares of this class, against the quarter before; not the company’s shares outstanding')])]),
        el('tbody', {}, d.map(function (x) {
          var i = x.issuer || {};
          return el('tr', {}, [el('th', { scope: 'row' }, [i.cik ? el('a', { href: '/app/?c=' + parseInt(i.cik, 10) + '&tab=ownership', text: i.name }) : i.name, i.ticker ? el('span', { class: 'tag', text: i.ticker }) : null, common(x.class_label) ? null : el('span', { class: 'mg-flag', title: 'Share class: ' + x.class_label, text: x.class_label }), x.split_adjusted ? el('a', { class: 'mg-flag', href: '/docs/flags/#compared-after-split', title: 'Shares before the split were put on the new basis before comparing', 'aria-label': 'Compared after the ' + (x.split || '') + ' split: what this means', text: 'Compared after the ' + (x.split || '') + ' split' }) : null]),
            el('td', { class: 'n mg-net', text: signed(x.net_managers) }), el('td', { class: 'n', text: int(x.managers_new) }), el('td', { class: 'n', text: int(x.managers_added) }), el('td', { class: 'n', text: int(x.managers_reduced) }), el('td', { class: 'n', text: int(x.managers_exited) }),
            el('td', { class: 'n', text: int(x.holders) + ' (' + int(x.holders_previous) + ')' }), el('td', { class: 'n', text: pct(x.shares_change_pct) })]);
        })));
      $('mg-notes').textContent = (b.notes_detail ? b.notes_detail.filter(function (n) { return n.audience === 'reader'; }).map(function (n) { return n.text; }) : b.notes || []).join(' '); // reader notes (N-01)
      var api = $('mg-api'); api.hidden = false; api.replaceChildren('The same list from the API: ', el('code', { text: 'curl -H "X-API-Key: $KEY" "' + location.origin + '/v1/managers/activity?direction=' + st.dir + '&min_holders=' + st.min + '&quarter=' + b.quarter + '"' }));
    });
  }
  search(); activity();
})();
