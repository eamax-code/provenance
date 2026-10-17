/* Provenance Explorer: framework-free client for the Provenance API. The API key lives in
   this browser only (localStorage) and is sent as X-API-Key to the same origin. */
(function () {
  'use strict';
  var KEY = 'prv_api_key';
  var state = { key: null, company: null, filingsOffset: 0, polling: null, view: 'explore', tab: 'facts' };
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else if (k === 'html') n.innerHTML = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var fmtNum = function (v) {
    if (v == null) return 'null';
    var n = Number(v); if (!isFinite(n)) return String(v);
    var abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B'; if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M'; if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toLocaleString('en-US');
  };
  var fmtTs = function (s) { return s ? s.replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace('Z', ' UTC') : 'null'; };
  var toastTimer;
  function toast(msg, kind) {
    var t = $('toast'); t.textContent = msg; t.className = 'toast ' + (kind || ''); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 6000);
  }
  function storage(get, value) { try { if (get) return localStorage.getItem(KEY); if (value === null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, value); } catch (e) { return null; } }

  /* ---- API ---- */
  function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    if (state.key) headers['X-API-Key'] = state.key;
    if (opts.body) headers['Content-Type'] = 'application/json';
    return fetch(path, { method: opts.method || 'GET', headers: headers, body: opts.body ? JSON.stringify(opts.body) : undefined }).then(function (r) {
      return r.text().then(function (text) {
        var body = null; try { body = text ? JSON.parse(text) : null; } catch (e) { body = null; }
        if (r.status === 401) { signOut('Your API key was rejected. Paste a valid key.'); throw new Error('unauthorized'); }
        if (r.status === 429) { var ra = r.headers.get('Retry-After'); toast('Rate limited. Retry in ' + (ra || 'a few') + ' seconds.', 'error'); throw new Error('rate_limited'); }
        if (!r.ok && r.status !== 202) { var msg = body && body.error ? body.error.message + ' (' + body.error.code + ', ' + body.error.request_id + ')' : 'HTTP ' + r.status; toast(msg, 'error'); throw new Error(msg); }
        return { status: r.status, body: body, headers: r.headers };
      });
    });
  }

  /* ---- session ---- */
  function setKey(key) {
    state.key = key; storage(false, key);
    $('gate').hidden = true; $('signout').hidden = false;
    $('key-pill').classList.add('on'); $('key-label').textContent = key.slice(0, 17) + '…';
    showView(state.view);
  }
  function signOut(message) {
    state.key = null; storage(false, null); state.company = null;
    $('gate').hidden = false; $('signout').hidden = true; $('key-pill').classList.remove('on'); $('key-label').textContent = 'no key';
    $('explore').hidden = true; $('console').hidden = true; $('company').hidden = true;
    if (message) { $('gate-status').textContent = message; }
  }
  $('key-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var key = $('key-input').value.trim(); if (!key) return;
    $('gate-status').textContent = 'Checking key…';
    state.key = key;
    api('/v1/developer/usage').then(function (res) {
      $('gate-status').textContent = '';
      setKey(key);
      toast('Connected. Plan: ' + res.body.plan.plan + ' · ' + res.body.plan.monthly_requests_used + '/' + res.body.plan.monthly_request_quota + ' requests this month.', 'ok');
      $('key-input').value = '';
    }).catch(function () { state.key = null; if (!$('gate-status').textContent) $('gate-status').textContent = 'Could not verify the key.'; });
  });
  $('signout').addEventListener('click', function () { signOut('Signed out. The key was removed from this browser.'); });

  /* ---- views & tabs ---- */
  function showView(name) {
    state.view = name;
    document.querySelectorAll('.view-btn').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-view') === name)); });
    $('explore').hidden = name !== 'explore'; $('console').hidden = name !== 'console';
    if (name === 'console' && window.ProvenanceConsole) window.ProvenanceConsole.load(api, toast);
    try { location.hash = name; } catch (e) {}
  }
  document.querySelectorAll('.view-btn').forEach(function (b) { b.addEventListener('click', function () { if (state.key) showView(b.getAttribute('data-view')); }); });
  document.querySelectorAll('.tab').forEach(function (b) {
    b.addEventListener('click', function () {
      state.tab = b.getAttribute('data-tab');
      document.querySelectorAll('.tab').forEach(function (t) { t.setAttribute('aria-pressed', String(t === b)); });
      ['facts', 'filings', 'freshness'].forEach(function (p) { $('pane-' + p).hidden = p !== state.tab; });
      loadTab();
    });
  });

  /* ---- search ---- */
  $('search-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var q = $('q').value.trim(); if (!q) return;
    var list = $('results'); list.innerHTML = ''; list.appendChild(el('li', { class: 'skeleton', text: 'Searching…' }));
    api('/v1/companies/search?q=' + encodeURIComponent(q) + '&limit=10').then(function (res) {
      list.innerHTML = '';
      var data = res.body.data;
      if (!data.length) {
        list.appendChild(el('li', { class: 'skeleton', text: 'No match in this deployment. If you know the CIK, open it directly:' }));
        if (/^\d{1,10}$/.test(q)) { var open = el('button', { class: 'btn small', type: 'button', text: 'Open CIK ' + q }); open.addEventListener('click', function () { openCompany(q); }); list.appendChild(el('li', {}, [open])); }
        return;
      }
      data.forEach(function (c) {
        var li = el('li', {}, [
          el('div', {}, [el('strong', { text: c.legal_name || '(name pending ingestion)' }), ' ', el('span', { class: 'mono', text: (c.ticker || '—') + ' · ' + (c.exchange || '—') + ' · CIK ' + c.cik })]),
          el('span', { class: 'badge ' + (c.ingestion_status === 'complete' ? 'ok' : c.ingestion_status), text: c.match_type + ' · ' + c.ingestion_status })
        ]);
        li.addEventListener('click', function () { openCompany(c.cik); });
        list.appendChild(li);
      });
    }).catch(function () { list.innerHTML = ''; });
  });

  /* ---- company ---- */
  function openCompany(cik) {
    clearTimeout(state.polling);
    $('company').hidden = false; $('results').innerHTML = '';
    $('c-name').textContent = 'Loading…'; $('c-cik').textContent = 'CIK ' + cik; $('c-meta').textContent = ''; $('c-badges').innerHTML = '';
    api('/v1/companies/' + encodeURIComponent(cik)).then(function (res) {
      var c = res.body;
      state.company = c;
      $('c-cik').textContent = 'CIK ' + c.cik;
      $('c-name').textContent = c.legal_name || 'Ingesting from the SEC…';
      $('c-meta').textContent = [c.ticker, c.exchange, c.sic_description, c.state_of_incorporation ? 'inc. ' + c.state_of_incorporation : null, c.fiscal_year_end ? 'FYE ' + c.fiscal_year_end : null].filter(Boolean).join(' · ');
      var badges = $('c-badges'); badges.innerHTML = '';
      badges.appendChild(el('span', { class: 'badge ' + c.ingestion_status, text: c.ingestion_status }));
      badges.appendChild(el('span', { class: 'badge ' + c.quality_status, text: 'quality ' + c.quality_status }));
      badges.appendChild(el('span', { class: 'badge', text: (c.filings_count || 0) + ' filings · ' + (c.facts_count || 0) + ' facts' }));
      var src = el('a', { class: 'badge', href: c.source_url, target: '_blank', rel: 'noopener', text: 'SEC source ↗' }); badges.appendChild(src);
      if (res.status === 202) {
        var wait = parseInt(res.headers.get('Retry-After') || '10', 10) * 1000;
        toast('This company is being ingested from the SEC. Refreshing in ' + Math.round(wait / 1000) + 's…');
        state.polling = setTimeout(function () { openCompany(cik); }, wait);
        return;
      }
      loadTab();
    }).catch(function (e) { if (String(e.message).indexOf('not_found') !== -1 || /404/.test(e.message)) $('c-name').textContent = 'Not found'; });
  }
  function loadTab() {
    if (!state.company || state.company.ingestion_status !== 'complete') return;
    if (state.tab === 'facts') loadFacts(); else if (state.tab === 'filings') { state.filingsOffset = 0; loadFilings(false); } else loadFreshness();
  }

  /* ---- facts ---- */
  ['f-metric', 'f-period', 'f-derived', 'f-all'].forEach(function (id) { $(id).addEventListener('change', loadFacts); });
  function loadFacts() {
    var c = state.company; if (!c) return;
    var params = new URLSearchParams({ metric: $('f-metric').value, period: $('f-period').value, limit: '100', include_derived: String($('f-derived').checked), include_all_observations: String($('f-all').checked) });
    $('facts-note').textContent = 'Loading…';
    api('/v1/companies/' + c.cik + '/facts?' + params).then(function (res) {
      var rows = res.body.data;
      $('facts-note').textContent = res.body.notes.join(' ') + (res.body.meta.total_matched != null ? ' Showing ' + rows.length + ' of ' + res.body.meta.total_matched + '.' : '');
      drawChart(rows.slice().reverse());
      var tb = $('facts-table').querySelector('tbody'); tb.innerHTML = '';
      if (!rows.length) tb.appendChild(el('tr', {}, [el('td', { colspan: '9', class: 'skeleton', text: 'No facts for this metric and period. Missing facts mean the SEC company-facts API did not expose a mappable value, not that the issuer has none.' })]));
      rows.forEach(function (f) {
        tb.appendChild(el('tr', {}, [
          el('td', { class: 'mono', text: (f.period_start ? f.period_start + ' → ' : '') + f.period_end }),
          el('td', { text: f.period_class + (f.fiscal_period ? ' (' + f.fiscal_period + ' FY' + f.fiscal_year + ')' : '') }),
          el('td', { class: 'num', text: fmtNum(f.value), title: f.value == null ? 'null' : String(f.value) }),
          el('td', { text: f.unit }),
          el('td', { text: f.form_type || '—' }),
          el('td', { class: 'mono', text: f.filed_date || '—' }),
          el('td', { class: 'mono wrap', text: f.source_tag + (f.revision_count > 1 ? ' · ' + f.revision_count + ' obs' : '') }),
          el('td', {}, [el('span', { class: 'badge ' + f.quality_status, text: f.quality_status + (f.derived ? ' (derived)' : '') })]),
          el('td', {}, [el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: f.accession_number || 'source' })])
        ]));
      });
    }).catch(function () { $('facts-note').textContent = ''; });
  }
  function drawChart(rows) {
    var svg = $('chart'); while (svg.firstChild) svg.removeChild(svg.firstChild);
    var NS = 'http://www.w3.org/2000/svg';
    var mk = function (tag, attrs) { var n = document.createElementNS(NS, tag); Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); }); return n; };
    var pts = rows.filter(function (r) { return r.value != null; }).slice(-24);
    var W = 800, H = 260, padL = 64, padR = 12, padT = 14, padB = 44;
    if (!pts.length) { var t = mk('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' }); t.textContent = 'No numeric values to chart'; svg.appendChild(t); return; }
    var vals = pts.map(function (p) { return Number(p.value); });
    var max = Math.max(0, Math.max.apply(null, vals)), min = Math.min(0, Math.min.apply(null, vals));
    var span = (max - min) || 1, iw = W - padL - padR, ih = H - padT - padB;
    var y = function (v) { return padT + (max - v) / span * ih; };
    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {
      var v = min + span * i / ticks, yy = y(v);
      svg.appendChild(mk('line', { x1: padL, x2: W - padR, y1: yy, y2: yy, class: 'grid' }));
      var lbl = mk('text', { x: padL - 8, y: yy + 4, 'text-anchor': 'end' }); lbl.textContent = fmtNum(v); svg.appendChild(lbl);
    }
    svg.appendChild(mk('line', { x1: padL, x2: W - padR, y1: y(0), y2: y(0), class: 'axis' }));
    var bw = iw / pts.length;
    pts.forEach(function (p, idx) {
      var v = Number(p.value), x = padL + idx * bw + bw * 0.15, h = Math.abs(y(v) - y(0));
      var rect = mk('rect', { x: x, y: Math.min(y(v), y(0)), width: Math.max(2, bw * 0.7), height: Math.max(1, h), rx: 2, class: 'bar' + (p.derived ? ' derived' : '') + (v < 0 ? ' neg' : '') });
      var title = document.createElementNS(NS, 'title'); title.textContent = p.period_end + ': ' + Number(p.value).toLocaleString('en-US') + ' ' + p.unit + (p.derived ? ' (derived)' : '') + ' · ' + p.quality_status; rect.appendChild(title);
      svg.appendChild(rect);
      if (pts.length <= 12 || idx % Math.ceil(pts.length / 12) === 0) { var xl = mk('text', { x: x + bw * 0.35, y: H - padB + 16, 'text-anchor': 'middle' }); xl.textContent = p.period_end.slice(0, 7); svg.appendChild(xl); }
    });
    var cap = mk('text', { x: W - padR, y: H - 6, 'text-anchor': 'end' }); cap.textContent = $('f-metric').value + ' · ' + (pts[0].unit || '') + ' · amber = derived by subtraction'; svg.appendChild(cap);
  }

  /* ---- filings ---- */
  $('fl-apply').addEventListener('click', function () { state.filingsOffset = 0; loadFilings(false); });
  $('fl-more').addEventListener('click', function () { loadFilings(true); });
  function loadFilings(append) {
    var c = state.company; if (!c) return;
    var params = new URLSearchParams({ limit: '50', offset: String(state.filingsOffset) });
    if ($('fl-form').value.trim()) params.set('form_type', $('fl-form').value.trim());
    if ($('fl-since').value) params.set('since', $('fl-since').value);
    api('/v1/companies/' + c.cik + '/filings?' + params).then(function (res) {
      var tb = $('filings-table').querySelector('tbody'); if (!append) tb.innerHTML = '';
      if (!res.body.data.length && !append) tb.appendChild(el('tr', {}, [el('td', { colspan: '7', class: 'skeleton', text: 'No filings match.' })]));
      res.body.data.forEach(function (f) {
        tb.appendChild(el('tr', {}, [
          el('td', { class: 'mono', text: f.filing_date || 'null' }), el('td', { text: f.form_type }), el('td', { class: 'mono', text: f.accession_number }),
          el('td', { class: 'mono', text: fmtTs(f.accepted_at) }), el('td', { class: 'mono', text: fmtTs(f.first_detected_at) }),
          el('td', {}, [el('span', { class: 'badge ' + f.quality_status, text: f.quality_status })]),
          el('td', {}, [el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: 'SEC index ↗' })])
        ]));
      });
      $('fl-more').hidden = !res.body.meta.has_more;
      if (res.body.meta.has_more) state.filingsOffset = res.body.meta.next_offset;
    });
  }

  /* ---- freshness ---- */
  function loadFreshness() {
    var c = state.company; if (!c) return;
    api('/v1/companies/' + c.cik + '/freshness').then(function (res) {
      var d = res.body, grid = $('fresh-grid'); grid.innerHTML = '';
      var kv = function (k, v, cls) { grid.appendChild(el('div', { class: 'kv' }, [el('div', { class: 'k', text: k }), el('div', { class: 'v' + (cls ? ' ' + cls : ''), text: v })])); };
      kv('status', d.status); kv('last successful SEC fetch', fmtTs(d.last_successful_fetch_at)); kv('fetch age (s)', d.last_successful_fetch_age_seconds == null ? 'null' : String(d.last_successful_fetch_age_seconds));
      kv('source Last-Modified', fmtTs(d.source_updated_at)); kv('last fetch error', d.last_fetch_error || 'none');
      if (d.latest_filing) {
        var lf = d.latest_filing;
        kv('latest filing', lf.form_type + ' ' + lf.accession_number); kv('filing date', lf.filing_date || 'null'); kv('SEC accepted_at', fmtTs(lf.accepted_at));
        kv('first detected', fmtTs(lf.first_detected_at)); kv('processed', fmtTs(lf.processed_at));
        kv('publication → detection (s)', lf.publication_to_detection_seconds == null ? 'null (SEC gives no publication time)' : String(lf.publication_to_detection_seconds));
        kv('acceptance → detection (s)', lf.acceptance_to_detection_seconds == null ? 'null' : String(lf.acceptance_to_detection_seconds));
        kv('processing (s)', lf.processing_seconds == null ? 'null' : String(lf.processing_seconds));
      }
      kv('poll interval (s)', String(d.ingestion.poll_interval_seconds)); kv('last run', (d.ingestion.last_run_status || 'none') + ' · ' + fmtTs(d.ingestion.last_run_finished_at));
      var notes = $('fresh-notes'); notes.innerHTML = ''; d.notes.forEach(function (n) { notes.appendChild(el('li', { text: n })); });
    });
  }

  /* ---- boot ---- */
  var saved = storage(true);
  if (saved) { state.key = saved; api('/v1/developer/usage').then(function () { setKey(saved); }).catch(function () {}); }
  var h = (location.hash || '').replace('#', ''); if (h === 'console') state.view = 'console';
})();
