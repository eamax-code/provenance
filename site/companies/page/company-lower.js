/* The company page's lower sections: segments, people, ownership and peers. Loaded by company.js
   when they come near the screen, so the first load stays light. Same rules as the rest of the page:
   every figure links its filing; text goes in through textContent only. */
(function () {
  'use strict';
  var P = window.CompanyPage, $ = P.$, el = P.ui.el, fmt = P.ui.fmt, srcLink = P.ui.srcLink, humanDates = P.ui.humanDates, DOT = P.ui.DOT;
  /* ---- segments from the latest 10-K: business, geographic, product ---- */
  var segKind = null, segMetric = 'revenue';
  var KIND = { business: 'Business', geographic: 'Geographic', product: 'Products and services' };
  var SEGM = { revenue: 'Revenue', operating_income: 'Operating income', pretax_income: 'Pretax income' };
  function segments(d) {
    // the API leaves out what can't be shown (a single member that never adds up) and says so in hidden[]
    var S = d.segments, box = $('segments');
    box.hidden = !S || !(S.kinds || []).length; if (box.hidden) return;
    var f = S.filing || {};
    $('seg-from').replaceChildren('As reported in the ', srcLink((f.form_type || '10-K') + ' filed ' + P.date(f.filed_date), f.source_url, 'accession ' + (f.accession_number || '')), f.fiscal_year ? ' for FY' + f.fiscal_year + '.' : '.');
    if (!S.kinds.some(function (k) { return k.kind === segKind; })) segKind = S.kinds[0].kind;
    var tabs = $('seg-kinds'); tabs.textContent = '';
    S.kinds.forEach(function (k) {
      var b = el('button', { type: 'button', role: 'tab', 'aria-selected': String(k.kind === segKind), 'aria-controls': 'seg-table', text: KIND[k.kind] || k.kind });
      b.addEventListener('click', function () { segKind = k.kind; segments(d); });
      tabs.appendChild(b);
    });
    var K = S.kinds.filter(function (k) { return k.kind === segKind; })[0];
    var metrics = Object.keys(K.metrics || {});
    if (metrics.indexOf(segMetric) < 0) segMetric = metrics[0];
    var mbox = $('seg-metrics'); mbox.textContent = '';
    if (metrics.length > 1) metrics.forEach(function (m) {
      var b = el('button', { type: 'button', 'aria-pressed': String(m === segMetric), text: SEGM[m] || m.replace(/_/g, ' ') });
      b.addEventListener('click', function () { segMetric = m; segments(d); });
      mbox.appendChild(b);
    });
    var M = K.metrics[segMetric] || {}, periods = K.periods || [];
    // lines that don't add up to the total (overlapping product lines, Microsoft's product view) have
    // no meaningful share: shares would sum past 100%, so the column goes and one line says why
    var unrec = !!(M.status && M.status[periods[0]] === 'unreconciled'), share = segMetric === 'revenue' && !unrec && (K.segments || []).some(function (sg) { return sg.share_of_revenue_pct != null; });
    var cell = function (v, extraTitle) {
      if (v == null) return el('td', { class: 'n na', text: 'not reported' });
      return el('td', { class: 'n' }, [srcLink(P.money(v), f.source_url, (SEGM[segMetric] || segMetric) + DOT + 'from the ' + (f.form_type || '10-K') + ' filed ' + P.date(f.filed_date) + (extraTitle ? DOT + extraTitle : ''))]);
    };
    var head = el('tr', {}, [el('th', { scope: 'col', class: 'fin-name', text: KIND[K.kind] ? KIND[K.kind] + ' segment' : 'Segment' })].concat(periods.map(function (p) {
      var st = M.status && M.status[p];
      return el('th', { scope: 'col', class: 'n' }, ['Year to ' + P.date(p), st === 'unreconciled' ? el('span', { class: 'tag', title: 'The segments do not add up to the consolidated figure within 1%, and the filing tags no reconciling item.', text: 'unreconciled' }) : null]);
    })).concat(share ? [el('th', { scope: 'col', class: 'n', text: 'Share of revenue' })] : []));
    var tb = el('tbody');
    (K.segments || []).forEach(function (sg) {
      var vals = (sg.values || {})[segMetric] || {};
      var nameCell = sg.label_source === 'member_name' ? el('th', { scope: 'row', class: 'fin-name member-name', title: 'Name from the XBRL member, not the company\'s own label', text: sg.label }) : el('th', { scope: 'row', class: 'fin-name', text: sg.label });
      var row = el('tr', {}, [nameCell].concat(periods.map(function (p) { return cell(vals[p]); })));
      if (share) {
        var pct = sg.share_of_revenue_pct;
        row.appendChild(el('td', { class: 'n share' }, pct == null ? ['—'] : [el('span', { class: 'seg-bar', style: 'width:' + Math.max(2, Math.min(100, pct)) * 0.6 + 'px', 'aria-hidden': 'true' }), P.pct(pct)]));
      }
      tb.appendChild(row);
    });
    // "Power & Energy: Intersegment Sales" rows follow their segments' order; corporate items last
    var segAt = function (l) { var i = (K.segments || []).findIndex(function (sg) { return String(l).indexOf(sg.label + ':') === 0; }); return i < 0 ? 1e3 : i; };
    (K.reconciling || []).slice().sort(function (a, b) { return segAt(a.label) - segAt(b.label); }).forEach(function (rc) {
      var vals = (rc.values || {})[segMetric] || {};
      if (!periods.some(function (p) { return vals[p] != null && vals[p] !== 0; })) return; // nothing, or $0 every year
      var row = el('tr', { class: 'recon' }, [el('th', { scope: 'row', class: 'fin-name', text: rc.label })].concat(periods.map(function (p) { return cell(vals[p], 'reconciling item, not a segment'); })));
      if (share) row.appendChild(el('td'));
      tb.appendChild(row);
    });
    var tot = el('tr', { class: 'total' }, [el('th', { scope: 'row', class: 'fin-name', text: 'Consolidated' })].concat(periods.map(function (p) { return cell((M.consolidated || {})[p], 'the company as a whole'); })));
    if (share) tot.appendChild(el('td', { class: 'n', text: '100%' }));
    tb.appendChild(tot);
    $('seg-table').replaceChildren(unrec ? el('p', { class: 'seg-warn', text: 'These lines overlap or leave part of the total out, so they don\u2019t add up to the consolidated figure' + (segMetric === 'revenue' ? '; shares of revenue are not shown.' : '.') }) : '', el('table', { class: 'fin seg' }, [el('caption', { class: 'vh', text: (KIND[K.kind] || K.kind) + ' segments, ' + (SEGM[segMetric] || segMetric) }), el('thead', {}, [head]), tb]));
    // the API's notes speak to developers (field names); the page says the same for readers
    $('seg-notes').textContent = 'As each annual report tags them. Names are the company\u2019s own; a dotted underline marks a name taken from the tag where the company gave none. Unreconciled: the lines don\u2019t add up to the consolidated figure within 1% and the report tags nothing that accounts for the difference.';
  }

  /* ---- people: who leads it now, then each person's changes, newest first ---- */
  var STATUS = { appointed: 'Appointed', departed: 'Departed', leaving: 'Leaving', 'in office': 'In office' };
  function people(d) {
    var L = d.leadership || { changes: [] }, box = $('people-list'), now = $('people-now');
    box.textContent = ''; now.textContent = '';
    $('people-count').textContent = L.item_502_filings ? L.item_502_filings + (L.item_502_filings === 1 ? ' filing' : ' filings') + ' with item 5.02 since ' + P.date(L.since) : '';
    var cur = L.current_leadership || {};
    [['ceo', 'Chief executive'], ['cfo', 'Chief financial officer'], ['chair', 'Chair']].forEach(function (r) {
      var p = cur[r[0]];
      now.appendChild(el('div', { class: 'now-role' }, [
        el('dt', { text: r[1] }),
        el('dd', {}, p ? [el('b', { text: p.name }), el('span', { class: 'muted', text: (p.title ? ' · ' + p.title : '') }), el('br'),
          el('span', { class: 'muted small' }, [(p.basis === '8-K item 5.02' && p.since ? 'since ' + P.date(p.since) + ', ' : '') + 'from ', srcLink(p.basis === '8-K item 5.02' ? '8-K' : 'Form 4', p.source_url, 'Filed ' + P.date(p.filing_date))])]
          : [el('span', { class: 'muted', text: 'Not named in recent filings' })])
      ]));
    });
    var list = L.people && L.people.length ? L.people : null;
    if (!list) {
      if (!L.changes.length) { box.appendChild(el('p', { class: 'muted', text: 'No officer or director change read from these filings yet.' })); return; }
      var by = {}, order = [];
      L.changes.forEach(function (ch) { var k = ch.person || 'An officer'; if (!by[k]) { by[k] = []; order.push(k); } by[k].push(ch); });
      list = order.map(function (n) { return { name: n, role: by[n][0].role, events: by[n].map(function (c) { return { filing_date: c.filing_date, sentence: c.what || c.change_label, verified: c.verified, source_url: c.source_url }; }) }; });
    }
    list.slice(0, 10).forEach(function (p) {
      var head = el('p', {}, [el('b', { text: p.name }), p.role ? ', ' + p.role : '']);
      if (p.status && STATUS[p.status]) head.appendChild(el('span', { class: 'tag', text: STATUS[p.status] + (p.status === 'leaving' && p.leaving_on ? ' ' + P.date(p.leaving_on) : '') }));
      var item = el('li', { class: 'person' + (p.current === false ? ' is-former' : '') }, [head]);
      var ul = el('ul');
      (p.events || []).slice().sort(function (a, b) { return a.filing_date < b.filing_date ? 1 : -1; }).forEach(function (ev) {
        ul.appendChild(el('li', {}, [
          el('span', { text: P.date(ev.filing_date) + ': ' + humanDates(ev.sentence || ev.change_label || '') }), ' ',
          srcLink('8-K', ev.source_url, 'Opens the filing'),
          ev.verified === false ? el('span', { class: 'tag', title: 'Read by a model; the sentence did not match the filing exactly. Open the 8-K to check.', text: 'unverified' }) : null
        ]));
      });
      item.appendChild(ul);
      box.appendChild(item);
    });
  }

  /* ---- ownership from 13F: top holders by value, changes since the quarter before ---- */
  var CHANGE = { new: 'New', added: 'Added', reduced: 'Reduced', exited: 'Exited', unchanged: 'Unchanged' };
  var quarterName = function (iso) { var m = /^(\d{4})-(\d{2})/.exec(iso || ''); return m ? 'Q' + Math.ceil(+m[2] / 3) + ' ' + m[1] : iso; };
  function ownership(d) {
    var o = d.ownership, box = $('ownership');
    box.hidden = !o; if (!o) return;
    $('own-when').textContent = quarterName(o.quarter) + ' (filed through ' + P.date(o.filed_through) + '). ' + (o.lag_note || '');
    var pct = o.institutional_pct;
    var pctTitle = o.institutional_pct_derived ? o.institutional_pct_derived.formula + (o.institutional_pct_derived.inputs || []).map(function (x) { return '; ' + x.name + ' ' + (x.value != null ? Number(x.value).toLocaleString('en-US') : '') + (x.quarter ? ' (' + quarterName(x.quarter) + ')' : x.as_of_date ? ' (' + P.date(x.as_of_date) + ')' : ''); }).join('') : '';
    var nums = $('own-nums'); nums.textContent = '';
    var tile = function (big, label, plain) { nums.appendChild(el('div', {}, [plain ? el('div', { class: 'own-flows' }, big) : el('b', {}, big), Array.isArray(label) ? el('span', {}, label) : el('span', { text: label })])); };
    tile([P.money(o.value_usd, null, 'USD')], 'held by institutions filing 13F');
    tile([pct != null ? P.pct(pct) : el('span', { class: 'own-na', text: 'No single %' }), pct != null ? el('span', { class: 'tag', title: pctTitle, text: 'derived' }) : null], pct != null ? 'of shares outstanding' : 'several share classes; holdings are valued, but shares aren\u2019t added across classes');
    tile([Number(o.holders_count).toLocaleString('en-US')], 'holders' + (o.holders_count_change != null ? ', ' + (o.holders_count_change >= 0 ? '+' : '−') + Math.abs(o.holders_count_change) + ' on the quarter before' : ''));
    var f = o.flows || {};
    tile([['new', 'new'], ['added', 'added'], ['reduced', 'reduced'], ['exited', 'exited']].map(function (k) { return el('span', {}, [el('strong', { text: Number(f[k[0]] || 0).toLocaleString('en-US') }), ' ' + k[1]]); }), // holders_count_change = new − exited − not_filed: last quarter's holders with no 13F for this one yet
      ['holders by change since ' + quarterName(o.previous_quarter)].concat(f.not_filed ? [el('br'), Number(f.not_filed).toLocaleString('en-US') + (f.not_filed === 1 ? ' holder hasn\u2019t' : ' holders haven\u2019t') + ' filed this quarter yet'] : []), true);
    $('own-flag').textContent = o.flows_note || ''; $('own-flag').hidden = !o.flows_note;
    var rows = o.top_holders || [];
    // several share classes (Berkshire A and B): shares and % aren't added across classes, so the two
    // columns go and the tile says why once, instead of "not added up" on every row
    var multi = rows.length && rows.every(function (h) { return h.shares == null && h.pct_of_outstanding == null; });
    var head = el('tr', {}, [el('th', { scope: 'col', text: 'Holder' }), el('th', { scope: 'col', class: 'n', text: 'Value' }), multi ? null : el('th', { scope: 'col', class: 'n opt', text: 'Shares' }), multi ? null : el('th', { scope: 'col', class: 'n', text: '% of shares' }), el('th', { scope: 'col', text: 'Change' }), el('th', { scope: 'col', class: 'opt', text: '13F' })]);
    var tb = el('tbody');
    rows.forEach(function (h) {
      var ch = h.change ? el('span', { class: 'tag', text: CHANGE[h.change] || h.change }) : null;
      var chText = h.shares_change_pct != null && h.change !== 'new' && h.change !== 'exited' ? ' ' + P.pct(h.shares_change_pct, true) : '';
      tb.appendChild(el('tr', {}, [
        el('th', { scope: 'row', text: P.orgName(h.name) }),
        el('td', { class: 'n', title: h.value_usd != null ? '$' + Number(h.value_usd).toLocaleString('en-US') : null, text: P.money(h.value_usd, null, 'USD') }),
        multi ? null : el('td', { class: 'n opt', text: h.shares != null ? fmt(h.shares, 'shares') : 'not added up' }),
        multi ? null : el('td', { class: 'n', text: h.pct_of_outstanding != null ? P.pct(h.pct_of_outstanding) : '—' }),
        el('td', {}, [ch, chText]),
        el('td', { class: 'opt' }, [srcLink(h.form_type + ', ' + P.date(h.filing_date), h.filing_url, 'accession ' + (h.accession_number || ''))])
      ]));
    });
    $('own-table').replaceChildren(el('caption', { class: 'vh', text: 'Largest institutional holders, ' + quarterName(o.quarter) }), el('thead', {}, [head]), tb);
    $('own-more').hidden = !o.has_more;
    $('own-notes').textContent = (o.notes || []).join(' ');
  }

  function peers(d) {
    var box = $('peers'); box.textContent = '';
    if (!d.peers || !d.peers.companies.length) { $('peer-card').hidden = true; return; }
    $('peer-card').hidden = false;
    $('peer-basis').textContent = 'Same industry: ' + d.peers.basis + '; companies that filed an annual report in the last two years, closest by revenue.';
    var rev = d.key_figures.filter(function (k) { return k.metric === 'revenue'; })[0];
    // ranked by size only within the company's own reporting currency; peers in another currency
    // (ranked: false) follow without a bar, never converted
    var rows = d.peers.companies.map(function (p) { return { name: P.orgName(p.display_name || p.name), cik: p.cik, ticker: p.ticker, v: p.latest_revenue, label: p.fiscal_label, cur: p.currency || 'USD', ranked: p.ranked !== false, note: p.note }; });
    if (rev) rows.push({ name: d.company.display_name, v: rev.value, label: rev.fiscal_label, cur: rev.currency || P.cur, ranked: true, me: true });
    var ranked = rows.filter(function (r) { return r.ranked; }).sort(function (a, b) { return b.v - a.v; });
    var other = rows.filter(function (r) { return !r.ranked; });
    var top = (ranked[0] && ranked[0].v) || 1;
    ranked.concat(other).forEach(function (r) {
      var bar = r.ranked ? el('span', { class: 'bar-h' }) : el('span', { class: 'muted peer-note', text: r.note || 'different currency, not ranked by size' });
      if (r.ranked) bar.style.width = Math.max(2, 100 * r.v / top) + '%';
      var nm = r.me ? el('b', { text: r.name }) : el('a', { href: '/companies/' + parseInt(r.cik, 10), text: r.name });
      box.appendChild(el('li', { class: (r.me ? 'me' : '') + (r.ranked ? '' : ' unranked') }, [el('span', { class: 'pn' }, [el('span', {}, [nm, r.ticker ? el('span', { class: 'muted', text: ' ' + r.ticker }) : null]), bar]), el('span', { class: 'n', text: P.money(r.v, null, r.cur) + ' ' + (r.label || '') })]));
    });
  }
  /* ---- identity: registry facts at the foot of the page ---- */
  function identity(d) {
    var c = d.company, dl = $('ident'); dl.textContent = '';
    var kv = function (k, v) { if (v == null || v === '' || (Array.isArray(v) && !v.length)) return; var dd = el('dd'); (Array.isArray(v) ? v : [v]).forEach(function (line, i) { if (i) dd.appendChild(el('br')); dd.appendChild(typeof line === 'string' ? document.createTextNode(line) : line); }); dl.appendChild(el('dt', { text: k })); dl.appendChild(dd); };
    kv('CIK', c.cik);
    (c.predecessors || []).forEach(function (p) { kv('Predecessor', [el('a', { href: '/companies/' + parseInt(p.cik, 10), text: P.orgName(p.display_name || p.name) + ' (CIK ' + p.cik + ')' }), ' until ' + P.date(p.effective_date)]); });
    if (c.successor) kv('Successor', [el('a', { href: '/companies/' + parseInt(c.successor.cik, 10), text: P.orgName(c.successor.display_name || c.successor.name) + ' (CIK ' + c.successor.cik + ')' }), ' from ' + P.date(c.successor.effective_date)]);
    kv('Tickers', (c.tickers.length ? c.tickers : [c.ticker]).filter(Boolean).map(function (t, i) { return t + (c.exchanges[i] ? ' on ' + c.exchanges[i] : ''); }).join(', '));
    var ln = c.legal_name_as_filed;
    if (ln && ln.name) kv('Legal name as filed', ln.source_url ? srcLink(ln.name, ln.source_url, 'From the cover of the filing, accession ' + (ln.accession_number || '')) : ln.name);
    kv('Formerly traded as', (c.former_tickers || []).map(function (t) { return t.ticker + (t.to ? ' (until ' + P.date(t.to) + ')' : ''); }).join(', '));
    // how the LEI was linked: quiet when certain; a plain qualifier when matched from the registers
    var idn = d.identity || {}, lei = idn.lei || c.lei, how = null;
    if (lei && idn.match_method === 'override') how = el('span', { class: 'muted', title: String(idn.evidence || '').replace(/^manual_cited:\s*/, ''), text: ' · checked by hand against GLEIF and the SEC record' });
    else if (lei && idn.confidence === 'medium') how = el('span', { class: 'muted', title: 'Matched from public registers; not stated in the company\u2019s filings.', text: ' · matched by name' + (/state_differs|city/.test(idn.match_method || '') ? ' and city' : '') });
    kv('LEI', lei ? [el('span', {}, [lei, how])] : 'Not filed with the SEC');
    (d.listings || []).forEach(function (l) { kv('Also listed', [l.isin, l.venue || l.mic].filter(Boolean).join(' on ')); });
    kv('Industry', c.sic_code ? 'SIC ' + c.sic_code + (c.sic_description ? ', ' + c.sic_description : '') : null);
    // the current audit firm only, as tagged on its latest annual report; no "since" until the history is backfilled
    var au = d.auditor && d.auditor.current;
    if (au) kv('Auditor', [el('span', {}, [au.latest_report ? srcLink(P.orgName(au.name), au.latest_report.source_url, 'Named on the ' + au.latest_report.form_type + ' filed ' + P.date(au.latest_report.filed_date)) : P.orgName(au.name), (au.location ? ', ' + au.location : '') + (au.pcaob_firm_id ? ' (PCAOB firm ' + au.pcaob_firm_id + ')' : '') + (au.since_basis === 'observed_change' && au.since ? ', since FY' + au.since : '')])].concat((d.auditor.firm_changes || []).slice().sort(function (a, b) { return b.fiscal_year - a.fiscal_year; }).slice(0, 3).map(function (x, i) {
      // a change of firm between two consecutive annual reports, newest first, with the 8-K item 4.01 when
      // one was filed; an older change names its incoming firm ("KPMG LLP replaced Ernst & Young LLP")
      return el('span', { class: 'muted' }, [(i ? P.orgName(x.to && x.to.name) + ' replaced ' : 'Replaced ') + P.orgName(x.from && x.from.name) + ' from ' + (x.first_report ? '' : 'FY' + x.fiscal_year),
        x.first_report ? srcLink('FY' + x.fiscal_year, x.first_report.source_url, x.first_report.form_type + ' filed ' + P.date(x.first_report.filed_date)) : null,
        x.item_401 ? [' (', srcLink('8-K item 4.01', x.item_401.source_url, 'filed ' + P.date(x.item_401.filing_date)), ')'] : null].flat().filter(Boolean));
    })));
    kv('Incorporated', P.state(c.state_of_incorporation));
    kv('Address', P.address(c.business_address));
    kv('Phone', P.phone(c.phone));
    kv('EIN', c.ein ? c.ein.slice(0, 2) + '-' + c.ein.slice(2) : null);
    var cov = d.cover || {};
    if (cov.shares_outstanding) kv('Shares outstanding', [srcLink(fmt(cov.shares_outstanding.value, 'shares'), cov.shares_outstanding.source_url, cov.shares_outstanding.form_type + ' filed ' + P.date(cov.shares_outstanding.filed_date)), ' on ' + P.date(cov.shares_outstanding.as_of_date)]);
    if (cov.public_float) kv('Public float', [srcLink(P.money(cov.public_float.value, null, /^[A-Z]{3}$/.test(cov.public_float.unit || '') ? cov.public_float.unit : 'USD'), cov.public_float.source_url, cov.public_float.form_type + ' filed ' + P.date(cov.public_float.filed_date)), ' on ' + P.date(cov.public_float.as_of_date)]);
    kv('Former names', c.former_names.length ? c.former_names.map(function (f) { return P.orgName(f.name) + (f.to ? ' (to ' + f.to.slice(0, 4) + ')' : ''); }).join('; ') : 'None recorded by the SEC');
    var h = d.history || {};
    kv('Filings loaded', h.first_filing_date ? P.date(h.first_filing_date) + ' to ' + P.date(h.latest_filing_date) + ', ' + h.filings_last_12_months + ' in the last 12 months' : null);
  }
  window.CompanyLower = { segments: segments, people: people, ownership: ownership, peers: peers, identity: identity };
})();
