/* Activist stakes (Q-07, docs/contracts/activists.md), shared by the Explorer's Ownership tab and /activists/ and
   loaded only where they show. A Schedule 13D stake in words and numbers ("up 2.1 points to 9.8%"), never green or
   red; a group's percent as filed, never summed; the purpose quoted from Item 4 as filed, never summarised, with the
   filing it comes from under it; and on every view the disclaimer and what the coverage leaves out. Text nodes
   only; links go to sec.gov/Archives or into the site. */
(function () {
  'use strict';
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  // a free-text 13D the coverage leaves out, named in the coverage note
  var EXAMPLE = 'https://www.sec.gov/Archives/edgar/data/891103/000090266424004719/0000902664-24-004719-index.html';
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  if (!document.getElementById('ac-css')) { var st = document.createElement('style'); st.id = 'ac-css'; st.textContent = '#pane-ownership #activists{grid-column:1/-1}.ac-list{list-style:none;margin:6px 0 0;padding:0}.ac-item{padding:14px 0;border-bottom:1px solid var(--line-soft)}.ac-who,.ac-stake,.ac-meta,.ac-sw{margin:0}.ac-stake{margin-top:2px;font-weight:700}.ac-meta{margin-top:2px;font-size:.88rem;color:var(--soft)}.ac-sw{margin-top:6px;font-size:.88rem}.ac-item a,.ac-cov a,.ac-row a{color:var(--ink);text-decoration-line:underline;text-decoration-color:var(--link-line);text-underline-offset:2px}.ac-tag{display:inline-block;margin-right:6px;padding:0 6px;border:1px solid var(--line);border-radius:4px;background:var(--surface-2);font-size:.78rem;font-weight:600}.ac-q{margin:10px 0 0;max-width:78ch}.ac-q blockquote{margin:0;padding:1px 0 1px 14px;border-left:3px solid var(--line);color:var(--ink);font-size:.94rem;line-height:1.55;white-space:pre-line;overflow-wrap:anywhere}.ac-q figcaption{margin-top:4px;font-size:.82rem;color:var(--soft)}.ac-nop{margin:8px 0 0}.ac-chain{margin-top:8px;font-size:.88rem}.ac-chain summary{cursor:pointer;min-height:32px;display:flex;align-items:center;gap:6px;color:var(--soft);font-weight:600;list-style:none}.ac-chain summary::-webkit-details-marker{display:none}.ac-chain summary::before{content:"▸"}.ac-chain[open] summary::before{content:"▾"}.ac-chain table{border-collapse:collapse;font-variant-numeric:tabular-nums;margin:4px 0}.ac-chain th,.ac-chain td{padding:5px 10px 5px 0;border-bottom:1px solid var(--line-soft);text-align:left;white-space:nowrap}.ac-chain thead th{font-size:.78rem;color:var(--soft);font-weight:600}.ac-chain .n{text-align:right}.ac-chain ul{margin:4px 0;padding-left:18px}.ac-disc{margin:0 0 4px;font-weight:600}.ac-tog{min-height:40px;margin-top:6px}.ac-cov{margin:10px 0 0;font-size:.85rem;color:var(--soft);max-width:90ch}'; document.head.appendChild(st); }
  var key = function () { try { return localStorage.getItem('prv_api_key') || 'demo'; } catch (e) { return 'demo'; } };
  var dmy = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MONTHS[+m[2] - 1].slice(0, 3) + ' ' + m[1] : ''; };
  var pc = function (v) { return v == null ? '—' : (+v).toFixed(1) + '%'; };
  var int = function (v) { return v == null ? '—' : Math.round(v).toLocaleString('en-US'); };
  var cap = function (s) { return s.charAt(0).toUpperCase() + s.slice(1); };
  // "13D", "13D/A No. 3": the form as filed without the word SCHEDULE
  var form = function (f, n) { var s = String(f || 'Filing').replace(/^SCHEDULE\s+/i, '').replace(/^SC\s+/i, ''); return n ? s + ' No. ' + n : s; };
  var link = function (text, url) { return ARCHIVE.test(url || '') ? el('a', { href: url, target: '_blank', rel: 'noopener', text: text + ' ↗' }) : text; };
  // a mark opens its entry on /docs/flags/ (Pattern A, 25 Nov); its name starts with the visible text
  var mk = function (text, id, cls) { return el('a', { class: cls, href: '/docs/flags/#' + id, 'aria-label': text + ': what this means', text: text }); };
  var common = function (c) { return !c || /^common stock$/i.test(String(c).trim()); };
  var ofClass = function (c) { return common(c) ? ' of the class' : ' of ' + c; };

  function load(path) {
    return fetch(path, { headers: { Accept: 'application/json', 'X-API-Key': key() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, b: b }; }); })
      .catch(function () { return { ok: false, status: 0, b: {} }; });
  }
  // the change from the filing before, in words and numbers: "up 2.1 points to 9.8%"; the first filing: "6.2%"
  function change(points, percent) {
    if (points == null) return pc(percent);
    var a = Math.abs(points);
    return a < 0.05 ? 'unchanged at ' + pc(percent) : (points > 0 ? 'up ' : 'down ') + a.toFixed(1) + ' points to ' + pc(percent);
  }
  // "Starboard Value LP and 2 others (group)": the lead filer, and the reporting persons with it
  function who(filer, n) {
    var o = (n || 1) - 1;
    return [el('b', { text: (filer && filer.name) || 'Filer not named' }), o > 0 ? ' and ' + o + (o === 1 ? ' other ' : ' others ') : null, o > 0 ? mk('(group)', 'group') : null];
  }
  // Item 4 quoted as filed, with the filing it comes from; an amendment that left Item 4 unchanged cites the earlier
  // filing ("stated in"); a cut excerpt links the whole Item 4
  function quote(p, accession) {
    if (!p || !p.excerpt) return el('p', { class: 'ac-nop muted small', text: 'No purpose stated in Item 4 of the structured filings.' });
    var carried = p.carried_forward != null ? p.carried_forward : !!(accession && p.accession_number && p.accession_number !== accession);
    var src = p.form ? form(p.form) + ' filed ' + dmy(p.filed_date) : 'as filed', lead = carried && p.form ? ['Item 4, ', mk('stated in', 'stated-in'), ' '] : ['Item 4, '];
    return el('figure', { class: 'ac-q' }, [el('blockquote', { cite: ARCHIVE.test(p.source_url || '') ? p.source_url : null, text: p.excerpt + (p.truncated ? ' …' : '') }),
      el('figcaption', {}, lead.concat(p.truncated ? [src + ' · ', link('Read the full Item 4', p.source_url)] : [link(src, p.source_url)]))]);
  }
  function switched(s) {
    return s ? el('p', { class: 'ac-sw' }, [mk('Switched from passive (13G) to active (13D)', 'switched', 'ac-tag'), 'after ', link(form(s.form) + ' filed ' + dmy(s.filed_date) + (s.percent != null ? ' at ' + pc(s.percent) : ''), s.source_url)]) : null;
  }
  function disclaimer(b) { return el('p', { class: 'ac-disc', text: ((b && b.labels) || {}).disclaimer || 'Information, not signals. Not investment advice.' }); }
  function coverage(b) {
    var m = /^(\d{4})-(\d{2})/.exec(((b && b.coverage) || {}).from || ''), when = m ? MONTHS[+m[2] - 1] + ' ' + m[1] : 'December 2024';
    return el('p', { class: 'ac-cov' }, ['Covers 13D filings in the SEC’s structured format, ' + when + ' onward. Earlier and free-text filings are not read: for example, ', link('the Schedule 13D on Match Group filed 15 July 2024', EXAMPLE), ' is not shown. ', el('a', { href: '/docs/flags/#activists-h', text: 'How to read the marks' })]);
  }

  // one filer's stake at a company (a chain from /v1/companies/{cik}/activists)
  function item(c) {
    var cur = c.current || {}, ch = c.chain || [], grp = c.group || [], first = c.first_filed || ch[0] || {};
    var pts = ch.length > 1 ? (ch[ch.length - 1] || {}).change_pct_points : null, words = change(pts, cur.percent) + ofClass(cur.class_label);
    var stake = c.status === 'exited' ? 'Exited: ' + words + ', under 5%' : ch.length > 1 ? cap(words) : pc(cur.percent) + ofClass(cur.class_label) + (/\/A/.test(cur.form || '') ? ', its first structured filing' : ', its first 13D');
    var more = [];
    if (grp.length > 1) more.push(el('p', { class: 'muted small', text: 'Reporting persons on the latest filing. The group’s percent is the figure the filing gives, not a sum across them (each reports the shares it is deemed to own):' }),
      el('ul', {}, grp.map(function (g) { return el('li', { text: g.name + (g.type_label || g.type ? ' (' + (g.type_label || g.type) + ')' : '') }); })));
    if (ch.length > 1) more.push(el('div', { class: 'tw' }, [el('table', {}, [el('caption', { class: 'vh', text: 'Filings in this stake, oldest first' }),
      el('thead', {}, [el('tr', {}, ['Filed', 'Filing', 'Event date', '% of class', 'Change', 'Shares'].map(function (h, i) { return el('th', { scope: 'col', class: i > 2 ? 'n' : null, text: h }); }))]),
      el('tbody', {}, ch.map(function (f) { var p = f.change_pct_points; return el('tr', {}, [el('td', { text: dmy(f.filed_date) }), el('td', {}, [link(form(f.form, f.amendment_number), f.source_url)]), el('td', { text: dmy(f.event_date) || '—' }), el('td', { class: 'n', text: pc(f.percent) }), el('td', { class: 'n', text: p == null ? 'first filing' : Math.abs(p) < 0.05 ? 'unchanged' : (p > 0 ? 'up ' : 'down ') + Math.abs(p).toFixed(1) + ' pts' }), el('td', { class: 'n', text: int(f.shares) })]); }))])]));
    return el('li', { class: 'ac-item' }, [el('p', { class: 'ac-who' }, who(c.filer, grp.length)), el('p', { class: 'ac-stake', text: stake }),
      // percent_basis: the chain never reached 5% on any one cover page, so the figure is one member's, not the group's
      c.percent_basis ? el('p', { class: 'ac-meta' }, ['The percent shown is the largest single reporting person’s; these filings give no group total. ', el('a', { href: '/docs/flags/#percent-basis', text: 'What this means' })]) : null,
      el('p', { class: 'ac-meta' }, ['Latest: ', link(form(cur.form, cur.amendment_number) + ' filed ' + dmy(cur.filed_date), cur.source_url), cur.event_date ? el('span', { title: 'The date of the event that required the filing, as filed', text: ' (event ' + dmy(cur.event_date) + ')' }) : null,
        cur.shares != null ? ' · ' + int(cur.shares) + ' shares' : null, ch.length > 1 ? ' · first 13D filed ' + dmy(first.filed_date) + ' at ' + pc(first.percent) : null]),
      switched(c.switched_from_13g), quote(c.purpose, cur.accession_number),
      more.length ? el('details', { class: 'ac-chain' }, [el('summary', { text: ch.length > 1 ? 'All ' + ch.length + ' filings in this stake' + (grp.length > 1 ? ', and the group' : '') : 'The ' + grp.length + ' reporting persons' })].concat(more)) : null]);
  }

  // block(host, response, {head: the heading row to keep, all: exited stakes shown, onAll(all): reload with or without them})
  function block(host, r, o) {
    o = o || {}; host.hidden = false;
    if (r.status === 404) { host.hidden = true; return; } // the endpoint is not on this server yet: show nothing rather than an error
    var b = r.b || {}, d = b.data || [], kids = [o.head, disclaimer(b)];
    if (!r.ok) kids.push(el('p', { class: 'muted', text: r.status === 403 ? 'Activist stakes for this company need a free key (the demo key covers the showcase companies).' : r.status === 429 ? 'Too many requests this minute; activist stakes will load on the next view.' : 'Activist stakes are unavailable right now.' }));
    else {
      kids.push(d.length ? el('ol', { class: 'ac-list' }, d.map(item)) : el('p', { class: 'muted', text: o.all ? 'No Schedule 13D stakes in the structured filings.' : 'No current Schedule 13D stake of 5% or more in the structured filings.' }));
      if (o.onAll) { var t = el('button', { type: 'button', class: 'linkish ac-tog', text: o.all ? 'Show current stakes only' : 'Include exited stakes' }); t.addEventListener('click', function () { o.onAll(!o.all); }); kids.push(t); }
      if ((b.notes || []).length) kids.push(el('p', { class: 'muted small', text: b.notes.join(' ') }));
    }
    kids.push(coverage(b));
    host.replaceChildren.apply(host, kids.filter(Boolean));
  }
  window.prvActivists = { load: load, block: block, quote: quote, change: change, who: who, switched: switched, disclaimer: disclaimer, coverage: coverage, form: form, link: link, dmy: dmy, pc: pc, int: int, cap: cap, ofClass: ofClass, el: el };
})();
