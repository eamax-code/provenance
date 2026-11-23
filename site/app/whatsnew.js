/* X-21 What's new, at the top of the Overview: the next deadline or a late notice, what changed in the
   latest 10-K, the last 90 days of trading plans and Form 144 notices, and pay versus performance in
   words. One request per cell, remembered per company; each cell opens its tab and says so in words when
   there is nothing to show. Information, not signals. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var cache = {};
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  function iso(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
  function pct(a, b) { if (a == null || b == null || !b) return null; var v = 100 * (a - b) / Math.abs(b); return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(0) + '%'; }
  function money(v) { if (v == null) return '—'; var a = Math.abs(v), p = (v < 0 ? '−' : '') + '$'; return a >= 1e9 ? p + (a / 1e9).toFixed(1) + 'B' : a >= 1e6 ? p + (a / 1e6).toFixed(1) + 'M' : p + Math.round(a).toLocaleString('en-US'); }
  function fetchOnce(key, fn) { if (!cache[key]) cache[key] = fn().then(function (r) { if (!r || !r.ok) delete cache[key]; return r; }, function (e) { delete cache[key]; throw e; }); return cache[key]; }

  // one cell: a label, a sentence (filled when its request returns) and the tab it opens
  function cell(label, tab, go, tone) {
    var say = el('p', { class: 'wn-say muted', text: 'Loading…' }), c = el('div', { class: 'wn-c' + (tone ? ' ' + tone : '') }, [el('p', { class: 'wn-l', text: label }), say]);
    var open = el('button', { type: 'button', class: 'linkish wn-go', 'aria-label': tab[1] + ': ' + label.toLowerCase(), text: tab[1] + ' →', on: { click: function () { go(tab[0]); } } });
    c.appendChild(open);
    return { node: c, set: function (kids, cls) { say.className = 'wn-say' + (cls ? ' ' + cls : ''); say.replaceChildren.apply(say, (Array.isArray(kids) ? kids : [kids]).filter(function (x) { return x != null && x !== ''; })); } };
  }
  var tag = function (t, title) { return el('span', { class: 'tag', title: title || null, text: t }); };

  function deadline(c, o) {
    var today = iso(new Date());
    if (o.asOf) { c.set('The calendar shows dates from today; turn off “As known on” to see them.', 'muted'); return; }
    fetchOnce('cal' + o.cik, function () { return o.load('/v1/companies/' + o.cik + '/calendar'); }).then(function (r) {
      if (!r || !r.ok) { c.set(r && r.status === 403 ? 'Needs a free key for this company.' : 'Not available just now.', 'muted'); return; }
      var items = (r.body.data || []).slice().sort(function (a, b) { return a.date < b.date ? -1 : 1; });
      var late = items.filter(function (i) { return i.kind === 'late_notice' && i.date >= iso(new Date(Date.now() - 45 * 864e5)); }).pop();
      if (late) { c.set([el('b', { text: late.title }), ' on ' + day(late.date)], 'is-warn'); return; }
      var next = items.filter(function (i) { return i.date >= today && !(i.kind === 'filing_deadline' && i.met_by); })[0];
      if (!next) { c.set('Nothing dated ahead in the filings loaded.', 'muted'); return; }
      c.set([el('b', { text: String(next.title || '').replace(/ \(period ending [^)]*\)/, '') }), ' ' + day(next.date), next.derived ? tag('derived', next.basis) : null]);
    });
  }
  function changed(c, o) {
    fetchOnce('chg' + o.cik + o.asOf, function () { return o.load('/v1/companies/' + o.cik + '/changes' + (o.asOf ? '?as_of=' + o.asOf : '')); }).then(function (r) {
      if (!r) return;
      if (!r.ok) { var why = ((r.body || {}).error || {}).reason; c.set({ not_read: 'Not compared yet.', prior_not_read: 'No earlier annual report to compare with yet.', not_split: 'Its risk factors can’t be split into headings.', not_annual_report: 'No annual report to compare.' }[why] || (r.status === 403 ? 'Needs a free key for this company.' : 'No annual report compared yet.'), 'muted'); return; }
      var b = r.body, k = (b.risk_factors || {}).counts;
      if (!b.prior) { c.set('No earlier annual report stored to compare with.', 'muted'); return; }
      if (!k) { c.set('No risk factors in the report to compare.', 'muted'); return; }
      var parts = [k.added ? '+' + k.added + ' added' : null, k.removed ? '−' + k.removed + ' removed' : null, k.reworded ? k.reworded + ' reworded' : null].filter(Boolean);
      c.set(parts.length ? [el('b', { text: 'Risk factors: ' + parts.join(', ') }), ' in the ' + (b.filing.form || '10-K') + ' filed ' + day(b.filing.filed_date)] : ['Risk factors unchanged in the ' + (b.filing.form || '10-K') + ' filed ' + day(b.filing.filed_date) + '.']);
    });
  }
  function insiders(c, o) {
    var since = iso(new Date((o.asOf ? Date.parse(o.asOf) : Date.now()) - 90 * 864e5));
    fetchOnce('ins' + o.cik + o.asOf, function () { return o.load('/v1/companies/' + o.cik + '/insider-plans?since=' + since + (o.asOf ? '&as_of=' + o.asOf : '')); }).then(function (r) {
      if (!r || !r.ok) { c.set(r && r.status === 403 ? 'Needs a free key for this company.' : 'Not available just now.', 'muted'); return; }
      var b = r.body, ps = b.plans || [], ss = b.proposed_sales || [], cap = function (n) { return !o.keyed && n >= 10 ? '10+' : String(n); };
      var ad = ps.filter(function (p) { return p.action !== 'terminated'; }).length, te = ps.length - ad;
      var bits = [ad ? cap(ad) + ' plan' + (ad === 1 ? '' : 's') + ' adopted' : null, te ? te + ' ended' : null, ss.length ? cap(ss.length) + ' Form 144 notice' + (ss.length === 1 ? '' : 's') : null].filter(Boolean);
      c.set(bits.length ? [el('b', { text: bits.join(', ') }), ' in 90 days. Information, not signals.'] : 'No trading plans or Form 144 notices in 90 days.', bits.length ? '' : 'muted');
    });
  }
  function pay(c, o) {
    fetchOnce('pay' + o.cik + o.asOf, function () { return o.load('/v1/companies/' + o.cik + '/executive-pay' + (o.asOf ? '?as_of=' + o.asOf : '')); }).then(function (r) {
      if (!r || !r.ok) { c.set(r && r.status === 403 ? 'Needs a free key for this company.' : 'Not available just now.', 'muted'); return; }
      var ys = r.body.years || [], a = ys[0], b = ys[1];
      if (!a) { c.set(o.why ? o.why : 'No pay-versus-performance table in the proxies loaded.', 'muted'); return; }
      var pa = (a.peo || [])[0] || {}, pb = b && (b.peo || [])[0] || {}, same = pb.name && pa.name === pb.name && (a.peo || []).length === 1;
      var capChg = same ? pct(pa.comp_actually_paid, pb.comp_actually_paid) : null, tsrChg = b ? pct(a.tsr, b.tsr) : null;
      c.set([el('b', { text: 'FY' + a.fiscal_year_end.slice(0, 4) + ': ' + (capChg ? 'CEO pay actually paid ' + capChg : 'CEO pay actually paid ' + money(pa.comp_actually_paid)) + (tsrChg ? ', TSR ' + tsrChg : '') }),
        (a.peo || []).length > 1 ? ' (two CEOs that year)' : !same && b ? ' (a new CEO)' : '', '. As disclosed in the proxy.']);
    });
  }

  // o: { cik, asOf, keyed, load(path) -> Promise<{ok,status,body}>, has(path) -> Promise<bool>, go(tab), why (empty-pay reason) }
  function band(o) {
    var box = el('section', { class: 'wn', 'aria-labelledby': 'wn-h' }, [el('h3', { id: 'wn-h', class: 'sr-only', text: 'What’s new' })]);
    var specs = [['/v1/companies/{cik}/calendar', 'Next deadline', ['calendar', 'Calendar'], deadline], ['/v1/companies/{cik}/changes', 'Latest annual report', ['filings', 'What changed'], changed],
      ['/v1/companies/{cik}/insider-plans', 'Insiders, last 90 days', ['people', 'People'], insiders], ['/v1/companies/{cik}/executive-pay', 'Pay versus performance', ['people', 'People'], pay]];
    var row = el('div', { class: 'wn-row' }); box.appendChild(row);
    specs.forEach(function (s) {
      var c = cell(s[1], s[2], o.go); row.appendChild(c.node);
      o.has(s[0]).then(function (y) { if (y) s[3](c, o); else c.node.remove(); });
    });
    return box;
  }
  window.ProvenanceNew = { band: band };
})();
