/* Provenance API playground. Sends real requests to this origin with the public demo key
   (or the visitor's own key, which stays in this browser). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var METRICS = ['revenue', 'operating_income', 'net_income', 'total_assets', 'operating_cash_flow'];
  var EVENT_TYPES = ['', 'new_listing', 'ipo', 'delisting', 'suspended', 'reinstated', 'modified'];
  var DEFAULTS = { cik: '320193', isin: '', lei: '' };

  /* Catalog: every read-only endpoint, with parameters and sensible defaults. */
  var CATALOG = [
    { group: 'US companies (SEC)', id: 'company-search', path: '/v1/companies/search', desc: 'Find companies by ticker, CIK or name. Matches are ranked and labelled by match type.',
      params: [{ name: 'q', req: true, def: 'apple', help: 'Ticker, CIK or company name' }, { name: 'limit', def: '5' }] },
    { group: 'US companies (SEC)', id: 'company-list', path: '/v1/companies', desc: 'List companies with filters. Sort by name, CIK or last processed.',
      params: [{ name: 'exchange', def: '', help: 'e.g. Nasdaq, NYSE' }, { name: 'sic', def: '', help: 'SEC SIC code' }, { name: 'state', def: '', help: 'State of incorporation' }, { name: 'ingested', type: 'select', options: ['', 'true', 'false'], def: 'true' }, { name: 'sort', type: 'select', options: ['name', 'cik', 'last_processed'], def: 'name' }, { name: 'limit', def: '10' }] },
    { group: 'US companies (SEC)', id: 'company-profile', path: '/v1/companies/{cik}', desc: 'Canonical profile with SEC source URL, ingestion state and counts.',
      params: [{ name: 'cik', loc: 'path', req: true, def: '@cik' }] },
    { group: 'US companies (SEC)', id: 'company-filings', path: '/v1/companies/{cik}/filings', desc: 'Recent filings, newest first, with SEC acceptance time (null when the SEC gives none) and the filing index link.',
      params: [{ name: 'cik', loc: 'path', req: true, def: '@cik' }, { name: 'form_type', def: '', help: 'e.g. 10-K, 10-Q, 8-K' }, { name: 'since', type: 'date', def: '' }, { name: 'limit', def: '5' }] },
    { group: 'US companies (SEC)', id: 'company-facts', path: '/v1/companies/{cik}/facts', desc: 'Normalized facts with units, periods, source tag, accession and mapping version on every row.',
      params: [{ name: 'cik', loc: 'path', req: true, def: '@cik' }, { name: 'metric', type: 'select', options: METRICS, def: 'revenue' }, { name: 'period', type: 'select', options: ['annual', 'quarterly', 'all'], def: 'annual' }, { name: 'include_derived', type: 'select', options: ['false', 'true'], def: 'false', help: 'Quarters derived by subtraction, marked derived=true' }, { name: 'limit', def: '5' }] },
    { group: 'US companies (SEC)', id: 'company-freshness', path: '/v1/companies/{cik}/freshness', desc: 'Last SEC fetch, detection and processing times. Latency only where comparable timestamps exist.',
      params: [{ name: 'cik', loc: 'path', req: true, def: '@cik' }] },
    { group: 'Facts across companies', id: 'facts-screen', path: '/v1/facts/screen', desc: 'Rank one metric across all ingested companies for a calendar year, with provenance on each row.',
      params: [{ name: 'metric', type: 'select', options: METRICS, def: 'total_assets', req: true }, { name: 'year', def: '2024', req: true }, { name: 'period', type: 'select', options: ['annual', 'quarterly'], def: 'annual' }, { name: 'unit', def: 'USD' }, { name: 'order', type: 'select', options: ['desc', 'asc'], def: 'desc' }, { name: 'limit', def: '10' }] },
    { group: 'Listings: Canada, EU, UK', id: 'listing-events', path: '/v1/markets/events', desc: 'New listings, delistings, suspensions and name changes from ESMA FIRDS, FCA FIRDS and GLEIF.',
      params: [{ name: 'type', type: 'select', options: EVENT_TYPES, def: '' }, { name: 'region', type: 'select', options: ['', 'europe', 'uk', 'canada'], def: '' }, { name: 'mic', def: '', help: 'Venue code, e.g. XPAR, XLON, XETA' }, { name: 'since', type: 'date', def: '', help: 'event_date on or after' }, { name: 'limit', def: '10' }] },
    { group: 'Listings: Canada, EU, UK', id: 'listing-instruments', path: '/v1/markets/instruments', desc: 'Search instruments on covered venues by issuer name, symbol or LEI.',
      params: [{ name: 'q', def: '', help: 'Issuer name, symbol or LEI' }, { name: 'region', type: 'select', options: ['', 'europe', 'uk', 'canada'], def: 'europe' }, { name: 'country', def: '', help: 'ISO country, e.g. FR' }, { name: 'status', type: 'select', options: ['', 'listed', 'delisted', 'suspended'], def: 'listed' }, { name: 'first_trade_since', type: 'date', def: '' }, { name: 'limit', def: '10' }] },
    { group: 'Listings: Canada, EU, UK', id: 'listing-instrument', path: '/v1/markets/instruments/{isin}', desc: 'Every venue listing of one ISIN plus the issuer identity from GLEIF.',
      params: [{ name: 'isin', loc: 'path', req: true, def: '@isin' }] },
    { group: 'Listings: Canada, EU, UK', id: 'listing-issuer', path: '/v1/markets/issuers/{lei}', desc: 'Issuer identity by LEI and its listings.',
      params: [{ name: 'lei', loc: 'path', req: true, def: '@lei' }] },
    { group: 'Listings: Canada, EU, UK', id: 'venues', path: '/v1/markets/', desc: 'Venues covered, with listed and delisted counts and last-seen time.', params: [] },
    { group: 'Public (no key)', id: 'stats', path: '/v1/stats', nokey: true, desc: 'Coverage and health of this deployment.', params: [] },
    { group: 'Public (no key)', id: 'plans', path: '/v1/public/plans', nokey: true, desc: 'Plan limits and pilot pricing.', params: [] }
  ];

  var current = null, lang = 'curl', lastBody = null;

  /* ---- key handling ---- */
  var saved = null; try { saved = localStorage.getItem('prv_api_key'); } catch (e) {}
  if (saved) { $('pg-use-mine').hidden = false; }
  $('pg-use-demo').addEventListener('click', function () { $('pg-key').value = 'demo'; keyNote(); renderCode(); });
  $('pg-use-mine').addEventListener('click', function () { $('pg-key').value = saved || ''; keyNote(); renderCode(); });
  $('pg-key').addEventListener('input', function () { keyNote(); renderCode(); });
  function keyNote() {
    var k = $('pg-key').value.trim();
    $('pg-key-note').textContent = k === 'demo' ? 'Demo: showcase companies, 10 rows, 20 requests/min.' : (k ? 'Your key stays in this browser.' : 'No key: only public endpoints will work.');
  }

  /* ---- catalog ---- */
  function renderCatalog() {
    var box = $('pg-catalog'); box.innerHTML = ''; var lastGroup = null;
    CATALOG.forEach(function (ep) {
      if (ep.group !== lastGroup) { box.appendChild(el('div', { class: 'pg-group', text: ep.group })); lastGroup = ep.group; }
      var b = el('button', { type: 'button', class: 'pg-item', 'data-id': ep.id }, [el('span', { class: 'm', text: 'GET' }), el('span', { text: ep.path.replace('/v1', '') })]);
      if (ep.nokey) b.appendChild(el('span', { class: 'tag', text: 'no key' }));
      b.addEventListener('click', function () { select(ep.id, true); });
      box.appendChild(b);
    });
  }
  function select(id, focus) {
    current = CATALOG.filter(function (e) { return e.id === id; })[0] || CATALOG[0];
    document.querySelectorAll('.pg-item').forEach(function (b) { b.setAttribute('aria-current', String(b.getAttribute('data-id') === current.id)); });
    $('pg-path').textContent = current.path; $('pg-desc').textContent = current.desc;
    var box = $('pg-params'); box.innerHTML = '';
    if (!current.params.length) box.appendChild(el('p', { class: 'muted small', text: 'No parameters.' }));
    current.params.forEach(function (p) {
      var id = 'pg-p-' + p.name, input;
      var def = typeof p.def === 'string' && p.def.charAt(0) === '@' ? DEFAULTS[p.def.slice(1)] || '' : (p.def || '');
      if (p.type === 'select') {
        input = el('select', { id: id, name: p.name });
        p.options.forEach(function (o) { var opt = el('option', { value: o, text: o === '' ? '(any)' : o }); if (o === def) opt.selected = true; input.appendChild(opt); });
      } else {
        input = el('input', { id: id, name: p.name, type: p.type === 'date' ? 'date' : 'text', value: def, autocomplete: 'off', spellcheck: 'false' });
      }
      input.addEventListener('input', renderCode); input.addEventListener('change', renderCode);
      var label = el('label', { for: id }, [p.name, p.req ? el('span', { class: 'req', text: ' *' }) : '', el('span', { class: 'loc', text: ' ' + (p.loc || 'query') })]);
      box.appendChild(el('div', { class: 'pg-field' }, [label, input].concat(p.help ? [el('small', { text: p.help })] : [])));
    });
    $('pg-hint').textContent = current.nokey ? 'Public endpoint: no key needed.' : '';
    try { history.replaceState(null, '', '#' + current.id); } catch (e) {}
    renderCode();
    if (focus) { var first = box.querySelector('input,select'); if (first) first.focus(); }
  }

  /* ---- request building ---- */
  function buildUrl() {
    var path = current.path, q = new URLSearchParams(), missing = [];
    current.params.forEach(function (p) {
      var v = ($('pg-p-' + p.name) || {}).value; v = v == null ? '' : String(v).trim();
      if (p.req && !v) missing.push(p.name);
      if (p.loc === 'path') path = path.replace('{' + p.name + '}', encodeURIComponent(v || '{' + p.name + '}'));
      else if (v !== '') q.set(p.name, v);
    });
    var qs = q.toString();
    return { path: path + (qs ? '?' + qs : ''), missing: missing };
  }
  function renderCode() {
    if (!current) return;
    var u = buildUrl(), full = location.origin + u.path, key = $('pg-key').value.trim(), hdr = current.nokey || !key ? '' : key, code;
    if (lang === 'curl') code = 'curl -sS ' + (hdr ? '-H "X-API-Key: ' + hdr + '" ' : '') + '"' + full + '"';
    else if (lang === 'python') code = 'import requests\n\nresp = requests.get(\n    "' + full + '",\n' + (hdr ? '    headers={"X-API-Key": "' + hdr + '"},\n' : '') + '    timeout=30,\n)\nresp.raise_for_status()\nprint(resp.json())';
    else code = 'const resp = await fetch("' + full + '"' + (hdr ? ', {\n  headers: { "X-API-Key": "' + hdr + '" },\n}' : '') + ');\nconst data = await resp.json();\nconsole.log(data);';
    $('pg-code').textContent = code;
    $('pg-send').disabled = u.missing.length > 0;
    if (u.missing.length) $('pg-hint').textContent = 'Required: ' + u.missing.join(', ');
    else if (!current.nokey) $('pg-hint').textContent = '';
  }
  document.querySelectorAll('#pg-tabs .tab').forEach(function (t) {
    t.addEventListener('click', function () { lang = t.getAttribute('data-lang'); document.querySelectorAll('#pg-tabs .tab').forEach(function (x) { x.setAttribute('aria-pressed', String(x === t)); }); renderCode(); });
  });

  /* ---- send ---- */
  $('pg-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var u = buildUrl(); if (u.missing.length) return;
    var key = $('pg-key').value.trim(), headers = { Accept: 'application/json' };
    if (key && !current.nokey) headers['X-API-Key'] = key;
    var started = performance.now();
    $('pg-status').textContent = 'sending…'; $('pg-status').className = 'badge'; $('pg-send').disabled = true;
    fetch(u.path, { headers: headers }).then(function (r) {
      return r.text().then(function (text) {
        var ms = Math.round(performance.now() - started), body = text;
        try { body = JSON.parse(text); } catch (err) {}
        lastBody = text;
        $('pg-status').textContent = r.status + ' ' + (r.statusText || ''); $('pg-status').className = 'badge s' + String(r.status).charAt(0);
        var meta = [ms + ' ms', (text.length / 1024).toFixed(1) + ' KB'];
        var rid = r.headers.get('X-Request-ID'); if (rid) meta.push(rid);
        var ra = r.headers.get('Retry-After'); if (ra) meta.push('retry after ' + ra + ' s');
        $('pg-meta').textContent = meta.join(' · ');
        renderJson(body); $('pg-copy-resp').disabled = false;
      });
    }).catch(function () {
      $('pg-status').textContent = 'network error'; $('pg-status').className = 'badge s5';
      $('pg-response').textContent = 'The request did not reach the API. It may be offline.';
    }).then(function () { $('pg-send').disabled = false; });
  });

  function renderJson(body) {
    var out = $('pg-response'); out.innerHTML = '';
    if (typeof body === 'string') { out.textContent = body; return; }
    var text = JSON.stringify(body, null, 2);
    var re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.appendChild(document.createTextNode(text.slice(last, m.index)));
      var cls = m[1] ? (m[2] ? 'k' : 's') : m[3] ? 'b' : m[0] === 'null' ? 'z' : 'n';
      out.appendChild(el('span', { class: cls, text: m[1] || m[0] }));
      if (m[2]) out.appendChild(document.createTextNode(m[2]));
      last = re.lastIndex;
    }
    if (last < text.length) out.appendChild(document.createTextNode(text.slice(last)));
  }

  function copy(text, btn) {
    var done = function () { var t = btn.textContent; btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = t; }, 1400); };
    try { navigator.clipboard.writeText(text).then(done, function () {}); } catch (e) {}
  }
  $('pg-copy-code').addEventListener('click', function () { copy($('pg-code').textContent, $('pg-copy-code')); });
  $('pg-copy-resp').addEventListener('click', function () { if (lastBody) copy(lastBody, $('pg-copy-resp')); });

  /* ---- defaults from live data: first showcase CIK, latest listing ISIN and LEI ---- */
  function loadDefaults() {
    var a = fetch('/v1/public/companies').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (d && d.data && d.data.length) DEFAULTS.cik = String(parseInt(d.data[0].cik, 10));
    }).catch(function () {});
    var b = fetch('/v1/public/listings/events').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      var withIsin = d && d.data ? d.data.filter(function (e) { return e.isin; })[0] : null;
      if (withIsin) DEFAULTS.isin = withIsin.isin;
    }).catch(function () {});
    return Promise.all([a, b]).then(function () {
      if (!DEFAULTS.isin) return;
      return fetch('/v1/markets/instruments/' + DEFAULTS.isin, { headers: { 'X-API-Key': 'demo' } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        var lei = d && (d.issuer && d.issuer.lei || (d.listings || []).map(function (l) { return l.issuer_lei; }).filter(Boolean)[0]);
        if (lei) DEFAULTS.lei = lei;
      }).catch(function () {});
    });
  }

  renderCatalog(); keyNote();
  var hash = (location.hash || '').replace('#', ''), autorun = /:run$/.test(hash);
  hash = hash.replace(/:run$/, '');
  select(CATALOG.some(function (e) { return e.id === hash; }) ? hash : 'listing-events');
  loadDefaults().then(function () {
    select(current.id);
    // Shareable links: /playground/#<endpoint>:run sends the request on open.
    if (autorun) $('pg-form').requestSubmit();
  });
})();
