/* Company seal (brand: Trace; docs/brand.md). Decorative, aria-hidden: a chip, a leader seeded by the CIK, a dot. */
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  function rng(c) {
    var h = 0x811c9dc5, t = String(+c) + ':C3', i;
    for (i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return function () { h = (h + 0x6D2B79F5) >>> 0; var x = h; x = Math.imul(x ^ (x >>> 15), x | 1); x ^= x + Math.imul(x ^ (x >>> 7), x | 61); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
  }
  function node(tag, a) { var n = document.createElementNS(NS, tag); for (var k in a) n.setAttribute(k, a[k]); return n; }
  window.prvSeal = function (cik) {
    var r = rng(cik), k = function (n) { return Math.floor(r() * n); };
    var x0 = 2 + k(2) * 3, y0 = 14 + k(3) * 7, x = x0 + 16, y = y0 + 5, d = 'M' + x + ',' + y, n = 2 + k(3), ex = 50 + k(3) * 2,
      f = Math.ceil(n / 2) === 1 ? ex - x : 14 + k(ex - x - 27), i, q, u;
    for (i = 0; i < n; i++) { // runs: right at least 14, up or down at least 18, square turns
      if (i % 2 === 0) x = i === 0 ? x + f : ex;
      else { q = 18 + k(3) * 6; u = r() < 0.5; if (u ? y - q < 8 : y + q > 56) u = !u; if (u ? y - q < 8 : y + q > 56) q = 18; y = u ? y - q : y + q; }
      d += 'L' + x + ',' + y;
    }
    var s = node('svg', { 'class': 'seal', viewBox: '0 0 64 64', 'aria-hidden': 'true', focusable: 'false' });
    s.appendChild(node('path', { fill: 'currentColor', d: 'M' + (x0 + 4) + ',' + (y0 - 1) + 'H' + (x0 + 20) + 'L' + (x0 + 16) + ',' + (y0 + 11) + 'H' + x0 + 'ZM' + (x - 4.8) + ',' + y + 'a4.8,4.8 0 1 0 9.6,0a4.8,4.8 0 1 0 -9.6,0Z' }));
    s.appendChild(node('path', { fill: 'none', stroke: 'currentColor', 'stroke-width': '3.6', d: d }));
    return s;
  };
  // on /companies/<cik>, mark the name heading of whichever layout is served
  var m = location.pathname.match(/^\/companies\/0*(\d+)/), h = document.getElementById('name');
  if (!m || !h) return;
  var mark = function () { if (h.textContent && !h.querySelector('.seal')) h.insertBefore(window.prvSeal(m[1]), h.firstChild); };
  new MutationObserver(mark).observe(h, { childList: true }); mark();
})();
