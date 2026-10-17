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

  function loadUsage() {
    var box = $('con-usage'); box.innerHTML = ''; box.appendChild(el('p', { class: 'skeleton', text: 'Loading usage…' }));
    api('/v1/developer/usage').then(function (res) {
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

  function loadWatches() {
    var box = $('con-watches'); box.innerHTML = '';
    api('/v1/watches?include_inactive=true&limit=100').then(function (res) {
      if (!res.body.data.length) { box.appendChild(el('p', { class: 'muted', text: 'No watches yet. Create one above; new filings for the company will be delivered as signed events.' })); return; }
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, [el('th', { text: 'CIK' }), el('th', { text: 'Type' }), el('th', { text: 'Destination' }), el('th', { text: 'Created' }), el('th', { text: 'Last delivered' }), el('th', { text: 'Status' }), el('th', { text: '' })])])]);
      var tb = el('tbody');
      res.body.data.forEach(function (w) {
        var actions = el('td', { class: 'row' });
        var dl = el('button', { class: 'btn small', type: 'button', text: 'Deliveries' });
        dl.addEventListener('click', function () { loadDeliveries(w); });
        actions.appendChild(dl);
        if (w.is_active) {
          var off = el('button', { class: 'btn small danger', type: 'button', text: 'Deactivate' });
          off.addEventListener('click', function () {
            if (off.getAttribute('data-armed') !== '1') { off.setAttribute('data-armed', '1'); off.textContent = 'Confirm'; setTimeout(function () { off.removeAttribute('data-armed'); off.textContent = 'Deactivate'; }, 4000); return; }
            api('/v1/watches/' + w.id, { method: 'DELETE' }).then(function () { toast('Watch deactivated. Historical deliveries are kept.', 'ok'); loadWatches(); loadUsage(); });
          });
          actions.appendChild(off);
        }
        tb.appendChild(el('tr', {}, [el('td', { class: 'mono', text: w.cik }), el('td', { text: w.destination_type }), el('td', { class: 'mono wrap', text: w.destination }), el('td', { class: 'mono', text: fmtTs(w.created_at) }), el('td', { class: 'mono', text: fmtTs(w.last_delivered_at) }), el('td', {}, [el('span', { class: 'badge ' + (w.is_active ? 'ok' : 'failed'), text: w.is_active ? 'active' : 'inactive' })]), actions]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
    });
  }

  function loadDeliveries(w) {
    var box = $('con-deliveries'); box.innerHTML = ''; box.hidden = false;
    box.appendChild(el('h3', { text: 'Deliveries for CIK ' + w.cik + ' → ' + w.destination }));
    api('/v1/watches/' + w.id + '/deliveries?limit=100').then(function (res) {
      if (!res.body.data.length) { box.appendChild(el('p', { class: 'muted', text: 'No deliveries yet. Events are created when a new filing is detected after the watch exists.' })); return; }
      var tbl = el('table', {}, [el('thead', {}, [el('tr', {}, [el('th', { text: 'Event' }), el('th', { text: 'Status' }), el('th', { class: 'num', text: 'Attempts' }), el('th', { text: 'HTTP' }), el('th', { text: 'Last error' }), el('th', { text: 'Next attempt' }), el('th', { text: 'Delivered' })])])]);
      var tb = el('tbody');
      res.body.data.forEach(function (d) {
        tb.appendChild(el('tr', {}, [el('td', { class: 'mono', text: d.event_id }), el('td', {}, [el('span', { class: 'badge ' + ({ delivered: 'ok', failed: 'failed', retrying: 'partial', pending: 'partial' }[d.status] || ''), text: d.status })]), el('td', { class: 'num', text: String(d.attempt_count) }), el('td', { text: d.last_status_code == null ? '—' : String(d.last_status_code) }), el('td', { class: 'wrap', text: d.last_error_redacted || '—' }), el('td', { class: 'mono', text: fmtTs(d.next_attempt_at) }), el('td', { class: 'mono', text: fmtTs(d.delivered_at) })]));
      });
      tbl.appendChild(tb); box.appendChild(el('div', { class: 'table-wrap' }, [tbl]));
    });
  }

  function bindCreate() {
    var form = $('watch-form'); if (form.getAttribute('data-bound')) return; form.setAttribute('data-bound', '1');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = { cik: $('w-cik').value.trim(), destination_type: $('w-type').value, destination: $('w-dest').value.trim() };
      api('/v1/watches', { method: 'POST', body: body }).then(function (res) {
        var w = res.body, out = $('watch-secret'); out.hidden = false; out.innerHTML = '';
        out.appendChild(el('p', {}, [el('strong', { text: 'Watch created for CIK ' + w.cik + '.' })]));
        if (w.webhook_secret) {
          out.appendChild(el('p', { class: 'small', text: 'Webhook secret, shown once. Verify X-Signature = v1=HMAC-SHA256(secret, "<X-Signature-Timestamp>.<body>").' }));
          var code = el('code', { class: 'secret', text: w.webhook_secret });
          var copy = el('button', { class: 'btn small', type: 'button', text: 'copy' });
          copy.addEventListener('click', function () { try { navigator.clipboard.writeText(w.webhook_secret).then(function () { copy.textContent = 'copied'; }); } catch (err) { /* selection fallback */ var r = document.createRange(); r.selectNodeContents(code); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); } });
          out.appendChild(el('div', { class: 'row' }, [code, copy]));
        }
        form.reset(); loadWatches(); loadUsage();
      });
    });
  }

  window.ProvenanceConsole = {
    load: function (apiFn, toastFn) {
      api = apiFn; toast = toastFn; bindCreate();
      $('con-deliveries').hidden = true;
      loadUsage(); loadKeys(); loadWatches();
    }
  };
})();
