(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var body = document.body;
  var thread = $('cx-thread'), input = $('cx-input'), form = $('cx-form'), send = $('cx-send');
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var DEMO = 'demo';
  var state = { key: DEMO, connected: false, sessionId: null, cik: null, busy: false, controller: null };

  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function sstore(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } }
  function sload(k) { try { return JSON.parse(sessionStorage.getItem(k) || 'null'); } catch (e) { return null; } }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svg(path) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
    s.innerHTML = path; // static markup defined in this file only
    return s;
  }
  function link(href, text, cls) {
    var a = el('a', cls, text);
    if (/^https:\/\//.test(href || '')) { a.href = href; a.target = '_blank'; a.rel = 'noopener'; }
    return a;
  }
  // Runs a DOM update inside a view transition; resolves once the update has been applied.
  function transition(fn) {
    if (document.startViewTransition && !reduced) return document.startViewTransition(fn).updateCallbackDone;
    fn(); return Promise.resolve();
  }
  // SEC names are often upper case ("MICROSOFT CORP"); show them in title case.
  function displayName(n) {
    if (!n || n !== n.toUpperCase()) return n || '';
    return n.toLowerCase().replace(/\b([a-z])/g, function (m) { return m.toUpperCase(); })
      .replace(/\b(Inc|Corp|Co|Ltd|Plc|Llc|Lp)\b/g, function (m) { return m === 'Llc' || m === 'Plc' ? m.toUpperCase() : m; });
  }

  // ---- text rendering: paragraphs, bullet lists and [n] citation pills, all as text nodes ----
  function inline(text, byN, parent) {
    text.split(/(\[\d{1,3}\])/).forEach(function (part) {
      var m = /^\[(\d{1,3})\]$/.exec(part);
      if (m && byN[m[1]]) {
        var a = link(byN[m[1]].url, m[1], 'cx-cite'); a.title = byN[m[1]].label; parent.appendChild(a);
      } else if (part) parent.appendChild(document.createTextNode(part));
    });
  }
  function renderText(text, citations) {
    var byN = {}; (citations || []).forEach(function (c) { byN[c.n] = c; });
    var frag = document.createDocumentFragment(), list = null;
    text.split('\n').forEach(function (line) {
      var bullet = /^\s*(?:[•\-*]|\d+\.)\s+(.*)$/.exec(line);
      if (bullet) {
        if (!list) { list = el('ul'); frag.appendChild(list); }
        var li = el('li'); inline(bullet[1], byN, li); list.appendChild(li);
      } else {
        list = null;
        if (line.trim()) { var p = el('p'); inline(line, byN, p); frag.appendChild(p); }
      }
    });
    return frag;
  }
  // Reveal text progressively, like a streamed answer. Finishes in about 1.5 s whatever the length.
  function stream(target, text, citations, done) {
    if (reduced) { target.appendChild(renderText(text, citations)); done(); return; }
    var words = text.split(/(\s+)/), i = 0, step = Math.max(2, Math.ceil(words.length / 90));
    (function tick() {
      i = Math.min(words.length, i + step);
      target.textContent = '';
      target.appendChild(renderText(words.slice(0, i).join(''), citations));
      keepScrolled();
      if (i < words.length) requestAnimationFrame(tick); else done();
    })();
  }
  function keepScrolled(force) {
    var near = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 160;
    if (force || near) thread.scrollTop = thread.scrollHeight;
  }

  // ---- leadership answers as cards with the filing's own sentence ----
  var TAGS = {
    appointment: ['Joined', 'in'], election: ['Elected', 'in'], role_change: ['New role', 'in'],
    departure: ['Leaving', 'out'], retirement: ['Retiring', 'out'],
    not_standing_for_reelection: ['Not standing again', 'out'], compensation: ['Pay', 'pay'], other: ['Other', '']
  };
  function initials(name) {
    var parts = (name || '').replace(/[^A-Za-z\s.'-]/g, '').split(/\s+/).filter(function (w) { return w && !/^(jr|sr|ii|iii|iv)\.?$/i.test(w); });
    if (!parts.length) return '·';
    return (parts[0].charAt(0) + (parts.length > 1 ? parts[parts.length - 1].charAt(0) : '')).toUpperCase();
  }
  function fact(dl, label, value) {
    if (!value) return;
    dl.appendChild(el('dt', null, label)); dl.appendChild(el('dd', null, value));
  }
  // Name first and bold, the role under it in a smaller font, then the tags and the details.
  function changeCard(f, c, byN, delay) {
    var tag = TAGS[c.change] || TAGS.other;
    var card = el('article', 'cx-change ' + tag[1]); card.style.animationDelay = delay + 's';
    var head = el('div', 'cx-change-head');
    head.appendChild(el('span', 'cx-initials', c.person ? initials(c.person) : '·'));
    var who = el('div');
    who.appendChild(el('h4', 'cx-change-who', c.person || 'Company-wide'));
    if (c.role) who.appendChild(el('p', 'cx-change-role', c.role.charAt(0).toUpperCase() + c.role.slice(1)));
    head.appendChild(who); card.appendChild(head);
    var tags = el('div', 'cx-change-tags');
    tags.appendChild(el('span', 'cx-tag ' + tag[1], tag[0]));
    tags.appendChild(el('span', 'cx-tag plain', 'Filed ' + f.filing_date));
    if (!c.verified) { var u = el('span', 'cx-tag warn', 'Unverified'); u.title = 'The quoted sentence could not be matched exactly in the filing'; tags.appendChild(u); }
    card.appendChild(tags);
    var dl = el('dl', 'cx-change-facts');
    fact(dl, 'What', c.what ? c.what.charAt(0).toUpperCase() + c.what.slice(1) : c.change_label);
    if (c.effective && (c.what || '').toLowerCase().indexOf(c.effective.toLowerCase().replace(/^the /, '')) < 0) fact(dl, 'Effective', c.effective);
    fact(dl, 'Reason', c.reason ? c.reason.charAt(0).toUpperCase() + c.reason.slice(1) : '');
    if (c.successor) fact(dl, /^(appointment|election|role_change)$/.test(c.change) ? 'Replaces' : 'Successor', c.successor);
    card.appendChild(dl);
    if (c.evidence) {
      var d = el('details'), s = el('summary', null, 'From the filing');
      d.appendChild(s);
      d.appendChild(el('blockquote', null, c.evidence));
      var src = el('div', 'cx-note'); src.appendChild(document.createTextNode('Source: '));
      inline('8-K filed ' + f.filing_date + ' [' + f.citation + ']', byN, src); d.appendChild(src);
      card.appendChild(d);
    }
    return card;
  }
  function renderLeadership(target, reply) {
    var byN = {}; (reply.citations || []).forEach(function (c) { byN[c.n] = c; });
    var lines = (reply.answer || '').split('\n');
    target.appendChild(renderText(lines[0], reply.citations));
    var box = el('div', 'cx-changes'), k = 0;
    reply.brief.leadership_filings.forEach(function (f) {
      if (f.changes && f.changes.length) {
        f.changes.forEach(function (c) { box.appendChild(changeCard(f, c, byN, (k++) * 0.06)); });
      } else {
        var card = el('article', 'cx-change'); card.style.animationDelay = (k++) * 0.06 + 's';
        var head = el('div', 'cx-change-head');
        head.appendChild(el('span', 'cx-initials', '8-K'));
        var who = el('div');
        who.appendChild(el('h4', 'cx-change-who', f.reading === 'ok' ? 'No named change' : 'Not read yet'));
        who.appendChild(el('p', 'cx-change-role', 'Filed ' + f.filing_date));
        head.appendChild(who); card.appendChild(head);
        var t = el('div', 'cx-change-text');
        inline((f.reading === 'ok' ? 'The item names no individual director or officer change (often a pay plan or arrangement). ' : 'This filing has not been read yet. ') + '[' + f.citation + ']', byN, t);
        card.appendChild(t);
        box.appendChild(card);
      }
    });
    target.appendChild(box);
    var foot = lines.filter(function (l) { return l && !/^\s*•/.test(l); }).slice(1).join(' ');
    if (foot) target.appendChild(el('p', 'cx-note', foot));
  }
  function isLeadership(reply) {
    var hasFilings = reply.brief && (reply.brief.leadership_filings || []).length > 0;
    if (reply.intent) return reply.intent === 'leadership' && hasFilings;
    return reply.answered_by === 'data' && hasFilings; // replies saved before "intent" existed
  }

  // ---- widgets: charts and figure tiles from the cited data ----
  var chartLib = null;
  function loadChartLib() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (!chartLib) {
      chartLib = new Promise(function (resolve, reject) {
        var sc = document.createElement('script');
        sc.src = '/vendor/chartjs-4.4.7/chart.umd.min.js';
        sc.onload = function () { resolve(window.Chart); };
        sc.onerror = function () { chartLib = null; reject(new Error('chart library unavailable')); };
        document.head.appendChild(sc);
      });
    }
    return chartLib;
  }
  function css(name) { return getComputedStyle(body).getPropertyValue(name).trim(); }
  function short(v) {
    var a = Math.abs(v), units = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
    for (var i = 0; i < units.length; i++) if (a >= units[i][0]) return (v < 0 ? '-$' : '$') + (a / units[i][0]).toFixed(a / units[i][0] >= 100 ? 0 : 1) + units[i][1];
    return '$' + v.toFixed(0);
  }
  function delta(p) {
    if (p == null) return null;
    return el('span', 'cx-delta ' + (p >= 0 ? 'up' : 'down'), (p > 0 ? '+' : '') + p.toFixed(1) + '%');
  }
  function sparkline(values) {
    if (!values || values.length < 2) return null;
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values), span = max - min || 1, w = 100, h = 30;
    var pts = values.map(function (v, i) { return [i * w / (values.length - 1), h - 3 - (v - min) / span * (h - 6)]; });
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 ' + w + ' ' + h); s.setAttribute('preserveAspectRatio', 'none'); s.setAttribute('class', 'cx-spark'); s.setAttribute('aria-hidden', 'true');
    var line = document.createElementNS(s.namespaceURI, 'polyline');
    line.setAttribute('points', pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '));
    line.setAttribute('vector-effect', 'non-scaling-stroke');
    s.appendChild(line);
    return s;
  }
  function tile(t, byN, i) {
    var box = el('div', 'cx-tile'); box.style.animationDelay = (0.05 * i) + 's';
    box.appendChild(el('div', 'cx-tile-label', t.label));
    var v = el('div', 'cx-tile-value', t.value); box.appendChild(v);
    var sub = el('div', 'cx-tile-sub');
    var d = delta(t.change_pct); if (d) sub.appendChild(d);
    if (t.sub) sub.appendChild(document.createTextNode(t.sub));
    if (t.citation) inline(' [' + t.citation + ']', byN, sub);
    box.appendChild(sub);
    var sp = sparkline(t.spark); if (sp) box.appendChild(sp);
    return box;
  }
  function statsWidget(w, byN) {
    var box = el('section', 'cx-widget');
    var head = el('div', 'cx-widget-head'); head.appendChild(el('h3', null, w.title)); box.appendChild(head);
    var grid = el('div', 'cx-tiles');
    w.items.forEach(function (t, i) { grid.appendChild(tile(t, byN, i)); });
    box.appendChild(grid);
    return box;
  }
  function chartWidget(w, byN) {
    var box = el('section', 'cx-widget');
    var head = el('div', 'cx-widget-head');
    head.appendChild(el('h3', null, w.title));
    var pts = w.points;
    head.appendChild(el('span', 'cx-widget-sub', pts[0].label + ' – ' + pts[pts.length - 1].label + ' · from annual reports'));
    box.appendChild(head);
    var grid = el('div', 'cx-tiles');
    (w.stats || []).forEach(function (t, i) { grid.appendChild(tile(t, byN, i)); });
    box.appendChild(grid);
    var wrap = el('div', 'cx-chart'), canvas = el('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', w.title + ': ' + pts.map(function (p) { return p.label + ' ' + p.display; }).join(', '));
    wrap.appendChild(canvas); box.appendChild(wrap);
    var legend = el('div', 'cx-legend'), l1 = el('span'), l2 = el('span');
    var i1 = el('i'); i1.style.background = css('--slate'); l1.appendChild(i1); l1.appendChild(document.createTextNode('Reported ' + w.title.split(' by ')[0].toLowerCase()));
    var i2 = el('i'); i2.style.background = css('--charcoal'); i2.style.borderRadius = '50%'; l2.appendChild(i2); l2.appendChild(document.createTextNode('Change from prior year'));
    legend.appendChild(l1); legend.appendChild(l2); box.appendChild(legend);
    // The figures as a table, with each year's source: also the fallback if the chart cannot load.
    var d = el('details'); d.appendChild(el('summary', null, 'Figures and sources'));
    var table = el('table', 'cx-table'), thead = el('thead'), tr = el('tr');
    ['Fiscal year ended', 'Value', 'Change', 'Source'].forEach(function (h) { tr.appendChild(el('th', null, h)); });
    thead.appendChild(tr); table.appendChild(thead);
    var tb = el('tbody');
    pts.forEach(function (p) {
      var r = el('tr');
      r.appendChild(el('td', null, p.period_end)); r.appendChild(el('td', null, p.display));
      r.appendChild(el('td', null, p.change_pct == null ? '—' : (p.change_pct > 0 ? '+' : '') + p.change_pct.toFixed(1) + '%'));
      var src = el('td'); inline(p.form_type + ' ' + p.filed_date + ' [' + p.citation + ']', byN, src); r.appendChild(src);
      tb.appendChild(r);
    });
    table.appendChild(tb); d.appendChild(table); box.appendChild(d);
    if (w.note) box.appendChild(el('p', 'cx-note', w.note));
    loadChartLib().then(function (Chart) { drawChart(Chart, canvas, w); })
      .catch(function () { wrap.remove(); legend.remove(); d.open = true; });
    return box;
  }
  function drawChart(Chart, canvas, w) {
    var pts = w.points, slate = css('--slate'), ink = css('--charcoal'), muted = css('--muted'), line = css('--line');
    var font = { family: css('--font-body') || 'sans-serif', size: 12 };
    var ctx = canvas.getContext('2d');
    var grad = ctx.createLinearGradient(0, 0, 0, canvas.parentNode.clientHeight || 280);
    grad.addColorStop(0, slate); grad.addColorStop(1, css('--slate-2'));
    var chart = new Chart(canvas, {
      data: {
        labels: pts.map(function (p) { return p.label; }),
        datasets: [
          { type: 'bar', label: 'Reported', data: pts.map(function (p) { return p.value; }), backgroundColor: grad, hoverBackgroundColor: css('--slate-deep'), borderRadius: 8, maxBarThickness: 56, yAxisID: 'y', order: 2 },
          { type: 'line', label: 'Change', data: pts.map(function (p) { return p.change_pct; }), borderColor: ink, backgroundColor: ink, pointRadius: 4, pointHoverRadius: 6, borderWidth: 2.5, tension: 0.35, spanGaps: true, yAxisID: 'pct', order: 1 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: reduced ? false : { duration: 900, easing: 'easeOutQuart' },
        interaction: { mode: 'index', intersect: false },
        onHover: function (e, els) { e.native.target.style.cursor = els.length ? 'pointer' : 'default'; },
        onClick: function (e, els) { if (els.length) { var p = pts[els[0].index]; if (/^https:\/\//.test(p.source_url)) window.open(p.source_url, '_blank', 'noopener'); } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#2b2f33', padding: 10, cornerRadius: 10, titleFont: font, bodyFont: font,
            callbacks: {
              title: function (items) { return 'Fiscal year ended ' + pts[items[0].dataIndex].period_end; },
              label: function (item) {
                var p = pts[item.dataIndex];
                if (item.datasetIndex === 0) return ' ' + p.display;
                return p.change_pct == null ? null : ' ' + (p.change_pct > 0 ? '+' : '') + p.change_pct.toFixed(1) + '% from prior year';
              },
              footer: function (items) { var p = pts[items[0].dataIndex]; return p.form_type + ' filed ' + p.filed_date + ' · click to open'; }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: muted, font: font }, border: { color: line } },
          y: { beginAtZero: true, grid: { color: line }, border: { display: false }, ticks: { color: muted, font: font, maxTicksLimit: 5, callback: function (v) { return short(v); } } },
          pct: { position: 'right', grid: { display: false }, border: { display: false }, ticks: { color: ink, font: font, maxTicksLimit: 5, callback: function (v) { return v + '%'; } } }
        }
      }
    });
    canvas._chart = chart;
  }
  // Reported years as solid bars, forecast years as outlined bars with the low-to-high range.
  function forecastWidget(w, byN) {
    var box = el('section', 'cx-widget cx-forecast');
    var head = el('div', 'cx-widget-head');
    head.appendChild(el('h3', null, w.title));
    var hist = w.history, fc = w.forecast;
    head.appendChild(el('span', 'cx-widget-sub', hist[0].label + ' – ' + fc[fc.length - 1].label + ' · ' +
      (w.summary.method === 'model' ? 'forecast by ' + (w.summary.model || 'a reasoning model') : 'forecast from the trend')));
    box.appendChild(head);
    var grid = el('div', 'cx-tiles');
    (w.stats || []).forEach(function (t, i) { grid.appendChild(tile(t, byN, i)); });
    box.appendChild(grid);
    var wrap = el('div', 'cx-chart'), canvas = el('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', w.title + ': ' + hist.map(function (p) { return p.label + ' ' + p.display; })
      .concat(fc.map(function (r) { return r.label + ' ' + r.base_display + ' forecast'; })).join(', '));
    wrap.appendChild(canvas); box.appendChild(wrap);
    var legend = el('div', 'cx-legend');
    [['Reported', css('--slate'), ''], ['Forecast, base case', 'transparent', 'dashed'], ['Low to high range', css('--red'), 'band']]
      .forEach(function (x) {
        var s = el('span'), i = el('i');
        i.style.background = x[1];
        if (x[2] === 'dashed') i.style.border = '2px dashed ' + css('--slate');
        if (x[2] === 'band') i.style.opacity = '0.35';
        s.appendChild(i); s.appendChild(document.createTextNode(x[0])); legend.appendChild(s);
      });
    box.appendChild(legend);
    var d = el('details'); d.appendChild(el('summary', null, 'Figures and sources'));
    var table = el('table', 'cx-table'), thead = el('thead'), tr = el('tr');
    ['Fiscal year', 'Low', 'Base', 'High', 'Basis'].forEach(function (h) { tr.appendChild(el('th', null, h)); });
    thead.appendChild(tr); table.appendChild(thead);
    var tb = el('tbody');
    hist.forEach(function (p) {
      var r = el('tr'); r.appendChild(el('td', null, p.label));
      r.appendChild(el('td', null, '')); r.appendChild(el('td', null, p.display)); r.appendChild(el('td', null, ''));
      var src = el('td'); inline('Reported [' + p.citation + ']', byN, src); r.appendChild(src); tb.appendChild(r);
    });
    fc.forEach(function (f) {
      var r = el('tr', 'cx-forecast-row'); r.appendChild(el('td', null, f.label));
      ['low', 'base', 'high'].forEach(function (k) {
        r.appendChild(el('td', null, f[k + '_display'] + ' (' + (f[k + '_growth'] > 0 ? '+' : '') + f[k + '_growth'].toFixed(1) + '%)'));
      });
      r.appendChild(el('td', null, 'Forecast')); tb.appendChild(r);
    });
    table.appendChild(tb); d.appendChild(table); box.appendChild(d);
    if (w.note) box.appendChild(el('p', 'cx-note', w.note));
    loadChartLib().then(function (Chart) { drawForecast(Chart, canvas, w); })
      .catch(function () { wrap.remove(); legend.remove(); d.open = true; });
    return box;
  }
  function drawForecast(Chart, canvas, w) {
    var hist = w.history, fc = w.forecast, nh = hist.length;
    var slate = css('--slate'), red = css('--red'), muted = css('--muted'), line = css('--line');
    var font = { family: css('--font-body') || 'sans-serif', size: 12 };
    var labels = hist.map(function (p) { return p.label; }).concat(fc.map(function (f) { return f.label; }));
    function pad(arr, before) { var a = []; for (var i = 0; i < before; i++) a.push(null); return a.concat(arr); }
    var last = hist[nh - 1].value;
    // The range starts at the last reported year so the band grows out of it.
    var low = pad([last].concat(fc.map(function (f) { return f.low; })), nh - 1);
    var high = pad([last].concat(fc.map(function (f) { return f.high; })), nh - 1);
    var ctx = canvas.getContext('2d');
    var grad = ctx.createLinearGradient(0, 0, 0, canvas.parentNode.clientHeight || 280);
    grad.addColorStop(0, slate); grad.addColorStop(1, css('--slate-2'));
    var chart = new Chart(canvas, {
      data: {
        labels: labels,
        datasets: [
          { type: 'bar', label: 'Reported', data: hist.map(function (p) { return p.value; }).concat(fc.map(function () { return null; })), backgroundColor: grad, borderRadius: 8, maxBarThickness: 48, grouped: false, order: 3 },
          { type: 'bar', label: 'Base case', data: pad(fc.map(function (f) { return f.base; }), nh), backgroundColor: 'rgba(98,123,140,0.14)', borderColor: slate, borderWidth: 2, borderDash: [6, 4], borderRadius: 8, maxBarThickness: 48, grouped: false, order: 2 },
          { type: 'line', label: 'Low case', data: low, borderColor: red, borderWidth: 1.5, borderDash: [4, 4], pointRadius: 0, tension: 0.3, fill: false, spanGaps: false, order: 1 },
          { type: 'line', label: 'High case', data: high, borderColor: red, borderWidth: 1.5, borderDash: [4, 4], pointRadius: 0, tension: 0.3, fill: '-1', backgroundColor: 'rgba(232,60,52,0.10)', spanGaps: false, order: 1 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: reduced ? false : { duration: 900, easing: 'easeOutQuart' },
        interaction: { mode: 'index', intersect: false },
        onHover: function (e, els) { e.native.target.style.cursor = els.length && els[0].index < nh ? 'pointer' : 'default'; },
        onClick: function (e, els) { if (els.length && els[0].index < nh) { var p = hist[els[0].index]; if (/^https:\/\//.test(p.source_url)) window.open(p.source_url, '_blank', 'noopener'); } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#2b2f33', padding: 10, cornerRadius: 10, titleFont: font, bodyFont: font,
            filter: function (item) { return item.raw != null && !(item.dataIndex === nh - 1 && item.datasetIndex > 1); },
            callbacks: {
              title: function (items) { var i = items[0].dataIndex; return i < nh ? 'Fiscal year ended ' + hist[i].period_end : fc[i - nh].label + ' (forecast)'; },
              label: function (item) {
                var i = item.dataIndex;
                if (i < nh) return ' Reported ' + hist[i].display;
                var f = fc[i - nh], k = ['', 'base', 'low', 'high'][item.datasetIndex];
                return ' ' + k.charAt(0).toUpperCase() + k.slice(1) + ' ' + f[k + '_display'] + ' (' + (f[k + '_growth'] > 0 ? '+' : '') + f[k + '_growth'].toFixed(1) + '%)';
              },
              footer: function (items) { return items[0].dataIndex < nh ? 'From the annual report · click to open' : 'Estimate, not a reported figure'; }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: muted, font: font }, border: { color: line } },
          y: { beginAtZero: true, grid: { color: line }, border: { display: false }, ticks: { color: muted, font: font, maxTicksLimit: 5, callback: function (v) { return short(v); } } }
        }
      }
    });
    canvas._chart = chart;
  }
  function renderWidgets(target, reply) {
    var byN = {}; (reply.citations || []).forEach(function (c) { byN[c.n] = c; });
    (reply.widgets || []).forEach(function (w) {
      if (w.type === 'forecast' && w.history && w.forecast) target.appendChild(forecastWidget(w, byN));
      else if (w.type === 'chart' && w.points && w.points.length) target.appendChild(chartWidget(w, byN));
      else if (w.type === 'stats' && w.items && w.items.length) target.appendChild(statsWidget(w, byN));
    });
  }

  // ---- messages ----
  function addUser(q) {
    var m = el('div', 'cx-msg user'); m.appendChild(el('div', 'cx-bubble', q));
    thread.appendChild(m); keepScrolled(true);
  }
  function addBot() {
    var m = el('div', 'cx-msg bot thinking');
    m.appendChild(el('div', 'cx-mark'));
    var b = el('div', 'cx-body'); m.appendChild(b);
    thread.appendChild(m); keepScrolled(true);
    return { msg: m, body: b };
  }
  function setStatus(bot, steps) {
    var i = 0, row = el('div', 'cx-status'), dots = el('span', 'cx-dots');
    dots.appendChild(el('i')); dots.appendChild(el('i')); dots.appendChild(el('i'));
    var txt = el('span', 'cx-status-text', steps[0]);
    row.appendChild(dots); row.appendChild(txt); bot.body.appendChild(row);
    var t = setInterval(function () {
      i = Math.min(steps.length - 1, i + 1);
      var n = el('span', 'cx-status-text', steps[i]); row.replaceChild(n, row.lastChild); txt = n;
    }, 1700);
    return function () { clearInterval(t); row.remove(); };
  }
  function meta(bot, reply) {
    var row = el('div', 'cx-meta');
    var c = reply.checks || {};
    if (reply.answer) {
      var ok = reply.answered_by === 'data' || c.grounded;
      var problems = [];
      if ((c.unverified_numbers || []).length) problems.push('numbers not in the data: ' + c.unverified_numbers.join(', '));
      if ((c.unknown_citations || []).length) problems.push('unknown citations');
      if ((c.bare_citation_lines || []).length) problems.push('loose citations');
      if (reply.answered_by !== 'data' && !(c.citations_used || []).length) problems.push('no citations');
      var badge = el('span', 'cx-badge ' + (ok ? 'ok' : 'warn'), ok ? '✓ Checked against SEC data' : 'Check: ' + problems.join('; '));
      row.appendChild(badge);
    }
    var by = reply.answered_by === 'data' ? 'Read from filings' : (reply.model ? reply.model + ' (local)' : null);
    if (by) row.appendChild(el('span', null, by + (reply.brief && reply.brief.as_of ? ' · as of ' + reply.brief.as_of : '')));
    if (reply.answer) {
      var copy = el('button', 'cx-act'); copy.type = 'button'; copy.title = 'Copy answer'; copy.setAttribute('aria-label', 'Copy answer');
      copy.appendChild(svg('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>'));
      copy.onclick = function () { try { navigator.clipboard.writeText(reply.answer); copy.title = 'Copied'; } catch (e) { /* clipboard blocked */ } };
      row.appendChild(copy);
    }
    bot.body.appendChild(row);
    (reply.notes || []).slice(1).forEach(function (n) { bot.body.appendChild(el('div', 'cx-note', n)); });
  }
  function showReply(bot, reply, animate, q) {
    bot.msg.classList.remove('thinking');
    var content = el('div'); bot.body.appendChild(content);
    if (!reply.company) {
      content.appendChild(el('p', null, (reply.notes || [])[0] || 'Which company do you mean?'));
      var chips = el('div', 'cx-chips');
      (reply.suggestions || []).forEach(function (s) {
        var chip = el('button', 'cx-chip', s.legal_name + (s.ticker ? ' · ' + s.ticker : '')); chip.type = 'button';
        chip.onclick = function () { state.cik = s.cik; ask((q || '') + ' ' + (s.ticker || s.legal_name)); };
        chips.appendChild(chip);
      });
      content.appendChild(chips);
      return;
    }
    state.cik = reply.company.cik;
    renderSide(reply);
    // SEC names are often upper case; read "Netflix Inc" rather than "NETFLIX INC" in the answer.
    if (reply.answer) reply = Object.assign({}, reply, { answer: reply.answer.split(reply.company.legal_name).join(displayName(reply.company.legal_name)) });
    if (!reply.answer) {
      content.appendChild(el('p', 'cx-note', 'The language model is not available right now; the figures for ' + displayName(reply.company.legal_name) + ' are below and in the company panel.'));
      renderWidgets(content, reply); meta(bot, reply); return;
    }
    if (isLeadership(reply)) { renderLeadership(content, reply); meta(bot, reply); keepScrolled(); return; }
    var finish = function () { renderWidgets(content, reply); meta(bot, reply); keepScrolled(); };
    if (animate) stream(content, reply.answer, reply.citations, finish);
    else { content.appendChild(renderText(reply.answer, reply.citations)); finish(); }
  }

  // ---- company drawer ----
  function fmtPct(p) { return p == null ? '' : (p > 0 ? '+' : '') + p.toFixed(1) + '%'; }
  function renderSide(reply) {
    var c = reply.company, brief = reply.brief || {};
    $('side-name').textContent = displayName(c.legal_name);
    $('side-meta').textContent = [c.ticker, c.exchange, 'CIK ' + c.cik, c.sic_description].filter(Boolean).join(' · ');
    var cov = brief.coverage || {};
    $('side-coverage').textContent = (cov.filings ? 'Loaded here: ' + cov.filings + ' filings, ' + cov.first_filed + ' to ' + cov.last_filed + (cov.stale ? ' (newer filings not loaded)' : '') : 'No filings loaded for this company.') +
      (cov.prospectus ? ' Prospectus read: ' + cov.prospectus.form_type + ' filed ' + cov.prospectus.filed_date + '.' : '');
    var m = $('side-metrics'); m.textContent = '';
    (brief.metrics || []).forEach(function (x) {
      var row = el('div', 'cx-metric'), left = el('span');
      left.appendChild(link(x.source_url, x.label)); left.appendChild(el('span', 'cx-muted cx-small', ' FY' + x.period_end.slice(0, 4)));
      var right = el('span', null, x.display + ' ');
      if (x.growth_pct != null) right.appendChild(el('span', x.growth_pct >= 0 ? 'up' : 'down', fmtPct(x.growth_pct)));
      row.appendChild(left); row.appendChild(right); m.appendChild(row);
    });
    if (!m.childNodes.length) m.appendChild(el('p', 'cx-muted cx-small', 'No annual figures loaded.'));
    var lead = $('side-leaders'); lead.textContent = '';
    (brief.leadership_filings || []).forEach(function (f) {
      var li = el('li'); li.appendChild(link(f.source_url, '8-K · ' + f.filing_date));
      (f.changes || []).forEach(function (ch) { li.appendChild(el('span', 'sub', (ch.person || 'Company-wide') + ' — ' + (TAGS[ch.change] || TAGS.other)[0].toLowerCase())); });
      lead.appendChild(li);
    });
    if (!lead.childNodes.length) lead.appendChild(el('li', 'cx-muted', 'None since ' + (cov.since || 'the last three years') + '.'));
    var fl = $('side-filings'); fl.textContent = '';
    (brief.filings || []).forEach(function (f) {
      var li = el('li'); li.appendChild(link(f.source_url, f.form_type + ' · ' + f.filing_date));
      if (f.items && f.items.length) li.appendChild(el('span', 'sub', 'Items ' + f.items.map(function (i) { return i.code; }).join(', ')));
      fl.appendChild(li);
    });
    var chip = $('cx-company-chip');
    $('cx-company-chip-text').textContent = c.ticker || displayName(c.legal_name);
    chip.hidden = false;
    $('cx-title').textContent = displayName(c.legal_name);
  }
  function drawer(open) {
    body.classList.toggle('drawer-open', open);
    $('cx-drawer').setAttribute('aria-hidden', open ? 'false' : 'true');
  }

  // ---- asking ----
  var LEAD_RE = /\b(leadership|ceo|cfo|coo|chief|executives?|officers?|directors?|board|resign\w*|appoint\w*|hired?|depart\w*|succession|chair\w*)\b/i;
  var TREND_RE = /\b(growth|grow\w*|grew|trend\w*|histor\w*|years|chart|graph|over time|yoy|cagr)\b/i;
  var FORECAST_RE = /\b(forecast\w*|predict\w*|projections?|outlook|estimates?|(?:next|coming|following|upcoming)\s+(?:\d{1,2}\s+|two\s+|three\s+|four\s+|five\s+)?(?:fiscal\s+)?years?)\b/i;
  function headers() { return { 'Content-Type': 'application/json', 'X-API-Key': state.key }; }

  function ask(q) {
    q = (q || '').trim().slice(0, 500);
    if (!q || state.busy) return;
    state.busy = true; send.disabled = true;
    var bot;
    var go = function () { body.dataset.state = 'chat'; addUser(q); bot = addBot(); };
    (body.dataset.state === 'home' ? transition(go) : (go(), Promise.resolve())).then(function () { request(q, bot); });
  }

  function request(q, bot) {
    var steps = FORECAST_RE.test(q)
      ? ['Finding the company…', 'Collecting annual and quarterly figures…', 'Reading the latest earnings release…', 'Scanning company and industry news…', 'Thinking it through, about a minute…']
      : LEAD_RE.test(q)
      ? ['Finding the company…', 'Reading the 8-K filings…', 'Checking names against the filing text…']
      : TREND_RE.test(q)
        ? ['Finding the company…', 'Collecting each annual report…', 'Building the chart…']
        : ['Finding the company…', 'Gathering SEC figures…', 'Writing the answer…', 'Checking every figure…'];
    var stop = setStatus(bot, steps);
    var payload = { message: q };
    if (state.cik) payload.cik = state.cik;
    if ($('cx-asof').value) payload.as_of = $('cx-asof').value;
    if (state.sessionId && state.connected) payload.session_id = state.sessionId;
    state.controller = window.AbortController ? new AbortController() : null;
    fetch('/v1/chat', { method: 'POST', headers: headers(), body: JSON.stringify(payload), signal: state.controller && state.controller.signal })
      .then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
      .then(function (res) {
        stop();
        if (res.status !== 200) {
          bot.msg.classList.remove('thinking');
          bot.body.appendChild(el('p', null, (res.body.error && res.body.error.message) || ('Error ' + res.status)));
          return;
        }
        var reply = res.body;
        showReply(bot, reply, true, q);
        if (reply.session_id && state.connected) {
          var fresh = !state.sessionId;
          state.sessionId = reply.session_id; setHash();
          if (fresh) loadSessions();
        } else if (!state.connected) {
          var log = sload('cx_demo') || []; log.push({ q: q, reply: reply }); sstore('cx_demo', log.slice(-30));
        }
      })
      .catch(function () { stop(); bot.msg.classList.remove('thinking'); bot.body.appendChild(el('p', null, 'Network error. Try again.')); })
      .finally(function () { state.busy = false; send.disabled = !input.value.trim(); state.controller = null; });
  }

  function newChat() {
    transition(function () {
      thread.textContent = ''; state.sessionId = null; state.cik = null; setHash();
      body.dataset.state = 'home'; $('cx-company-chip').hidden = true; $('cx-title').textContent = 'Company intelligence';
      drawer(false); markCurrent(); sstore('cx_demo', []);
    });
    closeSideOnMobile(); input.focus();
  }

  // ---- saved sessions (own API key only) ----
  function setHash() {
    var h = state.sessionId ? '#s=' + state.sessionId : '';
    if (location.hash !== h) history.replaceState(null, '', location.pathname + location.search + h);
  }
  function markCurrent() {
    document.querySelectorAll('.cx-session').forEach(function (li) { li.setAttribute('aria-current', li.dataset.id === state.sessionId ? 'true' : 'false'); });
  }
  function loadSessions() {
    var list = $('cx-session-list'), hint = $('cx-session-hint');
    if (!state.connected) { list.textContent = ''; hint.hidden = false; return; }
    hint.hidden = true;
    fetch('/v1/chat/sessions?limit=100', { headers: headers() }).then(function (r) { return r.ok ? r.json() : { data: [] }; }).then(function (b) {
      list.textContent = '';
      b.data.forEach(function (s, i) {
        var li = el('li', 'cx-session'); li.dataset.id = s.id; li.style.animationDelay = Math.min(i, 12) * 0.02 + 's';
        var open = el('button', 'open', s.title); open.type = 'button'; open.title = s.title;
        open.onclick = function () { openSession(s.id); };
        var del = el('button', 'del'); del.type = 'button'; del.setAttribute('aria-label', 'Delete chat'); del.title = 'Delete chat';
        del.appendChild(svg('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>'));
        del.onclick = function () {
          li.style.transition = 'opacity .2s, transform .2s'; li.style.opacity = '0'; li.style.transform = 'translateX(-8px)';
          fetch('/v1/chat/sessions/' + s.id, { method: 'DELETE', headers: headers() }).then(function () {
            li.remove(); if (state.sessionId === s.id) newChat();
          });
        };
        li.appendChild(open); li.appendChild(del); list.appendChild(li);
      });
      if (!b.data.length) { hint.textContent = 'Your chats will appear here.'; hint.hidden = false; }
      markCurrent();
    });
  }
  function openSession(id) {
    fetch('/v1/chat/sessions/' + id, { headers: headers() }).then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
      if (!s) { state.sessionId = null; setHash(); return; }
      transition(function () {
        thread.textContent = ''; state.sessionId = s.id; state.cik = s.company_cik; setHash();
        body.dataset.state = 'chat'; drawer(false);
        s.messages.forEach(function (m) {
          if (m.role === 'user') addUser(m.content);
          else if (m.reply) { var bot = addBot(); showReply(bot, m.reply, false); }
        });
        markCurrent(); keepScrolled(true);
      });
      closeSideOnMobile();
    });
  }

  // ---- account / API key ----
  function setAccount() {
    $('cx-account-name').textContent = state.connected ? 'Connected' : 'Demo mode';
    $('cx-account-sub').textContent = state.connected ? state.key.slice(0, 14) + '… · Disconnect' : 'Connect API key';
    $('cx-avatar').textContent = state.connected ? 'K' : 'D';
  }
  function connect(key) {
    return fetch('/v1/chat/sessions?limit=1', { headers: { 'X-API-Key': key } }).then(function (r) {
      if (!r.ok) throw new Error(r.status === 401 ? 'That key was not accepted.' : 'Could not check the key (HTTP ' + r.status + ').');
      state.key = key; state.connected = true; store('prov_key', key); setAccount(); loadSessions();
    });
  }
  $('cx-account').onclick = function () {
    if (state.connected) {
      state.key = DEMO; state.connected = false; store('prov_key', null); setAccount(); loadSessions(); newChat(); return;
    }
    $('cx-key-error').hidden = true; $('cx-key-input').value = ''; $('cx-key-modal').showModal();
  };
  $('cx-key-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var k = $('cx-key-input').value.trim(); if (!k) return;
    $('cx-key-save').disabled = true;
    connect(k).then(function () { $('cx-key-modal').close(); newChat(); })
      .catch(function (err) { var x = $('cx-key-error'); x.textContent = err.message; x.hidden = false; })
      .finally(function () { $('cx-key-save').disabled = false; });
  });
  $('cx-key-demo').onclick = function () { $('cx-key-modal').close(); };

  // ---- layout controls ----
  var mobile = window.matchMedia('(max-width: 860px)');
  function closeSideOnMobile() { if (mobile.matches) { body.classList.remove('side-open'); $('cx-scrim').hidden = true; } }
  $('cx-collapse').onclick = function () { if (mobile.matches) closeSideOnMobile(); else body.classList.add('side-closed'); };
  $('cx-open-side').onclick = function () {
    if (mobile.matches) { body.classList.add('side-open'); $('cx-scrim').hidden = false; } else body.classList.remove('side-closed');
  };
  $('cx-scrim').onclick = closeSideOnMobile;
  $('cx-new').onclick = newChat;
  $('cx-company-chip').onclick = function () { drawer(!body.classList.contains('drawer-open')); };
  $('cx-drawer-close').onclick = function () { drawer(false); };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { drawer(false); closeSideOnMobile(); } });
  $('cx-asof-btn').onclick = function () {
    var d = $('cx-asof'); d.hidden = !d.hidden; this.classList.toggle('on', !d.hidden);
    if (!d.hidden) d.focus(); else { d.value = ''; $('cx-asof-label').textContent = 'Latest data'; }
  };
  $('cx-asof').onchange = function () { $('cx-asof-label').textContent = this.value ? 'As of ' + this.value : 'Latest data'; };

  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 200) + 'px'; }
  input.addEventListener('input', function () { autosize(); send.disabled = state.busy || !input.value.trim(); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit')); }
  });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value; if (!q.trim() || state.busy) return;
    input.value = ''; autosize(); ask(q);
  });
  document.querySelectorAll('.cx-card[data-q]').forEach(function (b) { b.addEventListener('click', function () { ask(b.getAttribute('data-q')); }); });

  // ---- start ----
  setAccount();
  var saved = load('prov_key');
  var hashId = (/^#s=([0-9a-f-]{36})$/.exec(location.hash) || [])[1];
  var q0 = new URLSearchParams(location.search).get('q');
  var ready = saved && saved !== DEMO ? connect(saved).catch(function () { store('prov_key', null); }) : Promise.resolve();
  ready.then(function () {
    loadSessions();
    if (hashId && state.connected) openSession(hashId);
    else if (!state.connected && (sload('cx_demo') || []).length) {
      body.dataset.state = 'chat';
      sload('cx_demo').forEach(function (t) { addUser(t.q); showReply(addBot(), t.reply, false, t.q); });
      keepScrolled(true);
    }
    if (q0) ask(q0);
  });
  if (mobile.matches) { body.classList.remove('side-open'); input.placeholder = 'Ask about a company…'; }
  input.focus();
})();
