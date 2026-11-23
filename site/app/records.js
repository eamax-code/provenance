/* X-20 SEC comment letters (on Filings) and X-18 the corporate tree (on Connections). Letters: the SEC's
   review threads with the company's replies, topics from a reviewed keyword list. Tree: GLEIF Level 2
   parents and children (CC0; named, not linked) and the exhibit 21 subsidiaries, folded past 50. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var FOLD = 50;
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  function note(t) { return t ? el('p', { class: 'muted small', text: t }) : null; }
  function failed(r, what) {
    if (r && r.status === 403) return note(what + ' without a key covers the showcase companies only. Connect a free key to see this company.');
    if (r && r.status === 429) return note('Too many requests just now. Try again in a minute.');
    return note(what + ' could not be loaded just now.');
  }

  /* ---- X-20 comment letters ---- */
  function letters(host, o) {
    host.replaceChildren(el('h3', { id: 'cl-h', text: 'SEC comment letters' }), note('Loading the review correspondence…'));
    o.load('/v1/companies/' + o.cik + '/comment-letters?limit=' + (o.keyed ? 50 : 10)).then(function (r) {
      if (!r) return;
      var head = [el('h3', { id: 'cl-h', text: 'SEC comment letters' }), el('p', { class: 'muted small', text: 'The SEC’s questions on this company’s filings and the company’s replies, which the SEC releases after a review closes. Topics are tagged from a reviewed keyword list, not by a model.' })];
      if (!r.ok) { host.replaceChildren.apply(host, head.concat([failed(r, 'Comment letters')])); return; }
      var b = r.body, threads = b.threads || [], K = b.topic_keys || {}, off = null;
      var count = {}; threads.forEach(function (t) { (t.topics || []).forEach(function (k) { count[k] = (count[k] || 0) + 1; }); });
      var chips = el('div', { class: 'cl-topics', role: 'group', 'aria-label': 'Topics' }), list = el('ol', { class: 'cl-list' });
      var draw = function () {
        chips.replaceChildren.apply(chips, Object.keys(count).sort(function (a, c) { return count[c] - count[a]; }).map(function (k) { return el('button', { type: 'button', class: 'chip cl-topic', 'aria-pressed': String(off === k), text: (K[k] || k.replace(/_/g, ' ')) + ' ' + count[k], on: { click: function () { off = off === k ? null : k; draw(); } } }); }));
        list.replaceChildren.apply(list, threads.filter(function (t) { return !off || (t.topics || []).indexOf(off) > -1; }).map(function (t) { return thread(t, K); }));
      };
      var kids = head.concat([b.coverage === 'not_read' ? note('This company’s letters are listed but not read for topics yet.') : null]);
      if (!threads.length) kids.push(el('p', { class: 'muted', text: 'No SEC comment letters released for this company' + (b.since ? ' since ' + day(b.since) : ' in the last five years') + '.' }));
      else { kids.push(Object.keys(count).length ? chips : null, list); draw(); }
      kids.push(note((b.notes || []).join(' ')), !o.keyed && threads.length >= 10 ? note('Without a key, the 10 latest threads are shown.') : null);
      host.replaceChildren.apply(host, kids.filter(Boolean));
    });
  }
  function thread(t, K) {
    var ls = t.letters || [], first = ls[0] || {};
    var sum = el('summary', {}, [el('span', { class: 'cl-subj', text: t.subject || ('Review of file ' + (t.file_number || 'number not given')) }),
      el('span', { class: 'chip cl-st ' + (t.status === 'closed' ? 'is-closed' : 'is-open'), text: t.status === 'closed' ? 'Closed ' + day(t.closed) : 'Open or not known' }),
      el('span', { class: 'muted small', text: 'Opened ' + day(t.opened) + ' · ' + ls.length + (ls.length === 1 ? ' letter' : ' letters') + (t.file_number ? ' · file ' + t.file_number : '') })].concat((t.topics || []).map(function (k) { return el('span', { class: 'tag', text: K[k] || k.replace(/_/g, ' ') }); })));
    var rows = ls.map(function (l) {
      var who = l.from === 'sec' ? 'SEC letter' : l.kind === 'acceleration_request' ? 'Company: acceleration request' : 'Company reply';
      return el('li', { class: 'cl-l ' + (l.from === 'sec' ? 'from-sec' : 'from-co') }, [el('time', { datetime: l.date, text: day(l.date) }), el('span', { class: 'cl-who', text: who }),
        el('span', { class: 'cl-lt' }, (l.topics || []).map(function (k) { return el('span', { class: 'tag', text: K[k] || k.replace(/_/g, ' ') }); }).concat(l.readable === false ? [el('span', { class: 'muted small', text: 'scanned, not readable for topics' })] : [])),
        ARCHIVE.test(l.source_url || '') ? el('a', { href: l.source_url, target: '_blank', rel: 'noopener', text: (l.form || 'Letter') + ' ↗' }) : el('span')]);
    });
    return el('li', { class: 'cl-t' }, [el('details', {}, [sum, el('ol', { class: 'cl-letters' }, rows)])]);
  }

  /* ---- X-18 corporate tree ---- */
  var EXC = { NATURAL_PERSONS: 'Controlled by natural persons', NON_CONSOLIDATING: 'Its parent does not consolidate it', NO_KNOWN_PERSON: 'No parent: not consolidated by another entity', NON_PUBLIC: 'The parent is not disclosed', BINDING_LEGAL_COMMITMENTS: 'The parent cannot be disclosed for legal reasons' };
  function node(n, extra) {
    var ck = n.cik ? String(parseInt(n.cik, 10)) : null;
    return el('span', { class: 'ct-node' }, [ck ? el('a', { href: '/app/?c=' + ck + '&tab=connections', text: n.name || n.lei }) : el('span', { class: 'ct-name', text: n.name || n.lei }),
      n.jurisdiction ? el('span', { class: 'muted small', text: n.jurisdiction }) : null, n.lei ? el('span', { class: 'mono small muted ct-lei', title: 'Legal Entity Identifier', text: n.lei }) : null,
      n.status && n.status !== 'ACTIVE' ? el('span', { class: 'tag', text: String(n.status).toLowerCase() }) : null].concat(extra || []));
  }
  function folded(items, render, label) {
    var ul = el('ul', { class: 'ct-list' }), shown = Math.min(items.length, FOLD);
    var paint = function (k) { ul.replaceChildren.apply(ul, items.slice(0, k).map(function (x) { return el('li', {}, [render(x)]); })); };
    paint(shown);
    if (items.length <= FOLD) return [ul];
    var find = el('input', { type: 'search', class: 'ct-find', placeholder: 'Find in ' + items.length + ' ' + label, 'aria-label': 'Find in the ' + label });
    var more = el('button', { type: 'button', class: 'btn small', text: 'Show all ' + items.length, on: { click: function () { paint(items.length); more.remove(); } } });
    find.addEventListener('input', function () { var q = find.value.trim().toLowerCase(); if (!q) { paint(shown); return; } ul.replaceChildren.apply(ul, items.filter(function (x) { return String(x.name || '').toLowerCase().indexOf(q) > -1; }).slice(0, 200).map(function (x) { return el('li', {}, [render(x)]); })); });
    return [find, ul, more];
  }
  function tree(host, o) {
    host.replaceChildren(el('h3', { id: 'ct-h', text: 'Corporate tree' }), note('Loading the parents and subsidiaries…'));
    o.load('/v1/companies/' + o.cik + '/corporate-tree?children_limit=500&subsidiaries_limit=1000').then(function (r) {
      if (!r) return;
      var head = [el('h3', { id: 'ct-h', text: 'Corporate tree' })];
      if (!r.ok) { host.replaceChildren.apply(host, head.concat([failed(r, 'The corporate tree')])); return; }
      var b = r.body, E = b.entity || {}, P = b.parents || {}, C = b.children || {}, S = b.subsidiaries || {};
      var kids = head.slice();
      // parents above the entity, as a short chain
      var chain = el('ol', { class: 'ct-chain' });
      if (P.ultimate && !(P.direct && P.direct.lei === P.ultimate.lei)) chain.appendChild(el('li', {}, [el('span', { class: 'ct-rel', text: 'Ultimate parent' }), node(P.ultimate)]));
      if (P.direct) chain.appendChild(el('li', {}, [el('span', { class: 'ct-rel', text: P.ultimate && P.direct.lei === P.ultimate.lei ? 'Direct and ultimate parent' : 'Direct parent' }), node(P.direct)]));
      (P.exceptions || []).forEach(function (x) { chain.appendChild(el('li', { class: 'ct-exc' }, [el('span', { class: 'ct-rel', text: x.kind === 'ultimate' ? 'Ultimate parent' : 'Direct parent' }), el('span', { text: x.text || EXC[x.reason] || x.reason }), el('span', { class: 'mono small muted', text: ' ' + x.reason })])); });
      if (E.lei && !P.direct && !P.ultimate && !(P.exceptions || []).length) chain.appendChild(el('li', { class: 'ct-exc' }, [el('span', { class: 'ct-rel', text: 'Parent' }), el('span', { class: 'muted', text: 'Not reported to GLEIF.' })]));
      chain.appendChild(el('li', { class: 'ct-self' }, [el('span', { class: 'ct-rel', text: 'This company' }), node({ name: E.name || o.name, lei: E.lei, jurisdiction: E.jurisdiction })]));
      kids.push(E.lei ? chain : el('p', { class: 'muted', text: 'No LEI is matched to this company, so GLEIF has no parents or children to show. Its exhibit 21 subsidiaries are below.' }));
      if (E.lei) {
        var ch = C.data || [];
        kids.push(el('h4', { class: 'ct-k', text: 'Entities that report it as parent in GLEIF, ' + (C.total != null ? C.total : ch.length) }));
        kids = kids.concat(ch.length ? folded(ch, function (x) { return node(x, [el('span', { class: 'tag', text: x.relationship === 'ultimate_only' ? 'ultimate only' : 'direct' })]); }, 'GLEIF entities') : [note('None reported.')]);
        if (C.total > ch.length) kids.push(note('The first ' + ch.length + ' of ' + C.total + ' are shown.'));
      }
      var sub = S.data || [];
      kids.push(el('h4', { class: 'ct-k' }, ['Subsidiaries in exhibit 21, ' + (S.total != null ? S.total : sub.length) + ' ', S.filing && ARCHIVE.test(S.filing.source_url || '') ? el('a', { href: S.filing.source_url, target: '_blank', rel: 'noopener', text: (S.filing.form || '10-K') + ' filed ' + day(S.filing.filed_date) + ' ↗' }) : null]));
      kids = kids.concat(sub.length ? folded(sub, function (x) { return node({ name: x.name, jurisdiction: x.jurisdiction, lei: x.lei }); }, 'subsidiaries') : [note('No exhibit 21 in the filings loaded. Foreign private issuers list subsidiaries in the 20-F, which is not read here.')]);
      if (S.total > sub.length) kids.push(note('The first ' + sub.length + ' of ' + S.total + ' are shown.'));
      kids.push(note((b.notes || []).join(' ') || 'Parents and GLEIF children are from GLEIF Level 2 relationship data (CC0) as the entities report them; subsidiaries are as listed in exhibit 21.'),
        note('A subsidiary shows an LEI only when exactly one GLEIF entity has the same legal name and jurisdiction.'));
      host.replaceChildren.apply(host, kids.filter(Boolean));
    });
  }
  window.ProvenanceRecords = { letters: letters, tree: tree };
})();
