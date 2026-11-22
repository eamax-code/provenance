/* The company page (default layout): what the company is, how it is doing and what changed.
   One call to /v1/public/companies/{cik}/overview, optionally as of a date. Every figure links to
   its filing on sec.gov; missing values say "not reported"; derived values say so and list their
   inputs. Events and leadership are information, not signals. */
(function () {
  'use strict';
  var P = window.CompanyPage, $ = P.$, el = P.el;
  var narrow = window.matchMedia('(max-width: 760px)');
  var data = null, tab = 'income', filingFilter = 'reports', eventFilter = 'all', eventsAll = false;

  /* ---- formatting ---- */
  var DOT = ' · ';
  function fmt(v, unit) {
    if (v == null) return null;
    if (unit === '%') return P.pct(v);
    if (unit === 'USD/shares') return (v < 0 ? '−$' : '$') + Math.abs(v).toFixed(2);
    if (unit === 'shares') { var a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(2) + 'B' : a >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v.toLocaleString('en-US'); }
    if (unit && unit !== 'USD' && unit.indexOf('/') < 0) return P.money(v).replace('$', '') + ' ' + unit;
    return P.money(v);
  }
  var archive = function (u) { return u && u.indexOf('https://www.sec.gov/Archives/') === 0; };
  var srcLink = function (text, url, title) {
    if (!archive(url)) return el('span', { text: text, title: title });
    return el('a', { href: url, target: '_blank', rel: 'noopener', text: text, title: title });
  };
  /* ISO dates written by the summary service read as "26 Sep 2026" on the page */
  var humanDates = function (s) { return String(s || '').replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, function (m) { return P.date(m); }); };

  /* plain names for the forms people meet most */
  var FORMS = {
    '10-K': 'Annual report', '10-K/A': 'Annual report, amended', '10-Q': 'Quarterly report', '8-K': 'Current report', '8-K/A': 'Current report, amended',
    '20-F': 'Annual report (foreign issuer)', '40-F': 'Annual report (Canadian issuer)', '6-K': 'Foreign issuer report',
    'DEF 14A': 'Proxy statement', 'DEFA14A': 'Proxy material', '3': 'Insider, first holding', '4': 'Insider trade', '5': 'Insider, yearly', '144': 'Planned insider sale',
    'S-1': 'IPO registration', 'S-1/A': 'IPO registration, amended', 'F-1': 'IPO registration (foreign)', '424B4': 'Final prospectus', '424B2': 'Prospectus supplement', '424B3': 'Prospectus', 'FWP': 'Free-writing prospectus', 'S-3': 'Shelf registration', 'S-8': 'Employee plan registration',
    'SC 13G': '5% holder report', 'SC 13G/A': '5% holder report, amended', 'SC 13D': '5% holder report (active)', 'SC 13D/A': '5% holder report (active), amended',
    '25-NSE': 'Security delisted', '11-K': 'Employee plan annual report', 'SD': 'Conflict minerals report'
  };
  var GROUPS = {
    reports: { label: 'Reports and events', test: function (f) { return /^(10-K|10-Q|8-K|20-F|40-F|6-K|DEF 14A|11-K|25|NT )/.test(f); } },
    insiders: { label: 'Insiders', test: function (f) { return /^(3|4|5|144)(\/A)?$/.test(f) || /^SC 13[DG]/.test(f); } },
    offerings: { label: 'Offerings', test: function (f) { return /^(S-|F-|424B|FWP)/.test(f); } },
    all: { label: 'All', test: function () { return true; } }
  };

  /* ---- header ---- */
  function header(d) {
    var c = d.company, chips = $('chips');
    document.title = c.display_name + (c.ticker ? ' (' + c.ticker + ')' : '') + ' · filings and financials · Provenance';
    $('name').textContent = c.display_name;
    chips.textContent = '';
    (c.tickers.length ? c.tickers : [c.ticker]).filter(Boolean).forEach(function (t, i) { chips.appendChild(el('span', { class: 'chip', text: t + (c.exchanges[i] ? DOT + c.exchanges[i] : '') })); });
    if (c.filer_category) chips.appendChild(el('span', { class: 'chip quiet-chip', text: c.filer_category.split('; ')[0] }));
    var ipo = d.history && d.history.ipo_prospectus;
    if (ipo) chips.appendChild(el('span', { class: 'chip quiet-chip' }, [srcLink('IPO priced ' + P.date(ipo.filing_date), ipo.source_url)]));
    if (d.as_of) chips.appendChild(el('span', { class: 'chip asof-chip', text: 'Point in time: ' + P.date(d.as_of) }));
    var addr = P.address(c.business_address);
    $('meta').textContent = [c.sic_description, P.state(c.state_of_incorporation) && 'incorporated in ' + P.state(c.state_of_incorporation), c.fiscal_year_end_month && 'fiscal year ends ' + c.fiscal_year_end_month, addr && addr[addr.length - 1], 'CIK ' + c.cik].filter(Boolean).join(DOT);
    $('ask').href = P.chatUrl(d);
    $('edgar').href = c.filings_url;
    apiPanel(c);
  }

  /* ---- get this via API ---- */
  function apiPanel(c) {
    var cik = String(parseInt(c.cik, 10)), base = location.origin, asof = data && data.as_of ? '&as_of=' + data.as_of : '';
    var key = null; try { key = localStorage.getItem('prv_api_key'); } catch (e) {}
    var k = key ? '$PROVENANCE_API_KEY' : 'demo';
    var samples = {
      curl: 'curl -s "' + base + '/v1/companies/' + cik + '/facts?metric=revenue&period=annual' + asof + '" \\\n  -H "X-API-Key: ' + k + '"',
      python: 'from provenance_client import Client\n\nclient = Client(api_key="' + (key ? 'YOUR_KEY' : 'demo') + '", base_url="' + base + '")\nfor f in client.facts("' + cik + '", metric="revenue", period="annual"' + (asof ? ', as_of="' + data.as_of + '"' : '') + '):\n    print(f["period_label"], f["value"], f["source_url"])',
      mcp: 'Ask your agent, with Provenance added as a tool:\n"What were ' + (c.ticker || c.display_name) + '\'s revenue and operating income in each of the last five years, and which filings report them?"'
    };
    var pre = $('api-code'), tabs = $('api-tabs');
    var show = function (name) {
      pre.textContent = samples[name];
      tabs.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-k') === name)); });
    };
    tabs.onclick = function (e) { var b = e.target.closest('button'); if (b) show(b.getAttribute('data-k')); };
    $('api-copy').onclick = function () { try { navigator.clipboard.writeText(pre.textContent).then(function () { $('api-copy').textContent = 'Copied'; setTimeout(function () { $('api-copy').textContent = 'Copy'; }, 1400); }); } catch (e) {} };
    $('api-key').hidden = !!key;
    show('curl');
  }
  $('api-btn').addEventListener('click', function () {
    var open = $('api-btn').getAttribute('aria-expanded') !== 'true';
    $('api-btn').setAttribute('aria-expanded', String(open)); $('api-panel').hidden = !open;
  });

  /* ---- story and key figures ---- */
  function story(d) {
    var s = $('story'); s.textContent = '';
    // the written summary describes today, so it stays out of a point-in-time view
    var current = d.as_of && d.as_of_scope && (d.as_of_scope.current || []).indexOf('summary') > -1;
    s.hidden = !!current;
    if (d.summary && d.summary.text && !current) {
      var cites = {}; (d.summary.citations || []).forEach(function (c) { cites[c.n] = c; });
      humanDates(d.summary.text).split(/(\[\d+\])/).forEach(function (part) {
        var m = /^\[(\d+)\]$/.exec(part);
        if (m && cites[m[1]]) s.appendChild(el('sup', {}, [srcLink('[' + m[1] + ']', cites[m[1]].url, humanDates(cites[m[1]].label))]));
        else if (part) s.appendChild(document.createTextNode(part));
      });
    }
    $('finding').textContent = P.finding(d) || '';
    $('finding').hidden = !$('finding').textContent;
    var k = $('kpis'); k.textContent = '';
    var pick = ['revenue', 'operating_income', 'net_income'];
    pick.forEach(function (m) {
      var f = d.key_figures.filter(function (x) { return x.metric === m; })[0];
      var sub = f ? [f.fiscal_label + DOT, srcLink(f.form_type + ' filed ' + P.date(f.filed_date), f.source_url)] : ['not reported'];
      var pct = f ? f.change_pct : null;
      if (f && pct == null) { // same rule as the server: only between two positive consecutive years
        var ys = d.years.filter(function (y) { return y[m] != null; }), a = ys[ys.length - 1], b = ys[ys.length - 2];
        if (a && b && a.fiscal_year - b.fiscal_year === 1 && b[m] > 0 && a[m] >= 0) pct = 100 * (a[m] - b[m]) / b[m];
      }
      var change = pct != null ? el('span', { class: 'kpi-ch', text: P.pct(pct, true) + ' on the year' }) : null;
      k.appendChild(el('div', { class: 'kpi' }, [
        el('p', { class: 'kpi-label' }, [P.figureButton(d, m, [P.LABELS[m]], 'fv-name')]),
        el('p', { class: 'kpi-value' }, [f ? srcLink(P.money(f.value), f.source_url, 'Opens the filing') : 'not reported']),
        el('p', { class: 'kpi-sub' }, sub.concat(change ? [el('br'), change] : [])),
        P.figureButton(d, m, [P.spark(P.series(d.years, m), 120, 28)], 'fv-open kpi-spark')
      ]));
    });
    var ch = $('chart'); ch.textContent = '';
    ch.appendChild(P.revenueChart(d.years, { width: 560, height: 220, values: true }));
  }

  /* ---- financial statements ---- */
  function statements(d) {
    var st = d.statements, box = $('fin-table'), tabs = $('fin-tabs');
    if (!st || !st.sections || !st.sections.length) { $('financials').hidden = true; return; }
    $('financials').hidden = false;
    tabs.textContent = '';
    if (!st.sections.some(function (s) { return s.key === tab; })) tab = st.sections[0].key;
    st.sections.forEach(function (s) {
      var b = el('button', { type: 'button', role: 'tab', 'aria-selected': String(s.key === tab), 'aria-controls': 'fin-table', text: s.title });
      b.addEventListener('click', function () { tab = s.key; statements(d); tabs.querySelector('[aria-selected="true"]').focus(); });
      tabs.appendChild(b);
    });
    var sec = st.sections.filter(function (s) { return s.key === tab; })[0];
    var idx = st.fiscal_years.map(function (_, i) { return i; });
    if (narrow.matches) idx.reverse(); // newest year first on a phone
    var currencies = {}; sec.rows.forEach(function (r) { if (r.currency) currencies[r.currency] = 1; });
    $('fin-note').textContent = 'Annual, as filed' + (Object.keys(currencies).length ? DOT + 'in ' + Object.keys(currencies).join(', ') : '') + DOT + 'quarterly and trailing twelve months with a free key';
    var t = el('table', { class: 'fin' });
    t.appendChild(el('caption', { class: 'vh', text: sec.title + ', ' + st.fiscal_years[0] + ' to ' + st.fiscal_years[st.fiscal_years.length - 1] }));
    var hr = el('tr', {}, [el('th', { scope: 'col', class: 'fin-name', text: sec.key === 'ratios' ? 'Ratio' : 'Line item' })]);
    idx.forEach(function (i) { hr.appendChild(el('th', { scope: 'col', class: 'n', text: st.fiscal_years[i] })); });
    t.appendChild(el('thead', {}, [hr]));
    var tb = el('tbody');
    sec.rows.forEach(function (r) {
      var name = el('th', { scope: 'row', class: 'fin-name' }, [r.label]);
      if (r.derived) name.appendChild(el('span', { class: 'tag', title: (r.formula || 'Derived') + '. Computed here from two reported figures of the same fiscal year.', text: 'derived' }));
      if (r.currency && Object.keys(currencies).length > 1) name.appendChild(el('span', { class: 'tag', text: r.currency }));
      var tr = el('tr', {}, [name]);
      idx.forEach(function (i) {
        var c = r.cells[i], v = c ? fmt(c.value, r.unit) : null;
        if (!c || v == null) { tr.appendChild(el('td', { class: 'n na', text: 'not reported' })); return; }
        var title = r.derived
          ? (r.formula || '') + (c.inputs ? ': ' + c.inputs.map(function (x) { return x.metric.replace(/_/g, ' ') + ' ' + P.money(x.value) + ' (' + x.accession_number + ')'; }).join(', ') : '')
          : (c.form_type || '') + ' filed ' + P.date(c.filed_date) + DOT + 'accession ' + (c.accession_number || '') + DOT + 'period ended ' + P.date(c.period_end);
        var link = c.source_url || (c.inputs && c.inputs[0] && c.inputs[0].source_url);
        var kids = [srcLink(v, link, title)];
        if (c.quality_status && c.quality_status !== 'ok') kids.push(el('span', { class: 'tag', title: 'Quality: ' + c.quality_status.replace(/_/g, ' ') + '. Check the filing before relying on it.', text: c.quality_status === 'ambiguous_mapping' ? 'ambiguous' : c.quality_status.replace(/_/g, ' ') }));
        if (c.derived && !r.derived) kids.push(el('span', { class: 'tag', text: 'derived' }));
        tr.appendChild(el('td', { class: 'n' }, kids));
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    box.replaceChildren(t);
  }
  narrow.addEventListener && narrow.addEventListener('change', function () { if (data) statements(data); });

  /* ---- events timeline ---- */
  function events(d) {
    var list = d.events || [], box = $('event-list'), chips = $('event-chips');
    $('events').hidden = !list.length;
    if (!list.length) return;
    var types = []; list.forEach(function (e) { if (types.indexOf(e.short_label) < 0) types.push(e.short_label); });
    chips.textContent = '';
    ['all'].concat(types).forEach(function (t) {
      var b = el('button', { type: 'button', 'aria-pressed': String(eventFilter === t), text: t === 'all' ? 'All' : t });
      b.addEventListener('click', function () { eventFilter = t; events(d); });
      chips.appendChild(b);
    });
    box.textContent = '';
    var shown = list.filter(function (e) { return eventFilter === 'all' || e.short_label === eventFilter; });
    var more = $('event-more');
    more.hidden = eventsAll || shown.length <= 8;
    more.textContent = 'Show all ' + shown.length + ' events';
    more.onclick = function () { eventsAll = true; events(d); };
    shown.slice(0, eventsAll ? shown.length : 8).forEach(function (e) {
      box.appendChild(el('li', {}, [
        el('time', { datetime: e.date, text: P.date(e.date) }),
        el('span', { class: 'ev-what' }, [el('b', { text: e.short_label }), el('span', { class: 'muted', text: e.label })]),
        srcLink(e.form_type, e.filing_url, 'Opens the filing on sec.gov')
      ]));
    });
  }

  /* ---- people: who leads it now, then each person's changes, newest first ---- */
  var STATUS = { appointed: 'Appointed', departed: 'Departed', leaving: 'Leaving', 'in office': 'In office' };
  function people(d) {
    var L = d.leadership || { changes: [] }, box = $('people-list'), now = $('people-now');
    box.textContent = ''; now.textContent = '';
    $('people-count').textContent = L.item_502_filings ? L.item_502_filings + ' filings with item 5.02 since ' + P.date(L.since) : '';
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
    var tile = function (big, label, plain) { nums.appendChild(el('div', {}, [plain ? el('div', { class: 'own-flows' }, big) : el('b', {}, big), el('span', { text: label })])); };
    tile([P.money(o.value_usd)], 'held by institutions filing 13F');
    tile([pct != null ? P.pct(pct) : 'not computed', pct != null ? el('span', { class: 'tag', title: pctTitle, text: 'derived' }) : null], pct != null ? 'of shares outstanding' : 'several share classes; shares are not added across them');
    tile([Number(o.holders_count).toLocaleString('en-US')], 'holders' + (o.holders_count_change != null ? ', ' + (o.holders_count_change >= 0 ? '+' : '−') + Math.abs(o.holders_count_change) + ' on the quarter before' : ''));
    var f = o.flows || {};
    tile([['new', 'new'], ['added', 'added'], ['reduced', 'reduced'], ['exited', 'exited']].map(function (k) { return el('span', {}, [el('strong', { text: String(f[k[0]] || 0) }), ' ' + k[1]]); }), 'holders by change since ' + quarterName(o.previous_quarter), true);
    var rows = o.top_holders || [];
    var head = el('tr', {}, [el('th', { scope: 'col', text: 'Holder' }), el('th', { scope: 'col', class: 'n', text: 'Value' }), el('th', { scope: 'col', class: 'n opt', text: 'Shares' }), el('th', { scope: 'col', class: 'n', text: '% of shares' }), el('th', { scope: 'col', text: 'Change' }), el('th', { scope: 'col', class: 'opt', text: '13F' })]);
    var tb = el('tbody');
    rows.forEach(function (h) {
      var ch = h.change ? el('span', { class: 'tag', text: CHANGE[h.change] || h.change }) : null;
      var chText = h.shares_change_pct != null && h.change !== 'new' && h.change !== 'exited' ? ' ' + P.pct(h.shares_change_pct, true) : '';
      tb.appendChild(el('tr', {}, [
        el('th', { scope: 'row', text: h.name === h.name.toUpperCase() ? P.title(h.name) : h.name }),
        el('td', { class: 'n', title: h.value_usd != null ? '$' + Number(h.value_usd).toLocaleString('en-US') : null, text: P.money(h.value_usd) }),
        el('td', { class: 'n opt', text: h.shares != null ? fmt(h.shares, 'shares') : 'not added up' }),
        el('td', { class: 'n', text: h.pct_of_outstanding != null ? P.pct(h.pct_of_outstanding) : '—' }),
        el('td', {}, [ch, chText]),
        el('td', { class: 'opt' }, [srcLink(h.form_type + ', ' + P.date(h.filing_date), h.filing_url, 'accession ' + (h.accession_number || ''))])
      ]));
    });
    $('own-table').replaceChildren(el('caption', { class: 'vh', text: 'Largest institutional holders, ' + quarterName(o.quarter) }), el('thead', {}, [head]), tb);
    $('own-more').hidden = !o.has_more;
    $('own-notes').textContent = (o.notes || []).join(' ');
  }

  /* ---- filings with filters ---- */
  function filings(d) {
    var chips = $('filing-chips'), t = $('filings');
    chips.textContent = '';
    Object.keys(GROUPS).forEach(function (k) {
      var n = d.filings.filter(function (f) { return GROUPS[k].test(f.form_type); }).length;
      var b = el('button', { type: 'button', 'aria-pressed': String(filingFilter === k), text: GROUPS[k].label + ' ' + n });
      b.addEventListener('click', function () { filingFilter = k; filings(d); });
      chips.appendChild(b);
    });
    var rows = d.filings.filter(function (f) { return GROUPS[filingFilter].test(f.form_type); }).slice(0, 12);
    var tb = el('tbody');
    rows.forEach(function (f) {
      var about = f.items && f.items.length ? 'Items ' + f.items.map(function (i) { return i.label || i.code; }).join(', ') : (f.report_date ? 'period ' + P.date(f.report_date) : '');
      tb.appendChild(el('tr', {}, [
        el('td', { class: 'nw', text: P.date(f.filing_date) }),
        el('td', {}, [srcLink(f.form_type, f.source_url, 'Opens the filing'), el('span', { class: 'muted', text: f.form_label ? DOT + f.form_label : (FORMS[f.form_type] ? DOT + FORMS[f.form_type] : '') })]),
        el('td', { class: 'muted', text: about })
      ]));
    });
    if (!rows.length) tb.appendChild(el('tr', {}, [el('td', { colspan: '3', class: 'muted', text: 'None among the latest filings loaded.' })]));
    t.replaceChildren(el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: 'Filed' }), el('th', { scope: 'col', text: 'Form' }), el('th', { scope: 'col', text: 'About' })])]), tb);
  }

  /* ---- peers and identity ---- */
  function peers(d) {
    var box = $('peers'); box.textContent = '';
    if (!d.peers || !d.peers.companies.length) { $('peer-card').hidden = true; return; }
    $('peer-card').hidden = false;
    $('peer-basis').textContent = 'Same industry: ' + d.peers.basis + '; companies that filed an annual report in the last two years, closest by revenue.';
    var rev = d.key_figures.filter(function (k) { return k.metric === 'revenue'; })[0];
    var rows = d.peers.companies.map(function (p) { return { name: P.title(p.name), cik: p.cik, ticker: p.ticker, v: p.latest_revenue, label: p.fiscal_label }; });
    if (rev) rows.push({ name: d.company.display_name, v: rev.value, label: rev.fiscal_label, me: true });
    rows.sort(function (a, b) { return b.v - a.v; });
    var top = rows[0].v || 1;
    rows.forEach(function (r) {
      var bar = el('span', { class: 'bar-h' }); bar.style.width = Math.max(2, 100 * r.v / top) + '%';
      var nm = r.me ? el('b', { text: r.name }) : el('a', { href: '/companies/' + parseInt(r.cik, 10), text: r.name });
      box.appendChild(el('li', { class: r.me ? 'me' : '' }, [el('span', { class: 'pn' }, [el('span', {}, [nm, r.ticker ? el('span', { class: 'muted', text: ' ' + r.ticker }) : null]), bar]), el('span', { class: 'n', text: P.money(r.v) + ' ' + (r.label || '') })]));
    });
  }
  function identity(d) {
    var c = d.company, dl = $('ident'); dl.textContent = '';
    var kv = function (k, v) { if (v == null || v === '' || (Array.isArray(v) && !v.length)) return; var dd = el('dd'); (Array.isArray(v) ? v : [v]).forEach(function (line, i) { if (i) dd.appendChild(el('br')); dd.appendChild(typeof line === 'string' ? document.createTextNode(line) : line); }); dl.appendChild(el('dt', { text: k })); dl.appendChild(dd); };
    kv('CIK', c.cik);
    kv('Tickers', (c.tickers.length ? c.tickers : [c.ticker]).filter(Boolean).map(function (t, i) { return t + (c.exchanges[i] ? ' on ' + c.exchanges[i] : ''); }).join(', '));
    kv('LEI', c.lei || 'Not filed with the SEC');
    (d.listings || []).forEach(function (l) { kv('Also listed', [l.isin, l.venue || l.mic].filter(Boolean).join(' on ')); });
    kv('Industry', c.sic_code ? 'SIC ' + c.sic_code + (c.sic_description ? ', ' + c.sic_description : '') : null);
    kv('Incorporated', P.state(c.state_of_incorporation));
    kv('Address', P.address(c.business_address));
    kv('Phone', P.phone(c.phone));
    kv('EIN', c.ein ? c.ein.slice(0, 2) + '-' + c.ein.slice(2) : null);
    var cov = d.cover || {};
    if (cov.shares_outstanding) kv('Shares outstanding', [srcLink(fmt(cov.shares_outstanding.value, 'shares'), cov.shares_outstanding.source_url, cov.shares_outstanding.form_type + ' filed ' + P.date(cov.shares_outstanding.filed_date)), ' on ' + P.date(cov.shares_outstanding.as_of_date)]);
    if (cov.public_float) kv('Public float', [srcLink(P.money(cov.public_float.value), cov.public_float.source_url, cov.public_float.form_type + ' filed ' + P.date(cov.public_float.filed_date)), ' on ' + P.date(cov.public_float.as_of_date)]);
    kv('Former names', c.former_names.length ? c.former_names.map(function (f) { return P.title(f.name) + (f.to ? ' (to ' + f.to.slice(0, 4) + ')' : ''); }).join('; ') : 'None recorded by the SEC');
    var h = d.history || {};
    kv('Filings loaded', h.first_filing_date ? P.date(h.first_filing_date) + ' to ' + P.date(h.latest_filing_date) + ', ' + h.filings_last_12_months + ' in the last 12 months' : null);
  }

  /* ---- point in time ---- */
  function loadAt(asOf) {
    $('asof-error').textContent = '';
    $('page').classList.add('is-loading');
    var url = '/v1/public/companies/' + P.cik + '/overview' + (asOf ? '?as_of=' + encodeURIComponent(asOf) : '');
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json().then(function (b) { if (!r.ok) throw new Error((b.error && b.error.message) || ('HTTP ' + r.status)); return b; });
    }).then(function (d) {
      data = d; render(d);
      try { var u = new URL(location.href); if (asOf) u.searchParams.set('as_of', asOf); else u.searchParams.delete('as_of'); history.replaceState(null, '', u.pathname + u.search + u.hash); } catch (e) {}
    }).catch(function (e) {
      if (!data) {
        var st = $('state'); st.textContent = '';
        st.appendChild(el('h1', { class: 'state-title', text: 'This company is not on the public pages' }));
        st.appendChild(el('p', {}, ['Public pages cover the showcase companies. With a free key, the ', el('a', { href: '/app/', text: 'Explorer' }), ' and the ', el('a', { href: '/docs', text: 'API' }), ' cover every company that files with the SEC.']));
        return;
      }
      $('asof-error').textContent = e.message;
    }).then(function () { $('page').classList.remove('is-loading'); });
  }
  $('asof-form').addEventListener('submit', function (e) { e.preventDefault(); loadAt($('asof').value || null); });
  $('asof-latest').addEventListener('click', function () { $('asof').value = ''; loadAt(null); });

  function render(d) {
    header(d); story(d); statements(d); events(d); people(d); ownership(d); filings(d); peers(d); identity(d);
    $('asof').value = d.as_of || '';
    var picks = $('asof-picks'); picks.textContent = '';
    var ends = d.years.map(function (y) { return y; }).filter(function (y) { return y.period_end; });
    var iso = function (dt) { return dt.toISOString().slice(0, 10); }, now = new Date();
    var options = [];
    if (ends.length > 1) { var prev = ends[ends.length - 2]; options.push(['End of ' + prev.fiscal_label, prev.period_end]); }
    var y1 = new Date(now); y1.setFullYear(now.getFullYear() - 1); options.push(['A year ago', iso(y1)]);
    var y3 = new Date(now); y3.setFullYear(now.getFullYear() - 3); options.push(['Three years ago', iso(y3)]);
    options.forEach(function (o) { var b = el('button', { type: 'button', class: 'linkish', text: o[0] }); b.addEventListener('click', function () { loadAt(o[1]); }); picks.appendChild(b); });
    $('asof-latest').hidden = !d.as_of;
    var cur = d.as_of_scope && d.as_of && d.as_of_scope.current ? 'Point in time applies to figures, filings, events and leadership; ' + d.as_of_scope.current.join(', ').replace(/_/g, ' ') + ' stay current.' : '';
    $('asof-note').textContent = cur;
    $('notes').textContent = P.notes(d).join(' ');
    $('state').hidden = true; $('page').hidden = false;
  }

  var first = new URLSearchParams(location.search).get('as_of');
  loadAt(/^\d{4}-\d{2}-\d{2}$/.test(first || '') ? first : null).then(function () { if (data) P.openFromHash(data); });
})();
