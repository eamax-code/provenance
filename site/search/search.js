/* Search inside filings (Q-01, docs/contracts/filing-search.md): one hit per stored section, a snippet with the
   query marked from the API's offsets (text nodes only, never HTML), and the sec.gov/Archives document it came from.
   The state lives in the URL, so every search has its own link. Coverage is said in the summary line: this searches
   the sections the service holds, not all of EDGAR. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var SECTION = { annual_report: '10-K risk factors and MD&A', prospectus: 'Prospectuses', earnings_release: 'Earnings releases (8-K exhibit 99.1)', '8k_officers': 'Officer changes (8-K item 5.02)' };
  var ITEM = { '10k:1A': '10-K risk factors (Item 1A)', '10k:7': '10-K MD&A (Item 7)', '5.02': 'Officer changes (8-K item 5.02)', 'ex:99.1': 'Earnings releases (8-K exhibit 99.1)' };
  var FORMS = ['10-K', 'S-1', 'F-1', '424B4', '8-K'];
  var LIMIT = 20, MAXOFF = 500;
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };

  // ---- state <-> URL ----
  var st = { q: '', cik: '', form: [], section: '', filed_from: '', filed_to: '', sort: 'date' };
  (function () {
    var u = new URLSearchParams(location.search);
    st.q = (u.get('q') || '').slice(0, 200); st.cik = (u.get('cik') || '').replace(/\D/g, ''); st.form = (u.get('form') || '').split(',').filter(Boolean);
    st.section = u.get('section') || ''; st.filed_from = u.get('filed_from') || ''; st.filed_to = u.get('filed_to') || ''; st.sort = u.get('sort') === 'relevance' ? 'relevance' : 'date';
  })();
  function query(offset) {
    var u = new URLSearchParams(); u.set('q', st.q);
    if (st.cik) u.set('cik', st.cik); if (st.form.length) u.set('form', st.form.join(',')); if (st.section) u.set('section', st.section);
    if (st.filed_from) u.set('filed_from', st.filed_from); if (st.filed_to) u.set('filed_to', st.filed_to); if (st.sort !== 'date') u.set('sort', st.sort);
    if (offset) u.set('offset', offset); return u;
  }
  function syncUrl() { var u = query(0); history.replaceState(null, '', st.q ? '/search/?' + u.toString() : '/search/'); }

  // ---- the form ----
  var q = $('fs-q'); q.value = st.q;
  function facets(cov) {
    var secs = cov && cov.length ? cov.map(function (c) { return c.section; }) : Object.keys(SECTION);
    if (st.section && secs.indexOf(st.section) < 0) secs = secs.concat(st.section); // an item code from a link (10k:1A) shows as its own choice
    var sbox = $('fs-sections'); sbox.replaceChildren(el('legend', { text: 'Section' }));
    [''].concat(secs).forEach(function (s) {
      var c = (cov || []).filter(function (x) { return x.section === s; })[0];
      var r = el('input', { type: 'radio', name: 'fs-section', value: s }); r.checked = st.section === s;
      r.addEventListener('change', function () { st.section = s; run(); });
      sbox.appendChild(el('label', {}, [r, ' ' + (s ? SECTION[s] || ITEM[s] || s : 'Any section'), c ? el('span', { class: 'fs-n', title: 'companies', text: Number(c.companies).toLocaleString('en-US') }) : null]));
    });
    var fbox = $('fs-forms'); fbox.replaceChildren(el('legend', { text: 'Form' }));
    FORMS.forEach(function (f) {
      var b = el('input', { type: 'checkbox', value: f }); b.checked = st.form.indexOf(f) > -1;
      b.addEventListener('change', function () { st.form = FORMS.filter(function (x) { return x === f ? b.checked : st.form.indexOf(x) > -1; }); run(); });
      fbox.appendChild(el('label', {}, [b, ' ' + f + (f === '10-K' || f === 'S-1' || f === '8-K' ? ' and amendments' : '')]));
    });
  }
  facets(null);
  $('fs-from').value = st.filed_from; $('fs-to').value = st.filed_to; $('fs-cik').value = st.cik;
  [].forEach.call(document.querySelectorAll('input[name=fs-sort]'), function (r) { r.checked = r.value === st.sort; r.addEventListener('change', function () { st.sort = r.value; run(); }); });
  $('fs-from').addEventListener('change', function () { st.filed_from = this.value; run(); });
  $('fs-to').addEventListener('change', function () { st.filed_to = this.value; run(); });
  $('fs-cik').addEventListener('change', function () { st.cik = this.value.replace(/\D/g, ''); run(); });
  if (window.matchMedia && matchMedia('(max-width: 760px)').matches) $('fs-sheet').open = false; // a sheet under the box on phones
  // "Exact phrase" quotes what was typed; "Any word" joins the words with or; "All words" leaves it as typed
  function shaped() {
    var v = q.value.trim(), mode = (document.querySelector('input[name=fs-mode]:checked') || {}).value;
    if (mode === 'phrase' && v && !/^".*"$/.test(v)) return '"' + v.replace(/"/g, '') + '"';
    if (mode === 'any' && v.indexOf('"') < 0) return v.split(/\s+/).filter(Boolean).join(' or ');
    return v;
  }
  $('fs-form').addEventListener('submit', function (e) { e.preventDefault(); st.q = shaped().slice(0, 200); q.value = st.q; run(); });

  // ---- results ----
  var hitsBox = $('fs-hits'), more = $('fs-more'), seq = 0, next = 0, shown = 0, lastAcc = null;
  function marked(snippet, hl) {
    var out = [], at = 0;
    (hl || []).slice().sort(function (a, b) { return a[0] - b[0]; }).forEach(function (h) {
      if (h[0] < at || h[1] > snippet.length || h[1] <= h[0]) return;
      if (h[0] > at) out.push(snippet.slice(at, h[0]));
      out.push(el('b', { class: 'fs-m', text: snippet.slice(h[0], h[1]) })); at = h[1];
    });
    if (at < snippet.length) out.push(snippet.slice(at));
    return out;
  }
  function hit(h) {
    var f = h.filing || {}, sec = h.section || {}, link = ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: 'Open the document on sec.gov ↗' }) : null;
    var same = lastAcc && lastAcc === f.accession_number; lastAcc = f.accession_number;
    var co = el('a', { href: '/app/?c=' + parseInt(h.cik, 10), class: 'fs-co', text: h.company || 'CIK ' + h.cik });
    var head = same ? el('p', { class: 'fs-head fs-also' }, ['Also in this filing · ', el('span', { text: sec.title || sec.item || '' })])
      : el('h2', { class: 'fs-head' }, [co, h.ticker ? el('span', { class: 'tag', text: h.ticker }) : null, ' · ' + (f.form || '') + ' filed ' + day(f.filed_date) + ' · ', el('span', { class: 'fs-sec', text: sec.title || sec.item || '' })]);
    return el('li', { class: 'fs-hit' + (same ? ' fs-fold' : '') }, [head,
      same ? null : el('p', { class: 'fs-meta' }, [el('span', { class: 'mono', text: f.accession_number || '' }), link ? ' · ' : '', link]),
      el('p', { class: 'fs-snip' }, marked(h.snippet || '', h.highlights))]);
  }
  function coverage(cov) {
    if (!cov || !cov.length) return 'searches the filing sections this service holds, not all of EDGAR';
    var bit = { annual_report: '10-K risk factors and MD&A for ', prospectus: 'prospectuses for ', earnings_release: 'earnings releases for ', '8k_officers': 'officer-change 8-Ks for ' };
    return 'searches the sections we hold: ' + cov.map(function (c) { return (bit[c.section] || c.section + ' for ') + Number(c.companies).toLocaleString('en-US') + ' companies'; }).join(', ') + '; not all of EDGAR';
  }
  function say(text) { $('fs-sum').textContent = text; }
  // the per-section coverage sits under "What's searched" (PM, 24 Nov): open on desktop, closed on phones; the summary keeps one line
  var what = $('fs-what'); what.open = !(window.matchMedia && matchMedia('(max-width: 760px)').matches);
  function covList(cov) { var bit = { annual_report: '10-K risk factors and MD&A for ', prospectus: 'prospectuses for ', earnings_release: 'earnings releases for ', '8k_officers': 'officer-change 8-Ks for ' };
    return cov.map(function (c) { return (bit[c.section] || c.section + ' for ') + Number(c.companies).toLocaleString('en-US') + ' companies'; }).join(', '); }
  function run(append) {
    syncUrl();
    if (!st.q) { hitsBox.textContent = ''; more.hidden = true; return; }
    if (hitsBox.id !== 'fs-hits') { var ol = el('ol', { class: 'fs-hits', id: 'fs-hits' }); hitsBox.replaceWith(ol); hitsBox = ol; }
    document.body.classList.remove('fs-empty');
    var my = ++seq, off = append ? next : 0;
    if (!append) { hitsBox.textContent = ''; shown = 0; lastAcc = null; $('fs-h').textContent = /"/.test(st.q) ? 'Filings that say: ' + st.q : 'Filings that say “' + st.q + '”'; document.title = st.q + ' · Search inside filings · Provenance'; say('Searching…'); }
    more.hidden = true; if (!append) what.hidden = true;
    fetch('/v1/search/filings?' + query(off).toString() + '&limit=' + LIMIT, { headers: { Accept: 'application/json', 'X-API-Key': key() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); })
      .then(function (r) {
        if (my !== seq) return;
        if (!r.ok) {
          var e = (r.b && r.b.error) || {};
          say(r.status === 422 ? (e.message || 'That search has no word to look for. Try a word or a quoted phrase.')
            : r.status === 403 && e.code === 'demo_scope' ? 'The demo key searches the showcase companies only. Connect a free key in the Explorer to search every company we hold.'
            : r.status === 403 ? (e.message || 'This key cannot run that search.')
            : r.status === 429 ? 'Too many searches this minute. Try again in a moment.' : 'The search could not run. Check the connection and try again.');
          return;
        }
        var b = r.b, hits = b.hits || [], m = b.meta || {};
        if (!append) facets(b.coverage);
        hits.forEach(function (h) { hitsBox.appendChild(hit(h)); }); shown += hits.length;
        next = m.next_offset || off + hits.length;
        more.hidden = !m.has_more || next > MAXOFF;
        var sort = st.sort === 'relevance' ? 'most relevant first' : 'newest filing first', asof = st.filed_to ? ' · as known on ' + day(st.filed_to) : '';
        if (!shown) say('No stored section matches this search. It ' + coverage(b.coverage) + '.');
        else say(shown + ' section' + (shown === 1 ? '' : 's') + ' shown' + (m.has_more ? (next > MAXOFF ? ', more than 500: narrow the search to see the rest' : ', more below') : '') + ' · ' + sort + asof + ' · not all of EDGAR.');
        what.hidden = !shown || !(b.coverage && b.coverage.length);
        if (!what.hidden) $('fs-what-p').textContent = 'Searches the sections we hold: ' + covList(b.coverage) + '.';
        // the summary line already says what is searched, so the API's coverage note is not repeated (PM, 24 Nov); other notes show
        $('fs-cov').textContent = (b.notes || []).filter(function (n) { return !/not every filing on EDGAR/.test(n); }).join(' ');
        var api = $('fs-api'); api.hidden = false;
        api.replaceChildren('The same search from the API: ', el('code', { text: 'curl -H "X-API-Key: $KEY" "' + location.origin + '/v1/search/filings?' + query(0).toString() + '"' }));
      })
      .catch(function () { if (my === seq) say('The search could not run. Check the connection and try again.'); });
  }
  more.addEventListener('click', function () { run(true); });
  // before the first search: no filters to set yet, three searches to start from (PM, 24 Nov). Each returned real hits on
  // the live endpoint; "going concern" finds none among the showcase companies, so it shows only with a key.
  function examples() {
    var keyed = key() !== 'demo', ex = [
      keyed ? ['“going concern”', { q: '"going concern"' }] : null,
      ['“tariff” in 10-K risk factors', { q: 'tariff', section: '10k:1A' }],
      ['“chief financial officer” in 8-K item 5.02', { q: 'chief financial officer', section: '8k_officers' }]].filter(Boolean);
    var ul = el('ul', { class: 'fs-ex', 'aria-label': 'Example searches' }, ex.map(function (e) { return el('li', {}, [el('a', { href: '/search/?' + new URLSearchParams(e[1]).toString(), text: e[0] })]); }));
    hitsBox.replaceWith(ul); hitsBox = ul;
  }
  document.body.classList.toggle('fs-empty', !st.q);
  if (st.q) run();
  else { examples(); q.focus(); }
})();
