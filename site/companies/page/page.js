/* The company page and its layouts (issues #9, #10): data, formatting and small SVG charts.
   Every figure comes from /v1/public/companies/{cik}/overview and links to its filing. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var P = window.CompanyPage = {};
  P.cik = (location.pathname.match(/companies\/(\d{1,10})/) || [])[1] || '1018724';
  P.load = function () {
    return fetch('/v1/public/companies/' + P.cik + '/overview', { headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  };
  P.$ = function (id) { return document.getElementById(id); };
  P.el = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else if (attrs[k] != null) n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  P.money = function (v, digits) {
    if (v == null) return '—';
    var a = Math.abs(v), s = v < 0 ? '−$' : '$', d = digits == null ? 1 : digits;
    if (a >= 1e12) return s + (a / 1e12).toFixed(d) + 'T';
    if (a >= 1e9) return s + (a / 1e9).toFixed(d) + 'B';
    if (a >= 1e6) return s + (a / 1e6).toFixed(d) + 'M';
    if (a >= 1e3) return s + (a / 1e3).toFixed(0) + 'K';
    return s + a.toFixed(0);
  };
  P.pct = function (v, sign) { return v == null ? '—' : (sign && v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%'; };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  P.date = function (iso) { if (!iso) return '—'; var p = iso.slice(0, 10).split('-'); return parseInt(p[2], 10) + ' ' + MON[parseInt(p[1], 10) - 1] + ' ' + p[0]; };
  P.phone = function (p) { if (!p) return null; var d = p.replace(/\D/g, ''); return d.length === 10 ? '(' + d.slice(0, 3) + ') ' + d.slice(3, 6) + '-' + d.slice(6) : p; };
  P.title = function (s) { return s ? s.toLowerCase().replace(/\b([a-z])/g, function (m) { return m.toUpperCase(); }) : s; };
  P.address = function (a) {
    if (!a) return null;
    var street = [a.street1, a.street2].filter(Boolean).map(P.title).join(', ');
    var city = [P.title(a.city), a.stateOrCountry && a.stateOrCountry.length === 2 ? a.stateOrCountry : null, a.zipCode].filter(Boolean).join(' ');
    return [street, city, a.country !== 'United States' ? a.country : null].filter(Boolean);
  };
  var STATES = { AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', PR: 'Puerto Rico' };
  P.state = function (code) { return code ? STATES[code] || code : null; };
  P.LABELS = { revenue: 'Revenue', operating_income: 'Operating income', net_income: 'Net income', total_assets: 'Total assets', operating_cash_flow: 'Operating cash flow' };
  P.link = function (text, url, cls) {
    if (!url || url.indexOf('https://www.sec.gov/') !== 0) return P.el('span', { text: text, class: cls });
    return P.el('a', { href: url, target: '_blank', rel: 'noopener', text: text, class: cls });
  };
  /* The finding: what in this company's own numbers most needs saying. */
  P.finding = function (d) {
    var ys = d.years.filter(function (y) { return y.operating_margin_pct != null; });
    var last = ys[ys.length - 1];
    if (ys.length >= 5 && last) {
      var max = Math.max.apply(null, ys.map(function (y) { return y.operating_margin_pct; }));
      var min = Math.min.apply(null, ys.map(function (y) { return y.operating_margin_pct; }));
      if (last.operating_margin_pct === max) return 'Operating margin ' + P.pct(last.operating_margin_pct) + ' in ' + last.fiscal_label + ', the highest of the ' + ys.length + ' years shown.';
      if (last.operating_margin_pct === min) return 'Operating margin ' + P.pct(last.operating_margin_pct) + ' in ' + last.fiscal_label + ', the lowest of the ' + ys.length + ' years shown.';
    }
    var rev = d.key_figures.filter(function (k) { return k.metric === 'revenue'; })[0];
    if (rev && rev.change_pct != null) return 'Revenue ' + (rev.change_pct >= 0 ? 'up ' : 'down ') + P.pct(Math.abs(rev.change_pct)) + ' in ' + rev.fiscal_label + ' to ' + P.money(rev.value) + '.';
    return null;
  };
  /* Revenue bars (the latest in the accent) with an operating-margin line; every bar links. */
  P.revenueChart = function (years, opts) {
    opts = opts || {};
    var W = opts.width || 720, H = opts.height || 220, padB = 26, padT = 18, padL = 4, padR = opts.margin === false ? 4 : 40;
    var ys = years.filter(function (y) { return y.revenue != null; });
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('class', 'rev-chart'); svg.setAttribute('role', 'img');
    if (!ys.length) return svg;
    var max = Math.max.apply(null, ys.map(function (y) { return y.revenue; }));
    var first = ys[0], last = ys[ys.length - 1];
    svg.setAttribute('aria-label', 'Revenue by fiscal year, ' + first.fiscal_label + ' ' + P.money(first.revenue) + ' to ' + last.fiscal_label + ' ' + P.money(last.revenue) + '.');
    var plotW = W - padL - padR, step = plotW / ys.length, bw = Math.min(46, step * 0.62), plotH = H - padB - padT;
    var mx = Math.max(1, Math.max.apply(null, ys.map(function (y) { return Math.abs(y.operating_margin_pct || 0); })));
    ys.forEach(function (y, i) {
      var x = padL + i * step + (step - bw) / 2, h = plotH * y.revenue / max;
      var a = document.createElementNS(NS, 'a');
      var src = y.sources && y.sources.revenue; if (src) { a.setAttribute('href', src); a.setAttribute('target', '_blank'); }
      var r = document.createElementNS(NS, 'rect');
      r.setAttribute('x', x); r.setAttribute('y', padT + plotH - h); r.setAttribute('width', bw); r.setAttribute('height', Math.max(1, h));
      r.setAttribute('class', i === ys.length - 1 ? 'col latest' : 'col');
      var t = document.createElementNS(NS, 'title'); t.textContent = y.fiscal_label + ': revenue ' + P.money(y.revenue) + (y.operating_margin_pct != null ? ', operating margin ' + P.pct(y.operating_margin_pct) : '');
      r.appendChild(t); a.appendChild(r); svg.appendChild(a);
      if (opts.values && (i === ys.length - 1 || i === 0)) {
        var v = document.createElementNS(NS, 'text'); v.setAttribute('x', x + bw / 2); v.setAttribute('y', padT + plotH - h - 5); v.setAttribute('text-anchor', 'middle'); v.setAttribute('class', 'val'); v.textContent = P.money(y.revenue, 0); svg.appendChild(v);
      }
      var lab = document.createElementNS(NS, 'text'); lab.setAttribute('x', x + bw / 2); lab.setAttribute('y', H - 8); lab.setAttribute('text-anchor', 'middle'); lab.setAttribute('class', 'axis');
      lab.textContent = ys.length > 7 && i % 2 && i !== ys.length - 1 ? '' : y.fiscal_label.replace('FY', "'").replace("'20", "'"); svg.appendChild(lab);
    });
    if (opts.margin !== false) {
      var pts = ys.map(function (y, i) { return y.operating_margin_pct == null ? null : [padL + i * step + step / 2, padT + plotH * (1 - (y.operating_margin_pct + mx) / (2 * mx))]; }).filter(Boolean);
      if (pts.length > 1) {
        var path = document.createElementNS(NS, 'polyline'); path.setAttribute('points', pts.map(function (p) { return p.join(','); }).join(' ')); path.setAttribute('class', 'margin-line'); svg.appendChild(path);
        var lp = pts[pts.length - 1], lt = document.createElementNS(NS, 'text'); lt.setAttribute('x', W - 2); lt.setAttribute('y', lp[1] + 4); lt.setAttribute('text-anchor', 'end'); lt.setAttribute('class', 'margin-label'); lt.textContent = P.pct(last.operating_margin_pct); svg.appendChild(lt);
      }
    }
    return svg;
  };
  P.spark = function (values, w, h) {
    var svg = document.createElementNS(NS, 'svg'); w = w || 88; h = h || 24;
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h); svg.setAttribute('class', 'spark'); svg.setAttribute('aria-hidden', 'true');
    var vs = values.filter(function (v) { return v != null; }); if (vs.length < 2) return svg;
    var mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs), rng = mx - mn || 1;
    var pts = vs.map(function (v, i) { return (i * (w - 4) / (vs.length - 1) + 2) + ',' + (h - 3 - (v - mn) / rng * (h - 6)); });
    var pl = document.createElementNS(NS, 'polyline'); pl.setAttribute('points', pts.join(' ')); svg.appendChild(pl);
    var lastPt = pts[pts.length - 1].split(','), c = document.createElementNS(NS, 'circle'); c.setAttribute('cx', lastPt[0]); c.setAttribute('cy', lastPt[1]); c.setAttribute('r', 2.4); svg.appendChild(c);
    return svg;
  };
  /* The notes under the page; the disclaimer is in the site footer already. */
  P.notes = function (d) { return d.notes.filter(function (n) { return n.indexOf('not affiliated') < 0; }); };
  P.series = function (years, metric) { return years.map(function (y) { return y[metric]; }); };
  P.chatUrl = function (d) { return '/chat/?q=' + encodeURIComponent('Summarise ' + (d.company.ticker || d.company.display_name)); };
  /* ---- The figure view (issue #10): one figure's years as a large chart, with what they show.
     Everything is worked out here from the overview's stored figures; no model writes it. ---- */
  var ORDER = ['revenue', 'operating_income', 'net_income', 'operating_cash_flow', 'total_assets'];
  var SHARE = { operating_income: 1, net_income: 1, operating_cash_flow: 1 };
  var rowsFor = function (d, m) { return d.years.filter(function (y) { return y[m] != null; }); };
  /* A percentage only between two positive years; a move into or out of a loss has none. */
  var change = function (a, b) { return b > 0 && a >= 0 ? 100 * (a - b) / b : null; };
  var ordinal = function (n) { var s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
  var median = function (vs) { var s = vs.slice().sort(function (a, b) { return a - b; }), h = s.length >> 1; return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2; };
  var list = function (xs) { return xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1]; };
  /* Year-on-year changes, only between consecutive fiscal years with a positive base. */
  P.yearChanges = function (rows, m) {
    var out = [];
    rows.forEach(function (y, i) {
      var p = rows[i - 1];
      if (p && y.fiscal_year - p.fiscal_year === 1) out.push({ y: y, pct: change(y[m], p[m]), fell: y[m] < p[m] });
    });
    return out;
  };
  P.insights = function (d, m) {
    var rows = rowsFor(d, m), name = P.LABELS[m], out = [];
    if (!rows.length) return ['No annual figure for this was filed in the years shown.'];
    var last = rows[rows.length - 1], first = rows[0], ch = P.yearChanges(rows, m);
    var prevCh = ch.length && ch[ch.length - 1].y === last ? ch[ch.length - 1] : null;
    out.push(name + (m === 'total_assets' ? ' were ' : ' was ') + P.money(last[m]) + ' in ' + last.fiscal_label + (prevCh && prevCh.pct != null ? ', ' + (prevCh.pct >= 0 ? 'up ' : 'down ') + P.pct(Math.abs(prevCh.pct)) + ' on the year before.' : '.'));
    var span = last.fiscal_year - first.fiscal_year;
    if (rows.length >= 3 && span > 0 && rows.every(function (y) { return y[m] > 0; })) {
      var cagr = 100 * (Math.pow(last[m] / first[m], 1 / span) - 1);
      out.push('From ' + P.money(first[m]) + ' in ' + first.fiscal_label + ': ' + (cagr >= 0 ? 'growth of ' : 'a fall of ') + P.pct(Math.abs(cagr)) + ' a year, compounded over ' + span + ' years.');
    }
    if (ch.length >= 2) {
      var falls = ch.filter(function (c) { return c.fell; }), known = ch.filter(function (c) { return c.pct != null; });
      var up = known.reduce(function (a, c) { return c.pct > 0 && (!a || c.pct > a.pct) ? c : a; }, null);
      var down = known.reduce(function (a, c) { return c.pct < 0 && (!a || c.pct < a.pct) ? c : a; }, null);
      var biggest = [up && 'the largest rise was ' + P.pct(up.pct, true) + ' in ' + up.y.fiscal_label, down && 'the largest fall ' + P.pct(down.pct, true) + ' in ' + down.y.fiscal_label].filter(Boolean).join(', ');
      if (!falls.length) out.push('It rose every year shown' + (biggest ? '; ' + biggest : '') + '.');
      else out.push('It rose in ' + (ch.length - falls.length) + ' of ' + ch.length + ' years and fell in ' + list(falls.map(function (c) { return c.y.fiscal_label; })) + (biggest ? '; ' + biggest : '') + '.');
    }
    var losses = rows.filter(function (y) { return y[m] < 0; });
    if (losses.length && m !== 'total_assets') out.push((losses.length === 1 ? 'A loss in ' : 'Losses in ' + losses.length + ' of ' + rows.length + ' years: ') + list(losses.map(function (y) { return y.fiscal_label + ' (' + P.money(y[m]) + ')'; })) + '.');
    if (SHARE[m]) {
      var shares = rows.filter(function (y) { return y.revenue > 0; }).map(function (y) { return { y: y, v: 100 * y[m] / y.revenue }; });
      if (shares.length >= 2 && shares[shares.length - 1].y === last) {
        var now = shares[shares.length - 1].v, med = median(shares.map(function (s) { return s.v; }));
        var top = shares.reduce(function (a, s) { return s.v > a.v ? s : a; });
        out.push(P.pct(now) + ' of revenue in ' + last.fiscal_label + ', against a median of ' + P.pct(med) + ' over ' + shares.length + ' years' + (top.y === last ? '; the highest share shown.' : '; highest was ' + P.pct(top.v) + ' in ' + top.y.fiscal_label + '.'));
      }
    }
    if (m === 'total_assets') {
      var turn = rows.filter(function (y) { return y.revenue != null && y.total_assets > 0; });
      if (turn.length >= 2) {
        var t0 = turn[0], t1 = turn[turn.length - 1];
        out.push('Revenue was ' + (t1.revenue / t1.total_assets).toFixed(2) + ' times total assets in ' + t1.fiscal_label + ', against ' + (t0.revenue / t0.total_assets).toFixed(2) + ' in ' + t0.fiscal_label + '.');
      }
    }
    if (m === 'revenue' && d.peers && d.peers.companies.length) {
      var all = d.peers.companies.map(function (p) { return p.latest_revenue; }).concat([last.revenue]).sort(function (a, b) { return b - a; });
      var rank = all.indexOf(last.revenue) + 1;
      out.push((rank === 1 ? 'The largest' : 'The ' + ordinal(rank) + ' largest') + ' of ' + all.length + ' companies in ' + d.peers.basis.split(' (')[0] + ' by latest annual revenue.');
    }
    return out;
  };
  var svgEl = function (tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  };
  /* Bars from a zero line (losses below it), the latest in the accent, every bar linked. */
  P.figureChart = function (rows, m, width) {
    var W = Math.max(300, Math.round(width)), narrow = W < 560, H = narrow ? 240 : 320;
    var padL = 52, padR = 8, padT = 22, padB = 28;
    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, class: 'fv-chart', role: 'img' });
    if (!rows.length) return svg;
    var vals = rows.map(function (y) { return y[m]; });
    var hi = Math.max(0, Math.max.apply(null, vals)), lo = Math.min(0, Math.min.apply(null, vals));
    // Gridlines on round steps (1, 2 or 5 times a power of ten), the scale widened to meet them.
    // A small loss gets room below zero without pulling the scale down to a whole step.
    var raw = (hi - lo || 1) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), unit = raw / mag;
    var tick = mag * (unit <= 1.2 ? 1 : unit <= 2.5 ? 2 : unit <= 6 ? 5 : 10);
    hi = Math.ceil(hi / tick) * tick; lo = lo < 0 ? Math.max(Math.floor(lo / tick) * tick, lo * 1.25) : 0;
    var rng = hi - lo || 1, ticks = [];
    for (var t = Math.ceil(lo / tick) * tick; t <= hi + tick / 2; t += tick) ticks.push(Math.abs(t) < tick / 2 ? 0 : t);
    var tickText = ticks.map(function (t) { return t ? P.money(t, 0) : '0'; });
    if (new Set(tickText).size < ticks.length) tickText = ticks.map(function (t) { return t ? P.money(t, 1) : '0'; });
    var plotH = H - padT - padB, yOf = function (v) { return padT + (hi - v) / rng * plotH; };
    var first = rows[0], last = rows[rows.length - 1];
    svg.setAttribute('aria-label', P.LABELS[m] + ' by fiscal year, ' + first.fiscal_label + ' ' + P.money(first[m]) + ' to ' + last.fiscal_label + ' ' + P.money(last[m]) + '.');
    ticks.forEach(function (v, i) {
      var gy = yOf(v);
      svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: gy, y2: gy, class: 'grid' }));
      svg.appendChild(svgEl('text', { x: padL - 8, y: gy + 4, 'text-anchor': 'end', class: 'axis' }, tickText[i]));
    });
    svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: yOf(0), y2: yOf(0), class: 'zero' }));
    var step = (W - padL - padR) / rows.length, bw = Math.min(56, step * 0.64);
    var maxRow = rows.reduce(function (a, y) { return y[m] > a[m] ? y : a; }), minRow = rows.reduce(function (a, y) { return y[m] < a[m] ? y : a; });
    rows.forEach(function (y, i) {
      var v = y[m], x = padL + i * step + (step - bw) / 2, top = Math.min(yOf(v), yOf(0)), h = Math.max(1, Math.abs(yOf(v) - yOf(0)));
      var a = svgEl('a', {}), src = y.sources && y.sources[m];
      if (src && src.indexOf('https://www.sec.gov/') === 0) { a.setAttribute('href', src); a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener'); }
      var r = svgEl('rect', { x: x, y: top, width: bw, height: h, rx: 2, class: 'col' + (v < 0 ? ' neg' : '') + (y === last ? ' latest' : '') });
      r.appendChild(svgEl('title', {}, y.fiscal_label + ': ' + P.money(v) + (src ? ' (opens the filing)' : '')));
      a.appendChild(r); svg.appendChild(a);
      if (!narrow || y === last || y === first || y === maxRow || y === minRow) {
        svg.appendChild(svgEl('text', { x: x + bw / 2, y: (v < 0 ? yOf(0) : top) - 6, 'text-anchor': 'middle', class: 'val' + (y === last ? ' latest' : '') }, P.money(v, narrow || Math.abs(v) >= 1e11 ? 0 : 1)));
      }
      if (!narrow || i % 2 === (rows.length - 1) % 2) svg.appendChild(svgEl('text', { x: x + bw / 2, y: H - 8, 'text-anchor': 'middle', class: 'axis' }, narrow ? y.fiscal_label.replace('FY20', "'") : y.fiscal_label));
    });
    return svg;
  };
  var dialog, opener, current;
  function buildDialog() {
    dialog = P.el('dialog', { class: 'fv', 'aria-labelledby': 'fv-title' });
    dialog.innerHTML = '<div class="fv-head"><div><p class="fv-co" id="fv-co"></p><h2 id="fv-title"></h2></div><button type="button" class="fv-x" aria-label="Close">&times;</button></div>' +
      '<div class="fv-tabs" id="fv-tabs" aria-label="Figures"></div>' +
      '<p class="fv-big" id="fv-big"></p><div class="fv-plot" id="fv-plot"></div>' +
      '<div class="fv-cols"><section aria-labelledby="fv-ins-h"><h3 id="fv-ins-h">What the years show</h3><ul class="fv-ins" id="fv-ins"></ul></section>' +
      '<section aria-labelledby="fv-tab-h"><h3 id="fv-tab-h">Year by year</h3><div class="tw"><table id="fv-table"></table></div></section></div>' +
      '<div class="fv-foot"><a class="btn primary" id="fv-ask" href="/chat/">Ask about this</a><p class="small muted">Each bar and figure links to the annual report it comes from. As filed; not investment advice.</p></div>';
    document.body.appendChild(dialog);
    dialog.querySelector('.fv-x').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener('close', function () {
      try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
      if (opener && document.contains(opener)) opener.focus();
    });
    var resize; window.addEventListener('resize', function () { clearTimeout(resize); resize = setTimeout(function () { if (dialog.open) render(current.d, current.m); }, 150); });
  }
  function render(d, m) {
    current = { d: d, m: m };
    var $d = function (id) { return dialog.querySelector('#' + id); }, rows = rowsFor(d, m), last = rows[rows.length - 1];
    $d('fv-co').textContent = d.company.display_name + ' · annual reports';
    $d('fv-title').textContent = P.LABELS[m];
    var tabs = $d('fv-tabs'); tabs.textContent = '';
    ORDER.forEach(function (k) {
      if (!rowsFor(d, k).length) return;
      var b = P.el('button', { type: 'button', class: 'fv-tab', 'aria-pressed': String(k === m), text: P.LABELS[k] });
      b.addEventListener('click', function () { render(d, k); b.focus(); });
      tabs.appendChild(b);
    });
    var big = $d('fv-big'); big.textContent = '';
    var kf = d.key_figures.filter(function (k) { return k.metric === m; })[0];
    if (last) {
      big.appendChild(P.el('b', { text: P.money(last[m]) }));
      big.appendChild(P.el('span', { class: 'quiet' }, [last.fiscal_label + (kf && kf.form_type ? ' · ' : ''), kf && kf.form_type ? P.link(kf.form_type + ' filed ' + P.date(kf.filed_date), kf.source_url) : null]));
    }
    var plot = $d('fv-plot'); plot.textContent = '';
    plot.appendChild(P.figureChart(rows, m, plot.clientWidth || 860));
    var ins = $d('fv-ins'); ins.textContent = '';
    P.insights(d, m).forEach(function (t) { ins.appendChild(P.el('li', { text: t })); });
    var share = SHARE[m], tbl = $d('fv-table'); tbl.textContent = '';
    tbl.appendChild(P.el('thead', {}, [P.el('tr', {}, [P.el('th', { text: 'Year' }), P.el('th', { class: 'n', text: P.LABELS[m] }), P.el('th', { class: 'n', text: 'Change' }), share ? P.el('th', { class: 'n', text: 'Of revenue' }) : null])]));
    var tb = P.el('tbody'), ch = {};
    P.yearChanges(rows, m).forEach(function (c) { ch[c.y.fiscal_year] = c.pct != null ? P.pct(c.pct, true) : c.y[m] < 0 ? 'loss' : 'from a loss'; });
    rows.slice().reverse().forEach(function (y) {
      tb.appendChild(P.el('tr', {}, [P.el('td', { text: y.fiscal_label }), P.el('td', { class: 'n' }, [P.link(P.money(y[m]), y.sources[m])]), P.el('td', { class: 'n muted', text: ch[y.fiscal_year] || '—' }), share ? P.el('td', { class: 'n muted', text: y.revenue > 0 ? P.pct(100 * y[m] / y.revenue) : '—' }) : null]));
    });
    tbl.appendChild(tb);
    $d('fv-ask').href = '/chat/?q=' + encodeURIComponent('How has ' + (d.company.ticker || d.company.display_name) + "'s " + P.LABELS[m].toLowerCase() + ' changed over the years?');
    try { history.replaceState(null, '', '#figure=' + m); } catch (e) {}
  }
  P.openFigure = function (d, m, trigger) {
    if (!dialog) buildDialog();
    opener = trigger || document.activeElement;
    if (!dialog.open) dialog.showModal();
    render(d, m);
    dialog.querySelector('.fv-x').focus();
  };
  /* A button that opens the view: wraps a spark, a label or both. */
  P.figureButton = function (d, m, kids, cls) {
    var b = P.el('button', { type: 'button', class: cls || 'fv-open', 'aria-label': 'Open ' + P.LABELS[m].toLowerCase() + ' over ' + rowsFor(d, m).length + ' years', 'aria-haspopup': 'dialog' }, kids);
    b.addEventListener('click', function () { P.openFigure(d, m, b); });
    return b;
  };
  /* #figure=revenue opens the view on load, so it can be shared. */
  P.openFromHash = function (d) {
    var m = (location.hash.match(/^#figure=([a-z_]+)$/) || [])[1];
    if (m && P.LABELS[m] && rowsFor(d, m).length) P.openFigure(d, m);
  };
})();
