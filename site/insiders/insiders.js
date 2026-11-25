/* Insider trades (Q-03, docs/contracts/insider-screener.md): open-market buys (P) and sales (S) across companies, one row
   per Form 4, code and security class. Every filter lives in the URL, so each screen has its own link. Buy and sale are
   said in words, never by colour; flags (amended, value partial, cluster) sit on the row with a tooltip each. The CSV
   starts with the disclaimer. Text nodes only, never HTML; links go to sec.gov/Archives or into the Explorer. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var KEYS = ['type', 'since', 'until', 'as_of', 'min_value', 'max_value', 'role', 'title', 'cik', 'owner_cik', 'plan_10b5_1', 'cluster', 'sort'];
  var LIMIT = 50, MAXOFF = 5000, DISC = 'Information, not signals. Not investment advice.';
  // the presets (PM-approved labels); the first is the plain default screen
  var PRESETS = [['Latest', {}], ['Large buys (over $1M)', { type: 'buy', min_value: '1000000', sort: 'value' }],
    ['CEO and CFO sales', { type: 'sell', role: 'ceo,cfo' }], // the company's own CEO and CFO (contract: role=ceo,cfo; unit CEOs are out)
    ['Cluster buys', { type: 'buy', cluster: 'true' }], ['Not under a 10b5-1 plan', { plan_10b5_1: 'false' }]];
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  // a mark without its own filing link explains itself: it opens its entry on /docs/flags/ (the tooltip stays for mice)
  var fx = function (text, title, id) { return el('a', { class: 'it-flag', href: '/docs/flags/#' + id, title: title, 'aria-label': text + ': what this means', text: text }); };
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var dmy = function (iso, yr) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + (yr === false ? '' : ' ' + m[1]) : ''; };
  var int = function (v) { return v == null ? '—' : Math.round(v).toLocaleString('en-US'); };
  var usd = function (v, dp) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: dp || 0, maximumFractionDigits: dp || 0 }); };
  var big = function (v) { if (v == null) return '—'; var a = Math.abs(v); return a >= 1e9 ? '$' + (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? '$' + (v / 1e6).toFixed(1) + 'M' : a >= 1e4 ? '$' + Math.round(v / 1e3) + 'K' : usd(v); };
  // a share price: cents, or up to four decimals under $1 so $0.098 is not read as $0.10
  var px = function (v) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: Math.abs(v) < 1 ? 4 : 2 }); };
  var pct = function (v) { return v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%'; };
  // plain common equity says nothing ("Common Stock, no par value", "Ordinary Shares", "Common units"); a class, preferred stock or anything else shows as filed
  var commonStock = function (t) { t = String(t || '').trim(); return !t || /^(common|ordinary)( stock| shares?| units?)?\b(?!.*\b(class|series|preferred)\b)/i.test(t); };

  // ---- state <-> URL ----
  var st = {};
  (function () { var u = new URLSearchParams(location.search); KEYS.forEach(function (k) { var v = u.get(k); if (v) st[k] = v.slice(0, 200); }); })();
  function params(offset) { var u = new URLSearchParams(); KEYS.forEach(function (k) { if (st[k]) u.set(k, st[k]); }); if (offset) u.set('offset', offset); return u; }
  function syncUrl() { var q = params(0).toString(); history.replaceState(null, '', '/insiders/' + (q ? '?' + q : '')); }

  // ---- presets and the form ----
  var form = $('it-form');
  function samePreset(p) { return KEYS.every(function (k) { return (st[k] || '') === (p[k] || '') || (k === 'sort' && !p.sort && (st.sort || 'date') === 'date') || (k === 'type' && !p.type && (st.type || 'all') === 'all'); }); }
  function presets() {
    $('it-presets').replaceChildren.apply($('it-presets'), PRESETS.map(function (p) {
      var a = el('a', { href: '/insiders/' + (Object.keys(p[1]).length ? '?' + new URLSearchParams(p[1]).toString() : ''), text: p[0], 'aria-current': samePreset(p[1]) ? 'page' : null });
      a.addEventListener('click', function (e) { e.preventDefault(); st = Object.assign({}, p[1]); fill(); run(); });
      return a;
    }));
  }
  function fill() {
    [].forEach.call(form.elements, function (f) {
      if (!f.name) return;
      if (f.type === 'radio') f.checked = (st[f.name] || 'all') === f.value;
      else if (f.type === 'checkbox') f.checked = (st.role || '').split(',').indexOf(f.value) > -1;
      else f.value = st[f.name] || (f.name === 'sort' ? 'date' : '');
    });
  }
  function read() {
    var next = {}, roles = [];
    [].forEach.call(form.elements, function (f) {
      if (!f.name) return;
      if (f.type === 'radio') { if (f.checked && f.value !== 'all') next.type = f.value; }
      else if (f.type === 'checkbox') { if (f.checked) roles.push(f.value); }
      else if (f.value.trim()) next[f.name] = f.name === 'cik' ? f.value.replace(/\D/g, '') : f.value.trim();
    });
    if (roles.length) next.role = roles.join(',');
    if (next.sort === 'date') delete next.sort;
    if (st.cluster && next.type !== 'sell') next.cluster = st.cluster; // set by the Cluster buys preset; the form has no field for it
    if (st.owner_cik) next.owner_cik = st.owner_cik;
    st = next;
  }
  form.addEventListener('submit', function (e) { e.preventDefault(); read(); run(); });
  // the filters open only when the screen is not one of the presets (a hand-made screen shows what made it); the presets say the rest
  $('it-sheet').open = !(window.matchMedia && matchMedia('(max-width: 760px)').matches) && !PRESETS.some(function (p) { return samePreset(p[1]); });

  // ---- rows ----
  var body = $('it-rows'), more = $('it-more'), seq = 0, next = 0, rows = [], lastBody = null;
  function trade(r) { return el('span', { class: 'it-act it-' + (r.type === 'buy' ? 'buy' : 'sell'), text: r.type === 'buy' ? 'Buy' : 'Sale' }); }
  var f0 = function (r) { return (r.filing || {}).source_url || ''; };
  function flags(r) {
    var out = [];
    if (!commonStock(r.security_title)) out.push(el('span', { class: 'it-flag', title: 'Security class as filed: ' + r.security_title, text: r.security_title }));
    // Q-03d: a 4/A that restated the row: the figures shown are the 4/A's, the original's are said beside them
    var ff = r.amended && r.first_filed, fff = ff && ff.filing || {};
    if (ff) {
      out.push(fx('Amended (4/A)', 'Figures as amended on ' + dmy((r.filing || {}).filed_date) + '; first filed: ' + int(ff.shares) + ' shares' + (ff.average_price != null ? ' at ' + px(ff.average_price) : '') + ' (Form ' + (fff.form || '4') + ')', 'amended'));
      out.push(el('span', { class: 'it-ff' }, ['First filed: ' + int(ff.shares) + (ff.average_price != null ? ' at ' + px(ff.average_price) : '') + ' ', ARCHIVE.test(fff.source_url || '') ? el('a', { href: fff.source_url, target: '_blank', rel: 'noopener', text: 'Form ' + (fff.form || '4') + ' ↗', 'aria-label': 'The original Form ' + (fff.form || '4') + ' filed ' + dmy(fff.filed_date) + ' on sec.gov' }) : null]));
    }
    (ff ? [] : r.amended_by || []).slice(0, 1).forEach(function (a) {
      var t = 'Amended (4/A) on ' + dmy(a.filed_date) + ': the figures may have been corrected. Open the amendment on sec.gov.';
      out.push(ARCHIVE.test(a.source_url || '') ? el('a', { class: 'it-flag', href: a.source_url, target: '_blank', rel: 'noopener', title: t, text: 'Amended (4/A)' + ((r.amended_by || []).length > 1 ? ' ×' + r.amended_by.length : '') }) : fx('Amended (4/A)', t, 'amended'));
    });
    if (r.value_partial) out.push(fx('Value partial', 'Value partial: some lines had no price', 'value-partial'));
    if (r.price_outlier) out.push(fx('Price looks wrong as filed', 'The price on this Form 4 is far from this company\u2019s other trades that month; it may be a total typed in the price box. Left out of value filters and ranking.', 'price-outlier'));
    (r.duplicate_filings || []).slice(0, 1).forEach(function (d) { var t = 'Filed twice: the same trades on ' + f0(r) + ' and ' + d.source_url + '. Shown once.'; out.push(ARCHIVE.test(d.source_url || '') ? el('a', { class: 'it-flag', href: d.source_url, target: '_blank', rel: 'noopener', title: t, text: 'Filed twice' }) : fx('Filed twice', t, 'filed-twice')); });
    if (r.cluster) {
      var c = r.cluster, ef = c.event_filing || {}, ct = 'Cluster buy: ' + c.insiders + ' insiders bought from ' + dmy(c.first_trade) + ' to ' + dmy(c.event_date) + '. Open the filing behind the event.';
      out.push(ARCHIVE.test(ef.source_url || '') ? el('a', { class: 'it-flag', href: ef.source_url, target: '_blank', rel: 'noopener', title: ct, text: 'Cluster buy' }) : fx('Cluster buy', ct, 'cluster'));
    }
    return out.length ? el('span', { class: 'it-flags' }, out) : null;
  }
  function who(r) {
    var os = r.owners || [], o = os[0] || {};
    var role = o.officer_title || o.role || [o.is_director ? 'Director' : null, o.is_ten_percent_owner ? '10% owner' : null].filter(Boolean).join(', ');
    return [el('span', { class: 'it-who', text: (o.name || '—') + (os.length > 1 ? ' and ' + (os.length - 1) + ' more' : ''), title: os.length > 1 ? 'Joint filing: ' + os.map(function (x) { return x.name; }).join('; ') + '. The shares are counted once.' : null }), role ? el('span', { class: 'it-role', text: role }) : null];
  }
  function row(r) {
    var i = r.issuer || {}, f = r.filing || {}, d = r.first_date === r.last_date ? dmy(r.last_date) : dmy(r.first_date, r.first_date.slice(0, 4) !== (r.last_date || '').slice(0, 4)) + ' – ' + dmy(r.last_date);
    var cell = function (cls, kids, lab) { return el('td', { role: 'cell', class: cls, 'data-l': lab }, kids); };
    return el('tr', { role: 'row' }, [
      cell('it-filed', [dmy(f.filed_date)], 'Filed'),
      cell('it-date', [d + (r.lines > 1 ? ' · ' + r.lines + ' lines' : '')], 'Traded'),
      cell('it-co', [el('a', { href: '/app/?c=' + parseInt(i.cik, 10) + '&tab=ownership', text: i.name || 'CIK ' + i.cik }), i.ticker ? el('span', { class: 'tag', text: i.ticker }) : null], 'Company'),
      cell('it-ins', who(r).concat([flags(r)]), 'Insider'),
      cell('it-tr', [trade(r)], 'Trade'),
      cell('n', [int(r.shares)], 'Shares'),
      cell('n', [px(r.average_price)], 'Avg price'),
      cell('n it-val', [r.amended && !r.shares ? (ARCHIVE.test((r.filing || {}).source_url || '') ? el('a', { href: r.filing.source_url, target: '_blank', rel: 'noopener', text: 'Cancelled by 4/A' }) : 'Cancelled by 4/A') : el(r.price_outlier ? 's' : 'span', { class: r.price_outlier ? 'it-off' : null, title: r.price_outlier ? 'As filed; the price looks wrong, so this value is left out of value filters and ranking' : r.value == null ? 'No line had a price' : usd(r.value) + (r.value_partial ? ' (some lines had no price)' : ''), text: big(r.value) + (r.value_partial ? '*' : '') })], 'Value'),
      cell('n', [el('span', { title: r.holdings_change_pct == null ? (r.direct_indirect === 'mixed' ? 'Not worked out: direct and indirect holdings mixed' : 'Not worked out: no holding after the trade, or none before') : 'Derived: ' + int(r.shares) + ' shares against the ' + int(r.shares_after + (r.type === 'sell' ? r.shares : -r.shares)) + ' held before', text: pct(r.holdings_change_pct) })], 'Holding change'),
      cell('it-plan', [r.plan_10b5_1 === true ? 'Yes' : r.plan_10b5_1 === false ? 'No' : '—'], '10b5-1'),
      cell('it-f', [ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: 'Form ' + (f.form || '4') + ' ↗', 'aria-label': 'Form ' + (f.form || '4') + ' filed ' + dmy(f.filed_date) + ' on sec.gov' }) : 'Form ' + (f.form || '4')], 'Filing')
    ]);
  }
  function words(b) {
    var fl = b.filters || {}, ty = (st.type || 'all') === 'buy' ? 'buys' : st.type === 'sell' ? 'sales' : 'buys and sales';
    var sort = st.sort === 'value' ? 'largest value first' : st.sort === 'filed' ? 'newest filing first' : 'newest trade first';
    return 'Open-market ' + ty + (fl.since ? ' traded ' + dmy(fl.since) + ' to ' + dmy(fl.until) : '') + (fl.as_of ? ', as filed by ' + dmy(fl.as_of) : '') + ' · ' + sort + (b.through ? ' · Form 4 data through ' + dmy(b.through) : '');
  }
  function say(t) { $('it-sum').textContent = t; }
  function run(append) {
    syncUrl(); presets();
    var my = ++seq, off = append ? next : 0;
    if (!append) { body.textContent = ''; rows = []; say('Loading trades…'); $('it-csv').hidden = true; }
    more.hidden = true;
    fetch('/v1/insider-transactions?' + params(off).toString() + '&limit=' + LIMIT, { headers: { Accept: 'application/json', 'X-API-Key': key() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); })
      .then(function (r) {
        if (my !== seq) return;
        if (!r.ok) {
          var e = (r.b && r.b.error) || {};
          say(r.status === 422 ? (e.message || 'One of the filters is not valid. Check the dates and values.')
            : r.status === 403 && e.code === 'demo_scope' ? 'The demo key covers the showcase companies only. Connect a free key in the Explorer to screen every company.'
            : r.status === 403 ? (e.message || 'This key cannot run that screen.')
            : r.status === 429 ? 'Too many requests this minute. Try again in a moment.' : 'The trades could not load. Check the connection and try again.');
          return;
        }
        var b = r.b, data = b.data || [], m = b.meta || {};
        if (b.labels && b.labels.disclaimer) { DISC = b.labels.disclaimer; $('it-disc').textContent = DISC; }
        data.forEach(function (x) { body.appendChild(row(x)); }); rows = rows.concat(data); lastBody = b;
        next = m.next_offset || off + data.length; more.hidden = !m.has_more || next > MAXOFF;
        say(rows.length ? rows.length + ' trade' + (rows.length === 1 ? '' : 's') + ' shown' + (m.has_more ? ', more below' : '') + ' · ' + words(b) + '.' : 'No open-market trade matches these filters. ' + words(b) + '.');
        $('it-csv').hidden = !rows.length;
        $('it-notes').replaceChildren.apply($('it-notes'), (b.notes || []).map(function (n) { return el('span', { text: n + ' ' }); }));
        var api = $('it-api'); api.hidden = false;
        api.replaceChildren('The same screen from the API: ', el('code', { text: 'curl -H "X-API-Key: $KEY" "' + location.origin + '/v1/insider-transactions?' + params(0).toString() + '"' }));
      })
      .catch(function () { if (my === seq) say('The trades could not load. Check the connection and try again.'); });
  }
  more.addEventListener('click', function () { run(true); });

  // ---- CSV: the rows shown, the disclaimer as the first line ----
  $('it-csv').addEventListener('click', function () {
    var q = function (v) { v = v == null ? '' : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var lines = [q(DISC), ['filed_date', 'first_date', 'last_date', 'issuer_cik', 'issuer', 'ticker', 'owners', 'role_or_title', 'type', 'security_title', 'shares', 'average_price', 'value', 'value_partial', 'shares_after', 'holdings_change_pct_derived', 'plan_10b5_1', 'amended_by', 'amended', 'first_filed_shares', 'first_filed_average_price', 'first_filed_value', 'first_filed_accession', 'cluster_event_date', 'accession_number', 'form', 'filing_url'].join(',')];
    rows.forEach(function (r) {
      var i = r.issuer || {}, f = r.filing || {}, o = (r.owners || [])[0] || {};
      lines.push([f.filed_date, r.first_date, r.last_date, i.cik, i.name, i.ticker, (r.owners || []).map(function (x) { return x.name; }).join('; '), o.officer_title || o.role, r.type, r.security_title, r.shares, r.average_price, r.value, r.value_partial, r.shares_after, r.holdings_change_pct, r.plan_10b5_1, (r.amended_by || []).map(function (a) { return a.source_url; }).join(' '), !!r.amended, r.first_filed && r.first_filed.shares, r.first_filed && r.first_filed.average_price, r.first_filed && r.first_filed.value, r.first_filed && (r.first_filed.filing || {}).accession_number, r.cluster && r.cluster.event_date, f.accession_number, f.form, f.source_url].map(q).join(','));
    });
    (lastBody && lastBody.notes || []).forEach(function (n) { if (/demo key/i.test(n)) lines.splice(1, 0, q(n)); });
    var a = el('a', { href: URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' })), download: 'insider-trades-' + new Date().toISOString().slice(0, 10) + '.csv' });
    document.body.appendChild(a); a.click(); a.remove();
  });

  fill(); run();
})();
