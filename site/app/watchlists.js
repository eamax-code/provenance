/* Explorer watchlists (plan-explorer-chat X-07): named lists of companies with chosen columns and one
   event feed for the list. With a key and the API's /v1/watchlists, lists are stored on the server per
   key and "Watch" sets up the key's webhooks; without either, lists live in this browser and rows are
   built from each company's overview. Events are information, not signals. */
(function () {
  'use strict';
  var X = window.ProvenanceExplorer, $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  function money(v, cur) { if (v == null) return '—'; var a = Math.abs(v), p = (v < 0 ? '−' : '') + (!cur || cur === 'USD' ? '$' : cur + ' '); return a >= 1e12 ? p + (a / 1e12).toFixed(1) + 'T' : a >= 1e9 ? p + (a / 1e9).toFixed(1) + 'B' : a >= 1e6 ? p + (a / 1e6).toFixed(1) + 'M' : p + Math.round(a).toLocaleString('en-US'); }
  function pct(v, sign) { if (v == null || !isFinite(v)) return '—'; var r = Math.abs(v).toFixed(1); return (r === '0.0' ? '' : sign && v > 0 ? '+' : v < 0 ? '−' : '') + r + '%'; }
  var COLS = { revenue: 'Revenue', operating_margin: 'Operating margin', net_income: 'Net income', total_assets: 'Total assets', reporting_currency: 'Currency', latest_filing: 'Latest filing', last_event: 'Last event', holders_change: '13F holders' };
  var DEFAULT_COLS = ['revenue', 'operating_margin', 'latest_filing', 'last_event', 'holders_change'];
  var LKEY = 'prv_watchlists';

  /* ---- storage: the server per key when it exists; otherwise this browser ---- */
  var server = null; // null unknown, true, false
  function useServer() {
    if (!X.hasKey()) return Promise.resolve(false);
    if (server !== null) return Promise.resolve(server);
    return fetch('/openapi.json').then(function (r) { return r.ok ? r.json() : {}; }).then(function (j) { server = !!(j.paths && j.paths['/v1/watchlists']); return server; }).catch(function () { server = false; return false; });
  }
  function localLists() { try { return JSON.parse(localStorage.getItem(LKEY) || '[]').filter(function (l) { return l && l.id && Array.isArray(l.ciks); }); } catch (e) { return []; } }
  function saveLocal(lists) { try { localStorage.setItem(LKEY, JSON.stringify(lists)); } catch (e) {} }
  function send(method, path, body) {
    return fetch(path, { method: method, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-API-Key': X.key() }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.text().then(function (t) { var b = null; try { b = t ? JSON.parse(t) : null; } catch (e) {} return { ok: r.ok, status: r.status, body: b }; }); });
  }
  var api = {
    all: function () { return useServer().then(function (s) { return s ? send('GET', '/v1/watchlists?limit=50').then(function (r) { return r.ok ? (r.body.data || []) : []; }) : localLists(); }); },
    create: function (name) { return useServer().then(function (s) { if (s) return send('POST', '/v1/watchlists', { name: name, ciks: [], columns: DEFAULT_COLS }).then(function (r) { if (!r.ok) throw r; return r.body; }); var l = { id: 'local_' + Date.now().toString(36), name: name, ciks: [], columns: DEFAULT_COLS.slice() }; var all = localLists(); all.push(l); saveLocal(all); return l; }); },
    update: function (l, patch) { return useServer().then(function (s) { if (s) return send('PATCH', '/v1/watchlists/' + encodeURIComponent(l.id), patch).then(function (r) { if (!r.ok) throw r; return r.body; }); var all = localLists().map(function (x) { return x.id === l.id ? Object.assign({}, x, patch) : x; }); saveLocal(all); return Object.assign({}, l, patch); }); },
    remove: function (l) { return useServer().then(function (s) { if (s) return send('DELETE', '/v1/watchlists/' + encodeURIComponent(l.id)); saveLocal(localLists().filter(function (x) { return x.id !== l.id; })); }); }
  };

  /* ---- rows: the server's, or built from each company's overview ---- */
  var ovCache = {};
  function overview(cik) {
    if (!ovCache[cik]) ovCache[cik] = X.raw((X.hasKey() ? '/v1/companies/' : '/v1/public/companies/') + cik + '/overview').then(function (r) { return r.ok ? r.body : (X.hasKey() ? X.raw('/v1/public/companies/' + cik + '/overview').then(function (r2) { return r2.ok ? r2.body : null; }) : null); });
    return ovCache[cik];
  }
  function localRow(cik) {
    return overview(cik).then(function (d) {
      if (!d) return { cik: cik, missing: true };
      var c = d.company, cur = c.reporting_currency || 'USD', y = (d.years || []).filter(function (x) { return x.revenue != null; }), last = y[y.length - 1], prev = y[y.length - 2];
      var kf = function (m) { return (d.key_figures || []).filter(function (k) { return k.metric === m; })[0]; };
      var f = (d.filings || [])[0], e = (d.events || [])[0], o = d.ownership;
      return { cik: cik, name: c.display_name || c.legal_name, ticker: c.ticker, currency: cur,
        revenue: last ? { value: last.revenue, yoy: prev && prev.revenue > 0 && last.revenue >= 0 ? 100 * (last.revenue - prev.revenue) / prev.revenue : null, fiscal_label: last.fiscal_label, period_end: last.period_end, source_url: last.sources && last.sources.revenue } : null,
        operating_margin: last && last.operating_margin_pct != null ? { value: last.operating_margin_pct, fiscal_label: last.fiscal_label } : null,
        net_income: kf('net_income'), total_assets: kf('total_assets'),
        latest_filing: f ? { form_type: f.form_type, filing_date: f.filing_date || f.filed_date, filing_url: f.source_url || f.filing_url } : null,
        last_event: e ? { title: e.short_label || e.label, date: e.date, filing_url: e.filing_url, form_type: e.form_type } : null,
        holders_change: o && o.listed !== false ? { quarter: o.quarter, holders_count: o.holders_count, holders_change: o.holders_count_change } : null,
        events: d.events || [], filings: d.filings || [] };
    });
  }

  /* ---- the view ---- */
  var S = { lists: [], cur: null, busy: false };
  function load() {
    var host = $('watchlists'); if (!host) return;
    host.replaceChildren(el('p', { class: 'muted', text: 'Loading your lists…' }));
    useServer().then(function (srv) {
      return api.all().then(function (lists) {
        S.lists = lists; if (!S.cur || !lists.some(function (l) { return l.id === S.cur; })) S.cur = lists[0] ? lists[0].id : null;
        render(srv);
      });
    });
  }
  function current() { return S.lists.filter(function (l) { return l.id === S.cur; })[0] || null; }
  function render(srv) {
    var host = $('watchlists'), l = current();
    var side = el('nav', { class: 'wl-side', 'aria-label': 'Your watchlists' }, [
      el('ul', {}, S.lists.map(function (x) { return el('li', {}, [el('button', { type: 'button', class: 'wl-pick', 'aria-pressed': String(x.id === S.cur), on: { click: function () { S.cur = x.id; render(srv); } } }, [x.name, el('span', { class: 'muted small', text: ' ' + x.ciks.length })])]); })),
      el('form', { class: 'row wl-new', on: { submit: function (e) { e.preventDefault(); var n = e.target.querySelector('input').value.trim().slice(0, 80); if (!n) return; api.create(n).then(function (x) { S.cur = x.id; load(); }).catch(function (r) { X.toast(r && r.body && r.body.error ? r.body.error.message : 'Could not create the list.', 'error'); }); } } }, [el('label', { class: 'sr-only', for: 'wl-name', text: 'New list name' }), el('input', { id: 'wl-name', type: 'text', maxlength: '80', placeholder: 'New list, e.g. Energy majors' }), el('button', { type: 'submit', class: 'btn small', text: 'Create' })]),
      el('p', { class: 'muted small', text: srv ? 'Stored with your key on the server.' : X.hasKey() ? 'Stored in this browser until server lists are available.' : 'Stored in this browser. Connect a key to keep lists on the server.' })]);
    var main = el('section', { class: 'wl-main' }, [l ? el('p', { class: 'muted', text: 'Loading…' }) : el('p', { class: 'muted', text: 'Create a list, then add companies from here or with "Add to watchlist" on any company.' })]);
    host.replaceChildren(el('div', { class: 'wl-grid' }, [side, main]));
    if (l) renderList(l, main, srv);
  }
  function renderList(l, main, srv) {
    var cols = (l.columns || DEFAULT_COLS).filter(function (c) { return COLS[c]; });
    // server rows nest cells by column (X-07); flatten them to the same shape as local rows
    var flat = function (x) {
      var c = x.cells || {}, o = { cik: x.cik, name: window.Workspace ? window.Workspace.orgName(x.display_name) : x.display_name, ticker: x.ticker, currency: c.reporting_currency || 'USD' };
      Object.keys(c).forEach(function (k) { var v = c[k]; o[k] = v && typeof v === 'object' && v.yoy ? Object.assign({}, v, { yoy: v.yoy.value_pct }) : v; });
      return o;
    };
    var rowsP = srv ? send('GET', '/v1/watchlists/' + encodeURIComponent(l.id) + '/rows').then(function (r) { return r.ok ? (r.body.data || []).map(flat) : []; }) : Promise.all(l.ciks.map(function (c) { return localRow(String(parseInt(c, 10))); }));
    rowsP.then(function (rows) {
      var head = el('tr', {}, [el('th', { scope: 'col', text: 'Company' })].concat(cols.map(function (c) { return el('th', { scope: 'col', class: /revenue|margin|income|assets|holders/.test(c) ? 'n' : '', text: COLS[c] }); })).concat([el('th', { scope: 'col', text: '' })]));
      var body = rows.map(function (r) {
        var cik = String(parseInt(r.cik, 10)), cur = r.currency || r.reporting_currency || 'USD';
        var cell = function (c) {
          var v = r[c];
          if (c === 'reporting_currency') return el('td', { text: cur });
          if (v == null) return el('td', { class: 'n muted', title: 'not reported', text: '—' });
          if (c === 'revenue' || c === 'net_income' || c === 'total_assets') return el('td', { class: 'n' }, [window.ProvCard ? window.ProvCard.door(money(v.value, cur), Object.assign({ label: COLS[c], currency: cur }, v)) : money(v.value, cur), v.yoy != null ? el('span', { class: 'muted small', text: ' ' + pct(v.yoy, true) }) : null]);
          if (c === 'operating_margin') return el('td', { class: 'n', text: pct(v.value) });
          if (c === 'holders_change') return el('td', { class: 'n', text: v.holders_count != null ? Number(v.holders_count).toLocaleString('en-US') + (v.holders_change != null ? ' (' + (v.holders_change >= 0 ? '+' : '−') + Math.abs(v.holders_change) + ')' : '') : '—' });
          if (c === 'latest_filing') return el('td', {}, [ARCHIVE.test(v.filing_url || '') ? el('a', { href: v.filing_url, target: '_blank', rel: 'noopener', text: v.form_type + ' ↗' }) : v.form_type, el('span', { class: 'muted small', text: ' ' + day(v.filing_date) })]);
          if (c === 'last_event') return el('td', {}, [v.title || v.short_label || '', el('span', { class: 'muted small', text: ' ' + day(v.date) })]);
          return el('td', { text: String(v) });
        };
        return el('tr', {}, [el('th', { scope: 'row' }, [el('a', { href: '/app/?c=' + cik, text: r.name || r.display_name || 'CIK ' + cik }), r.ticker ? el('span', { class: 'muted small', text: ' ' + r.ticker }) : null])].concat(cols.map(cell)).concat([el('td', {}, [el('button', { type: 'button', class: 'x', 'aria-label': 'Remove ' + (r.name || cik) + ' from the list', text: '×', on: { click: function () { var ciks = l.ciks.filter(function (x) { return String(parseInt(x, 10)) !== cik; }); api.update(l, { ciks: ciks }).then(load); } } })])]));
      });
      // add a company: the same search as the palette
      var q = el('input', { type: 'search', placeholder: 'Add a company: ticker, name or CIK', 'aria-label': 'Add a company to this list', autocomplete: 'off' }), sug = el('ul', { class: 'results wl-sug' }), t;
      q.addEventListener('input', function () { clearTimeout(t); var v = q.value.trim(); if (!v) { sug.textContent = ''; return; } t = setTimeout(function () { X.raw((X.hasKey() ? '/v1/companies/search?limit=6&q=' : '/v1/public/companies/search?q=') + encodeURIComponent(v)).then(function (r) { if (!r.ok || q.value.trim() !== v) return; sug.replaceChildren.apply(sug, (r.body.data || []).filter(function (c) { return X.hasKey() || c.is_public_page; }).slice(0, 6).map(function (c) { var li = el('li', { tabindex: '0', role: 'button' }, [el('span', { text: window.Workspace ? window.Workspace.orgName(c.display_name || c.legal_name) : c.display_name || c.legal_name }), el('span', { class: 'mono', text: [c.ticker, 'CIK ' + parseInt(c.cik, 10)].filter(Boolean).join(' · ') })]); var add = function () { if (l.ciks.length >= 50) return; api.update(l, { ciks: l.ciks.concat([String(parseInt(c.cik, 10))]).filter(function (x, i, a) { return a.indexOf(x) === i; }) }).then(load); }; li.addEventListener('click', add); li.addEventListener('keydown', function (e) { if (e.key === 'Enter') add(); }); return li; })); }); }, 160); });
      var colSel = el('select', { 'aria-label': 'Add a column', on: { change: function (e) { if (e.target.value && cols.length < 8) api.update(l, { columns: cols.concat([e.target.value]) }).then(load); } } }, [el('option', { value: '', text: '+ Column' })].concat(Object.keys(COLS).filter(function (c) { return cols.indexOf(c) < 0; }).map(function (c) { return el('option', { value: c, text: COLS[c] }); })));
      var cmp = rows.length > 1 ? el('a', { class: 'btn small', href: '/app/?c=' + parseInt(rows[0].cik, 10) + '&tab=compare&cmp=' + rows.slice(1, 5).map(function (r) { return parseInt(r.cik, 10); }).join(','), text: rows.length > 5 ? 'Compare the first five' : 'Compare all ' + rows.length }) : null;
      var del = el('button', { type: 'button', class: 'btn small danger', text: 'Delete list', on: { click: function () { if (del.dataset.sure) { api.remove(l).then(function () { S.cur = null; load(); }); } else { del.dataset.sure = '1'; del.textContent = 'Delete “' + l.name + '”?'; } } } });
      var watch = srv ? watchForm(l) : null;
      main.replaceChildren.apply(main, [el('div', { class: 'ch-bar' }, [el('h3', { text: l.name }), el('span', { class: 'muted small', text: rows.length + ' of 50 companies' }), el('span', { class: 'ch-acts' }, [cmp, del])]),
        el('div', { class: 'row wl-add' }, [q, colSel]), sug,
        rows.length ? el('div', { class: 'tw' }, [el('table', { class: 'ov-table wl-table' }, [el('thead', {}, [head]), el('tbody', {}, body)])]) : el('p', { class: 'muted', text: 'No companies yet. Add one above.' }),
        watch, feed(l, rows, srv)].filter(Boolean));
    });
  }
  function watchForm(l) {
    var dest = el('input', { type: 'url', placeholder: 'https://your-webhook.example/…', 'aria-label': 'Webhook address for this list', required: 'required' });
    var out = el('p', { class: 'muted small', role: 'status' });
    return el('form', { class: 'row wl-watch', on: { submit: function (e) { e.preventDefault(); send('POST', '/v1/watchlists/' + encodeURIComponent(l.id) + '/watch', { destination_type: 'webhook', destination: dest.value.trim() }).then(function (r) { out.textContent = r.ok ? 'Watching ' + ((r.body && r.body.watch_ids) || []).length + ' companies; each is a watch on your key, signed as usual.' : (r.body && r.body.error ? r.body.error.message : 'Could not set up the watches.'); }); } } }, [el('span', { class: 'muted small', text: 'Watch the list:' }), dest, el('button', { type: 'submit', class: 'btn small', text: 'Watch' }), out]);
  }
  /* X-16 "since you last looked": what this browser saw of each list last time (when, which items, which
     companies) stays in this browser; the first view on a page load is compared with it, then it is replaced */
  var SKEY = 'prv_wl_seen', before = {};
  function seenAll() { try { return JSON.parse(localStorage.getItem(SKEY) || '{}') || {}; } catch (e) { return {}; } }
  function itemKey(i) { return [i.date, i.cik, i.form, i.url, i.title].join('|'); }
  function stamp(t) { var d = new Date(t); return isNaN(d) ? '' : day(d.toISOString()) + ', ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
  var FORMS = { '4': 'Insider transaction', '3': 'Initial insider holdings', '5': 'Annual insider holdings', '144': 'Proposed insider sale', '10-K': 'Annual report', '10-Q': 'Quarterly report', '8-K': 'Current report', 'DEF 14A': 'Proxy statement', 'DEFA14A': 'Additional proxy material', 'FWP': 'Free writing prospectus', 'SC 13G': 'Ownership over 5%', 'SC 13G/A': 'Ownership over 5%, amended', 'SC 13D': 'Ownership over 5%, active', '11-K': 'Employee plan report', 'S-8': 'Employee share registration' };
  function formName(f) { return FORMS[f] || (/^424B/.test(f || '') ? 'Prospectus' : 'Filing'); }
  function feed(l, rows, srv) {
    var box = el('section', { class: 'ws-sec wl-feed', 'aria-label': 'Events for this list' }, [el('h3', { text: 'Events across the list' }), el('p', { class: 'muted small', text: 'Information, not signals. Not investment advice.' })]);
    var row = function (i, fresh) { return el('li', fresh ? { class: 'tl-new' } : {}, [el('time', { datetime: i.date, text: day(i.date) }), el('span', { class: 'tag', text: i.who }), el('span', { class: 'tl-t', text: String(i.title || '').replace(/\b(\d{4}-\d{2}-\d{2})\b/g, function (m) { return day(m); }) }), ARCHIVE.test(i.url || '') ? el('a', { href: i.url, target: '_blank', rel: 'noopener', text: (i.form || 'Filing') + ' ↗' }) : el('span')]); };
    var draw = function (items) {
      items.sort(function (a, b) { return a.date < b.date ? 1 : -1; }); items = items.slice(0, 40);
      if (!(l.id in before)) before[l.id] = seenAll()[l.id] || null; // once per page load, so a re-render keeps the marks
      var prev = before[l.id], had = {}, known = {};
      if (prev) { (prev.keys || []).forEach(function (k) { had[k] = 1; }); (prev.ciks || []).forEach(function (c) { known[c] = 1; }); }
      // new: not shown last time, for a company that was on the list then (a company added since brings its history, not news)
      var fresh = prev ? items.filter(function (i) { return !had[itemKey(i)] && known[i.cik] && (!prev.newest || i.date >= prev.newest); }) : [];
      var rest = items.filter(function (i) { return fresh.indexOf(i) < 0; });
      var all = seenAll(); all[l.id] = { t: new Date().toISOString(), keys: items.map(itemKey), ciks: rows.map(function (r) { return String(parseInt(r.cik, 10)); }), newest: items.length ? items[0].date : (prev && prev.newest) || null };
      try { localStorage.setItem(SKEY, JSON.stringify(all)); } catch (e) { /* storage blocked: nothing is marked next time */ }
      var since = prev ? stamp(prev.t) : '';
      box.appendChild(el('div', { class: 'wl-since', role: 'status' }, [
        prev ? el('p', {}, [el('b', { text: fresh.length ? fresh.length + ' new since you last looked' : 'Nothing new since you last looked' }), el('span', { class: 'muted small', text: ' · ' + since })])
          : el('p', { class: 'muted small', text: 'Next time you open this list, anything filed after now is marked new. The time of your visit stays in this browser.' })]));
      if (fresh.length) box.appendChild(el('ol', { class: 'tl tl-fresh', 'aria-label': 'New since ' + since }, fresh.map(function (i) { return row(i, true); })));
      if (fresh.length && rest.length) box.appendChild(el('h4', { class: 'wl-earlier', text: 'Earlier' }));
      box.appendChild(rest.length ? el('ol', { class: 'tl' }, rest.map(function (i) { return row(i, false); })) : fresh.length ? el('span') : el('p', { class: 'muted', text: 'No events for these companies in the filings loaded.' }));
    };
    if (srv) send('GET', '/v1/watchlists/' + encodeURIComponent(l.id) + '/events?limit=40&types=8k_item,officer_change,auditor_change,ipo,insider,13f_quarter').then(function (r) { draw(((r.ok && r.body && r.body.data) || []).map(function (i) { return { date: i.date, cik: String(parseInt(i.cik, 10)), who: i.display_name || i.cik, title: i.title, url: i.filing_url, form: i.form_type }; })); });
    else {
      var items = [];
      rows.forEach(function (r) {
        var ck = String(parseInt(r.cik, 10)), urls = {};
        (r.events || []).forEach(function (e) { urls[e.filing_url] = 1; items.push({ date: e.date, cik: ck, who: r.ticker || r.name, title: e.short_label || e.label, url: e.filing_url, form: e.form_type }); });
        // filings with no event of their own (a 10-Q, a Form 4) count as news too
        (r.filings || []).slice(0, 8).forEach(function (f) { var u = f.source_url || f.filing_url, dt = f.filing_date || f.filed_date; if (dt && !urls[u]) items.push({ date: dt, cik: ck, who: r.ticker || r.name, title: formName(f.form_type), url: u, form: f.form_type }); });
      });
      draw(items);
    }
    return box;
  }

  /* ---- "Add to watchlist" from a company ---- */
  function addCompany(cik) {
    return api.all().then(function (lists) {
      var l = lists.filter(function (x) { return x.id === S.cur; })[0] || lists[0];
      return (l ? Promise.resolve(l) : api.create('My watchlist')).then(function (list) {
        var ck = String(parseInt(cik, 10)); if (list.ciks.map(function (x) { return String(parseInt(x, 10)); }).indexOf(ck) > -1) return list;
        return api.update(list, { ciks: list.ciks.concat([ck]) });
      }).then(function (list) { S.cur = list.id; X.toast('Added to “' + list.name + '”.', 'ok'); return list; });
    });
  }
  window.ProvenanceWatchlists = { load: load, add: addCompany };
  if ($('watchlists-view') && !$('watchlists-view').hidden) load();
})();
