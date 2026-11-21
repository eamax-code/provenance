/* Companies going public (F-02): the pipeline by stage from /v1/public/ipos/pipeline and one deal
   card from /v1/public/ipos/{cik}, each value with the prospectus sentence it came from. Links go to
   the filings on sec.gov only. Information, not investment advice. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var day = function (iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? +m[3] + ' ' + MON[+m[2] - 1] + ' ' + m[1] : (iso || ''); };
  var el = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] == null) return; if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c != null && c !== false) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var json = function (url) { return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) { return r.json().then(function (b) { if (!r.ok) throw new Error((b.error && b.error.message) || r.status); return b; }); }); };
  var link = function (text, url) { return ARCHIVE.test(url || '') ? el('a', { href: url, target: '_blank', rel: 'noopener', text: text }) : el('span', { text: text }); };
  var big = function (v) { var a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(2).replace(/\.?0+$/, '') + 'B' : a >= 1e6 ? (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : v.toLocaleString('en-US'); };
  var usd = function (v, cur) { return v == null ? null : (cur && cur !== 'USD' ? cur + ' ' : '$') + (Math.abs(v) >= 1e6 ? big(v) : v.toFixed(2)); };

  var STAGES = [
    ['confidential', 'Confidential', 'Draft filed privately (DRS)'],
    ['filed', 'Filed', 'Registration made public'],
    ['amended', 'Amended', 'Registration amended'],
    ['effective', 'Effective', 'SEC declared it effective'],
    ['listing', 'Listing', 'Exchange registration (8-A)'],
    ['priced', 'Priced', 'Final prospectus (424B4)'],
    ['withdrawn', 'Withdrawn', 'Registration withdrawn']
  ];
  var LABEL = {}; STAGES.forEach(function (s) { LABEL[s[0]] = s[1]; });
  var rows = [], stage = 'all', chosen = null, everyRow = false, window_ = null;

  /* ---- one value that opens its sentence ---- */
  function evidence(label, shown, t, extra) {
    if (!t) return null;
    var d = el('details', { class: 'ev' + (t.derived ? ' is-derived' : '') });
    d.appendChild(el('summary', {}, [
      el('span', { class: 'ev-label', text: label }),
      el('span', { class: 'ev-value', text: shown }),
      extra ? el('span', { class: 'ev-extra', text: extra }) : null,
      t.derived ? el('span', { class: 'tag', text: 'derived' }) : null
    ]));
    d.appendChild(el('div', { class: 'ev-body' }, [
      el('blockquote', { text: t.evidence || '' }),
      el('p', {}, [(t.derived ? 'Worked out from the ' : 'From the ') + t.form_type + ' filed ' + day(t.filing_date) + ': ', link('open it on sec.gov', t.source_url)])
    ]));
    return d;
  }

  /* ---- the deal card ---- */
  function deal(cik) {
    return json('/v1/public/ipos/' + cik).then(function (d) {
      chosen = String(parseInt(d.cik, 10));
      var t = d.terms || {}, v = function (k) { return t[k] && t[k].value; }, cur = v('currency') || 'USD';
      $('deal-name').textContent = d.name;
      var stageStep = d.milestones && d.milestones[d.stage];
      $('deal-meta').textContent = [v('ticker') || d.ticker, v('exchange') || d.exchange, LABEL[d.stage] + (stageStep ? ' ' + day(stageStep.filing_date) : ''), d.blank_check ? 'blank-check company' : null].filter(Boolean).join(' · ');
      $('deal-actions').replaceChildren(
        el('a', { class: 'btn', href: '/companies/' + chosen, text: 'Company page' }),
        el('a', { class: 'btn', href: '/chat/?q=' + encodeURIComponent('Summarise the IPO of ' + d.name), text: 'Ask about this IPO' })
      );
      var range = v('price_low') != null && v('price_high') != null ? usd(v('price_low'), cur) + ' to ' + usd(v('price_high'), cur) : null;
      var vs = v('price_final') != null && v('price_high') != null ? (v('price_final') > v('price_high') ? 'above the range' : v('price_final') < v('price_low') ? 'below the range' : 'within the range') : null;
      var figs = [
        v('price_final') != null ? evidence('Priced at', usd(v('price_final'), cur), t.price_final, range ? 'range ' + range + ', ' + vs : null) : (range ? evidence('Price range', range, t.price_low) : null),
        evidence('Gross proceeds', usd(v('gross_proceeds'), cur), t.gross_proceeds),
        evidence('Shares offered', v('shares_offered') != null ? big(v('shares_offered')) : null, t.shares_offered, v('shares_primary') != null ? big(v('shares_primary')) + ' new' + (v('shares_secondary') ? ', ' + big(v('shares_secondary')) + ' sold by holders' : '') : null),
        evidence('Underwriting discount', usd(v('underwriting_discount_total'), cur), t.underwriting_discount_total, v('underwriting_discount_per_share') != null ? '$' + v('underwriting_discount_per_share').toFixed(3) + ' a share' : null)
      ].filter(function (x) { return x && x.querySelector('.ev-value').textContent; });
      $('deal-figures').replaceChildren.apply($('deal-figures'), figs.length ? figs : [el('p', { class: 'muted', text: 'No deal terms in the prospectus yet. They appear once a price range is filed.' })]);
      var dates = $('deal-dates'); dates.textContent = '';
      [['Closing', 'closing_date'], ['Research quiet period ends', 'quiet_period_end'], ['Lock-up ends', 'lockup_expiry']].forEach(function (x) {
        var item = t[x[1]]; if (!item) return;
        var extra = x[1] === 'lockup_expiry' && v('lockup_days') ? v('lockup_days') + ' days' + (v('lockup_days_max') && v('lockup_days_max') !== v('lockup_days') ? ', up to ' + v('lockup_days_max') + ' for some holders' : '') : null;
        dates.appendChild(el('div', {}, [evidence(x[0], day(item.value), item, extra)]));
      });
      if (!dates.children.length) dates.appendChild(el('p', { class: 'muted', text: 'No dates yet.' }));
      var uw = $('deal-uw'); uw.textContent = '';
      var leads = v('lead_underwriters') || [], all = v('underwriters') || [];
      if (leads.length) uw.appendChild(evidence('Leads', leads.join(' and '), t.lead_underwriters));
      if (all.length) {
        var more = el('details', { class: 'uw-all' }, [el('summary', { text: 'All ' + all.length + ' underwriters' }), el('ul', {}, all.map(function (n) { return el('li', { text: n }); }))]);
        uw.appendChild(more);
      }
      if (!uw.children.length) uw.appendChild(el('p', { class: 'muted', text: 'Named in the final prospectus.' }));
      var steps = $('deal-steps'); steps.textContent = '';
      STAGES.map(function (s) { return [s, d.milestones && d.milestones[s[0]]]; }).filter(function (x) { return x[1]; })
        .sort(function (a, b) { return a[1].filing_date < b[1].filing_date ? -1 : a[1].filing_date > b[1].filing_date ? 1 : 0; })
        .forEach(function (x) {
          steps.appendChild(el('li', {}, [el('b', { text: x[0][1] }), ' ', el('span', { class: 'muted', text: day(x[1].filing_date) + ' · ' }), link(x[1].form_type, x[1].source_url)]));
        });
      $('deal').classList.remove('is-waiting');
      markChosen();
    });
  }
  function choose(cik, scroll) {
    deal(cik).then(function () {
      try { var u = new URL(location.href); u.searchParams.set('cik', cik); history.replaceState(null, '', u.pathname + u.search); } catch (e) {}
      if (scroll) $('deal').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    }).catch(function (e) {
      $('deal').classList.remove('is-waiting');
      $('deal-name').textContent = 'This offering is outside the public window';
      $('deal-meta').textContent = (e && e.message) || 'Older offerings are in the API with a free key.';
      $('deal-figures').replaceChildren(el('p', {}, [el('a', { href: '/account/', text: 'Get a free key' }), ' to read every offering, with the same evidence.']));
      $('deal-dates').textContent = ''; $('deal-uw').textContent = ''; $('deal-steps').textContent = ''; $('deal-actions').textContent = '';
    });
  }

  /* ---- stages and the table ---- */
  function stages(counts) {
    var nav = $('stages'); nav.textContent = '';
    var btn = function (key, name, n, hint) {
      var b = el('button', { type: 'button', 'aria-pressed': String(stage === key), title: hint }, [el('span', { class: 'st-n', text: String(n) }), el('span', { class: 'st-name', text: name })]);
      b.addEventListener('click', function () { stage = stage === key ? 'all' : key; table(); stages(counts); });
      return b;
    };
    var ol = el('ol', { class: 'st-flow' });
    STAGES.slice(0, 6).forEach(function (s) { ol.appendChild(el('li', {}, [btn(s[0], s[1], counts[s[0]] || 0, s[2])])); });
    nav.appendChild(ol);
    nav.appendChild(el('div', { class: 'st-side' }, [btn(STAGES[6][0], STAGES[6][1], counts.withdrawn || 0, STAGES[6][2])]));
  }
  function priceText(r) {
    var t = r.terms || {}, cur = t.currency || 'USD';
    if (t.price_final != null) return usd(t.price_final, cur);
    if (t.price_low != null && t.price_high != null) return usd(t.price_low, cur) + '–' + usd(t.price_high, cur).replace(/^\$/, '');
    return '—';
  }
  function table() {
    var hideSpac = $('no-spac').checked;
    var shown = rows.filter(function (r) { return (stage === 'all' || r.stage === stage) && !(hideSpac && r.blank_check); });
    var lock = $('lockups').checked;
    var w = window_ || {};
    var span = w.activity_days ? 'active in the last ' + w.activity_days + ' days' : '';
    $('pipe-summary').textContent = shown.length + ' compan' + (shown.length === 1 ? 'y' : 'ies') + (stage === 'all' ? '' : ' at ' + LABEL[stage]) + (lock ? ' with a lock-up ending in the next 90 days' : (span ? ' ' + span : '') + ', newest activity first') + '. Older offerings are in the API with a free key.';
    var head = el('tr', {}, ['Company', 'Stage reached', 'Last filing', 'Price', 'Proceeds', lock ? 'Lock-up ends' : null].filter(Boolean).map(function (h, i) { return el('th', { scope: 'col', class: (i >= 3 ? 'n' : '') + (i === 4 ? ' opt' : ''), text: h }); }));
    var tb = el('tbody');
    var more = $('pipe-more');
    more.hidden = everyRow || shown.length <= 25;
    more.textContent = 'Show all ' + shown.length;
    more.onclick = function () { everyRow = true; table(); };
    shown.slice(0, everyRow ? shown.length : 25).forEach(function (r) {
      var latest = r.milestones && r.milestones[r.stage], t = r.terms || {}, cik = String(parseInt(r.cik, 10));
      var open = el('button', { type: 'button', class: 'row-open', 'aria-label': 'Open the deal card for ' + r.name }, [r.name]);
      open.addEventListener('click', function () { choose(cik, true); });
      tb.appendChild(el('tr', { 'data-cik': cik }, [
        el('th', { scope: 'row' }, [open, r.ticker || t.ticker ? el('span', { class: 'muted', text: ' ' + (r.ticker || t.ticker) }) : null, r.blank_check ? el('span', { class: 'tag', text: 'blank check' }) : null]),
        el('td', {}, [LABEL[r.stage] || r.stage, latest ? el('span', { class: 'muted' }, [' · ', link(latest.form_type, latest.source_url), ' ' + day(latest.filing_date)]) : null]),
        el('td', { class: 'nw', text: day(r.last_activity) }),
        el('td', { class: 'n', text: priceText(r) }),
        el('td', { class: 'n opt', text: t.gross_proceeds != null ? usd(t.gross_proceeds, t.currency) : '—' }),
        lock ? el('td', { class: 'n' }, [t.lockup_expiry ? day(t.lockup_expiry) : '—', el('span', { class: 'tag', text: 'derived' })]) : null
      ]));
    });
    if (!shown.length) tb.appendChild(el('tr', {}, [el('td', { colspan: '6', class: 'muted', text: 'No company at this stage in the period shown.' })]));
    $('pipe-table').replaceChildren(el('caption', { class: 'vh', text: 'Companies going public' }), el('thead', {}, [head]), tb);
    markChosen();
  }
  function markChosen() { document.querySelectorAll('#pipe-table tr[data-cik]').forEach(function (tr) { tr.classList.toggle('is-chosen', tr.getAttribute('data-cik') === chosen); }); }
  function load() {
    var lock = $('lockups').checked;
    return json('/v1/public/ipos/pipeline' + (lock ? '?lockup_within_days=90' : '')).then(function (d) {
      rows = d.data || []; window_ = d.window || null;
      if (!lock) stages(d.counts || {});
      table();
      return d;
    }).catch(function () { $('stages').replaceChildren(el('p', { class: 'muted', text: 'The pipeline is unavailable right now.' })); });
  }
  $('no-spac').addEventListener('change', table);
  $('lockups').addEventListener('change', load);

  var want = new URLSearchParams(location.search).get('cik');
  if (want && /^\d{1,10}$/.test(want)) choose(want, false);
  load().then(function (d) {
    if (want && /^\d{1,10}$/.test(want)) return;
    // otherwise the largest priced deal in the period, by gross proceeds
    var pick = (d && d.data || []).filter(function (r) { return r.stage === 'priced' && r.terms && r.terms.price_final != null && !r.blank_check; })
      .sort(function (a, b) { return (b.terms.gross_proceeds || 0) - (a.terms.gross_proceeds || 0); })[0];
    if (pick) choose(String(parseInt(pick.cik, 10)), false);
  });
})();
