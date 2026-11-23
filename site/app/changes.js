/* X-14 What changed: a 10-K's risk factors and MD&A headings against the company's previous 10-K, as
   added, removed or reworded (side by side, words that changed marked). Each side links its filing. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var WHY = {
    not_read: 'This report has not been read for changes yet. The largest filers are read first; the rest follow.',
    prior_not_read: 'The previous annual report has not been read yet, so there is nothing to compare with.',
    not_split: 'The risk factors in this report could not be split into headings, so they are not compared. The full text is in the filing.',
    not_annual_report: 'Changes are compared for annual reports (10-K, 20-F) only.'
  };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  function fy(f) { return f && f.period ? 'FY' + f.period.slice(0, 4) : ''; }
  function flink(f, text) { return f && ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: text }) : el('span', { text: text }); }
  // MD&A table column heads ("2025", "Change") are not headings
  function real(i) { var h = String(i.heading || '').trim(); return h.length > 3 && !/^(\d{4}|change|total|%|\$)$/i.test(h) && !/^[\d\s.,%$()-]+$/.test(h); }

  // word diff (longest common subsequence on words): what was taken out of the old text, what the new one adds
  function diff(a, b) {
    var A = String(a || '').split(/(\s+)/), B = String(b || '').split(/(\s+)/), n = A.length, m = B.length;
    if (n * m > 600000) return null; // too long to mark word by word: shown plain
    var L = []; for (var i = 0; i <= n; i++) { L.push(new Uint16Array(m + 1)); }
    for (i = n - 1; i >= 0; i--) for (var j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    var oa = [], ob = []; i = 0; j = 0;
    while (i < n && j < m) { if (A[i] === B[j]) { oa.push([0, A[i]]); ob.push([0, B[j]]); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) oa.push([1, A[i++]]); else ob.push([1, B[j++]]); }
    while (i < n) oa.push([1, A[i++]]); while (j < m) ob.push([1, B[j++]]);
    return [oa, ob];
  }
  function marked(parts, tag) {
    var p = el('p', { class: 'chg-text' }), buf = '', on = false;
    var flush = function () { if (!buf) return; p.appendChild(on ? el(tag, { text: buf }) : document.createTextNode(buf)); buf = ''; };
    parts.forEach(function (x) { var w = x[1], ch = !!x[0] && /\S/.test(w); if (ch !== on && /\S/.test(w)) { flush(); on = ch; } buf += w; });
    flush(); return p;
  }
  function more(text, len) { return len && len > String(text || '').length ? el('span', { class: 'muted small', text: ' … ' + (len - String(text).length).toLocaleString('en-US') + ' more characters in the filing.' }) : null; }

  function one(i, kind, r) {
    var f = kind === 'removed' ? r.prior : r.filing;
    var body = el('details', { class: 'chg-d' }, [el('summary', {}, [el('span', { class: 'chg-h', text: i.heading }), i.group ? el('span', { class: 'muted small chg-g', text: i.group }) : null])]);
    body.appendChild(el('p', { class: 'chg-text' }, [i.text || 'No text under this heading.', more(i.text, i.text_length)]));
    body.appendChild(el('p', { class: 'small' }, [flink(f, (kind === 'removed' ? 'In the ' : 'New in the ') + (f && f.form || '10-K') + ' filed ' + day(f && f.filed_date) + ' ↗')]));
    return el('li', { class: 'chg-i chg-' + kind }, [body]);
  }
  function reworded(i, r, k, o) {
    var d = diff(i.text_before, i.text), cut = String(i.text_before || '').length >= 1450 && String(i.text || '').length >= 1450;
    // both texts are cut at 1,500 characters: past the last word they share, a difference is the cut, not a change
    if (d && cut) d.forEach(function (side) { for (var k = side.length - 1; k >= 0 && side[k][0]; k--) side[k][0] = 0; });
    var hd = i.heading_before && i.heading_before !== i.heading ? diff(i.heading_before, i.heading) : null;
    var side = function (label, f, head, text, parts, hparts, tag) {
      return el('div', { class: 'chg-side' }, [el('p', { class: 'chg-when' }, [flink(f, label + ' · ' + (f && f.form || '10-K') + ' filed ' + day(f && f.filed_date) + ' ↗')]),
        hparts ? (function () { var h = marked(hparts, tag); h.className = 'chg-h'; return h; })() : el('p', { class: 'chg-h', text: head }),
        parts ? marked(parts, tag) : el('p', { class: 'chg-text', text: text || '' })]);
    };
    var sim = i.similarity != null ? Math.round(i.similarity * 100) + '% similar' : '';
    var det = el('details', { class: 'chg-d' }, [el('summary', {}, [el('span', { class: 'chg-h', text: i.heading }), el('span', { class: 'muted small chg-g', text: [i.group, sim].filter(Boolean).join(' · ') })]),
      cut ? el('p', { class: 'muted small', text: 'Both texts are cut at 1,500 characters; the ends are not compared.' }) : null,
      el('div', { class: 'chg-pair' }, [side('Before, ' + fy(r.prior), r.prior, i.heading_before || i.heading, i.text_before, d && d[0], hd && hd[0], 'del'), side('Now, ' + fy(r.filing), r.filing, i.heading, i.text, d && d[1], hd && hd[1], 'ins')])]);
    // the open item is part of the link (cho = its place in this list, from 1)
    if (o && o.open === k) { det.open = true; setTimeout(function () { det.scrollIntoView({ block: 'start' }); }, 0); }
    det.addEventListener('toggle', function () { if (o && o.onOpen) o.onOpen(det.open ? k : null); });
    if (o && o.ask) det.appendChild(el('p', { class: 'small' }, [el('a', { class: 'ask', href: o.ask('What changed in the risk factor "' + String(i.heading).slice(0, 140) + '" in ' + (o.name || 'the company') + '’s ' + (r.filing.form || '10-K') + ' filed ' + r.filing.filed_date + '? (accession ' + r.filing.accession_number + ')'), 'aria-label': 'Ask in chat about this change', text: 'Ask about this change →' })]));
    return el('li', { class: 'chg-i chg-reworded' }, [det]);
  }
  function part(r, key, title, o) {
    var P = r[key];
    if (!P) return el('p', { class: 'muted', text: key === 'risk_factors' ? 'No risk factors to compare: smaller reporting companies may omit Item 1A.' : 'No MD&A headings to compare.' });
    var add = (P.added || []).filter(real), rem = (P.removed || []).filter(real), rew = (P.reworded || []).filter(real);
    var c = P.counts || {};
    var kids = [el('p', { class: 'chg-sum' }, [el('b', { text: add.length + ' added' }), ' · ', el('b', { text: rem.length + ' removed' }), ' · ', el('b', { text: rew.length + ' reworded' }), el('span', { class: 'muted', text: ' · ' + (c.unchanged != null ? c.unchanged + ' unchanged' : '') + (c.now != null ? ', ' + c.now + ' headings now, ' + c.before + ' before' : '') })])];
    var group = function (label, items, fn) { if (!items.length) return; kids.push(el('h4', { class: 'chg-k', text: label + ' (' + items.length + ')' })); kids.push(el('ol', { class: 'chg-list' }, items.map(fn))); };
    group('Added', add, function (i) { return one(i, 'added', r); });
    group('Removed', rem, function (i) { return one(i, 'removed', r); });
    group('Reworded, biggest rewrites first', rew, function (i, k) { return reworded(i, r, k + 1, o); });
    if (!add.length && !rem.length && !rew.length) kids.push(el('p', { class: 'muted', text: 'No ' + title.toLowerCase() + ' headings were added, removed or reworded.' }));
    return el('div', { class: 'chg-part' }, kids);
  }

  // o: { load(path) -> Promise<{ok,status,body}>, cik, accession (optional), keyed }
  function render(host, o) {
    var path = o.accession ? '/v1/filings/' + encodeURIComponent(o.accession) + '/changes' : '/v1/companies/' + o.cik + '/changes';
    host.replaceChildren(el('h3', { id: 'chg-h', text: 'What changed in the annual report' }), el('p', { class: 'muted', text: 'Comparing with the previous annual report…' }));
    o.load(path).then(function (r) {
      if (!r) return;
      if (!r.ok) {
        var e = (r.body && r.body.error) || {}, why = WHY[e.reason] || (r.status === 403 ? 'Without a key this covers the showcase companies only. Connect a free key to compare this company’s reports.' : r.status === 404 ? 'No annual report to compare in the filings loaded.' : 'The comparison could not be loaded just now.');
        host.replaceChildren(el('h3', { id: 'chg-h', text: 'What changed in the annual report' }), el('p', { class: 'muted', text: why })); return;
      }
      var b = r.body, st = { key: o.section === 'mdna' ? 'mdna' : 'risk_factors' }, open = o.open || null, first = true;
      var seg = el('span', { class: 'seg', role: 'group', 'aria-label': 'Section' }), out = el('div', { class: 'chg-out' });
      var draw = function () {
        seg.replaceChildren.apply(seg, [['risk_factors', 'Risk factors'], ['mdna', 'MD&A']].map(function (x) { return el('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(st.key === x[0]), text: x[1], on: { click: function () { st.key = x[0]; open = null; if (o.onState) o.onState({ section: st.key, open: null }); draw(); } } }); }));
        out.replaceChildren(part(b, st.key, st.key === 'mdna' ? 'MD&A' : 'Risk factor', { open: first ? open : null, ask: o.ask, name: o.name, onOpen: function (k) { open = k; if (o.onState) o.onState({ section: st.key, open: k }); } })); first = false;
      };
      var lead = b.prior ? el('p', { class: 'chg-lead' }, ['The ', flink(b.filing, (b.filing.form || '10-K') + ' filed ' + day(b.filing.filed_date) + ' ↗'), ' (' + fy(b.filing) + ') against the ', flink(b.prior, (b.prior.form || '10-K') + ' filed ' + day(b.prior.filed_date) + ' ↗'), ' (' + fy(b.prior) + '), heading by heading.'])
        : el('p', { class: 'chg-lead' }, ['The ', flink(b.filing, (b.filing.form || '10-K') + ' filed ' + day(b.filing.filed_date) + ' ↗'), ': no earlier annual report is stored, so its headings are listed without a comparison.']);
      host.replaceChildren(el('h3', { id: 'chg-h', text: 'What changed in the annual report' }), lead, el('div', { class: 'ch-bar' }, [seg]), out,
        el('p', { class: 'muted small' }, [(b.method && b.method.matching) || '', b.method && b.method.threshold != null ? ' Threshold: ' + b.method.threshold + '.' : '', ' Texts are the first 1,500 characters; the full section is in the filing.']));
      draw();
    });
  }
  window.ProvenanceChanges = { render: render };
})();
