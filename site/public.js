/* Provenance public pages: directory, company, status, and landing live blocks.
   Keyless: only /v1/stats and /v1/public/* are called. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var fmtNum = function (v) {
    if (v == null) return 'null';
    var n = Number(v), a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B'; if (a >= 1e6) return (n / 1e6).toFixed(2) + 'M'; if (a >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toLocaleString('en-US');
  };
  var fmtInt = function (n) { return n == null ? '—' : Number(n).toLocaleString('en-US'); };
  var fmtTs = function (s) { return s ? s.replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace('Z', ' UTC') : 'null'; };
  function getJSON(path) {
    return fetch(path, { headers: { Accept: 'application/json' } }).then(function (r) {
      return r.text().then(function (t) { var b = null; try { b = t ? JSON.parse(t) : null; } catch (e) {} return { ok: r.ok, status: r.status, body: b }; });
    });
  }
  function setState(id, text) { var s = $(id); if (!s) return; s.hidden = !text; if (text) s.textContent = text; }

  /* ---- shared card ---- */
  function companyCard(c) {
    var rev = c.latest_annual_revenue, lf = c.latest_filing;
    var a = el('a', { class: 'card', href: '/companies/' + c.cik });
    a.appendChild(el('div', { class: 'ticker', text: (c.ticker || '—') + ' · ' + (c.exchange || '—') + ' · CIK ' + c.cik }));
    a.appendChild(el('div', { class: 'name', text: c.display_name || c.legal_name }));
    a.appendChild(el('div', { class: 'big', text: rev ? (rev.unit === 'USD' ? '$' + fmtNum(rev.value) : /^[A-Z]{3}$/.test(rev.unit || '') ? rev.unit + '\u00a0' + fmtNum(rev.value) : fmtNum(rev.value) + ' ' + rev.unit) : 'Revenue not reported' }));
    a.appendChild(el('div', { class: 'fine', text: rev ? 'Revenue, ' + (rev.period_label || humanDay(rev.period_end)) : 'No single annual revenue figure mapped' }));
    a.appendChild(el('div', { class: 'fine', text: lf ? 'Latest filing ' + lf.form_type + ', ' + humanDay(lf.filing_date) : 'No filings yet' }));
    a.appendChild(el('div', { class: 'fine', text: fmtInt(c.filings_count) + ' filings · ' + fmtInt(c.facts_count) + ' facts' }));
    return a;
  }

  /* the number of metrics comes from the live stats, so the sentence never goes stale */
  document.addEventListener('shell:stats', function (e) {
    var d = e.detail, n = d && d.facts && d.facts.by_metric ? Object.keys(d.facts.by_metric).length : 0, s = $('dir-metrics');
    if (s && n) s.textContent = n + ' reported';
  });
  /* ---- directory ---- */
  function directory() {
    var grid = $('dir-grid'); if (!grid) return;
    getJSON('/v1/public/companies').then(function (res) {
      if (!res.ok) throw new Error(res.status);
      grid.innerHTML = '';
      if (!res.body.data.length) { setState('dir-state', 'Nothing has been ingested yet. Once the operator seeds a universe, companies appear here.'); return; }
      setState('dir-state', '');
      res.body.data.forEach(function (c) { grid.appendChild(companyCard(c)); });
      var m = $('dir-meta'); if (m) m.textContent = 'Public pages, no key needed. A free key opens every company the same way.';
    }).catch(function () { setState('dir-state', 'Live data unavailable right now.'); });
  }

  /* ---- status page ---- */
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var humanDay = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : 'not given'; };
  function statusPage() {
    var grid = $('status-kv'); if (!grid) return;
    getJSON('/v1/stats').then(function (res) {
      if (!res.ok) throw new Error(res.status);
      var d = res.body; grid.innerHTML = '';
      // the three numbers a builder checks first
      var setLead = function (id, v) { var n = $(id); if (n) { n.textContent = v; n.classList.toggle('is-na', !/\d/.test(v)); } }; // words, not a figure: not at figure size
      var ql = d.quality_snapshot && d.quality_snapshot.latency, p50 = ql && ql.accept_to_detect_p50_seconds;
      setLead('lead-latency', p50 == null ? 'Not measured yet' : p50 < 90 ? p50 + ' s' : p50 < 5400 ? Math.round(p50 / 60) + ' min' : p50 < 172800 ? (p50 / 3600).toFixed(1) + ' hours' : Math.round(p50 / 86400) + ' days');
      // health leads (Jakob: a status page opens with the state), from fields /v1/stats already returns
      var hb = $('lead-health'), hn = $('lead-health-note');
      if (hb) { hb.lastChild.textContent = 'US filings: ' + (d.service.health || 'unknown'); hb.className = d.service.health === 'ok' ? 'is-ok' : 'is-warn'; }
      // read as a time: "last fetch 05:30 UTC" today, with the day before it otherwise
      var lf = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(d.freshness.last_successful_fetch_at || '');
      if (hn) hn.textContent = lf ? 'last fetch ' + (lf[1] === new Date().toISOString().slice(0, 10) ? '' : humanDay(lf[1]) + ', ') + lf[2] + ' UTC' : 'no successful fetch yet';
      setLead('lead-latest', d.filings.latest_filing_date ? humanDay(d.filings.latest_filing_date) : 'None yet');
      setLead('lead-companies', fmtInt(d.companies.ingested));
      var kv = function (k, v) { grid.appendChild(el('div', { class: 'kv' }, [el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v })])); };
      kv('US filings health', d.service.health); kv('Version', d.service.version);
      kv('Companies', fmtInt(d.companies.ingested) + ' ingested / ' + fmtInt(d.companies.known) + ' known'); kv('Filings', fmtInt(d.filings.total) + ' (' + fmtInt(d.filings.with_acceptance_timestamp) + ' with SEC acceptance time)');
      kv('Facts', fmtInt(d.facts.total)); kv('Facts by quality', Object.keys(d.facts.by_quality).sort().map(function (k) { return k.replace(/_/g, ' ') + ' ' + fmtInt(d.facts.by_quality[k]); }).join(' · ') || '—');
      kv('Last successful SEC fetch', fmtTs(d.freshness.last_successful_fetch_at)); kv('Poll interval', d.freshness.poll_interval_seconds + ' s');
      kv('Last ingestion run', (d.ingestion.last_run_status || 'none') + (d.ingestion.last_run_finished_at ? ' · ' + fmtTs(d.ingestion.last_run_finished_at) : '')); kv('Notifications', fmtInt(d.notifications.delivered_total) + ' delivered · ' + fmtInt(d.notifications.pending_deliveries) + ' pending · ' + fmtInt(d.notifications.failed_total) + ' failed');
      var q = d.quality_snapshot, qgrid = $('quality-kv'); qgrid.innerHTML = '';
      if (!q) { setState('quality-state', 'No quality snapshot yet; one is written at the end of each ingestion run.'); }
      else {
        setState('quality-state', '');
        var qkv = function (k, v) { qgrid.appendChild(el('div', { class: 'kv' }, [el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v })])); };
        var dur = function (sec) { if (sec == null) return '—'; if (sec < 90) return sec + ' s'; if (sec < 5400) return Math.round(sec / 60) + ' min'; if (sec < 172800) return (sec / 3600).toFixed(1) + ' h'; return Math.round(sec / 86400) + ' days'; };
        var lat = q.latency || {};
        qkv('SEC acceptance to here, last 24 h', lat.accept_to_detect_p50_seconds == null ? 'no new filings measured' : dur(lat.accept_to_detect_p50_seconds) + ' median · ' + dur(lat.accept_to_detect_p95_seconds) + ' for 95%');
        qkv('New filings, last 24 h', fmtInt(lat.filings_processed_24h || 0));
        qkv('Taken at', fmtTs(q.taken_at)); qkv('Stale companies', fmtInt(q.companies.stale)); qkv('Duplicate filings', fmtInt(q.filings.duplicates));
        qkv('Facts with full provenance', q.facts.with_provenance_pct == null ? 'none (no facts)' : q.facts.with_provenance_pct + '%'); qkv('Ambiguous mappings', fmtInt(q.facts.by_quality.ambiguous_mapping)); qkv('Invalid source values', fmtInt(q.facts.by_quality.invalid_source_value));
        qkv('Oldest pending delivery', q.notifications.oldest_pending_age_seconds == null ? 'none' : q.notifications.oldest_pending_age_seconds + ' s'); qkv('Universe', fmtInt(q.universe.active) + ' active · ' + fmtInt(q.universe.due) + ' due · ' + fmtInt(q.universe.disabled) + ' disabled');
      }
      var g = $('status-generated'); if (g) g.textContent = 'generated ' + fmtTs(d.generated_at) + ' · cached ' + d.cache_ttl_seconds + ' s';
      var L = d.listings || {}, lgrid = $('listings-kv');
      if (lgrid) {
        lgrid.innerHTML = '';
        var lkv = function (k, v) { lgrid.appendChild(el('div', { class: 'kv' }, [el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v })])); };
        var evs = L.events_by_type || {};
        lkv('Venues covered', fmtInt(L.venues)); lkv('Instruments tracked', fmtInt(L.instruments));
        lkv('Events by type', Object.keys(evs).sort().map(function (k) { return k.replace(/_/g, ' ') + ' ' + fmtInt(evs[k]); }).join(' · ') || 'none yet');
        setState('listings-status-state', (L.instruments || 0) > 0 ? '' : 'No international listings ingested yet. Run scripts/ingest_markets.py --all.');
      }
      var usEmpty = d.service.health === 'empty';
      setState('status-state', usEmpty && (L.instruments || 0) === 0 ? 'Nothing has been ingested yet.' : (usEmpty ? 'US filings: none ingested yet (SEC access needs a contact address in the User-Agent). International listings are live below.' : ''));
    }).catch(function () { setState('status-state', 'Live status unavailable right now.'); });
  }

  /* ---- landing live blocks ---- */
  function landing() {
    if (!$('live-data')) return;
    getJSON('/v1/public/plans').then(function (res) {
      if (!res.ok) return;
      res.body.data.forEach(function (p) {
        var card = document.querySelector('.plan[data-plan="' + p.name + '"]'); if (!card) return;
        var price = card.querySelector('[data-price]');
        if (price && p.price_usd_per_month != null) { price.setAttribute('data-monthly', String(p.price_usd_per_month)); price.setAttribute('data-annual', String(p.annual_price_usd_per_month)); if (!document.getElementById('bill-annual') || document.getElementById('bill-annual').getAttribute('aria-pressed') !== 'true') price.textContent = '$' + p.price_usd_per_month; else price.textContent = '$' + p.annual_price_usd_per_month; }
        var lim = { rate: fmtInt(p.rate_limit_per_minute) + ' requests / minute', monthly: fmtInt(p.monthly_request_quota) + ' requests / month', watches: fmtInt(p.max_watches) + ' watched companies', export: fmtInt(p.max_export_rows) + ' rows per export' };
        Object.keys(lim).forEach(function (k) { var li = card.querySelector('[data-limit="' + k + '"]'); if (li) li.textContent = lim[k]; });
        var row = function (key) { return document.querySelector('[data-compare="' + key + '"] [data-plan-col="' + p.name + '"]'); };
        var cells = { rate: fmtInt(p.rate_limit_per_minute), monthly: fmtInt(p.monthly_request_quota), watches: fmtInt(p.max_watches), export: fmtInt(p.max_export_rows) };
        Object.keys(cells).forEach(function (k) { var c = row(k); if (c) c.textContent = cells[k]; });
      });
      var tag = $('pricing-live'); if (tag) tag.textContent = 'Limits loaded live from /v1/public/plans · ' + res.body.pricing_status + ' pricing';
    }).catch(function () {});
    getJSON('/v1/public/companies').then(function (res) {
      var grid = $('live-data-grid'); if (!grid) return;
      if (!res.ok) throw new Error(res.status);
      grid.innerHTML = '';
      if (!res.body.data.length) { setState('live-data-state', 'No companies ingested yet. The operator seeds a universe with scripts/bulk_ingest.py.'); return; }
      setState('live-data-state', '');
      res.body.data.slice(0, 6).forEach(function (c) { grid.appendChild(companyCard(c)); });
      var first = res.body.data.filter(function (c) { return c.latest_annual_revenue; })[0];
      if (first) renderHeroSample(first);
    }).catch(function () { setState('live-data-state', 'Live data unavailable right now; the sample above is illustrative.'); });
  }
  function renderHeroSample(c) {
    var pre = $('hero-sample'), bar = $('hero-sample-url'); if (!pre) return;
    var r = c.latest_annual_revenue;
    var span = function (cls, text) { return el('span', { class: cls, text: text }); };
    var lines = [
      ['metric', '"revenue"', 's'], ['value', String(r.value), 'n'], ['unit', JSON.stringify(r.unit), 's'], ['period_start', JSON.stringify(r.period_start), 's'], ['period_end', JSON.stringify(r.period_end), 's'],
      ['period_class', '"annual"', 's'], ['form_type', JSON.stringify(r.form_type), 's'], ['accession_number', JSON.stringify(r.accession_number), 's'], ['source_tag', JSON.stringify(r.source_tag), 's'], ['source_url', JSON.stringify(r.source_url), 's'],
      ['mapping_version', '"1.1.0"', 's'], ['quality_status', JSON.stringify(r.quality_status), 's'], ['derived', 'false', 'n']
    ];
    pre.innerHTML = ''; pre.appendChild(document.createTextNode('{\n'));
    lines.forEach(function (l, i) { pre.appendChild(document.createTextNode('  ')); pre.appendChild(span('k', '"' + l[0] + '"')); pre.appendChild(document.createTextNode(': ')); pre.appendChild(span(l[2], l[1])); pre.appendChild(document.createTextNode(i < lines.length - 1 ? ',\n' : '\n')); });
    pre.appendChild(document.createTextNode('}  ')); pre.appendChild(span('c', '// live: ' + c.legal_name + ' latest annual revenue from /v1/public/companies'));
    if (bar) bar.textContent = 'GET /v1/companies/' + c.cik + '/facts?metric=revenue&period=annual';
  }

  /* ---- listings page ---- */
  var EVENT = { new_listing: 'New listing', ipo: 'First admission', delisting: 'Delisted', suspended: 'Suspended', reinstated: 'Reinstated', modified: 'Details changed' };
  var SOURCE = { esma_firds: 'ESMA FIRDS', fca_firds: 'FCA FIRDS', gleif: 'GLEIF', tmx: 'TMX lists', cse: 'CSE list' };
  function listingsPage() {
    var tbl = $('listings-table'); if (!tbl) return;
    getJSON('/v1/public/listings/events').then(function (res) {
      if (!res.ok) throw new Error(res.status);
      var tb = tbl.querySelector('tbody'); tb.innerHTML = '';
      if (!res.body.data.length) { setState('listings-state', 'No listing events yet. Run scripts/ingest_markets.py --all to pull the latest FIRDS deltas.'); return; }
      setState('listings-state', '');
      res.body.data.forEach(function (e) {
        var v = res.body.venues[e.mic] || {};
        // the event date only: when we noticed a change is never shown (owner rule, 2026-11-04)
        // explicit roles: on phones each row is drawn as a card (display: grid), which would drop table semantics
        tb.appendChild(el('tr', { role: 'row' }, [
          el('td', { role: 'cell', text: humanDay(e.event_date) }),
          el('td', { role: 'cell' }, [el('span', { class: 'badge', text: (EVENT[e.event_type] || e.event_type.replace(/_/g, ' ')) })]),
          el('td', { role: 'cell', class: 'wrap', text: e.issuer_name }),
          el('td', { role: 'cell', class: 'mono', text: e.isin || e.symbol || e.listing_key }),
          el('td', { role: 'cell', text: e.mic + ' · ' + (v.name || '') + (v.country ? ' (' + v.country + ')' : '') }),
          el('td', { role: 'cell', text: SOURCE[e.source] || e.source })
        ]));
      });
      var m = $('listings-meta'); if (m) m.textContent = res.body.data.length + ' events · generated ' + fmtTs(res.body.generated_at);
    }).catch(function () { setState('listings-state', 'Live data unavailable right now.'); });
  }

  directory(); statusPage(); landing(); listingsPage();
})();
