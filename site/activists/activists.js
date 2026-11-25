/* Activist stakes across companies (Q-07, docs/contracts/activists.md): Schedules 13D filed in a window, by kind
   (new, increased, decreased, exited, switched from 13G), newest first. The stake in words and numbers, the purpose
   quoted from Item 4 as filed, the disclaimer and the coverage note on every view. State in the URL; the shared
   helpers are /app/activists.js. Text nodes only. */
(function () {
  'use strict';
  var A = window.prvActivists; if (!A) return;
  var $ = function (id) { return document.getElementById(id); }, el = A.el;
  var KIND = { new: ['new 13D stake', 'new 13D stakes'], increased: ['increased stake', 'increased stakes'], decreased: ['decreased stake', 'decreased stakes'],
    exited: ['exit (a stake reported under 5%)', 'exits (stakes reported under 5%)'], switched: ['switch from a passive 13G to a 13D', 'switches from a passive 13G to a 13D'] };
  var iso = function (d) { return d.toISOString().slice(0, 10); };
  var hasKey = function () { try { return !!localStorage.getItem('prv_api_key'); } catch (e) { return false; } };
  var st = { kind: 'new', win: '30', since: '', until: '', min: '' }, seq = 0, rows = [], next = null;
  (function () {
    var u = new URLSearchParams(location.search), d = /^\d{4}-\d{2}-\d{2}$/;
    if (KIND[u.get('kind')]) st.kind = u.get('kind');
    if (/^(10|20)$/.test(u.get('min_percent') || '')) st.min = u.get('min_percent');
    if (/^(90|365)$/.test(u.get('days') || '')) st.win = u.get('days');
    if (d.test(u.get('since') || '')) { st.since = u.get('since'); st.until = d.test(u.get('until') || '') ? u.get('until') : ''; st.win = 'custom'; }
  })();
  // a window from the URL that is not one of the presets keeps its dates as its own option
  if (st.win === 'custom') $('ac-win').appendChild(el('option', { value: 'custom', text: A.dmy(st.since) + ' to ' + (st.until ? A.dmy(st.until) : 'today') }));
  $('ac-win').value = st.win; $('ac-min').value = st.min;
  function range() { if (st.win !== 'custom') { var s = new Date(); s.setUTCDate(s.getUTCDate() - +st.win); return { since: iso(s), until: '' }; } return { since: st.since, until: st.until }; }
  function syncUrl() {
    var u = new URLSearchParams(); if (st.kind !== 'new') u.set('kind', st.kind);
    if (st.win === 'custom') { u.set('since', st.since); if (st.until) u.set('until', st.until); } else if (st.win !== '30') u.set('days', st.win);
    if (st.min) u.set('min_percent', st.min);
    var s = u.toString(); history.replaceState(null, '', '/activists/' + (s ? '?' + s : ''));
  }

  // one filing: the company, the filer (and its group), the stake in words, the purpose as filed
  function row(x) {
    var c = x.company || {}, k = x.kind || st.kind, words = A.change(x.change_pct_points, x.percent) + A.ofClass(x.class_label);
    var stake = k === 'exited' ? 'Exited: ' + words + ', under 5%' : k === 'increased' || k === 'decreased' ? A.cap(words) : k === 'amended' ? 'Amended: ' + (x.change_pct_points == null ? A.pc(x.percent) + A.ofClass(x.class_label) : words) : 'New stake: ' + A.pc(x.percent) + A.ofClass(x.class_label);
    return el('li', { class: 'ac-row' }, [el('p', { class: 'ac-when', text: A.dmy(x.filed_date) }), el('div', { class: 'ac-body' }, [
      el('p', { class: 'ac-co' }, [c.cik ? el('a', { href: '/app/?c=' + parseInt(c.cik, 10) + '&tab=ownership#activists', text: c.name || 'Company' }) : c.name, c.ticker ? el('span', { class: 'tag', text: c.ticker }) : null]),
      el('p', { class: 'ac-who' }, A.who(x.filer, x.group_size)),
      el('p', { class: 'ac-stake' }, [stake, el('span', { class: 'ac-meta', text: (x.shares != null ? ' · ' + A.int(x.shares) + ' shares' : '') + ' · ' }), A.link(A.form(x.form, x.amendment_number) + ' filed ' + A.dmy(x.filed_date), x.source_url)]),
      A.switched(x.switched_from_13g), A.quote(x.purpose, x.accession_number)])]);
  }
  function why(r) { var e = (r.b && r.b.error) || {}; return r.status === 422 ? (e.message || 'Those filters are not valid.') : r.status === 429 ? 'Too many requests this minute. Try again in a moment.' : 'Activist stakes could not load. Check the connection and try again.'; }
  function path(off) {
    var w = range(), q = '/v1/activists?kind=' + st.kind + '&since=' + w.since + (w.until ? '&until=' + w.until : '') + (st.min ? '&min_percent=' + st.min : '');
    return { api: q, full: q + '&limit=50' + (off ? '&offset=' + off : '') };
  }
  function summary(more) {
    var w = range(), n = rows.length, k = KIND[st.kind];
    $('ac-sum').textContent = (more ? 'The latest ' + n : n) + ' ' + k[n === 1 ? 0 : 1] + ' filed ' + A.dmy(w.since) + ' to ' + (w.until ? A.dmy(w.until) : 'today') + (st.min ? ', at ' + st.min + '% or more' : '') + ', newest first.';
  }
  function draw(off) {
    syncUrl(); var my = ++seq, list = $('ac-rows'), more = $('ac-more'), p = path(off);
    [].forEach.call(document.querySelectorAll('.ac-tabs [role=tab]'), function (t) { var on = t.getAttribute('data-kind') === st.kind; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; });
    if (!off) { rows = []; list.textContent = ''; $('ac-sum').textContent = 'Loading…'; }
    more.hidden = true;
    A.load(p.full).then(function (r) {
      if (my !== seq) return;
      if (!r.ok) { $('ac-sum').textContent = r.status === 404 ? 'Activist stakes are not available on this server yet.' : why(r); return; }
      var b = r.b, d = b.data || [], m = b.meta || {};
      $('ac-disc').replaceWith(Object.assign(A.disclaimer(b), { id: 'ac-disc' })); $('ac-cov').replaceWith(Object.assign(A.coverage(b), { id: 'ac-cov' }));
      rows = rows.concat(d); next = m.has_more ? m.next_offset : null;
      d.forEach(function (x) { list.appendChild(row(x)); });
      if (!rows.length) { var w = range(); $('ac-sum').textContent = 'No ' + KIND[st.kind][1] + ' filed ' + A.dmy(w.since) + ' to ' + (w.until ? A.dmy(w.until) : 'today') + (st.min ? ' at ' + st.min + '% or more' : '') + (hasKey() ? '.' : ' at the showcase companies.'); }
      else summary(next != null);
      more.hidden = next == null;
      // without a key the list covers the showcase companies only (at most 10 rows): said on every keyless view, so an
      // empty list is never read as "no stakes were filed"
      var notes = (b.notes || []).slice(), scope = !hasKey() ? 'Without a key, this list covers the showcase companies only, at most 10 rows. ' : '';
      $('ac-notes').replaceChildren.apply($('ac-notes'), [scope, scope ? el('a', { href: '/account/', text: 'A free key shows every company' }) : null, scope ? '. ' : null, notes.join(' ')].filter(Boolean));
      var api = $('ac-api'); api.hidden = false; api.replaceChildren('The same list from the API: ', el('code', { text: 'curl -H "X-API-Key: $KEY" "' + location.origin + p.api + '"' }));
    });
  }
  // tabs: click, and arrow keys move between them (roving tabindex)
  var tabs = [].slice.call(document.querySelectorAll('.ac-tabs [role=tab]'));
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { st.kind = t.getAttribute('data-kind'); draw(0); });
    t.addEventListener('keydown', function (e) { var j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : -9; if (j === -9) return; e.preventDefault(); var n = tabs[(j + tabs.length) % tabs.length]; n.focus(); n.click(); });
  });
  $('ac-win').addEventListener('change', function () { st.win = this.value; draw(0); });
  $('ac-min').addEventListener('change', function () { st.min = this.value; draw(0); });
  $('ac-more').addEventListener('click', function () { if (next != null) draw(next); });
  draw(0);
})();
