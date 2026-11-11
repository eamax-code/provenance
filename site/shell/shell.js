/* The site shell (GH #11, #12): header menus, the current page, the footer's live figures, and the
   reader's theme in chat and the Explorer. Every page loads it; it needs nothing else. */
(function () {
  'use strict';
  var doc = document.documentElement;
  doc.classList.add('js');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var canHover = window.matchMedia('(hover: hover)').matches;
  var EXPO = 'cubic-bezier(0.16, 1, 0.3, 1)';

  /* ---------- themes: dark everywhere; chat and the Explorer let a reader choose ---------- */
  var THEMES = [
    { id: 'dark', name: 'Dark', note: 'The site theme', sw: ['#141719', '#20252a', '#ff5a4f'] },
    { id: 'light', name: 'Light', note: 'Grey paper, charcoal ink', sw: ['#eef2f5', '#ffffff', '#c92f28'] },
    { id: 'ledger', name: 'Ledger', note: 'Warm paper, serif headings', sw: ['#f4efe6', '#fffcf6', '#1f6b4f'] },
    { id: 'terminal', name: 'Terminal', note: 'Dense, amber, fixed-width figures', sw: ['#0d1117', '#161d26', '#e8990f'] }
  ];
  var FONTS = {
    ledger: 'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=Newsreader:opsz,wght@6..72,600&display=swap',
    terminal: 'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap'
  };
  var STORE = 'prv-theme';
  var valid = function (t) { return THEMES.some(function (x) { return x.id === t; }); };
  function loadFonts(t) {
    if (!FONTS[t] || document.querySelector('link[data-theme-font="' + t + '"]')) return;
    var l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = FONTS[t]; l.setAttribute('data-theme-font', t);
    document.head.appendChild(l);
  }
  function current() { return doc.getAttribute('data-theme') || 'dark'; }
  function apply(t) {
    if (!valid(t)) t = 'dark';
    if (t === 'dark') doc.removeAttribute('data-theme'); else doc.setAttribute('data-theme', t);
    loadFonts(t);
    try { localStorage.setItem(STORE, t); } catch (e) { /* storage blocked */ }
    document.dispatchEvent(new CustomEvent('shell:theme', { detail: { theme: t } }));
    return t;
  }
  /* A list of radio choices; onPick(theme) runs after the theme is applied. */
  function picker(host, onPick) {
    var fs = document.createElement('fieldset');
    fs.className = 'theme-pick';
    var lg = document.createElement('legend'); lg.textContent = 'Theme'; fs.appendChild(lg);
    var name = 'theme-' + Math.random().toString(36).slice(2, 8);
    THEMES.forEach(function (t) {
      var lab = document.createElement('label'), inp = document.createElement('input'), sw = document.createElement('span'), txt = document.createElement('span');
      inp.type = 'radio'; inp.name = name; inp.value = t.id; inp.checked = current() === t.id;
      sw.className = 'sw'; sw.setAttribute('aria-hidden', 'true');
      t.sw.forEach(function (c) { var i = document.createElement('i'); i.style.background = c; sw.appendChild(i); });
      txt.textContent = t.name;
      var sm = document.createElement('small'); sm.textContent = t.note; txt.appendChild(sm);
      inp.addEventListener('change', function () { if (inp.checked) { apply(t.id); if (onPick) onPick(t.id); } });
      lab.appendChild(inp); lab.appendChild(sw); lab.appendChild(txt); fs.appendChild(lab);
    });
    document.addEventListener('shell:theme', function (e) {
      fs.querySelectorAll('input').forEach(function (i) { i.checked = i.value === e.detail.theme; });
    });
    host.appendChild(fs);
    return fs;
  }
  /* The theme saved with the API key, so it follows the reader to another browser. */
  function profile(key, body) {
    if (!key) return Promise.resolve(null);
    var opts = { headers: { 'X-API-Key': key, Accept: 'application/json' } };
    if (body) { opts.method = 'PATCH'; opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch('/v1/developer/profile', opts).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  function syncTheme(key) {
    return profile(key).then(function (p) { if (p && p.ui_theme && p.ui_theme !== current()) apply(p.ui_theme); return p; });
  }
  function saveTheme(key, t) { return profile(key, { ui_theme: t }); }
  if (doc.hasAttribute('data-theme')) loadFonts(current());
  window.Shell = { THEMES: THEMES, theme: current, setTheme: apply, picker: picker, syncTheme: syncTheme, saveTheme: saveTheme };

  /* ---------- header ---------- */
  function roll(el) {
    var t = el.textContent.trim();
    if (!t || el.querySelector('.roll')) return;
    var r = document.createElement('span'), a = document.createElement('span'), b = document.createElement('span');
    r.className = 'roll'; a.textContent = t; b.textContent = t; b.setAttribute('aria-hidden', 'true');
    r.appendChild(a); r.appendChild(b); el.replaceChildren(r);
  }
  function cascade(nodes) {
    if (reduce || !document.body.animate) return;
    Array.prototype.forEach.call(nodes, function (n, i) {
      n.animate([{ opacity: 0, transform: 'translateY(12px)' }, { opacity: 1, transform: 'none' }], { duration: 650, delay: 40 + i * 30, easing: EXPO, fill: 'backwards' });
    });
  }
  function header() {
    var btn = document.getElementById('site-menu-btn'), nav = document.getElementById('site-nav');
    if (!btn || !nav) return;
    var groups = Array.prototype.slice.call(nav.querySelectorAll('.site-group'));
    var desktop = window.matchMedia('(min-width: 981px)');
    /* the page you are on: its link, and the group that holds it */
    var here = location.pathname.replace(/^\/companies\/\d+.*$/, '/companies/');
    document.querySelectorAll('.site-bar a[href]').forEach(function (a) {
      var p = a.getAttribute('href');
      if (p.charAt(0) !== '/' || p.indexOf('#') >= 0 || p === '/') return;
      if (p === here) { a.setAttribute('aria-current', 'page'); var g = a.closest('.site-group'); if (g) g.classList.add('here'); }
    });
    if (!reduce) document.querySelectorAll('.site-link, .site-bar .site-wrap > .site-button').forEach(roll);
    var syncPill = function () {};
    var setMenu = function (open) {
      nav.classList.toggle('open', open); btn.setAttribute('aria-expanded', String(open)); btn.textContent = open ? 'Close' : 'Menu';
      document.body.style.overflow = open && !desktop.matches ? 'hidden' : '';
    };
    var closeGroups = function (except) {
      groups.forEach(function (g) { if (g !== except) { g.classList.remove('open'); g.querySelector('.site-group-btn').setAttribute('aria-expanded', 'false'); } });
      syncPill();
    };
    function unfold(g, dir) {
      var m = g.querySelector('.site-menu');
      if (reduce || !m.animate || !desktop.matches) return;
      m.animate(dir
        ? [{ opacity: 0, transform: 'translateX(' + dir * 28 + 'px)' }, { opacity: 1, transform: 'none' }]
        : [{ opacity: 0, transform: 'translateY(-8px)', clipPath: 'inset(0 0 100% 0 round 6px)' }, { opacity: 1, transform: 'none', clipPath: 'inset(0 0 0 0 round 6px)' }],
        { duration: dir ? 500 : 600, easing: EXPO });
      cascade(m.querySelectorAll('li'));
    }
    btn.addEventListener('click', function () { setMenu(!nav.classList.contains('open')); });
    Array.prototype.forEach.call(nav.children, function (el, i) { el.style.setProperty('--i', i); });
    groups.forEach(function (g, gi) {
      var b = g.querySelector('.site-group-btn');
      b.addEventListener('click', function () {
        var was = groups.findIndex(function (x) { return x.classList.contains('open'); });
        var open = !g.classList.contains('open');
        closeGroups(g); g.classList.toggle('open', open); b.setAttribute('aria-expanded', String(open));
        if (open) unfold(g, was >= 0 && was !== gi ? (gi > was ? 1 : -1) : 0);
        syncPill();
      });
      /* With one menu open, pointing at another group opens it, as in a menu bar. */
      b.addEventListener('pointerenter', function () { if (canHover && desktop.matches && !g.classList.contains('open') && nav.querySelector('.site-group.open')) b.click(); });
      g.addEventListener('focusout', function (e) { if (!g.contains(e.relatedTarget)) { g.classList.remove('open'); b.setAttribute('aria-expanded', 'false'); syncPill(); } });
    });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) { setMenu(false); closeGroups(null); } });
    document.addEventListener('click', function (e) { if (!e.target.closest('.site-group')) closeGroups(null); });
    desktop.addEventListener('change', function () { setMenu(false); closeGroups(null); });
    if (canHover && !reduce) {
      var pill = document.createElement('span');
      pill.className = 'site-pill'; pill.setAttribute('aria-hidden', 'true');
      nav.insertBefore(pill, nav.firstChild); nav.classList.add('has-pill');
      var pillTo = function (el) {
        if (!el || !desktop.matches) { pill.classList.remove('on'); return; }
        var nr = nav.getBoundingClientRect(), r = el.getBoundingClientRect(), appearing = !pill.classList.contains('on');
        if (appearing) pill.style.transition = 'none';
        pill.style.setProperty('--x', (r.left - nr.left) + 'px'); pill.style.setProperty('--y', (r.top - nr.top) + 'px');
        pill.style.setProperty('--w', r.width + 'px'); pill.style.setProperty('--h', r.height + 'px');
        if (appearing) { void pill.offsetWidth; pill.style.transition = ''; }
        pill.classList.add('on');
      };
      var openBtn = function () { var g = nav.querySelector('.site-group.open'); return g ? g.querySelector('.site-group-btn') : null; };
      nav.addEventListener('pointerover', function (e) { var t = e.target.closest('.site-group-btn, .site-link'); if (t) pillTo(t); });
      nav.addEventListener('pointerleave', function () { pillTo(openBtn()); });
      syncPill = function () { if (!nav.matches(':hover')) pillTo(openBtn()); };
    }
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var openG = nav.querySelector('.site-group.open');
      if (openG) { closeGroups(null); openG.querySelector('.site-group-btn').focus(); return; }
      if (nav.classList.contains('open')) { setMenu(false); btn.focus(); }
    });
  }

  /* ---------- footer: live coverage from /v1/stats ---------- */
  function stats() {
    var box = document.getElementById('live-facts');
    if (!box) return;
    var fmt = function (n) { return Number(n).toLocaleString('en-US'); };
    var set = function (name, v) { box.querySelectorAll('[data-stat="' + name + '"]').forEach(function (el) { el.textContent = v; }); };
    var show = function (id, on) { var el = document.getElementById(id); if (el) el.hidden = !on; };
    function load() {
      fetch(box.getAttribute('data-source'), { headers: { Accept: 'application/json' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          set('companies', fmt(d.companies.ingested)); set('filings', fmt(d.filings.total)); set('facts', fmt(d.facts.total));
          show('status-empty', !d.companies.ingested); show('status-error', false);
          var note = document.getElementById('live-note');
          if (note) note.textContent = 'Live from /v1/stats, ' + d.generated_at.replace('T', ' ').slice(0, 16) + ' UTC. Latest filing ' + (d.filings.latest_filing_date || 'none') + '.';
          document.dispatchEvent(new CustomEvent('shell:stats', { detail: d }));
        })
        .catch(function () { show('status-error', true); document.dispatchEvent(new CustomEvent('shell:stats', { detail: null })); });
    }
    load(); setInterval(load, 30000);
  }

  function start() { header(); stats(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
