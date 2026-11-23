/* D-15 private raises (Form D): one company's exempt offerings on Filings, and the list of all of them in
   the Screener with industry, state, amount, date and exemption filters. Self-reported by the issuer on
   Form D; amounts as filed. A Form D is a notice, not a registration: the SEC does not review it. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var BASIS = 'Self-reported by the issuer on Form D; amounts as filed.';
  var EX = { '06b': 'Rule 506(b)', '06c': 'Rule 506(c)', '04': 'Rule 504', '4a5': 'Section 4(a)(5)', '04a7': 'Section 4(a)(7)', '3C': 'Investment Company Act 3(c)', '3C.1': '3(c)(1)', '3C.7': '3(c)(7)', '3C.5': '3(c)(5)', '04a2': 'Section 4(a)(2)', '05': 'Rule 505', '04.': 'Rule 504' };
  var INDUSTRIES = ['Biotechnology', 'Pharmaceuticals', 'Other Health Care', 'Other Technology', 'Computers', 'Telecommunications', 'Pooled Investment Fund', 'Commercial Banking', 'Other Banking and Financial Services', 'Insurance', 'Investing', 'REITS and Finance', 'Commercial', 'Residential', 'Other Real Estate', 'Oil and Gas', 'Energy Conservation', 'Electric Utilities', 'Other Energy', 'Manufacturing', 'Retailing', 'Restaurants', 'Agriculture', 'Airlines and Airports', 'Other'];
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { var v = attrs[k]; if (v == null || v === false) return; if (k === 'text') n.textContent = v; else if (k === 'on') Object.keys(v).forEach(function (e) { n.addEventListener(e, v[e]); }); else n.setAttribute(k, v); });
    (kids || []).forEach(function (c) { if (c != null && c !== '') n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function day(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : '—'; }
  function money(v) { if (v == null) return '—'; var a = Math.abs(v); return '$' + (a >= 1e9 ? (a / 1e9).toFixed(1) + 'B' : a >= 1e6 ? (a / 1e6).toFixed(1) + 'M' : a >= 1e3 ? Math.round(a / 1e3) + 'K' : Math.round(a)); }
  function parseAmt(t) { var m = /^\s*\$?([\d.]+)\s*([kmb]?)\s*$/i.exec(t || ''); return m ? Math.round(parseFloat(m[1]) * ({ k: 1e3, m: 1e6, b: 1e9 }[m[2].toLowerCase()] || 1)) : null; }
  function note(t) { return t ? el('p', { class: 'muted small', text: t }) : null; }
  function door(text, f, label) { var info = { label: label, currency: 'USD', form_type: f.form || 'D', filed_date: f.filed_date, accession_number: f.accession_number, source_url: f.source_url, fiscal_label: 'As filed on Form D' }; return window.ProvCard ? window.ProvCard.door(text, info) : document.createTextNode(text); }
  function askLink(q, cik, what) { var p = new URLSearchParams(); p.set('q', q.slice(0, 480)); if (cik) p.set('cik', String(parseInt(cik, 10))); return el('a', { class: 'ask', href: '/chat/?' + p.toString(), 'aria-label': 'Ask in chat about ' + what, text: 'Ask' }); }
  function exem(codes) { return (codes || []).map(function (c) { return EX[c] || c; }).join(', ') || '—'; }
  function failed(r, what) {
    if (r && r.status === 403) return note(what + ' without a key covers the showcase companies only. Connect a free key.');
    if (r && r.status === 422) return note(((r.body || {}).error || {}).message || 'One of the filters is not valid.');
    if (r && r.status === 429) return note('Too many requests just now. Try again in a minute.');
    return note(what + ' could not be loaded just now.');
  }
  function offered(x) { return x.indefinite ? 'Indefinite' : money(x.total_offering_amount); }
  function amounts(x, who) {
    var f = x.latest_filing || {};
    return [x.indefinite ? el('span', { text: 'Indefinite' }) : x.total_offering_amount == null ? '—' : door(money(x.total_offering_amount), f, who + ', total offering amount'),
      el('span', { class: 'muted small', text: ' · raised ' }), x.total_amount_sold == null ? '—' : door(money(x.total_amount_sold), f, who + ', raised (total amount sold, cumulative)'),
      // D-15b: an amount of $100B or more from an issuer that is not a cash vehicle is kept as filed and flagged
      x.quality_status === 'suspect_amount' ? el('span', { class: 'tag tag-sus', title: 'Kept exactly as the issuer filed it, but $100B or more from an issuer that is not a cash or liquidity fund is probably a filing error. Left out of “largest raised” unless included.', text: 'Implausible amount as filed' }) : null];
  }

  /* one company's offerings, on Filings */
  function company(host, o) {
    host.replaceChildren(el('h3', { id: 'pr-h', text: 'Private raises (Form D)' }), note('Loading…'));
    o.load('/v1/companies/' + o.cik + '/private-raises?limit=' + (o.keyed ? 50 : 10)).then(function (r) {
      if (!r) return;
      var head = el('h3', { id: 'pr-h', text: 'Private raises (Form D)' });
      if (!r.ok) { host.replaceChildren(head, failed(r, 'Form D offerings')); return; }
      var items = r.body.data || [];
      if (!items.length) { host.replaceChildren(head, note('No Form D offerings by this company in the SEC’s Form D data sets loaded here (the last eight quarters).')); return; }
      var rows = items.map(function (x) {
        var f = x.latest_filing || {}, ps = x.related_persons || [];
        var det = el('details', { class: 'pr-d' }, [el('summary', {}, [el('span', { class: 'pr-when', text: day(f.filed_date) }), el('span', {}, amounts(x, 'This offering')), el('span', { class: 'muted small', text: (x.industry_group || '') + ' · ' + exem(x.exemptions) })]),
          el('dl', { class: 'pr-dl' }, [el('dt', { text: 'Investors' }), el('dd', { text: x.investors ? x.investors.total + (x.investors.non_accredited ? ', ' + x.investors.non_accredited + ' not accredited' : ', all accredited') : '—' }),
            el('dt', { text: 'First sale' }), el('dd', { text: x.first_sale_yet_to_occur ? 'Yet to occur' : day(x.first_sale_date) }),
            el('dt', { text: 'Remaining' }), el('dd', { text: x.indefinite ? '—' : money(x.total_remaining) }),
            x.minimum_investment != null ? el('dt', { text: 'Minimum investment' }) : null, x.minimum_investment != null ? el('dd', { text: money(x.minimum_investment) }) : null,
            ps.length ? el('dt', { text: 'Related persons' }) : null, ps.length ? el('dd', { text: ps.map(function (p) { return p.name + (p.relationships && p.relationships.length ? ' (' + p.relationships.join(', ') + ')' : ''); }).join('; ') + (x.related_persons_count > ps.length ? ' and ' + (x.related_persons_count - ps.length) + ' more' : '') }) : null,
            el('dt', { text: 'Filings' }), el('dd', {}, (x.filings || [f]).map(function (g) { return ARCHIVE.test(g.source_url || '') ? el('a', { href: g.source_url, target: '_blank', rel: 'noopener', text: (g.form || 'D') + ' ' + day(g.filed_date) + ' ↗ ' }) : null; }))]),
          el('p', { class: 'small' }, [askLink('Tell me about the Form D offering filed ' + (f.filed_date || '') + ' (accession ' + (f.accession_number || '') + '): how much was raised, from how many investors, under which exemption?', o.cik, 'this Form D offering')])]);
        return el('li', {}, [det]);
      });
      host.replaceChildren.apply(host, [head, el('ol', { class: 'pr-list' }, rows), note(r.body.labels && r.body.labels.basis || BASIS), note((r.body.notes || []).join(' '))].filter(Boolean)); // a null child prints "null"
    });
  }

  /* the list, in the Screener: filters in the address, one request per Apply */
  function list(host, o) {
    var q = new URLSearchParams(location.search), F = { industry: q.get('pi') || '', state: q.get('ps') || '', min: q.get('pa') || '', from: q.get('pf') || '', to: q.get('pt') || '', exemption: q.get('px') || '' };
    var dl = el('datalist', { id: 'pr-ind' }, INDUSTRIES.map(function (i) { return el('option', { value: i }); }));
    var fi = el('input', { type: 'text', list: 'pr-ind', value: F.industry, placeholder: 'Any industry', 'aria-label': 'Industry group, as filed' });
    var fs = el('input', { type: 'text', value: F.state, size: '4', maxlength: '2', placeholder: 'Any', 'aria-label': 'Issuer state or country code, two letters' });
    var fa = el('input', { type: 'text', value: F.min, size: '7', placeholder: 'e.g. 50M', 'aria-label': 'Raised (amount sold) at least, e.g. 50M' });
    var order = q.get('po') === 'sold' ? 'sold' : 'new';
    var fq = el('input', { type: 'checkbox' }); fq.checked = q.get('pq') === '1';
    // cash and liquidity funds roll subscriptions over, so they top 'largest raised'; left out there unless asked for
    var FUNDS = 'Pooled Investment Fund', xi = q.get('pxi'), dflt = function () { return order === 'sold' ? FUNDS : ''; };
    var fe = el('input', { type: 'text', list: 'pr-ind', value: xi == null ? dflt() : xi === 'none' ? '' : xi, placeholder: 'None', 'aria-label': 'Leave out an industry group, as filed' });
    var feL = el('label', { class: 'scr-l', title: 'Leave out one industry group as filed. “Pooled Investment Fund” (cash and liquidity funds whose subscriptions roll over) is left out of Largest raised unless you clear it.' }, ['Leave out ', fe]);
    var fqL = el('label', { class: 'scr-l check', title: 'Offerings of $100B or more from issuers that are not cash or liquidity funds, kept as filed but flagged' }, [fq, ' Include implausible amounts']);
    var fo = el('span', { class: 'seg', role: 'group', 'aria-label': 'Order' }, [['new', 'Newest first'], ['sold', 'Largest raised']].map(function (x) { return el('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(order === x[0]), text: x[1], on: { click: function () { order = x[0]; if (new URLSearchParams(location.search).get('pxi') == null) fe.value = dflt(); [].forEach.call(fo.children, function (b, i) { b.setAttribute('aria-pressed', String(['new', 'sold'][i] === order)); }); apply(false); } } }); }));
    var ff = el('input', { type: 'date', value: F.from, 'aria-label': 'Filed from' }), ft = el('input', { type: 'date', value: F.to, 'aria-label': 'Filed to' });
    var fx = el('select', { 'aria-label': 'Exemption' }, [['', 'Any exemption'], ['06b', 'Rule 506(b)'], ['06c', 'Rule 506(c)'], ['04', 'Rule 504'], ['4a5', 'Section 4(a)(5)'], ['3C.1', 'Inv. Co. Act 3(c)(1)'], ['3C.7', 'Inv. Co. Act 3(c)(7)']].map(function (x) { var op = el('option', { value: x[0], text: x[1] }); if (x[0] === F.exemption) op.selected = true; return op; }));
    var out = el('div', { class: 'pr-out', 'aria-live': 'polite' }), cursor = null, rows = [];
    var apply = function (more) {
      if (!more) { cursor = null; rows = []; }
      var amt = parseAmt(fa.value);
      if (fa.value.trim() && amt == null) { out.replaceChildren(note('Write the amount like 50M, 2.5B or 750K.')); fa.focus(); return; }
      var p = new URLSearchParams(); if (fi.value.trim()) p.set('industry', fi.value.trim()); if (fs.value.trim()) p.set('state', fs.value.trim().toUpperCase()); if (amt != null) p.set('min_sold', amt); if (order === 'sold') p.set('order', 'sold'); if (fq.checked) p.set('include_suspect', 'true'); if (fe.value.trim()) p.set('exclude_industry', fe.value.trim());
      if (ff.value) p.set('from', ff.value); if (ft.value) p.set('to', ft.value); if (fx.value) p.set('exemption', fx.value); p.set('limit', o.keyed ? 50 : 10); if (more && cursor) p.set('cursor', cursor);
      var u = new URLSearchParams(location.search); u.set('sv', 'raises'); [['pi', fi.value.trim()], ['ps', fs.value.trim().toUpperCase()], ['pa', fa.value.trim()], ['pf', ff.value], ['pt', ft.value], ['px', fx.value], ['po', order === 'sold' ? 'sold' : ''], ['pq', fq.checked ? '1' : ''], ['pxi', fe.value.trim() === dflt() ? '' : fe.value.trim() || 'none']].forEach(function (x) { if (x[1]) u.set(x[0], x[1]); else u.delete(x[0]); });
      try { history.replaceState(null, '', location.pathname + '?' + u.toString() + '#screener'); } catch (e) {}
      if (!more) out.replaceChildren(note('Loading…'));
      o.load('/v1/private-raises?' + p.toString()).then(function (r) {
        if (!r || !r.ok) { out.replaceChildren(failed(r, 'Private raises')); return; }
        rows = rows.concat(r.body.data || []); cursor = r.body.meta && r.body.meta.has_more ? r.body.meta.next_cursor : null;
        draw(r.body);
      });
    };
    var draw = function (b) {
      if (!rows.length) { out.replaceChildren(el('p', { class: 'muted', text: 'No Form D offerings match these filters in the last eight quarters loaded.' })); return; }
      var head = el('tr', {}, ['Filed', 'Issuer', 'Industry', 'Offered · raised', 'Investors', 'Exemption', 'Form D'].map(function (h, i) { return el('th', { scope: 'col', class: i === 3 || i === 4 ? 'n' : '', text: h }); }));
      var body = rows.map(function (x) {
        var I = x.issuer || {}, f = x.latest_filing || {}, ck = I.cik ? String(parseInt(I.cik, 10)) : null, nm = o.name ? o.name(I.name || '') : I.name;
        return el('tr', {}, [el('td', { text: day(f.filed_date) }), el('th', { scope: 'row' }, [I.is_registrant && ck ? el('a', { href: '/app/?c=' + ck, text: nm }) : el('span', { text: nm }), el('span', { class: 'muted small pp-title', text: [I.state, I.entity_type, I.is_registrant ? 'files reports with the SEC' : null].filter(Boolean).join(' · ') })]),
          el('td', { class: 'muted', text: x.industry_group || '—' }), el('td', { class: 'n' }, amounts(x, nm)), el('td', { class: 'n', text: x.investors ? String(x.investors.total) : '—' }), el('td', { class: 'muted', text: exem(x.exemptions) }),
          el('td', {}, [ARCHIVE.test(f.source_url || '') ? el('a', { href: f.source_url, target: '_blank', rel: 'noopener', text: (f.form || 'D') + ' ↗' }) : '—', ' ', askLink('Tell me about ' + nm + '’s Form D offering filed ' + (f.filed_date || '') + ' (accession ' + (f.accession_number || '') + ').', I.is_registrant ? I.cik : null, nm + '’s offering')])]);
      });
      var more = cursor && o.keyed ? el('button', { type: 'button', class: 'btn small', text: 'Load more', on: { click: function () { apply(true); } } }) : null;
      var table = el('table', { class: 'pp-table pr-table pp-stack' }, [el('thead', {}, [head]), el('tbody', {}, body)]), hs = [].map.call(head.children, function (h) { return h.textContent; });
      [].forEach.call(table.tBodies[0].rows, function (r) { [].forEach.call(r.children, function (c, i) { if (i > 1) c.setAttribute('data-l', hs[i]); }); }); // on phones each offering reads as a card
      out.replaceChildren.apply(out, [el('div', { class: 'tw' }, [table]), more,
        !o.keyed && rows.length >= 10 ? note('Without a key, the 10 latest matches are shown.') : null, note((b.labels && b.labels.basis) || BASIS), note((b.notes || []).join(' '))].filter(Boolean));
    };
    var form = el('form', { class: 'ch-bar pr-f', on: { submit: function (e) { e.preventDefault(); apply(false); } } }, [
      el('label', { class: 'scr-l' }, ['Industry ', fi]), dl, el('label', { class: 'scr-l' }, ['State ', fs]), el('label', { class: 'scr-l' }, ['Raised at least ', fa]),
      el('label', { class: 'scr-l' }, ['Filed from ', ff]), el('label', { class: 'scr-l' }, ['to ', ft]), fx, fo, feL, fqL, el('button', { type: 'submit', class: 'btn small primary', text: 'Apply' })]);
    host.replaceChildren(el('p', { class: 'muted small', text: 'Exempt offerings filed on Form D in the last eight quarters, newest first. ' + BASIS + ' A Form D is a notice, not a registration; the SEC does not review it. Not investment advice.' }), form, out);
    apply(false);
  }
  // the Screener's two modes: company financials (screener.js) and private raises; the mode is ?sv=raises
  var specP = null;
  function has(path) { specP = specP || fetch('/openapi.json', { headers: { Accept: 'application/json' } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { return j && j.paths ? j.paths : {}; }).catch(function () { return {}; }); return specP.then(function (p) { return !!p[path]; }); }
  function mode(q0) {
    q0 = q0 || new URLSearchParams(location.search); // read before the financial screen rewrites the address
    var sec = document.getElementById('screener'), ctl = document.getElementById('scr-ctl'), out = document.getElementById('scr-out'); if (!sec || !ctl) return;
    has('/v1/private-raises').then(function (y) {
      if (!y) return;
      var X = window.ProvenanceExplorer, bar = document.getElementById('scr-mode'), view = document.getElementById('pr-view');
      if (!bar) { bar = el('div', { id: 'scr-mode', class: 'seg', role: 'group', 'aria-label': 'Screen' }); sec.insertBefore(bar, ctl); }
      if (!view) { view = el('div', { id: 'pr-view', hidden: 'hidden' }); sec.insertBefore(view, out.nextSibling); }
      var set = function (v) {
        ctl.hidden = out.hidden = v === 'raises'; view.hidden = v !== 'raises';
        bar.replaceChildren.apply(bar, [['fin', 'Company financials'], ['raises', 'Private raises (Form D)']].map(function (x) { return el('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(v === x[0]), text: x[1], on: { click: function () { var u = new URLSearchParams(location.search); if (x[0] === 'raises') u.set('sv', 'raises'); else u.delete('sv'); try { history.replaceState(null, '', location.pathname + (u.toString() ? '?' + u.toString() : '') + '#screener'); } catch (e) {} set(x[0]); } } }); }));
        if (v === 'raises' && !view.dataset.on) { view.dataset.on = '1'; list(view, { keyed: X.hasKey(), name: window.Workspace ? window.Workspace.orgName : null, load: function (path) { return X.raw(path, X.hasKey() ? null : 'demo'); } }); }
      };
      if (q0.get('sv') === 'raises') { try { history.replaceState(null, '', location.pathname + '?' + q0.toString() + '#screener'); } catch (e) {} }
      set(q0.get('sv') === 'raises' ? 'raises' : 'fin');
    });
  }
  window.ProvenanceRaises = { company: company, list: list, mode: mode };
})();
