/* X-17 People: who runs the company (8-K item 5.02 and Forms 3/4/5), what the proxy says they were paid
   against total shareholder return (Item 402(v)), their Rule 10b5-1 trading plans (Item 408(a)) and their
   Form 144 notices, each followed by the Form 4 sale we matched to it. Every figure opens its card.
   Information, not signals; not investment advice. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var DISCLAIMER = 'Information, not signals. Not investment advice.';
  var SVGNS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function sv(tag, attrs, text) { var n = document.createElementNS(SVGNS, tag); Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); }); if (text != null) n.textContent = text; return n; }
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  function money(v, cur, d) {
    if (v == null) return '—'; var a = Math.abs(v), p = (v < 0 ? '−' : '') + (!cur || cur === 'USD' ? '$' : cur + ' '); d = d == null ? 1 : d;
    return a >= 1e12 ? p + (a / 1e12).toFixed(d) + 'T' : a >= 1e9 ? p + (a / 1e9).toFixed(d) + 'B' : a >= 1e6 ? p + (a / 1e6).toFixed(d) + 'M' : a >= 1e3 ? p + (a / 1e3).toFixed(0) + 'K' : p + a.toFixed(0);
  }
  function num(v) { return v == null ? '—' : Number(v).toLocaleString('en-US'); }
  function door(text, info) { return window.ProvCard ? window.ProvCard.door(text, info) : document.createTextNode(text); }
  function link(f, text) { return f && ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: text || ((f.form || f.form_type || 'Filing') + ' ↗') }) : el('span', { class: 'muted', text: '—' }); }
  function sec(id, title, kids, cls) { return el('section', { class: 'ws-sec pp-sec' + (cls ? ' ' + cls : ''), 'aria-labelledby': id }, [el('h3', { id: id, text: title })].concat(kids)); }
  // on phones a table reads as cards: each cell carries its column's name
  function stack(t) { var hs = [].map.call(t.querySelectorAll('thead th'), function (h) { return h.textContent; }); [].forEach.call(t.querySelectorAll('tbody tr'), function (r) { var off = r.classList.contains('pp-peo2') ? 1 : 0; [].forEach.call(r.children, function (c, i) { if (hs[i + off] && i + off) c.setAttribute('data-l', hs[i + off]); }); }); t.classList.add('pp-stack'); return t; }
  // 'Ask about this': a link into chat with the company (cik and as_of come with the link) and the filing named in the question
  var ASK = null, CO = 'the company';
  function ask(q, what) { return ASK ? el('a', { class: 'ask', href: ASK(q.slice(0, 480)), 'aria-label': 'Ask in chat about ' + what, title: 'Ask in chat about ' + what, text: 'Ask' }) : null; }
  function note(t) { return t ? el('p', { class: 'muted small', text: t }) : null; }
  function failed(r, what) {
    if (r && r.status === 403) return note(what + ' without a key covers the showcase companies only. Connect a free key to see this company.');
    if (r && r.status === 429) return note('Too many requests just now. Try again in a minute' + (r.key ? '.' : ', or connect a free key.'));
    return note(what + ' could not be loaded just now.');
  }

  /* officers and directors: current first, then those who left (from the overview's leadership block) */
  function officers(d, name) {
    var L = d.leadership || {}, ppl = (L.people || []).slice(), cur = L.current_leadership || {};
    var lead = ['ceo', 'cfo', 'chair'].filter(function (k) { return cur[k] && cur[k].name; }).map(function (k) {
      var c = cur[k];
      return el('li', {}, [el('span', { class: 'pp-role', text: { ceo: 'CEO', cfo: 'CFO', chair: 'Chair' }[k] }), el('b', { text: name(c.name) }),
        el('span', { class: 'muted small', text: (c.since ? ' since ' + day(c.since) : c.reporting_since ? ' reporting since ' + day(c.reporting_since) : '') + (c.basis ? ' · ' + c.basis : '') }), ARCHIVE.test(c.source_url || '') ? el('a', { href: c.source_url, target: '_blank', rel: 'noopener', text: 'source ↗' }) : null]);
    });
    var row = function (p) {
      var ev = (p.events || [])[0];
      return el('tr', {}, [el('th', { scope: 'row', text: name(p.name) }), el('td', { text: p.role || '—' }), el('td', { class: 'muted', text: p.status || '' }),
        el('td', { class: 'muted', text: p.reporting_since ? day(p.reporting_since) : '—' }),
        el('td', {}, ev ? [el('span', { class: 'small', text: ev.change_label ? ev.change_label.charAt(0).toUpperCase() + ev.change_label.slice(1) + (ev.effective ? ', effective ' + ev.effective : '') + ' ' : '' }), ARCHIVE.test(ev.source_url || '') ? el('a', { href: ev.source_url, target: '_blank', rel: 'noopener', text: '8-K ' + day(ev.filing_date) + ' ↗' }) : null] : [el('span', { class: 'muted', text: '—' })])]);
    };
    var head = el('tr', {}, ['Name', 'Role', 'Status', 'Reporting since', 'Latest change'].map(function (h) { return el('th', { scope: 'col', text: h }); }));
    var now = ppl.filter(function (p) { return p.current !== false; }), gone = ppl.filter(function (p) { return p.current === false; });
    var kids = [lead.length ? el('ul', { class: 'pp-lead' }, lead) : null];
    if (now.length) kids.push(el('div', { class: 'tw' }, [stack(el('table', { class: 'pp-table' }, [el('thead', {}, [head]), el('tbody', {}, now.map(row))]))]));
    if (gone.length) { var dt = el('details', { class: 'pp-gone' }, [el('summary', { text: 'Left the company, ' + gone.length })]); dt.appendChild(el('div', { class: 'tw' }, [stack(el('table', { class: 'pp-table' }, [el('thead', {}, [head.cloneNode(true)]), el('tbody', {}, gone.map(row))]))])); kids.push(dt); }
    if (!ppl.length && !lead.length) kids.push(note('No officer or director changes in the filings loaded since ' + day(L.since) + '.'));
    kids.push(note('From 8-K item 5.02 and the officer titles on Forms 3, 4 and 5' + (L.since ? ', since ' + day(L.since) : '') + '.'));
    return sec('pp-off-h', 'Officers and directors', kids);
  }

  /* pay versus performance (Item 402(v)): PEO and NEO-average pay, CAP against company and peer TSR */
  var TAG = { total: 'ecd:PeoTotalCompAmt', cap: 'ecd:PeoActuallyPaidCompAmt', neo_total: 'ecd:NonPeoNeoAvgTotalCompAmt', neo_cap: 'ecd:NonPeoNeoAvgCompActuallyPaidAmt', tsr: 'ecd:TotalShareholderRtnAmt', peer_tsr: 'ecd:PeerGroupTotalShareholderRtnAmt', ni: 'us-gaap:NetIncomeLoss', csm: 'ecd:CoSelectedMeasureAmt' };
  // D-10b: when no single 10-K gives the exact year end, the API sends the month end and fiscal_year_end_rounded
  function lateIn(iso) { return 'late ' + MON[+iso.slice(5, 7) - 1] + ' ' + iso.slice(0, 4); }
  function fyEnd(y) {
    return y.fiscal_year_end_rounded ? el('span', { title: 'The proxy gives only the month end (' + day(y.fiscal_year_end) + '); the exact last day of this fiscal year is not tagged' }, [lateIn(y.fiscal_year_end), el('span', { class: 'muted small', text: ' (month end shown)' })]) : day(y.fiscal_year_end);
  }
  function payInfo(b, y, label, tag, value) {
    var s = y.source || b.proxy || {}, r = !!y.fiscal_year_end_rounded;
    return { label: label, value: value, currency: b.currency, fiscal_label: r ? 'Fiscal year ending ' + lateIn(y.fiscal_year_end) + '; the proxy gives only the month end' : 'Fiscal year', period_end: r ? null : y.fiscal_year_end, form_type: s.form || 'DEF 14A', filed_date: s.filed_date, accession_number: s.accession_number, source_url: s.source_url, source_tag: tag };
  }
  function pvpChart(b, years, w) {
    var ys = years.slice().reverse(), W = Math.max(300, Math.min(1200, w || 720)), H = 240, pl = 58, pr = 52, pt = 14, pb = 30;
    var capMax = 0, tsrMax = 0;
    ys.forEach(function (y) { (y.peo || []).forEach(function (p) { capMax = Math.max(capMax, p.comp_actually_paid || 0, p.total_comp || 0); }); tsrMax = Math.max(tsrMax, y.tsr || 0, y.peer_tsr || 0); });
    var capMin = 0; ys.forEach(function (y) { (y.peo || []).forEach(function (p) { capMin = Math.min(capMin, p.comp_actually_paid || 0); }); });
    if (!capMax || !tsrMax) return null;
    var Y = function (v) { return pt + (H - pt - pb) * (capMax - v) / ((capMax - capMin) || 1); }, T = function (v) { return pt + (H - pt - pb) * (1 - v / (tsrMax * 1.08)); };
    var step = (W - pl - pr) / ys.length, X = function (i) { return pl + step * i + step / 2; };
    var svg = sv('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'pp-chart', role: 'img', width: W, height: H });
    var desc = ys.map(function (y) { var p = (y.peo || [])[0] || {}; return y.fiscal_year_end.slice(0, 4) + ': compensation actually paid ' + money(p.comp_actually_paid, b.currency) + ', TSR ' + (y.tsr == null ? 'not given' : y.tsr) + (y.peer_tsr != null ? ', peer TSR ' + y.peer_tsr : ''); }).join('; ');
    svg.setAttribute('aria-label', 'Pay versus performance by fiscal year. ' + desc);
    [0, 0.5, 1].forEach(function (f) { var v = capMin + (capMax - capMin) * f, y = Y(v); svg.appendChild(sv('line', { x1: pl, x2: W - pr, y1: y, y2: y, class: f ? 'grid' : 'zero' })); svg.appendChild(sv('text', { x: pl - 6, y: y + 4, 'text-anchor': 'end', class: 'axis' }, money(v, b.currency, 0))); });
    [0, 0.5, 1].forEach(function (f) { var v = tsrMax * 1.08 * f; svg.appendChild(sv('text', { x: W - pr + 6, y: T(v) + 4, class: 'axis' }, '$' + Math.round(v))); });
    if (capMin < 0) svg.appendChild(sv('line', { x1: pl, x2: W - pr, y1: Y(0), y2: Y(0), class: 'zero' }));
    ys.forEach(function (y, i) {
      var ps = y.peo || [], bw = Math.min(30, step * 0.5 / Math.max(1, ps.length));
      ps.forEach(function (p, k) { var v = p.comp_actually_paid; if (v == null) return; var x = X(i) + (k - (ps.length - 1) / 2) * bw - bw / 2; svg.appendChild(sv('rect', { x: x, y: Math.min(Y(0), Y(v)), width: bw - 2, height: Math.max(1, Math.abs(Y(0) - Y(v))), class: 'pp-bar' })); });
      svg.appendChild(sv('text', { x: X(i), y: H - 8, 'text-anchor': 'middle', class: 'axis' }, 'FY' + y.fiscal_year_end.slice(0, 4)));
    });
    [['tsr', 'pp-tsr'], ['peer_tsr', 'pp-peer']].forEach(function (s) {
      var pts = ys.map(function (y, i) { return y[s[0]] == null ? null : [X(i), T(y[s[0]])]; }).filter(Boolean); if (!pts.length) return;
      svg.appendChild(sv('polyline', { points: pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '), class: s[1], fill: 'none' }));
      pts.forEach(function (p) { svg.appendChild(sv('circle', { cx: p[0], cy: p[1], r: 3.5, class: s[1] + '-dot' })); });
    });
    var key = el('p', { class: 'pp-key small' }, [el('span', { class: 'k-bar' }), 'Compensation actually paid to the PEO (left axis) ', el('span', { class: 'k-tsr' }), 'Company TSR, value of $100 invested (right axis) ', years.some(function (y) { return y.peer_tsr != null; }) ? el('span', { class: 'k-peer' }) : null, years.some(function (y) { return y.peer_tsr != null; }) ? 'Peer group TSR' : null]);
    return el('div', { class: 'pp-chart-wrap' }, [svg, key]);
  }
  // why a company has no pay-versus-performance table, from what its own filings say about it
  function payWhy(d, nm, short) {
    var c = d.company || {}, cv = d.cover || {}, cat = c.filer_category || cv.filer_category || '', fa = {};
    (d.filing_activity || []).forEach(function (g) { fa[g.group] = g.total; });
    var forms = (d.filings || []).map(function (f) { return f.form_type || ''; }), so = (cv.shares_outstanding || {}).form_type || '';
    if (forms.some(function (f) { return /^(20-F|40-F|6-K)/.test(f); }) || /^(20-F|40-F)/.test(so)) return short ? 'Foreign private issuer: no US proxy, so no pay-versus-performance table.' : nm + ' reports as a foreign private issuer (Form 20-F or 40-F). Foreign private issuers file no US proxy statement, so there is no pay-versus-performance table; the annual report describes executive pay without these tags.';
    if (/emerging growth/i.test(cat)) return short ? 'Emerging growth company: exempt from the pay-versus-performance table.' : nm + ' is an emerging growth company, which is exempt from the pay-versus-performance table (Item 402(v) of Regulation S-K).';
    if (d.ipo_terms) return short ? 'Newly public: no pay-versus-performance table yet.' : nm + ' is newly public. The table covers only years in which a company already reported to the SEC, so its first proxies may not have one.';
    if (!fa['Annual reports']) return short ? 'No annual report yet, so no proxy table.' : nm + ' has not filed an annual report here yet, so no proxy with a pay-versus-performance table either.';
    if (!fa['Proxy statements']) return short ? 'No proxy statement in the filings loaded.' : 'No proxy statement from ' + nm + ' in the filings loaded.';
    return short ? 'No tagged pay-versus-performance table in the proxies loaded.' : 'No proxy from ' + nm + ' with a tagged pay-versus-performance table in the filings loaded. Proxies filed before 2023 do not have one.';
  }
  function pay(b, name, w, d) {
    var years = b.years || [], cur = b.currency, nm = ((d.company || {}).display_name || name((d.company || {}).legal_name || 'This company')).replace(/\.$/, ''); // the API's display name is already cased (SAP SE)
    if (!years.length) return [el('p', { class: 'pp-why', text: payWhy(d, nm) }), note((b.as_of ? 'As known on ' + day(b.as_of) + '. ' : '') + ((b.labels || {}).disclaimer || DISCLAIMER))];
    var cols = ['Fiscal year ended', 'PEO', 'Total pay', 'Actually paid', 'Other NEOs, average total', 'Average actually paid', 'TSR ($100)', 'Peer TSR', 'Net income', 'Company-selected measure'];
    var body = [];
    years.forEach(function (y) {
      var ps = y.peo && y.peo.length ? y.peo : [{}], n = y.neo_average || {}, csm = y.company_selected_measure;
      ps.forEach(function (p, k) {
        var who = p.name ? name(p.name) : 'PEO';
        var cells = [k ? el('td', { class: 'muted', text: '' }) : el('th', { scope: 'row', rowspan: String(ps.length) }, [fyEnd(y), ' ', ask('How did ' + CO + '’s CEO pay compare with total shareholder return in fiscal ' + y.fiscal_year_end.slice(0, 4) + '? (proxy ' + ((y.source || b.proxy || {}).accession_number || '') + ')', 'pay versus performance in fiscal ' + y.fiscal_year_end.slice(0, 4))]), el('td', { text: p.name ? name(p.name) : '—' }),
          el('td', { class: 'n' }, [p.total_comp == null ? '—' : door(money(p.total_comp, cur), payInfo(b, y, who + ', total pay (Summary Compensation Table)', TAG.total, p.total_comp))]),
          el('td', { class: 'n strong' }, [p.comp_actually_paid == null ? '—' : door(money(p.comp_actually_paid, cur), payInfo(b, y, who + ', compensation actually paid', TAG.cap, p.comp_actually_paid))])];
        if (k) cells.shift();
        if (!k) cells = cells.concat([
          el('td', { class: 'n', rowspan: String(ps.length) }, [n.total_comp == null ? '—' : door(money(n.total_comp, cur), payInfo(b, y, 'other named executives, average total pay', TAG.neo_total, n.total_comp))]),
          el('td', { class: 'n', rowspan: String(ps.length) }, [n.comp_actually_paid == null ? '—' : door(money(n.comp_actually_paid, cur), payInfo(b, y, 'other named executives, average compensation actually paid', TAG.neo_cap, n.comp_actually_paid))]),
          el('td', { class: 'n', rowspan: String(ps.length) }, [y.tsr == null ? '—' : door('$' + Number(y.tsr).toFixed(2), payInfo(b, y, 'company TSR: value of $100 invested', TAG.tsr, y.tsr))]),
          el('td', { class: 'n', rowspan: String(ps.length) }, [y.peer_tsr == null ? '—' : door('$' + Number(y.peer_tsr).toFixed(2), payInfo(b, y, 'peer group TSR: value of $100 invested', TAG.peer_tsr, y.peer_tsr))]),
          el('td', { class: 'n', rowspan: String(ps.length) }, [y.net_income == null ? '—' : door(money(y.net_income, cur), payInfo(b, y, 'net income, as in the pay-versus-performance table', TAG.ni, y.net_income))]),
          el('td', { class: 'n', rowspan: String(ps.length) }, [csm && csm.value != null ? el('span', {}, [el('span', { class: 'muted small', text: (csm.name || '') + ' ' }), door(money(csm.value, cur), payInfo(b, y, csm.name || 'company-selected measure', TAG.csm, csm.value))]) : '—'])]);
        body.push(el('tr', { class: k ? 'pp-peo2' : '' }, cells));
      });
    });
    var neoNames = (years[0].neo_average || {}).names || [], src = /smaller reporting/i.test((d.company || {}).filer_category || '');
    var table = el('table', { class: 'pp-table pp-pay', 'aria-label': 'Pay versus performance by fiscal year; arrow keys move between figures' }, [el('thead', {}, [el('tr', {}, cols.map(function (c, i) { return el('th', { scope: 'col', class: i > 1 ? 'n' : '', text: c }); }))]), el('tbody', {}, body)]);
    if (window.Workspace && window.Workspace.rove) window.Workspace.rove(table);
    stack(table); table.classList.add('pp-paystack'); // on phones each year reads as a card // one Tab stop, arrow keys inside, as in Statements
    return [pvpChart(b, years, w), el('div', { class: 'tw' }, [table]),
      neoNames.length ? note('Other named executives in fiscal ' + years[0].fiscal_year_end.slice(0, 4) + ': ' + neoNames.map(name).join(', ') + '.') : null,
      src ? note(nm + ' is a smaller reporting company: its proxy gives three years and no peer TSR or company-selected measure.') : null,
      note(((b.labels || {}).basis || 'As disclosed in the proxy.') + ' ' + ((b.labels || {}).disclaimer || DISCLAIMER)),
      el('details', { class: 'pp-about' }, [el('summary', { text: 'About these figures' })].concat([(b.measures || []).length ? note('Most important measures linking pay to performance, as the proxy lists them: ' + b.measures.join(', ') + '.') : null].concat((b.notes || []).map(note)).filter(Boolean)))];
  }

  /* Rule 10b5-1 plans, then Form 144 notices with the Form 4 sale matched to each */
  function plans(b, name) {
    var ps = b.plans || [];
    if (!ps.length) return [note('No trading plans tagged in the 10-Qs and 10-Ks loaded for this period.')];
    var head = el('tr', {}, ['Plan date', 'Person', 'Action', 'Kind', 'Runs to', 'Shares', 'Disclosed in'].map(function (h, i) { return el('th', { scope: 'col', class: i === 5 ? 'n' : '', text: h }); }));
    return [el('div', { class: 'tw' }, [stack(el('table', { class: 'pp-table' }, [el('thead', {}, [head]), el('tbody', {}, ps.map(function (p) {
      var f = p.filing || {};
      return el('tr', {}, [el('td', {}, [p.date ? day(p.date) : (p.date_as_written || '—'), p.action === 'terminated' && p.original_adoption_date ? el('span', { class: 'muted small pp-title', text: 'adopted ' + day(p.original_adoption_date) }) : null]), el('th', { scope: 'row' }, [name(p.person_name || '—'), p.title ? el('span', { class: 'muted small pp-title', text: p.title }) : null]),
        el('td', {}, [el('span', { class: 'chip pp-act ' + (p.action === 'terminated' ? 'is-end' : 'is-new'), text: p.action === 'terminated' ? 'Terminated' : 'Adopted' })]),
        el('td', { class: 'muted', text: p.plan_type === 'non_rule_10b5_1' ? 'Not under Rule 10b5-1' : 'Rule 10b5-1' }),
        el('td', { class: 'muted', text: p.expiration_date ? day(p.expiration_date) : p.duration_days ? p.duration_days + ' days' : '—' }),
        el('td', { class: 'n' }, [p.shares == null ? el('span', { class: 'muted', text: '—' }) : door(num(p.shares), { label: name(p.person_name || '') + ', shares the plan covers', period_end: f.period, fiscal_label: 'Quarter', form_type: f.form, filed_date: f.filed_date, accession_number: f.accession_number, source_url: f.source_url, source_tag: 'ecd:TrdArrSecuritiesAggAvailAmt' })]),
        el('td', {}, [link(f, (f.form || 'Filing') + ' ' + day(f.filed_date) + ' ↗'), ' ', ask('Who adopted or terminated Rule 10b5-1 trading plans at ' + CO + '? (' + (p.person_name || '') + ', ' + (p.action || '') + ' ' + (p.date || '') + ', ' + (f.form || '') + ' ' + (f.accession_number || '') + ')', 'this trading plan')])]);
    }))]))])];
  }
  function sales(b, name) {
    var ss = b.proposed_sales || [];
    if (!ss.length) return [note('No Form 144 notices in the filings loaded for this period.')];
    var head = el('tr', {}, ['Notice filed', 'Person', 'Shares', 'Market value', 'Planned sale', 'Then on Form 4'].map(function (h, i) { return el('th', { scope: 'col', class: i === 2 || i === 3 ? 'n' : '', text: h }); }));
    return [el('div', { class: 'tw' }, [stack(el('table', { class: 'pp-table' }, [el('thead', {}, [head]), el('tbody', {}, ss.map(function (s) {
      var f = s.filing || {}, fb = s.followed_by, who = name(s.person_name || '—');
      var i144 = function (label, tag) { return { label: who + ', ' + label, period_end: s.approx_sale_date, fiscal_label: 'Planned sale', form_type: '144', filed_date: f.filed_date, accession_number: f.accession_number, source_url: f.source_url, source_tag: tag }; };
      var then = fb ? el('td', {}, [el('span', {}, ['Sold ', door(num(fb.shares), { label: who + ', shares sold (Form 4)', period_end: fb.transaction_date, fiscal_label: 'Transaction', form_type: fb.form || '4', filed_date: fb.filed_date, accession_number: fb.accession_number, source_url: fb.source_url }),
          fb.average_price != null ? ' at $' + Number(fb.average_price).toFixed(2) : '', ' on ' + day(fb.transaction_date) + ' ']), link(fb, 'Form 4 ↗'),
          el('span', { class: 'muted small pp-match', title: (b.notes || [])[1] || '', text: (fb.match && fb.match.rule === 'same_person_name' ? 'Matched by name' : 'Matched by CIK') + (fb.match && fb.match.days_after_notice != null ? ', ' + fb.match.days_after_notice + ' days after the notice' : '') })])
        : el('td', { class: 'muted', text: s.followed_by_status === 'pending' ? 'Our Form 4 data does not cover the 90 days after this notice yet.' : s.followed_by_status === 'no_sale_reported' ? 'No Form 4 sale reported within 90 days; a notice does not oblige a sale.' : 'No Form 4 sale matched yet; a notice does not oblige a sale.' });
      return el('tr', {}, [el('td', {}, [link(f, day(f.filed_date) + ' ↗'), ' ', ask('What did ' + who + ' sell after the Form 144 filed ' + (f.filed_date || '') + ' at ' + CO + '? (Form 144 ' + (f.accession_number || '') + ')', 'this Form 144 notice')]), el('th', { scope: 'row' }, [who, (s.relationships || []).length ? el('span', { class: 'muted small pp-title', text: s.relationships.join(', ') }) : null]),
        el('td', { class: 'n' }, [s.shares == null ? '—' : door(num(s.shares), i144('shares in the notice', null))]),
        el('td', { class: 'n' }, [s.aggregate_market_value == null ? '—' : door(money(s.aggregate_market_value, 'USD'), i144('market value the filer gave on the notice', null))]),
        el('td', { class: 'muted', text: s.approx_sale_date ? day(s.approx_sale_date) : '—' }), then]);
    }))]))])];
  }

  // o: { cik, d, keyed, load(path) -> Promise<{ok,status,body}>, has(path) -> Promise<bool>, name(fn) }
  function render(pane, o) {
    var name = o.name || function (x) { return x; };
    var paySec = sec('pp-pay-h', 'Pay versus performance', [note('Loading the proxy figures…')], 'pp-paysec');
    var planSec = sec('pp-plan-h', 'Trading plans (Rule 10b5-1)', [note('Loading…')]);
    var saleSec = sec('pp-sale-h', 'Proposed sales (Form 144), then the sale (Form 4)', [note('Loading…')]);
    ASK = o.ask || null; CO = ((o.d.company || {}).display_name || name((o.d.company || {}).legal_name || 'the company')).replace(/\.$/, '');
    var off = officers(o.d, name), secs = { officers: off, pay: paySec, plans: planSec, sales: saleSec };
    // a short section list: each entry is a link (sec=), so a section can be shared and Back returns to it
    var nav = el('nav', { class: 'pp-nav', 'aria-label': 'People sections' }, [['officers', 'Officers and directors'], ['pay', 'Pay versus performance'], ['plans', 'Trading plans'], ['sales', 'Form 144']].map(function (x) {
      return el('a', { href: '?c=' + parseInt(o.cik, 10) + '&tab=people&sec=' + x[0], 'aria-current': o.section === x[0] ? 'true' : null, text: x[1], on: { click: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); if (o.onSection) o.onSection(x[0]); [].forEach.call(nav.children, function (a) { a.removeAttribute('aria-current'); }); e.currentTarget.setAttribute('aria-current', 'true'); if (secs[x[0]].isConnected) secs[x[0]].scrollIntoView({ block: 'start', behavior: 'smooth' }); } } });
    }));
    pane.replaceChildren(el('p', { class: 'muted small', text: DISCLAIMER + ' Pay is as disclosed in the proxy; plans and notices are as filed.' }), nav, off, paySec, planSec, saleSec);
    if (o.section && secs[o.section]) setTimeout(function () { if (secs[o.section].isConnected) secs[o.section].scrollIntoView({ block: 'start' }); }, 1200); // after the figures load
    var put = function (s, kids) { s.replaceChildren.apply(s, [s.firstChild].concat(kids.filter(Boolean))); };
    o.has('/v1/companies/{cik}/executive-pay').then(function (yes) {
      if (!yes) { paySec.remove(); return; }
      o.load('/v1/companies/' + o.cik + '/executive-pay').then(function (r) { put(paySec, r && r.ok ? pay(r.body, name, paySec.clientWidth - 30, o.d) : [failed(r && Object.assign(r, { key: o.keyed }), 'Pay')]); });
    });
    o.has('/v1/companies/{cik}/insider-plans').then(function (yes) {
      if (!yes) { planSec.remove(); saleSec.remove(); return; }
      o.load('/v1/companies/' + o.cik + '/insider-plans').then(function (r) {
        if (!r || !r.ok) { put(planSec, [failed(r && Object.assign(r, { key: o.keyed }), 'Trading plans')]); saleSec.remove(); return; }
        var b = r.body, cap = function (n) { return !o.keyed && n === 10 ? note('Without a key, up to 10 rows are shown.') : null; }, dis = function () { return note(((b.labels || {}).disclaimer) || DISCLAIMER); }; // a node can sit in one place only
        put(planSec, plans(b, name).concat([note((b.notes || [])[0] || ''), cap((b.plans || []).length), dis()]));
        put(saleSec, sales(b, name).concat([note((b.notes || [])[1] || ''), cap((b.proposed_sales || []).length), dis()]));
      });
    });
  }
  window.ProvenancePeople = { render: render, why: payWhy };
})();
