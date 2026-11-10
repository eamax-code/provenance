/* Theme and gamification prototypes: theme switching, data, and small charts. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var X = window.Poc = {};
  X.THEMES = [['archive', 'Archive'], ['archive-dark', 'Archive dark'], ['ledger', 'Ledger'], ['terminal', 'Terminal']];
  X.theme = function () { return document.documentElement.getAttribute('data-theme') || 'archive'; };
  X.setTheme = function (t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('poc-theme', t); } catch (e) {}
    document.querySelectorAll('.themes button').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.theme === t)); });
    var u = new URL(location.href); u.searchParams.set('theme', t);
    try { history.replaceState(null, '', u); } catch (e) {}
    document.dispatchEvent(new CustomEvent('poc:theme', { detail: t }));
  };
  X.switcher = function (host) {
    X.THEMES.forEach(function (t) {
      var b = X.el('button', { type: 'button', 'data-theme': t[0], 'aria-pressed': String(X.theme() === t[0]), text: t[1] });
      b.addEventListener('click', function () { X.setTheme(t[0]); });
      host.appendChild(b);
    });
  };
  X.$ = function (id) { return document.getElementById(id); };
  X.el = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else if (attrs[k] != null) n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  X.svg = function (tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  };
  X.overview = function (cik) {
    return fetch('/v1/public/companies/' + cik + '/overview', { headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  };
  X.money = function (v, d) {
    if (v == null) return '—';
    var a = Math.abs(v), s = v < 0 ? '−$' : '$'; d = d == null ? 1 : d;
    if (a >= 1e12) return s + (a / 1e12).toFixed(d) + 'T';
    if (a >= 1e9) return s + (a / 1e9).toFixed(d) + 'B';
    if (a >= 1e6) return s + (a / 1e6).toFixed(d) + 'M';
    return s + Math.round(a).toLocaleString('en-US');
  };
  X.pct = function (v, sign) { return v == null ? '—' : (sign && v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%'; };
  X.int = function (n) { return Number(n).toLocaleString('en-US'); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  X.date = function (iso) { if (!iso) return '—'; var p = iso.slice(0, 10).split('-'); return parseInt(p[2], 10) + ' ' + MON[+p[1] - 1] + ' ' + p[0]; };
  X.link = function (text, url) {
    if (!url || url.indexOf('https://www.sec.gov/') !== 0) return X.el('span', { text: text });
    return X.el('a', { href: url, target: '_blank', rel: 'noopener', text: text });
  };
  X.LABELS = { revenue: 'Revenue', operating_income: 'Operating income', net_income: 'Net income', total_assets: 'Total assets', operating_cash_flow: 'Operating cash flow' };
  X.spark = function (vals) {
    var w = 84, h = 22, s = X.svg('svg', { viewBox: '0 0 ' + w + ' ' + h, class: 'spark', 'aria-hidden': 'true' });
    var vs = vals.filter(function (v) { return v != null; }); if (vs.length < 2) return s;
    var mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs), r = mx - mn || 1;
    var pts = vs.map(function (v, i) { return (2 + i * (w - 4) / (vs.length - 1)) + ',' + (h - 3 - (v - mn) / r * (h - 6)); });
    s.appendChild(X.svg('polyline', { points: pts.join(' ') }));
    var l = pts[pts.length - 1].split(','); s.appendChild(X.svg('circle', { cx: l[0], cy: l[1], r: 2.4 }));
    return s;
  };
  /* Revenue bars, the latest in the accent, an operating-margin line; every bar links to its filing. */
  X.bars = function (years, W, H) {
    var ys = years.filter(function (y) { return y.revenue != null; }), padL = 4, padR = 36, padT = 20, padB = 24;
    var s = X.svg('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'bars', role: 'img', 'aria-label': 'Revenue by fiscal year' });
    if (!ys.length) return s;
    var max = Math.max.apply(null, ys.map(function (y) { return y.revenue; })), step = (W - padL - padR) / ys.length, bw = Math.min(44, step * .62), ph = H - padT - padB;
    [0.5, 1].forEach(function (f) { s.appendChild(X.svg('line', { x1: padL, x2: W - padR, y1: padT + ph * (1 - f), y2: padT + ph * (1 - f), class: 'grid' })); });
    ys.forEach(function (y, i) {
      var x = padL + i * step + (step - bw) / 2, h = ph * y.revenue / max, last = i === ys.length - 1;
      var a = X.svg('a', y.sources && y.sources.revenue ? { href: y.sources.revenue, target: '_blank' } : {});
      var r = X.svg('rect', { x: x, y: padT + ph - h, width: bw, height: Math.max(1, h), rx: 2, class: 'col' + (last ? ' latest' : '') });
      r.appendChild(X.svg('title', {}, y.fiscal_label + ': ' + X.money(y.revenue)));
      a.appendChild(r); s.appendChild(a);
      if (last || i === 0) s.appendChild(X.svg('text', { x: x + bw / 2, y: padT + ph - h - 6, 'text-anchor': 'middle', class: 'val' + (last ? ' latest' : '') }, X.money(y.revenue, 0)));
      if (i % 2 === (ys.length - 1) % 2) s.appendChild(X.svg('text', { x: x + bw / 2, y: H - 6, 'text-anchor': 'middle', class: 'axis' }, y.fiscal_label.replace('FY20', "'")));
    });
    var ms = ys.map(function (y) { return y.operating_margin_pct; }), mx = Math.max.apply(null, ms.map(function (m) { return Math.abs(m || 0); }).concat([1]));
    var pts = ys.map(function (y, i) { return y.operating_margin_pct == null ? null : [padL + i * step + step / 2, padT + ph * (1 - (y.operating_margin_pct + mx) / (2 * mx))]; }).filter(Boolean);
    if (pts.length > 1) {
      s.appendChild(X.svg('polyline', { points: pts.map(function (p) { return p.join(','); }).join(' '), class: 'margin' }));
      var lp = pts[pts.length - 1]; s.appendChild(X.svg('text', { x: W - 2, y: lp[1] + 4, 'text-anchor': 'end', class: 'val' }, X.pct(ys[ys.length - 1].operating_margin_pct)));
    }
    return s;
  };
  X.toast = function (mark, title, text) {
    var host = document.querySelector('.toasts') || document.body.appendChild(X.el('div', { class: 'toasts', 'aria-live': 'polite' }));
    var t = X.el('div', { class: 'toast', role: 'status' }, [X.el('span', { class: 'mark', 'aria-hidden': 'true', text: mark }), X.el('b', { text: title }), X.el('span', { text: text })]);
    host.appendChild(t);
    // two at a time: an older one steps aside for the newest
    while (host.children.length > 2) host.firstChild.remove();
    setTimeout(function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 320); }, 4200);
  };
})();
