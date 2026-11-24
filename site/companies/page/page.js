/* The company page and its layouts (issues #9, #10): data, formatting and small SVG charts.
   Every figure comes from /v1/public/companies/{cik}/overview and links to its filing. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var P = window.CompanyPage = {};
  P.cik = (location.pathname.match(/companies\/(\d{1,10})/) || [])[1] || '1018724';
  /* one address per company whatever the layout (GH #21) */
  (function () {
    var href = location.origin + '/companies/' + ('0000000000' + P.cik).slice(-10);
    var link = document.createElement('link');
    link.rel = 'canonical';
    link.href = href;
    document.head.appendChild(link);
    var og = document.querySelector('meta[property="og:url"]') || document.createElement('meta');
    og.setAttribute('property', 'og:url');
    og.setAttribute('content', href);
    document.head.appendChild(og);
  })();
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
  /* Amounts read in the company's own reporting currency (SAP in EUR, Toyota in JPY), never converted:
     "$" only for USD, the ISO code before the number otherwise. company.js sets P.cur on load. */
  P.cur = 'USD';
  P.curPrefix = function (cur) { cur = cur || P.cur || 'USD'; return cur === 'USD' ? '$' : cur + '\u00a0'; };
  P.money = function (v, digits, cur) {
    if (v == null) return '—';
    var a = Math.abs(v), s = (v < 0 ? '−' : '') + P.curPrefix(cur), d = digits == null ? 1 : digits;
    if (a >= 1e12) return s + (a / 1e12).toFixed(d) + 'T';
    if (a >= 1e9) return s + (a / 1e9).toFixed(d) + 'B';
    if (a >= 1e6) return s + (a / 1e6).toFixed(d) + 'M';
    if (a >= 1e3) return s + (a / 1e3).toFixed(0) + 'K';
    return s + a.toFixed(0);
  };
  P.pct = function (v, sign) { return v == null ? '—' : (sign && v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%'; };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  P.date = function (iso) { if (!iso) return '—'; var p = iso.slice(0, 10).split('-'); return parseInt(p[2], 10) + ' ' + MON[parseInt(p[1], 10) - 1] + ' ' + p[0]; };
  /* ISO dates inside service-written text read as "26 Sep 2026" on every layout */
  P.humanDates = function (s) { return String(s || '').replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, function (m) { return P.date(m); }); };
  P.phone = function (p) { if (!p) return null; var d = p.replace(/\D/g, ''); return d.length === 10 ? '(' + d.slice(0, 3) + ') ' + d.slice(3, 6) + '-' + d.slice(6) : p; };
  P.title = function (s) { return s ? s.toLowerCase().replace(/\b([a-z])/g, function (m) { return m.toUpperCase(); }) : s; };
  P.address = function (a) {
    if (!a) return null;
    var street = [a.street1, a.street2].filter(Boolean).map(P.title).join(', ');
    var abroad = ABROAD[a.stateOrCountry];
    if (abroad) { // EDGAR fills these as city "JAPAN", zip "00000", country "United States"
      var place = [a.city, a.zipCode].filter(function (x) { return x && !/^0+$/.test(x) && abroad.toLowerCase().indexOf(x.toLowerCase()) < 0; }).map(P.title).join(' ');
      return [street, place, abroad].filter(Boolean);
    }
    var city = [P.title(a.city), a.stateOrCountry && a.stateOrCountry.length === 2 ? a.stateOrCountry : null, a.zipCode].filter(Boolean).join(' ');
    return [street, city, a.country !== 'United States' ? a.country : null].filter(Boolean);
  };
  var STATES = { AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', PR: 'Puerto Rico' };
  /* EDGAR's codes for places outside the US (M0 Japan, 2M Germany, A6 Ontario); an unknown code is
     left out rather than shown raw */
  var ABROAD = { A0: 'Alberta, Canada', A1: 'British Columbia, Canada', A2: 'Manitoba, Canada', A3: 'New Brunswick, Canada', A4: 'Newfoundland, Canada', A5: 'Nova Scotia, Canada', A6: 'Ontario, Canada', A7: 'Prince Edward Island, Canada', A8: 'Quebec, Canada', A9: 'Saskatchewan, Canada', B0: 'Yukon, Canada', C3: 'Australia', D0: 'Bermuda', D5: 'Brazil', E9: 'Cayman Islands', F4: 'China', F5: 'Taiwan', G7: 'Denmark', I0: 'France', K3: 'Hong Kong', K7: 'India', L2: 'Ireland', L3: 'Israel', L6: 'Italy', M0: 'Japan', M5: 'South Korea', N4: 'Luxembourg', O5: 'Mexico', P7: 'Netherlands', U0: 'Singapore', U3: 'Spain', V7: 'Sweden', V8: 'Switzerland', X0: 'United Kingdom', '2M': 'Germany' };
  P.state = function (code) { return code ? STATES[code] || ABROAD[code] || null : null; };
  /* Organisation names filed in capitals (13F filers, audit firms) ("FMR LLC", "BANK OF AMERICA CORP /DE/"): title case them but keep
     legal forms and initialisms, drop EDGAR's state suffix; names filed in mixed case stay as filed */
  var KEEP = { LLC: 1, LP: 1, LLP: 1, PLC: 1, NA: 1, AG: 1, SA: 1, SE: 1, NV: 1, ASA: 1, AB: 1, FMR: 1, UBS: 1, ADS: 1, ADR: 1, ADRS: 1, KPMG: 1, BDO: 1, RSM: 1, EY: 1, PWC: 1, CBIZ: 1, MNP: 1, BNY: 1, TIAA: 1, CIBC: 1, RBC: 1, HSBC: 1, ABN: 1, AMRO: 1, BNP: 1, II: 1, III: 1, USA: 1, US: 1 };
  var LOWER = { OF: 1, AND: 1, THE: 1, FOR: 1, DE: 1 };
  P.orgName = function (n) {
    n = String(n || '').replace(/\s*\/[A-Za-z]{2,3}\/?\s*$/, '').trim();
    if (n !== n.toUpperCase()) return n;
    return n.split(/(\s+|[,.&()-])/).map(function (w, i) {
      if (!/[A-Z]/.test(w)) return w;
      if (KEEP[w]) return w;
      if (i && LOWER[w]) return w.toLowerCase();
      if (w === 'JPMORGAN') return 'JPMorgan';
      if (w === 'GMBH') return 'GmbH';
      return w.charAt(0) + w.slice(1).toLowerCase();
    }).join('');
  };
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
      r.setAttribute('class', (i === ys.length - 1 ? 'col latest' : 'col') + (y.predecessor ? ' pred' : ''));
      var t = document.createElementNS(NS, 'title'); t.textContent = y.fiscal_label + ': revenue ' + P.money(y.revenue) + (y.operating_margin_pct != null ? ', operating margin ' + P.pct(y.operating_margin_pct) : '') + (y.predecessor ? '. ' + (y.registrant_label || 'Reported by predecessor registrant (CIK ' + y.registrant_cik + ')') : '');
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
  // the figure view (issue #10) loads on first open (figure-view.js), so it costs the first load nothing
  var rowsFor = function (d, m) { return d.years.filter(function (y) { return y[m] != null; }); }, fvLoad = null;
  P.openFigure = function (d, m, trigger) {
    trigger = trigger || document.activeElement;
    fvLoad = fvLoad || new Promise(function (ok, no) { var s = document.createElement('script'); s.src = '/companies/page/figure-view.js'; s.onload = ok; s.onerror = function () { fvLoad = null; no(); }; document.head.appendChild(s); });
    fvLoad.then(function () { P.openFigureNow(d, m, trigger); }, function () {});
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
