/* One fund manager (Q-02, GET /v1/managers/{cik}): a quarter's Form 13F positions compared with the quarter before,
   what was sold out, and the value of each loaded quarter. Changes compare shares, said in words (New, Added,
   Reduced, Unchanged), never colour. Flags carry a tooltip each. No CUSIPs; links go to sec.gov/Archives or into
   the site. Holdings are as of the quarter end and filed up to 45 days later: said next to the quarter. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//, NS = 'http://www.w3.org/2000/svg';
  var CIK = (location.pathname.match(/managers\/(\d{1,10})/) || [])[1] || (/^\d{1,10}$/.test(new URLSearchParams(location.search).get('cik') || '') ? new URLSearchParams(location.search).get('cik') : null);
  var CHANGE = { new: 'New', added: 'Added', reduced: 'Reduced', unchanged: 'Unchanged' };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var dmy = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; };
  var qn = function (iso) { var m = /^(\d{4})-(\d{2})/.exec(iso || ''); return m ? 'Q' + Math.ceil(+m[2] / 3) + ' ' + m[1] : ''; };
  var int = function (v) { return v == null ? '—' : Math.round(v).toLocaleString('en-US'); };
  var big = function (v) { if (v == null) return '—'; var a = Math.abs(v); return a >= 1e12 ? '$' + (v / 1e12).toFixed(2) + 'T' : a >= 1e9 ? '$' + (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? '$' + (v / 1e6).toFixed(1) + 'M' : '$' + Math.round(v).toLocaleString('en-US'); };
  var pct = function (v, sign) { return v == null ? '—' : (sign ? (v > 0 ? '+' : v < 0 ? '−' : '') : '') + Math.abs(v).toFixed(sign ? 1 : 2) + '%'; };
  var common = function (c) { return !c || /^common stock$/i.test(String(c).trim()); };
  // a mark cites its filing when it has one; otherwise it opens its entry on /docs/flags/ (id)
  var flag = function (text, tip, href, id) { return href && ARCHIVE.test(href) ? el('a', { class: 'mg-flag', href: href, target: '_blank', rel: 'noopener', title: tip, text: text }) : id ? el('a', { class: 'mg-flag', href: '/docs/flags/#' + id, title: tip, 'aria-label': text + ': what this means', text: text }) : el('span', { class: 'mg-flag', title: tip, text: text }); };
  var arch = function (text, href, label) { return ARCHIVE.test(href || '') ? el('a', { href: href, target: '_blank', rel: 'noopener', text: text, 'aria-label': label || null }) : text; };

  var st = { quarter: '', sort: 'value' }, off = 0, seq = 0, shown = 0;
  (function () { var u = new URLSearchParams(location.search); st.quarter = /^\d{4}-\d{2}-\d{2}$/.test(u.get('quarter') || '') ? u.get('quarter') : ''; st.sort = /^(change|name)$/.test(u.get('sort') || '') ? u.get('sort') : 'value'; })();
  function syncUrl() { var u = new URLSearchParams(); if (st.quarter) u.set('quarter', st.quarter); if (st.sort !== 'value') u.set('sort', st.sort); var s = u.toString(); history.replaceState(null, '', '/managers/' + CIK + '/' + (s ? '?' + s : '')); }
  $('mg-sort').value = st.sort;
  $('mg-sort').addEventListener('change', function () { st.sort = this.value; load(); });
  $('mg-quarter').addEventListener('change', function () { st.quarter = this.value; load(); });
  $('mg-more').addEventListener('click', function () { load(true); });

  function change(c) {
    if (!c) return [flag('Possible split; not compared', 'The shares all managers hold of this security moved as a split would, so this quarter is not compared with the one before.', null, 'possible-split')];
    var out = [el('span', { class: 'mg-ch', text: CHANGE[c.status] || c.status }), c.status === 'added' || c.status === 'reduced' ? ' ' + pct(c.shares_change_pct, true) : ''];
    if (c.split_adjusted) out.push(' ', flag('Compared after the ' + (c.split || '') + ' split', 'Shares before the split were put on the new basis before comparing.', null, 'compared-after-split'));
    return out;
  }
  function who(i) { i = i || {}; return i.cik ? [el('a', { href: '/app/?c=' + parseInt(i.cik, 10) + '&tab=ownership', text: i.name }), i.ticker ? el('span', { class: 'tag', text: i.ticker }) : null] : [el('span', { title: 'Name as filed on Forms 13F; not matched to a company here', text: i.name || '—' })]; }
  function hist(h, cur) {
    var fig = $('mg-hist'), rows = (h || []).slice().reverse(); fig.hidden = rows.length < 2; if (fig.hidden) return;
    var W = 560, H = 120, pad = 18, bw = Math.min(56, (W - 8) / rows.length - 8), max = Math.max.apply(null, rows.map(function (r) { return r.value_usd || 0; })) || 1;
    var svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + (H + pad)); svg.setAttribute('class', 'mg-hchart'); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Reported value by quarter: ' + rows.map(function (r) { return qn(r.quarter) + ' ' + (r.value_usd == null ? 'not added up' : big(r.value_usd)); }).join(', '));
    rows.forEach(function (r, i) {
      var x = 4 + i * (bw + 8), v = r.value_usd, h2 = v == null ? 0 : Math.max(2, (H - 16) * v / max), g = document.createElementNS(NS, 'g');
      var rect = document.createElementNS(NS, 'rect'); rect.setAttribute('x', x); rect.setAttribute('y', H - h2); rect.setAttribute('width', bw); rect.setAttribute('height', h2); rect.setAttribute('rx', 2); rect.setAttribute('class', 'mg-bar' + (r.quarter === cur ? ' cur' : ''));
      var t = document.createElementNS(NS, 'title'); t.textContent = qn(r.quarter) + ': ' + (v == null ? 'values look reported in thousands; not added up' : big(v)) + ', ' + int(r.positions) + ' positions'; rect.appendChild(t); g.appendChild(rect);
      var lab = document.createElementNS(NS, 'text'); lab.setAttribute('x', x + bw / 2); lab.setAttribute('y', H + 13); lab.setAttribute('text-anchor', 'middle'); lab.setAttribute('class', 'mg-ax'); lab.textContent = rows.length <= 6 ? qn(r.quarter) : !i || r.quarter.slice(0, 4) !== rows[i - 1].quarter.slice(0, 4) ? r.quarter.slice(0, 4) : ''; g.appendChild(lab); // more than six quarters: each year once
      if (v != null && r.quarter === cur) { var vl = document.createElementNS(NS, 'text'); vl.setAttribute('x', x + bw / 2); vl.setAttribute('y', H - h2 - 4); vl.setAttribute('text-anchor', 'middle'); vl.setAttribute('class', 'mg-val'); vl.textContent = big(v); g.appendChild(vl); }
      svg.appendChild(g);
    });
    fig.replaceChildren(fig.querySelector('figcaption') || el('figcaption', { text: 'Reported value by quarter' }), svg);
  }
  function load(append) {
    if (!CIK) { $('mg-state').textContent = 'No manager CIK in the address.'; return; }
    syncUrl(); var my = ++seq; if (!append) { off = 0; shown = 0; }
    fetch('/v1/managers/' + CIK + '?sort=' + st.sort + (st.quarter ? '&quarter=' + st.quarter : '') + '&limit=100&offset=' + off, { headers: { Accept: 'application/json', 'X-API-Key': key() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); })
      .then(function (r) {
        if (my !== seq) return;
        var e = (r.b && r.b.error) || {};
        if (!r.ok) { $('mg-state').hidden = false; $('mg-state').textContent = r.status === 404 ? (e.message || 'No Form 13F is stored for this CIK.') : r.status === 403 && e.code === 'demo_scope' ? 'The demo key opens the showcase companies’ managers only. Connect a free key in the Explorer to open every manager’s 13F portfolio.' : r.status === 403 ? (e.message || 'This key cannot open that portfolio.') : r.status === 422 ? (e.message || 'That quarter is not loaded for this manager.') : r.status === 429 ? 'Too many requests this minute. Try again in a moment.' : 'The manager could not load. Check the connection and try again.'; return; }
        var b = r.b, m = b.manager || {}, f = b.filing || {}, t = b.totals || {}, pos = b.positions || [];
        $('mg-state').hidden = true; $('mg-page').hidden = false;
        if (!append) {
          document.title = m.name + ' · Fund manager · Provenance';
          $('mg-name').textContent = m.name;
          $('mg-meta').replaceChildren.apply($('mg-meta'), ['CIK ' + ('0000000000' + parseInt(m.cik, 10)).slice(-10) + ' · ', arch(f.form + (f.amendment_type ? ' (' + f.amendment_type.toLowerCase() + ')' : '') + ' filed ' + dmy(f.filed_date) + ' ↗', f.source_url, f.form + ' filed ' + dmy(f.filed_date) + ' on sec.gov')].concat(f.replaces ? [', replacing ', arch('the ' + (f.replaces.form || '13F-HR') + ' filed ' + dmy(f.replaces.filed_date) + ' ↗', f.replaces.source_url)] : [])
            .concat((f.amendments || []).map(function (a) { return el('span', {}, [' · ', arch(a.form + (a.amendment_type ? ' (' + a.amendment_type.toLowerCase() + ')' : '') + ' filed ' + dmy(a.filed_date) + ' ↗', a.source_url)]); }))
            .concat(m.company_cik ? [' · ', el('a', { href: '/companies/' + parseInt(m.company_cik, 10), text: 'Its company page' })] : []));
          $('mg-q').textContent = 'Quarter ending ' + dmy(b.quarter);
          if (b.labels && b.labels.disclaimer) $('mg-disc').textContent = b.labels.disclaimer;
          var sel = $('mg-quarter'); sel.replaceChildren.apply(sel, (b.history || []).map(function (h) { return el('option', { value: h.quarter, text: dmy(h.quarter) }); })); sel.value = b.quarter;
          var fl = [];
          if (f.value_scale_suspect) fl.push(flag('Values look reported in thousands; left out of totals', 'This 13F’s values look 1,000 times too small, as if still reported in thousands after 2023. They are shown as filed and left out of totals, shares of the portfolio and rankings.', null, 'thousands'));
          if (f.confidential_omitted) fl.push(flag('Some positions confidential; missing here as on EDGAR', 'The manager asked the SEC for confidential treatment of some positions, so they are not in this 13F.'));
          $('mg-flags').replaceChildren.apply($('mg-flags'), fl); $('mg-flags').hidden = !fl.length;
          var tile = function (label, v, prev) { return el('div', {}, [el('b', { text: v }), el('span', { text: label + (prev ? ' · ' + prev + ' the quarter before' : '') })]); };
          // a quarter with only a 13F notice: its holdings are on the managers the notice names (PM copy)
          var nt = !!b.notice_only, nb = $('mg-notice');
          nb.hidden = !nt; $('mg-totals').hidden = nt; $('mg-portfolio').hidden = nt;
          if (nt) nb.replaceChildren(el('p', {}, [el('b', { text: 'Files notices only. Its holdings are reported by:' }), ' ', el('a', { href: '/docs/flags/#notice-only', text: 'What this means' })]),
            el('ul', {}, (b.reported_by || []).map(function (x) { return el('li', {}, [x.cik && x.files_holdings_here ? el('a', { href: '/managers/' + parseInt(x.cik, 10) + '/', text: x.name }) : x.name]); })),
            el('p', {}, ['The notice: ', arch((f.form || '13F-NT') + ' filed ' + dmy(f.filed_date) + ' ↗', f.source_url, (f.form || '13F-NT') + ' on sec.gov')]));
          $('mg-totals').replaceChildren(tile('reported value of positions', big(t.value_usd), t.previous_value_usd != null ? big(t.previous_value_usd) : null), tile('positions', int(t.positions), t.previous_positions != null ? int(t.previous_positions) : null), tile('matched to companies here', int(t.matched_positions), null));
          hist(b.history, b.quarter);
          $('mg-pos').replaceChildren(el('caption', { class: 'sr-only', text: 'Positions, ' + qn(b.quarter) }), el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: 'Company' }), el('th', { scope: 'col', class: 'n', text: 'Shares' }), el('th', { scope: 'col', class: 'n', text: 'Value' }), el('th', { scope: 'col', class: 'n' }, [el('span', { title: 'Derived: the position’s value over the reported value of all positions', text: '% of portfolio' })]), el('th', { scope: 'col', text: 'Change since ' + qn(b.previous_quarter) })])]), el('tbody', { id: 'mg-pos-b' }));
          var ex = b.exited || [];
          $('mg-exited-s').hidden = !ex.length;
          $('mg-ex-sum').textContent = ex.length + ' position' + (ex.length === 1 ? '' : 's') + ' held at ' + dmy(b.previous_quarter) + ' and not at ' + dmy(b.quarter) + '.';
          $('mg-exited').replaceChildren(el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: 'Company' }), el('th', { scope: 'col', class: 'n', text: 'Shares before' }), el('th', { scope: 'col', class: 'n', text: 'Value before' })])]),
            el('tbody', {}, ex.map(function (x) { return el('tr', {}, [el('th', { scope: 'row' }, who(x.issuer).concat([common(x.class_label) ? null : el('span', { class: 'mg-flag', title: 'Share class', text: x.class_label })])), el('td', { class: 'n', text: int(x.shares_previous) }), el('td', { class: 'n', text: big(x.value_previous_usd) })]); })));
          $('mg-notes').textContent = (b.notes_detail ? b.notes_detail.filter(function (n) { return n.audience === 'reader'; }).map(function (n) { return n.text; }) : b.notes || []).join(' '); // reader notes (N-01)
          var api = $('mg-api'); api.hidden = false; api.replaceChildren('The same portfolio from the API: ', el('code', { text: 'curl -H "X-API-Key: $KEY" "' + location.origin + '/v1/managers/' + CIK + '?quarter=' + b.quarter + '&sort=' + st.sort + '"' }));
        }
        var tb = $('mg-pos-b');
        pos.forEach(function (p) {
          tb.appendChild(el('tr', {}, [el('th', { scope: 'row' }, who(p.issuer).concat([common(p.class_label) ? null : el('span', { class: 'mg-flag', title: 'Share class as filed: ' + (p.title_of_class || p.class_label), text: p.class_label })])),
            el('td', { class: 'n', text: int(p.shares) }), el('td', { class: 'n', title: p.value_usd != null ? '$' + int(p.value_usd) : null, text: big(p.value_usd) }), el('td', { class: 'n', text: pct(p.pct_of_portfolio) }), el('td', {}, change(p.change))]));
        });
        shown += pos.length; var mm = b.meta || {}; off = mm.next_offset || off + pos.length; $('mg-more').hidden = !mm.has_more;
        $('mg-sum').textContent = shown + ' of ' + int(t.positions) + ' positions shown · ' + (st.sort === 'change' ? 'largest change first' : st.sort === 'name' ? 'by name' : 'largest value first') + ' · shares only (options and principal-amount rows are not in 13F holdings here).';
      })
      .catch(function () { if (my === seq) $('mg-state').textContent = 'The manager could not load. Check the connection and try again.'; });
  }
  load();
})();
