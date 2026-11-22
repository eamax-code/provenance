/* Developer console: usage, keys, watches and deliveries. Loaded by app.js on demand. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var fmt = function (n) { return n == null ? '—' : Number(n).toLocaleString('en-US'); };
  var fmtTs = function (s) { return s ? s.replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace('Z', ' UTC') : '—'; };
  var api, toast;

  function bar(used, limit) {
    var pct = limit ? Math.min(100, Math.round(100 * used / limit)) : 0;
    var wrap = el('div', { class: 'meter', title: used + ' / ' + limit });
    var fill = el('div', { class: 'meter-fill' + (pct > 90 ? ' hot' : '') }); fill.style.width = pct + '%';
    wrap.appendChild(fill); return wrap;
  }

  /* Requests per UTC day: one bar a day, the error share in red on top. */
  function dailyChart(days) {
    var NS = 'http://www.w3.org/2000/svg', W = 720, H = 140, pad = 18;
    var max = Math.max(1, Math.max.apply(null, days.map(function (d) { return d.requests; })));
    var total = days.reduce(function (a, d) { return a + d.requests; }, 0);
    var errors = days.reduce(function (a, d) { return a + d.errors; }, 0);
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + (H + pad)); svg.setAttribute('class', 'usage-chart');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Requests per day: ' + fmt(total) + ' over ' + days.length + ' days, ' + fmt(errors) + ' errors, busiest day ' + fmt(max) + '.');
    var step = W / days.length, bw = Math.max(1, step * 0.72);
    days.forEach(function (d, i) {
      var x = i * step + (step - bw) / 2, h = H * d.requests / max, he = H * d.errors / max;
      var g = document.createElementNS(NS, 'g');
      var t = document.createElementNS(NS, 'title'); t.textContent = d.day + ': ' + fmt(d.requests) + ' requests, ' + fmt(d.errors) + ' errors'; g.appendChild(t);
      var ok = document.createElementNS(NS, 'rect');
      ok.setAttribute('x', x); ok.setAttribute('y', H - h); ok.setAttribute('width', bw); ok.setAttribute('height', Math.max(h, d.requests ? 1 : 0)); ok.setAttribute('class', 'ok');
      g.appendChild(ok);
      if (d.errors) {
        var er = document.createElementNS(NS, 'rect');
        er.setAttribute('x', x); er.setAttribute('y', H - h); er.setAttribute('width', bw); er.setAttribute('height', Math.max(he, 1)); er.setAttribute('class', 'err');
        g.appendChild(er);
      }
      svg.appendChild(g);
    });
    [[0, days[0].day], [days.length - 1, days[days.length - 1].day]].forEach(function (p, j) {
      var lab = document.createElementNS(NS, 'text');
      lab.setAttribute('x', j ? W : 0); lab.setAttribute('y', H + pad - 4); lab.setAttribute('text-anchor', j ? 'end' : 'start');
      lab.textContent = p[1]; svg.appendChild(lab);
    });
    return el('figure', { class: 'usage-fig' }, [svg, el('figcaption', { class: 'muted small', text: 'Requests per UTC day; red is the share that ended in an error.' })]);
  }

  function loadUsage() {
    var box = $('con-usage'); box.innerHTML = ''; box.appendChild(el('p', { class: 'skeleton', text: 'Loading usage…' }));
    var days = parseInt(($('con-window') || { value: '30' }).value, 10) || 30;
    var from = new Date(Date.now() - days * 86400000).toISOString();
    api('/v1/developer/usage?from=' + encodeURIComponent(from)).then(function (res) {
      var u = res.body, p = u.plan; box.innerHTML = '';
      var grid = el('div', { class: 'grid' });
      var kv = function (k, v, extra) { var d = el('div', { class: 'kv' }, [el('div', { class: 'k', text: k }), el('div', { class: 'v', text: v })]); if (extra) d.appendChild(extra); grid.appendChild(d); };
      kv('plan', p.plan);
      kv('requests this month', fmt(p.monthly_requests_used) + ' / ' + fmt(p.monthly_request_quota), bar(p.monthly_requests_used, p.monthly_request_quota));
      kv('rate limit', fmt(p.rate_limit_per_minute) + ' / minute');
      kv('watched companies', fmt(p.watched_companies_used) + ' / ' + fmt(p.max_watches), bar(p.watched_companies_used, p.max_watches));
      kv('export rows per request', fmt(p.max_export_rows));
      kv('window', fmtTs(u.from) + ' → ' + fmtTs(u.to));
      kv('requests (window)', fmt(u.total_requests) + ' · ' + fmt(u.successful_requests) + ' ok · ' + fmt(u.error_requests) + ' errors');
      kv('exports (window)', fmt(u.export_rows) + ' rows · ' + fmt(u.export_bytes) + ' bytes');
      box.appendChild(grid);
      if (u.daily && u.daily.length) box.appendChild(dailyChart(u.daily));
      var routes = Object.keys(u.requests_by_route);
      if (routes.length) {
        var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, [el('th', { text: 'Route' }), el('th', { class: 'num', text: 'Requests' })])])]);
        var tb = el('tbody'); routes.sort(function (a, b) { return u.requests_by_route[b] - u.requests_by_route[a]; }).forEach(function (r) { tb.appendChild(el('tr', {}, [el('td', { class: 'mono', text: r }), el('td', { class: 'num', text: fmt(u.requests_by_route[r]) })])); });
        tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
      }
    }).catch(function () { box.innerHTML = ''; });
  }

  function loadKeys() {
    var box = $('con-keys'); box.innerHTML = '';
    api('/v1/developer/api-keys').then(function (res) {
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, [el('th', { text: 'Prefix' }), el('th', { text: 'Label' }), el('th', { text: 'Plan' }), el('th', { text: 'Created' }), el('th', { text: 'Last used' }), el('th', { text: 'Status' }), el('th', { text: '' })])])]);
      var tb = el('tbody');
      res.body.data.forEach(function (k) {
        var action = el('td');
        if (k.is_active) {
          var btn = el('button', { class: 'btn small danger', type: 'button', text: 'Revoke' });
          btn.addEventListener('click', function () {
            if (btn.getAttribute('data-armed') !== '1') { btn.setAttribute('data-armed', '1'); btn.textContent = 'Confirm revoke'; setTimeout(function () { btn.removeAttribute('data-armed'); btn.textContent = 'Revoke'; }, 4000); return; }
            api('/v1/developer/api-keys/' + k.id, { method: 'DELETE' }).then(function () { toast('Key ' + k.key_prefix + '… revoked.', 'ok'); loadKeys(); });
          });
          action.appendChild(btn);
        }
        tb.appendChild(el('tr', {}, [el('td', { class: 'mono', text: k.key_prefix + '…' }), el('td', { text: k.label || '—' }), el('td', { text: k.plan }), el('td', { class: 'mono', text: fmtTs(k.created_at) }), el('td', { class: 'mono', text: fmtTs(k.last_used_at) }), el('td', {}, [el('span', { class: 'badge ' + (k.is_active ? 'ok' : 'failed'), text: k.is_active ? 'active' : 'revoked ' + fmtTs(k.revoked_at) })]), action]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
      box.appendChild(el('p', { class: 'muted small', text: 'Keys are listed for every key sharing your owner email. New keys are issued by an operator; revoking the key you are using signs you out.' }));
    });
  }

  var SPEC = null;
  function spec() { return SPEC || (SPEC = fetch('/openapi.json').then(function (r) { return r.ok ? r.json() : { paths: {} }; }).catch(function () { return { paths: {} }; })); }
  function has(path, method) { return spec().then(function (d) { return !!(d.paths && d.paths[path] && d.paths[path][method]); }); }
  function testButton(base, id, kind, cell) {
    has(base + '/{watch_id}/test', 'post').then(function (ok) {
      if (!ok) return;
      var b = el('button', { class: 'btn small', type: 'button', text: 'Send test' });
      b.addEventListener('click', function () {
        b.disabled = true; b.textContent = 'Sending…';
        api(base + '/' + id + '/test', { method: 'POST' }).then(function (res) {
          var r = res.body || {};
          toast(r.delivered ? 'Test delivered: your endpoint answered ' + r.status_code + '.' : 'Test not delivered' + (r.status_code ? ': your endpoint answered ' + r.status_code : '') + (r.error ? ' (' + r.error + ')' : '') + '.', r.delivered ? 'ok' : 'error');
        }).catch(function () {}).then(function () { b.disabled = false; b.textContent = 'Send test'; });
      });
      cell.insertBefore(b, cell.firstChild);
    });
  }
  function pauseButton(base, w, cell, reload) {
    has(base + '/{watch_id}', 'patch').then(function (ok) {
      if (!ok) return;
      if (!w.is_active) return; // deleted watches cannot be resumed
      var b = el('button', { class: 'btn small', type: 'button', text: w.paused ? 'Resume' : 'Pause' });
      b.addEventListener('click', function () {
        // the API pauses with is_active: false and resumes with true; "paused" in the response says which
        api(base + '/' + w.id, { method: 'PATCH', body: { is_active: !!w.paused } }).then(function () { toast(w.paused ? 'Resumed.' : 'Paused. Nothing is sent or queued until you resume it.', 'ok'); reload(); });
      });
      cell.appendChild(b);
    });
  }
  function loadWatches() {
    var box = $('con-watches'); box.innerHTML = '';
    api('/v1/watches?include_inactive=true&limit=100').then(function (res) {
      if (!res.body.data.length) { box.appendChild(el('p', { class: 'muted', text: 'No watches yet. Create one above; new filings for the company will be delivered as signed events.' })); return; }
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, [el('th', { text: 'CIK' }), el('th', { text: 'Type' }), el('th', { text: 'Destination' }), el('th', { text: 'Created' }), el('th', { text: 'Last delivered' }), el('th', { text: 'Status' }), el('th', { text: '' })])])]);
      var tb = el('tbody');
      res.body.data.forEach(function (w) {
        var actions = el('td', { class: 'row' });
        var dl = el('button', { class: 'btn small', type: 'button', text: 'Deliveries' });
        dl.addEventListener('click', function () { loadDeliveries('/v1/watches/' + w.id, 'CIK ' + w.cik + ' → ' + w.destination, 'a new filing is detected'); });
        actions.appendChild(dl);
        if (w.is_active && w.destination_type === 'webhook') testButton('/v1/watches', w.id, 'webhook', actions);
        pauseButton('/v1/watches', w, actions, loadWatches);
        if (w.is_active) {
          var off = el('button', { class: 'btn small danger', type: 'button', text: 'Deactivate' });
          off.addEventListener('click', function () {
            if (off.getAttribute('data-armed') !== '1') { off.setAttribute('data-armed', '1'); off.textContent = 'Confirm'; setTimeout(function () { off.removeAttribute('data-armed'); off.textContent = 'Deactivate'; }, 4000); return; }
            api('/v1/watches/' + w.id, { method: 'DELETE' }).then(function () { toast('Watch deactivated. Historical deliveries are kept.', 'ok'); loadWatches(); loadUsage(); });
          });
          actions.appendChild(off);
        }
        tb.appendChild(el('tr', {}, [el('td', { class: 'mono', text: w.cik }), el('td', { text: w.destination_type }), el('td', { class: 'mono wrap', text: w.destination }), el('td', { class: 'mono', text: fmtTs(w.created_at) }), el('td', { class: 'mono', text: fmtTs(w.last_delivered_at) }), el('td', {}, [el('span', { class: 'badge ' + (!w.is_active ? 'failed' : w.paused ? 'partial' : 'ok'), text: !w.is_active ? 'inactive' : w.paused ? 'paused' : 'active' })]), actions]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
    });
  }

  function loadDeliveries(path, label, trigger) {
    var box = $('con-deliveries'); box.innerHTML = ''; box.hidden = false;
    box.appendChild(el('h3', { text: 'Deliveries for ' + label }));
    api(path + '/deliveries?limit=100').then(function (res) {
      if (!res.body.data.length) { box.appendChild(el('p', { class: 'muted', text: 'No deliveries yet. Events are created when ' + trigger + ' after the watch exists.' })); return; }
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, [el('th', { text: 'Event' }), el('th', { text: 'Status' }), el('th', { class: 'num', text: 'Attempts' }), el('th', { text: 'HTTP' }), el('th', { text: 'Last error' }), el('th', { text: 'Next attempt' }), el('th', { text: 'Delivered' })])])]);
      var tb = el('tbody');
      res.body.data.forEach(function (d) {
        tb.appendChild(el('tr', {}, [el('td', { class: 'mono', text: d.event_id }), el('td', {}, [el('span', { class: 'badge ' + ({ delivered: 'ok', failed: 'failed', retrying: 'partial', pending: 'partial' }[d.status] || ''), text: d.status })]), el('td', { class: 'num', text: String(d.attempt_count) }), el('td', { text: d.last_status_code == null ? '—' : String(d.last_status_code) }), el('td', { class: 'wrap', text: d.last_error_redacted || '—' }), el('td', { class: 'mono', text: fmtTs(d.next_attempt_at) }), el('td', { class: 'mono', text: fmtTs(d.delivered_at) })]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
    });
  }

  /* Listing watches: new listings, delistings, suspensions on a venue, country or region. */
  var SCOPES = { mic: 'Venue (MIC)', country: 'Country', region: 'Region' };
  function loadListingWatches() {
    var box = $('con-lwatches'); if (!box) return; box.innerHTML = '';
    api('/v1/listing-watches?include_inactive=true&limit=100').then(function (res) {
      if (!res.body.data.length) { box.appendChild(el('p', { class: 'muted', text: 'No listing watches yet. Events on the venues you choose are delivered as signed webhooks or emails.' })); return; }
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, ['Scope', 'Events', 'Destination', 'Created', 'Last delivered', 'Status', ''].map(function (h) { return el('th', { text: h }); }))])]);
      var tb = el('tbody');
      res.body.data.forEach(function (w) {
        var label = SCOPES[w.scope_type] + ' ' + w.scope_value;
        var actions = el('td', { class: 'row' });
        var dl = el('button', { class: 'btn small', type: 'button', text: 'Deliveries' });
        dl.addEventListener('click', function () { loadDeliveries('/v1/listing-watches/' + w.id, label + ' → ' + w.destination, 'a listing event is read'); });
        actions.appendChild(dl);
        if (w.is_active && w.destination_type === 'webhook') testButton('/v1/listing-watches', w.id, 'webhook', actions);
        pauseButton('/v1/listing-watches', w, actions, loadListingWatches);
        if (w.is_active) {
          var off = el('button', { class: 'btn small danger', type: 'button', text: 'Deactivate' });
          off.addEventListener('click', function () {
            if (off.getAttribute('data-armed') !== '1') { off.setAttribute('data-armed', '1'); off.textContent = 'Confirm'; setTimeout(function () { off.removeAttribute('data-armed'); off.textContent = 'Deactivate'; }, 4000); return; }
            api('/v1/listing-watches/' + w.id, { method: 'DELETE' }).then(function () { toast('Listing watch deactivated. Historical deliveries are kept.', 'ok'); loadListingWatches(); loadUsage(); });
          });
          actions.appendChild(off);
        }
        tb.appendChild(el('tr', {}, [el('td', { text: label }), el('td', { text: w.event_types.join(', ').replace(/_/g, ' ') }), el('td', { class: 'mono wrap', text: w.destination }), el('td', { class: 'mono', text: fmtTs(w.created_at) }), el('td', { class: 'mono', text: fmtTs(w.last_delivered_at) }), el('td', {}, [el('span', { class: 'badge ' + (!w.is_active ? 'failed' : w.paused ? 'partial' : 'ok'), text: !w.is_active ? 'inactive' : w.paused ? 'paused' : 'active' })]), actions]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
    });
  }
  /* ---- event-type watches ---- */
  var FALLBACK_TYPES = [
    ['sec.restatement', 'Restatement (4.02)'], ['sec.auditor_change', 'Auditor change (4.01)'], ['sec.bankruptcy', 'Bankruptcy (1.03)'],
    ['sec.change_in_control', 'Change in control (5.01)'], ['sec.acquisition_completed', 'Acquisition completed (2.01)'], ['sec.material_agreement', 'Material agreement (1.01)'],
    ['sec.officer_change', 'Officer or director change (5.02)'], ['sec.shareholder_vote', 'Shareholder vote (5.07)'], ['sec.results', 'Results (2.02)'],
    ['sec.late_filing', 'Late filing (NT 10-K/Q)'], ['sec.delisting', 'Form 25 listing removal'], ['sec.deregistration', 'Deregistration (Form 15)'],
    ['sec.tender_offer', 'Tender offer'], ['sec.merger_proxy', 'Merger proxy'], ['sec.ipo_priced', 'IPO priced (424B4)']
  ];
  function eventTypes() {
    return has('/v1/event-types', 'get').then(function (ok) {
      if (!ok) return FALLBACK_TYPES.map(function (x) { return { type: x[0], label: x[1] }; });
      return api('/v1/event-types').then(function (r) { return ((r.body && (r.body.data || r.body)) || []).filter(function (e) { return e.type_watch !== false; }); });
    });
  }
  function bindTypeCreate(allowed) {
    var form = $('twatch-form'); if (!form) return;
    $('tw-plan').hidden = false; $('tw-upgrade').hidden = !!allowed;
    Array.prototype.forEach.call(form.elements, function (f) { f.disabled = !allowed; });
    var box = $('tw-types');
    if (!box.getAttribute('data-filled')) {
      box.setAttribute('data-filled', '1');
      eventTypes().then(function (list) {
        list.forEach(function (e) {
          var lab = el('label', { class: 'check', title: (e.label || e.type) + (e.delivery === 'hourly_batch' ? '. Without a filter it arrives as one hourly batch.' : '') }, [el('input', { type: 'checkbox', name: 'tw-ev', value: e.type }), ' ' + (e.short_label || e.label || e.type) + (e.delivery === 'hourly_batch' ? ' ·  hourly' : '')]);
          box.appendChild(lab);
          if (!allowed) lab.querySelector('input').disabled = true;
        });
      });
    }
    if (form.getAttribute('data-bound')) return; form.setAttribute('data-bound', '1');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var types = Array.prototype.map.call(form.querySelectorAll('input[name="tw-ev"]:checked'), function (c) { return c.value; });
      if (!types.length) { toast('Pick at least one event type.', 'error'); return; }
      var ciks = $('tw-ciks').value.split(/[\s,]+/).map(function (c) { return c.replace(/\D/g, ''); }).filter(Boolean);
      var body = { event_types: types, destination: $('tw-dest').value.trim() };
      if ($('tw-sic').value.trim()) body.sic_prefix = $('tw-sic').value.trim();
      if ($('tw-exchange').value.trim()) body.exchange = $('tw-exchange').value.trim();
      if ($('tw-filer').value) body.filer_category = $('tw-filer').value;
      if (ciks.length) body.ciks = ciks;
      api('/v1/type-watches', { method: 'POST', body: body }).then(function (res) {
        showSecret($('twatch-secret'), 'Event-type watch created for ' + types.length + ' type' + (types.length > 1 ? 's' : '') + '.', res.body.webhook_secret);
        form.reset(); loadTypeWatches(); loadUsage();
      });
    });
  }
  function scopeText(w) {
    return [w.sic_prefix && 'SIC ' + w.sic_prefix + '…', w.exchange, w.filer_category, w.ciks && w.ciks.length && w.ciks.length + ' companies'].filter(Boolean).join(' · ') || 'All companies';
  }
  function loadTypeWatches() {
    var box = $('con-twatches'); if (!box) return; box.innerHTML = '';
    api('/v1/type-watches?include_inactive=true&limit=100').then(function (res) {
      var rows = (res.body && res.body.data) || [];
      if (!rows.length) { box.appendChild(el('p', { class: 'muted', text: 'No event-type watches yet.' })); return; }
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, ['Event types', 'Companies', 'Destination', 'Delivery', 'Last delivered', 'Status', ''].map(function (h) { return el('th', { text: h }); }))])]);
      var tb = el('tbody');
      rows.forEach(function (w) {
        var actions = el('td', { class: 'row' });
        has('/v1/type-watches/{watch_id}/deliveries', 'get').then(function (ok) {
          if (!ok) return;
          var dl = el('button', { class: 'btn small', type: 'button', text: 'Deliveries' });
          dl.addEventListener('click', function () { loadDeliveries('/v1/type-watches/' + w.id, w.event_types.join(', ') + ' → ' + w.destination, 'a matching filing is read'); });
          actions.insertBefore(dl, actions.firstChild);
        });
        if (w.is_active) testButton('/v1/type-watches', w.id, 'webhook', actions);
        pauseButton('/v1/type-watches', w, actions, loadTypeWatches);
        if (w.is_active) {
          var off = el('button', { class: 'btn small danger', type: 'button', text: 'Deactivate' });
          off.addEventListener('click', function () {
            if (off.getAttribute('data-armed') !== '1') { off.setAttribute('data-armed', '1'); off.textContent = 'Confirm'; setTimeout(function () { off.removeAttribute('data-armed'); off.textContent = 'Deactivate'; }, 4000); return; }
            api('/v1/type-watches/' + w.id, { method: 'DELETE' }).then(function () { toast('Event-type watch deactivated. Historical deliveries are kept.', 'ok'); loadTypeWatches(); loadUsage(); });
          });
          actions.appendChild(off);
        }
        tb.appendChild(el('tr', {}, [el('td', { class: 'wrap', text: w.event_types.join(', ') }), el('td', { text: scopeText(w) }), el('td', { class: 'mono wrap', text: w.destination }), el('td', { text: w.delivery_mode === 'batched' || w.delivery_mode === 'hourly_batch' ? 'Hourly batch' : 'As filed' }), el('td', { class: 'mono', text: fmtTs(w.last_delivered_at) }), el('td', {}, [el('span', { class: 'badge ' + (!w.is_active ? 'failed' : w.paused ? 'partial' : 'ok'), text: !w.is_active ? 'inactive' : w.paused ? 'paused' : 'active' })]), actions]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
    }).catch(function () {});
  }
  function gateTypeWatches() {
    // the plan's own flag from the one plan table decides; Free and Analyst see the form, disabled
    Promise.all([
      api('/v1/developer/usage').then(function (r) { return r.body && r.body.plan && r.body.plan.plan; }).catch(function () { return null; }),
      fetch('/plans.json').then(function (r) { return r.json(); }).catch(function () { return { data: [] }; })
    ]).then(function (x) {
      var plan = (x[1].data || []).filter(function (p) { return p.name === x[0]; })[0];
      bindTypeCreate(x[0] === 'internal' || x[0] === 'enterprise' || !!(plan && plan.type_watches));
    });
  }

  function showSecret(out, title, secret) {
    out.hidden = false; out.innerHTML = '';
    out.appendChild(el('p', {}, [el('strong', { text: title })]));
    if (!secret) return;
    out.appendChild(el('p', { class: 'small', text: 'Webhook secret, shown once. Verify X-Signature = v1=HMAC-SHA256(secret, "<X-Signature-Timestamp>.<body>").' }));
    var code = el('code', { class: 'secret', text: secret });
    var copy = el('button', { class: 'btn small', type: 'button', text: 'copy' });
    copy.addEventListener('click', function () { try { navigator.clipboard.writeText(secret).then(function () { copy.textContent = 'copied'; }); } catch (err) { var r = document.createRange(); r.selectNodeContents(code); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); } });
    out.appendChild(el('div', { class: 'row' }, [code, copy]));
  }
  function bindListingCreate() {
    var form = $('lwatch-form'); if (!form || form.getAttribute('data-bound')) return; form.setAttribute('data-bound', '1');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var types = Array.prototype.map.call(form.querySelectorAll('input[name="lw-ev"]:checked'), function (c) { return c.value; });
      if (!types.length) { toast('Pick at least one event type.', 'error'); return; }
      var body = { scope_type: $('lw-scope').value, scope_value: $('lw-value').value.trim(), event_types: types, destination_type: $('lw-type').value, destination: $('lw-dest').value.trim() };
      api('/v1/listing-watches', { method: 'POST', body: body }).then(function (res) {
        var w = res.body;
        showSecret($('lwatch-secret'), 'Listing watch created for ' + SCOPES[w.scope_type].toLowerCase() + ' ' + w.scope_value + '.', w.webhook_secret);
        form.reset(); loadListingWatches(); loadUsage();
      });
    });
  }

  function bindCreate() {
    var win = $('con-window'); if (win && !win.getAttribute('data-bound')) { win.setAttribute('data-bound', '1'); win.addEventListener('change', loadUsage); }
    var form = $('watch-form'); if (form.getAttribute('data-bound')) return; form.setAttribute('data-bound', '1');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = { cik: $('w-cik').value.trim(), destination_type: $('w-type').value, destination: $('w-dest').value.trim() };
      api('/v1/watches', { method: 'POST', body: body }).then(function (res) {
        var w = res.body;
        showSecret($('watch-secret'), 'Watch created for CIK ' + w.cik + '.', w.webhook_secret);
        form.reset(); loadWatches(); loadUsage();
      });
    });
  }

  window.ProvenanceConsole = {
    load: function (apiFn, toastFn) {
      api = apiFn; toast = toastFn; bindCreate(); bindListingCreate(); gateTypeWatches();
      $('con-deliveries').hidden = true;
      loadUsage(); loadKeys(); loadWatches(); loadTypeWatches(); loadListingWatches();
    }
  };
})();
