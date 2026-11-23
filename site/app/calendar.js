/* X-15 calendar: a company's or a watchlist's dated items, as a list or a month. Deadlines, lock-up
   and quiet-period ends are derived from rules and the company's own filings: each says so, with its
   rule one click away. Information, not signals. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var KINDS = { filing_deadline: 'Filing deadline', late_notice: 'Late filing notice', lockup_expiry: 'Lock-up ends', quiet_period_end: 'Quiet period ends', annual_meeting: 'Annual meeting', proposed_sale_window_end: 'Form 144 window ends' };
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var uid = 0;
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function parse(s) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ''); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; }
  function day(s) { var d = parse(s); return d ? d.getDate() + ' ' + MON[d.getMonth()] + ' ' + d.getFullYear() : '—'; }
  function wd(s) { var d = parse(s); return d ? WD[d.getDay()] : ''; }
  function nice(t) { return String(t || '').replace(/\b(\d{4}-\d{2}-\d{2})\b/g, function (m) { return day(m); }); }

  // which API routes this deployment has (from /openapi.json, once), so a missing endpoint is never requested
  var specP = null;
  function available(path) {
    specP = specP || fetch('/openapi.json', { headers: { Accept: 'application/json' } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { return j && j.paths ? j.paths : {}; }).catch(function () { return {}; });
    return specP.then(function (p) { return path instanceof RegExp ? Object.keys(p).some(function (k) { return path.test(k); }) : !!p[path]; });
  }

  // one item: date, kind, title (and company on a watchlist), derived with its rule, the filing
  function item(i, o, all, today) {
    var dated = el('time', { datetime: i.date }, [el('b', { text: day(i.date) }), el('span', { class: 'muted small', text: ' ' + wd(i.date) })]);
    var kids = [el('span', { class: 'cal-kind k-' + i.kind, text: KINDS[i.kind] || String(i.kind || '').replace(/_/g, ' ') }), el('span', { class: 'cal-t', text: nice(i.title) })];
    if (o.multi && i.company) kids.unshift(el('a', { class: 'cal-co', href: '/app/?c=' + parseInt(i.company.cik, 10) + '&tab=calendar', text: o.name ? o.name(i.company.name) : i.company.name }));
    var extra = [];
    if (i.derived) {
      var id = 'calb' + (++uid), basis = el('p', { id: id, class: 'cal-basis muted small', hidden: 'hidden' }, [String(i.basis || 'Worked out here from rules and the company’s filings').replace(/\.?\s*$/, '.'),
        i.source && i.source.why ? ' From the ' + (i.source.form || 'filing') + ' filed ' + day(i.source.filed_date) + ': ' + i.source.why + '.' : '']);
      kids.push(el('button', { type: 'button', class: 'tag tag-derived', 'aria-expanded': 'false', 'aria-controls': id, title: 'Derived from a rule; show the rule', text: 'derived', on: { click: function (e) { var b = e.currentTarget, open = b.getAttribute('aria-expanded') !== 'true'; b.setAttribute('aria-expanded', String(open)); basis.hidden = !open; } } }));
      extra.push(basis);
    }
    // a deadline already met (before or after its date) links the report; one that has passed unmet says so
    if (i.kind === 'filing_deadline' && (i.met_by || i.date < today)) {
      var late = all.some(function (x) { return x.kind === 'late_notice' && (!x.company || !i.company || x.company.cik === i.company.cik) && x.date <= i.date && x.date >= isoAdd(i.date, -20); });
      kids.push(i.met_by && ARCHIVE.test(i.met_by.source_url || '') ? el('a', { class: 'cal-met' + (i.filed_late ? ' is-late' : ''), href: i.met_by.source_url, target: '_blank', rel: 'noopener', text: (i.filed_late ? 'Filed late, ' : 'Filed ') + day(i.met_by.filed_date) + ' ↗' })
        : el('span', { class: 'cal-miss', text: late ? 'Not filed by the due date' : 'No report found' }));
    }
    var src = i.source && ARCHIVE.test(i.source.source_url || '') && !i.derived ? el('a', { href: i.source.source_url, target: '_blank', rel: 'noopener', text: (i.source.form || 'Filing') + ' ↗' }) : i.derived && i.source && ARCHIVE.test(i.source.source_url || '') ? el('a', { href: i.source.source_url, target: '_blank', rel: 'noopener', title: 'The filing this date is worked out from', text: 'basis ' + (i.source.form || 'filing') + ' ↗' }) : el('span');
    if (o.ask) { var cn = i.company && i.company.name ? (o.name ? o.name(i.company.name) : i.company.name) : 'the company';
      kids.push(el('a', { class: 'ask', href: o.ask(('When is ' + cn + '’s ' + nice(i.title).replace(/^(\S)/, function (m) { return m.toLowerCase(); }) + ' (' + i.date + ')' + (i.derived ? ', and how is that date worked out?' : '?') + (i.source && i.source.accession_number ? ' (based on ' + (i.source.form || 'filing') + ' ' + i.source.accession_number + ')' : '')).slice(0, 480), i.company && i.company.cik), 'aria-label': 'Ask in chat about ' + nice(i.title), text: 'Ask' })); }
    return el('li', { class: 'cal-i' + (i.derived ? ' is-derived' : '') + (i.date < today ? ' is-past' : '') }, [dated, el('span', { class: 'cal-body' }, [el('span', { class: 'cal-line' }, kids)].concat(extra)), src]);
  }
  function isoAdd(s, n) { var d = parse(s); d.setDate(d.getDate() + n); return iso(d); }

  // items grouped under month headings
  function list(items, o, all, today) {
    var out = [], cur = null, ul = null;
    items.forEach(function (i) {
      var k = i.date.slice(0, 7);
      if (k !== cur) { cur = k; var d = parse(i.date); out.push(el('h4', { class: 'cal-month', text: MONTH[d.getMonth()] + ' ' + d.getFullYear() })); ul = el('ol', { class: 'cal-list' }); out.push(ul); }
      ul.appendChild(item(i, o, all, today));
    });
    return out;
  }

  // o: { load(params) -> Promise<{ok, status, body}>, multi, name(fn), keyed, empty }
  function mount(host, o) {
    var today = iso(new Date());
    var s0 = o.state || {}, st = { view: s0.view === 'month' ? 'month' : 'list', month: s0.month || today.slice(0, 7), off: {}, data: null, cache: {} };
    (s0.off || []).forEach(function (k) { st.off[k] = true; });
    var tell = function () { if (o.onState) o.onState({ view: st.view, month: st.month, off: Object.keys(st.off).filter(function (k) { return st.off[k]; }) }); };
    var region = el('div', { class: 'cal-out', 'aria-live': 'polite' });
    function fetchRange(from, to) {
      var k = (from || '') + '|' + (to || '');
      if (!st.cache[k]) st.cache[k] = o.load(from ? { from: from, to: to } : {}).then(function (r) { if (!r || !r.ok) { delete st.cache[k]; } return r; });
      return st.cache[k];
    }
    function bar(items) {
      var seg = el('span', { class: 'seg', role: 'group', 'aria-label': 'Show as' }, ['list', 'month'].map(function (v) { return el('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(st.view === v), text: v === 'list' ? 'List' : 'Month', on: { click: function () { st.view = v; draw(); } } }); }));
      var kinds = Object.keys(KINDS).filter(function (k) { return items.some(function (i) { return i.kind === k; }); });
      var chips = kinds.length > 1 ? el('span', { class: 'cal-kinds', role: 'group', 'aria-label': 'Kinds shown' }, kinds.map(function (k) { return el('button', { type: 'button', class: 'chip cal-chip k-' + k, 'aria-pressed': String(!st.off[k]), text: KINDS[k], on: { click: function () { st.off[k] = !st.off[k]; draw(); } } }); })) : null;
      return el('div', { class: 'ch-bar cal-bar' }, [seg, chips]);
    }
    function shown(items) { return items.filter(function (i) { return !st.off[i.kind]; }).sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; }); }
    function fail(r) {
      if (r && r.status === 429) return el('p', { class: 'muted', text: o.keyed ? 'Too many requests just now. Try again in a minute.' : 'The shared demo key is busy or spent for today. Try again later, or connect a free key.' });
      if (r && r.status === 403) return el('p', { class: 'muted', text: 'Without a key the calendar shows the showcase companies only. Connect a free key to see this one.' });
      return el('p', { class: 'muted', text: 'The calendar could not be loaded just now.' });
    }
    function foot(body, items) {
      var notes = (body && body.notes || []).slice();
      if (!o.keyed && items.length >= 10) notes.push('Without a key, up to 10 items are shown.');
      if (body && body.meta && body.meta.truncated) notes.push('The first 500 items are shown.');
      return notes.length ? el('div', { class: 'cal-notes' }, notes.map(function (n) { return el('p', { class: 'muted small', text: n }); })) : null;
    }
    function drawList() {
      region.replaceChildren(el('p', { class: 'muted', text: 'Loading the calendar…' }));
      fetchRange().then(function (r) {
        if (!r || !r.ok) { host.replaceChildren(bar([]), region); region.replaceChildren(fail(r)); return; }
        var all = r.body.data || [], items = shown(all);
        var up = items.filter(function (i) { return i.date >= today; }), past = items.filter(function (i) { return i.date < today; }).reverse();
        var kids = [up.length ? null : el('p', { class: 'muted', text: o.empty || 'Nothing dated ahead in the filings loaded.' })].concat(list(up, o, all, today));
        if (past.length) { var d = el('details', { class: 'cal-past' }, [el('summary', { text: 'Recent, ' + past.length + (past.length === 1 ? ' item' : ' items') })]); list(past, o, all, today).forEach(function (n) { d.appendChild(n); }); kids.push(d); }
        kids.push(foot(r.body, all));
        host.replaceChildren(bar(all), region);
        region.replaceChildren.apply(region, kids.filter(Boolean));
      });
    }
    function drawMonth() {
      var y = +st.month.slice(0, 4), m = +st.month.slice(5, 7) - 1, first = new Date(y, m, 1), last = new Date(y, m + 1, 0);
      var nav = function (n) { return function () { var d = new Date(y, m + n, 1); st.month = iso(d).slice(0, 7); draw(); }; };
      var head = el('div', { class: 'cal-mhead' }, [el('button', { type: 'button', class: 'btn small', 'aria-label': 'Previous month', text: '‹', on: { click: nav(-1) } }), el('h4', { class: 'cal-mtitle', text: MONTH[m] + ' ' + y }), el('button', { type: 'button', class: 'btn small', 'aria-label': 'Next month', text: '›', on: { click: nav(1) } }),
        st.month !== today.slice(0, 7) ? el('button', { type: 'button', class: 'btn small', text: 'This month', on: { click: function () { st.month = today.slice(0, 7); draw(); } } }) : null]);
      region.replaceChildren(head, el('p', { class: 'muted', text: 'Loading…' }));
      fetchRange(iso(first), iso(last)).then(function (r) {
        if (!r || !r.ok) { host.replaceChildren(bar([]), region); region.replaceChildren(head, fail(r)); return; }
        var all = r.body.data || [], items = shown(all).filter(function (i) { return i.date.slice(0, 7) === st.month; }), by = {};
        items.forEach(function (i) { (by[i.date] = by[i.date] || []).push(i); });
        var rows = [], cells = [], lead = first.getDay();
        for (var k = 0; k < lead; k++) cells.push(el('td', { class: 'cal-pad' }));
        for (var dd = 1; dd <= last.getDate(); dd++) {
          var key = iso(new Date(y, m, dd)), its = by[key] || [];
          cells.push(el('td', { class: 'cal-d' + (key === today ? ' is-today' : '') + (its.length ? ' has' : '') }, [el('span', { class: 'cal-n', text: String(dd) })].concat(its.length ? [el('ul', { class: 'cal-marks' }, its.slice(0, 3).map(function (i) { return el('li', { class: 'k-' + i.kind + (i.derived ? ' is-derived' : ''), title: (KINDS[i.kind] || i.kind) + (i.derived ? ' (derived)' : '') + ': ' + nice(i.title) }, [el('span', { class: 'cal-lab', text: (o.multi && i.company ? (o.name ? o.name(i.company.name) : i.company.name) + ': ' : '') + nice(i.title) })]); }).concat(its.length > 3 ? [el('li', { class: 'cal-more', text: '+' + (its.length - 3) })] : []))] : [])));
          if (key === today) cells[cells.length - 1].setAttribute('aria-current', 'date');
        }
        while (cells.length % 7) cells.push(el('td', { class: 'cal-pad' }));
        for (var c = 0; c < cells.length; c += 7) rows.push(el('tr', {}, cells.slice(c, c + 7)));
        var table = el('table', { class: 'cal-grid' }, [el('caption', { class: 'sr-only', text: MONTH[m] + ' ' + y + ', ' + items.length + (items.length === 1 ? ' item' : ' items') }), el('thead', {}, [el('tr', {}, WD.map(function (w) { return el('th', { scope: 'col', abbr: w, text: w }); }))]), el('tbody', {}, rows)]);
        host.replaceChildren(bar(all), region);
        region.replaceChildren.apply(region, [head, el('div', { class: 'tw' }, [table])].concat(items.length ? list(items, o, all, today) : [el('p', { class: 'muted', text: 'Nothing dated in ' + MONTH[m] + ' ' + y + '.' })]).concat([foot(r.body, all)]).filter(Boolean));
      });
    }
    function draw() { tell(); if (st.view === 'month') drawMonth(); else drawList(); }
    host.replaceChildren(region); draw();
  }
  window.ProvenanceCalendar = { mount: mount, available: available, kinds: KINDS };
})();
