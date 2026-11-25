/* A 10-K item as filed (Q-09, docs/contracts/sections.md), at /filings/{accession}/{item}/ (or section.html?a=&i=).
   The text exactly as the API gives it, split into its paragraphs; subheadings set from their offsets (start minus
   offsets.start into text), never reworded; a contents column (a sheet on phones); ?q= marks every match the way
   Search does and steps through them. Text nodes only; links go to sec.gov/Archives or into the site. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var dmy = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; };
  var get = function (p) { return fetch(p, { headers: { Accept: 'application/json', 'X-API-Key': key() } }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); }).catch(function () { return { ok: false, status: 0, b: {} }; }); };
  var link = function (text, href) { return ARCHIVE.test(href || '') ? el('a', { href: href, target: '_blank', rel: 'noopener', text: text + ' ↗' }) : null; };

  var u = new URLSearchParams(location.search), pm = location.pathname.match(/\/filings\/(\d{10}-\d{2}-\d{6})\/(1A|7)\/?$/i);
  var ACC = pm ? pm[1] : (/^\d{10}-\d{2}-\d{6}$/.test(u.get('a') || '') ? u.get('a') : '');
  var ITEM = (pm ? pm[2] : (u.get('i') || '1A')).toUpperCase(), Q = (u.get('q') || '').trim().slice(0, 200);
  var here = function (item) { return pm ? '/filings/' + ACC + '/' + item + '/' : '/filings/section.html?a=' + ACC + '&i=' + item; };
  var say = function (t, extra) { $('sx-text').replaceChildren.apply($('sx-text'), [el('p', { class: 'sx-state', text: t })].concat(extra || [])); };
  if (!ACC || !/^(1A|7)$/.test(ITEM)) { say('This address does not name a filing and an item (1A or 7).'); return; }

  // the words to mark: quoted phrases as written, other words on their own (as Search matches them)
  function terms(q) { var out = [], re = /"([^"]+)"|(\S+)/g, m; while ((m = re.exec(q))) { var t = (m[1] || m[2]).replace(/[^\w\s'’-]/g, '').trim(); if (t.length > 1 && !/^(and|or|not|the|of|in|a|an|to)$/i.test(t)) out.push(t); } return out; }
  function marked(text, rx) {
    if (!rx) return [text];
    var out = [], last = 0, m; rx.lastIndex = 0;
    while ((m = rx.exec(text))) { if (!m[0]) { rx.lastIndex++; continue; } out.push(text.slice(last, m.index), el('mark', { class: 'sx-m', text: m[0] })); last = m.index + m[0].length; }
    out.push(text.slice(last)); return out;
  }

  function render(b) {
    var text = b.text || '', base = (b.offsets || {}).start || 0, subs = (b.subheadings || []).slice().sort(function (x, y) { return x.start - y.start; });
    // the words together come first, so "supply chain" side by side is one match; each word alone still marks
    var t = terms(Q); if (t.length > 1) t.unshift(t.join(' '));
    var rx = t.length ? new RegExp('\\b(' + t.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+'); }).join('|') + ')', 'gi') : null;
    // paragraphs with their start offset in text; a paragraph that is a subheading becomes a heading
    var paras = [], at = 0;
    text.split('\n\n').forEach(function (p) { paras.push({ s: at, t: p }); at += p.length + 2; });
    var hs = {}; subs.forEach(function (h) { hs[h.start - base] = h; });
    var toc = [], blocks = [], cur = [], n = 0;
    var flush = function () { if (cur.length) blocks.push(el('div', { class: 'sx-block' }, cur)); cur = []; };
    paras.forEach(function (p) {
      var h = hs[p.s];
      if (h) {
        flush(); var id = 'h' + (++n), lvl = h.group ? 'h2' : 'h3';
        cur.push(el(lvl, { id: id, class: 'sx-sub' }, marked(p.t, rx)));
        toc.push(el('li', { class: h.group ? 'g' : null }, [el('a', { href: '#' + id, text: p.t.length > 120 ? p.t.slice(0, 117) + '…' : p.t })]));
      } else cur.push(el('p', {}, marked(p.t, rx)));
      if (cur.length >= 12) flush(); // blocks of about a dozen paragraphs paint lazily (content-visibility)
    });
    flush();
    $('sx-text').replaceChildren.apply($('sx-text'), blocks);
    if (!toc.length) $('sx-text').parentNode.classList.add('notoc');
    if (toc.length) {
      var list = function () { return el('ol', {}, toc.map(function (li) { return li.cloneNode(true); })); };
      $('sx-toc').replaceChildren(el('p', { class: 'sx-toc-h', text: 'Contents' }), list()); $('sx-toc').hidden = false;
      $('sx-sheet-nav').replaceChildren(list()); $('sx-tocbtn').hidden = false;
    }
    // matches of ?q=: say how many, step through them, start at the first
    var ms = [].slice.call(document.querySelectorAll('mark.sx-m'));
    if (Q) {
      var f = $('sx-find'), i = 0, go = function (k) { if (!ms.length) return; ms[i].classList.remove('on'); i = (k + ms.length) % ms.length; ms[i].classList.add('on'); ms[i].scrollIntoView({ block: 'center' }); pos.textContent = (i + 1) + ' of ' + ms.length; };
      var pos = el('span', { class: 'sx-pos' }), prev = el('button', { type: 'button', class: 'btn', text: 'Previous' }), next = el('button', { type: 'button', class: 'btn', text: 'Next' });
      prev.addEventListener('click', function () { go(i - 1); }); next.addEventListener('click', function () { go(i + 1); });
      f.replaceChildren.apply(f, ms.length ? [el('span', { text: ms.length + ' match' + (ms.length === 1 ? '' : 'es') + ' for “' + Q + '” · ' }), pos, ' ', prev, next] : ['No match for “' + Q + '” in this section.']);
      f.hidden = false; if (ms.length) { ms[0].classList.add('on'); pos.textContent = '1 of ' + ms.length; setTimeout(function () { ms[0].scrollIntoView({ block: 'center' }); }, 0); }
    } else if (location.hash && document.getElementById(location.hash.slice(1))) document.getElementById(location.hash.slice(1)).scrollIntoView();
  }

  function header(b) {
    var co = b.company || 'Company', cik = parseInt(b.cik, 10);
    $('sx-co').replaceChildren(cik ? el('a', { href: '/app/?c=' + cik + '&tab=filings', text: co }) : co);
    $('sx-h').textContent = b.heading || ('Item ' + ITEM + '. ' + (b.title || ''));
    document.title = (b.heading || ('Item ' + ITEM)) + ' · ' + co + ' ' + (b.form || '10-K') + ' · Provenance';
    $('sx-meta').replaceChildren.apply($('sx-meta'), [(b.form || '10-K') + ' filed ' + dmy(b.filed_date) + (b.report_date ? ', for the year ended ' + dmy(b.report_date) : '') + ' · ',
      link('The ' + (b.form || '10-K') + ' document on sec.gov', (b.document || {}).url), ' · ', link('Filing index', b.filing_url)].filter(Boolean));
  }

  // the items held for this filing: a switch when more than one
  get('/v1/filings/' + ACC + '/sections').then(function (r) {
    var items = (r.ok && r.b.items) || [];
    if (r.ok && r.b.coverage) $('sx-cov').textContent = r.b.coverage;
    if (items.length > 1) {
      var nav = $('sx-items');
      nav.replaceChildren.apply(nav, items.map(function (x) { var on = String(x.item).toUpperCase() === ITEM; return el('a', { href: here(x.item) + (Q ? '?q=' + encodeURIComponent(Q) : ''), 'aria-current': on ? 'page' : null, text: 'Item ' + x.item + ' · ' + (x.title || '') }); }));
      nav.hidden = false;
    }
  });
  get('/v1/filings/' + ACC + '/sections/' + ITEM).then(function (r) {
    if (!r.ok) {
      var e = (r.b && r.b.error) || {};
      say(r.status === 404 ? (e.message || 'This item is not held for this filing.') : r.status === 403 ? 'This filing needs a free key (the demo key covers the showcase companies).' : r.status === 429 ? 'Too many requests this minute. Try again in a moment.' : 'The section could not load. Check the connection and try again.',
        r.status === 403 ? [el('p', {}, [el('a', { href: '/account/', text: 'Get a free key' })])] : null);
      return;
    }
    header(r.b); render(r.b);
  });

  // contents as a sheet on phones: a modal dialog, Esc and the backdrop close it, a choice closes it too
  var sheet = $('sx-sheet');
  $('sx-tocbtn').addEventListener('click', function () { sheet.showModal(); });
  $('sx-close').addEventListener('click', function () { sheet.close(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet || e.target.closest('a')) sheet.close(); });
})();
