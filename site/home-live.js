/* Home page, live parts: one company's latest revenue with its filing record, and the newest
   EDGAR registrations and 8-K events. Stored data only; every link goes to the filing on sec.gov.
   Without script the page keeps the figure built into it and the strip says it is loading. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var ARCHIVE = /^https:\/\/www\.sec\.gov\/Archives\//;
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var day = function (iso, withYear) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    if (!m) return iso || '';
    return +m[3] + ' ' + MONTHS[+m[2] - 1] + (withYear === false ? '' : ' ' + m[1]);
  };
  var money = function (v, unit) {
    if (v == null) return 'not reported';
    var s = Math.abs(v).toLocaleString('en-US');
    return (v < 0 ? '−' : '') + (unit === 'USD' ? '$' + s : s + ' ' + (unit || ''));
  };
  var node = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var json = function (url) { return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); };

  /* company count from the shell's live stats */
  document.addEventListener('shell:stats', function (e) {
    var d = e.detail; if (!d || !d.companies || !d.companies.ingested) return;
    document.querySelectorAll('[data-live-stat="companies"]').forEach(function (el) { el.textContent = d.companies.ingested.toLocaleString('en-US') + ' US public companies'; });
  });

  /* ---- the figure and its record ---- */
  var pick = $('live-pick'), card = $('live-record'), cache = {};
  function row(field, label, value) {
    return node('div', { class: 'rec-row', 'data-field': field }, [node('dt', { text: label }), node('dd', {}, value)]);
  }
  function tagWords(tag) {
    // break long XBRL tags between words so they wrap inside the card
    var out = [];
    String(tag || '').split(/(?=[A-Z][a-z])/).forEach(function (part, i) { if (i) out.push(node('wbr')); out.push(part); });
    return out;
  }
  function paint(bundle, ticker) {
    var m = (bundle.metrics || []).filter(function (x) { return x.metric === 'revenue'; })[0];
    var facts = m && m.facts ? m.facts.slice() : [];
    facts.sort(function (a, b) { return a.period_end < b.period_end ? 1 : -1; });
    var f = facts[0], c = bundle.company || {};
    $('live-name').textContent = (c.legal_name || '').toUpperCase() + (ticker ? ' · ' + ticker : '');
    if (!f) {
      $('live-value').textContent = 'not reported';
      $('live-what').textContent = 'No annual revenue is mapped for this company yet.';
      $('live-quality').hidden = true;
      $('live-rows').replaceChildren();
      return;
    }
    var label = f.period_label || (f.period_class === 'annual' ? 'FY' + (f.period_fiscal_year || f.fiscal_year) : (f.fiscal_period || '') + ' ' + (f.period_fiscal_year || f.fiscal_year));
    var q = f.quality_status || 'ok', chip = $('live-quality');
    chip.hidden = false; chip.textContent = 'quality ' + q.replace(/_/g, ' '); chip.classList.toggle('is-note', q !== 'ok');
    $('live-value').textContent = money(f.value, f.unit);
    var short = function (v) { var a = Math.abs(v); return a >= 1e9 ? '$' + (v / 1e9).toFixed(1) + ' billion' : a >= 1e6 ? '$' + (v / 1e6).toFixed(1) + ' million' : null; };
    $('live-what').textContent = 'Revenue, ' + (f.unit || '') + ', ' + label + (f.unit === 'USD' && short(f.value) ? ' · ' + short(f.value) : '');
    var link = ARCHIVE.test(f.source_url || '') ? node('a', { class: 'ui-link', href: f.source_url, target: '_blank', rel: 'noopener', text: 'open on sec.gov' }) : null;
    $('live-rows').replaceChildren(
      row('filing', 'Filing', [f.form_type + ' filed ' + day(f.filed_date) + (link ? ' · ' : ''), link]),
      row('accession', 'Accession', [f.accession_number || '']),
      row('tag', 'XBRL tag', tagWords((f.source_taxonomy ? f.source_taxonomy + ':' : '') + (f.source_tag || ''))),
      row('period', 'Fiscal period', [label + ', ' + day(f.period_start) + ' to ' + day(f.period_end)]),
      row('derived', 'Status', [f.derived ? 'Derived by Provenance, not filed as such' : 'Reported as filed']),
      row('mapping', 'Mapping', ['version ' + (f.mapping_version || bundle.mapping_version || '')])
    );
    var cik = String(parseInt(c.cik || bundle.cik, 10));
    $('live-call').textContent = 'curl "' + location.origin + '/v1/companies/' + cik + '/facts?metric=revenue&limit=1" -H "X-API-Key: demo"';
  }
  function choose(btn) {
    pick.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
    var cik = btn.getAttribute('data-cik'), ticker = btn.textContent.trim();
    card.classList.add('is-loading');
    (cache[cik] || (cache[cik] = json('/v1/public/companies/' + cik)))
      .then(function (b) { paint(b, ticker); })
      .catch(function () { delete cache[cik]; $('live-what').textContent = 'Live data is unavailable right now; this is the figure built into the page.'; })
      .then(function () { card.classList.remove('is-loading'); });
  }
  if (pick && card) {
    pick.addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) choose(b); });
    choose(pick.querySelector('[aria-pressed="true"]') || pick.querySelector('button'));
  }

  /* ---- live from EDGAR ---- */
  function entry(r, what) {
    var name = r.company_name || ('CIK ' + r.cik);
    var who = node('span', { class: 'who' }, [node('a', { href: '/companies/' + parseInt(r.cik, 10), text: name }), r.ticker ? node('small', { text: r.ticker }) : null]);
    var when = node('span', { class: 'when' }, [ARCHIVE.test(r.filing_url || '') ? node('a', { href: r.filing_url, target: '_blank', rel: 'noopener', text: r.form_type + ', ' + day(r.date, false) }) : r.form_type + ', ' + day(r.date, false)]);
    return node('li', {}, [who, node('span', { class: 'what', text: what }), when]);
  }
  function list(id, url, label, empty) {
    var box = $(id); if (!box) return;
    json(url).then(function (d) {
      var rows = (d.data || []).map(function (r) { return entry(r, label(r)); });
      box.replaceChildren.apply(box, rows.length ? rows : [node('li', { class: 'edgar-empty', text: empty })]);
    }).catch(function () {
      box.replaceChildren(node('li', { class: 'edgar-empty', text: 'The live list is unavailable right now.' }));
    });
  }
  list('edgar-ipos', '/v1/public/ipos?limit=5', function (r) { return r.stage_label + (r.blank_check ? ' (blank check)' : ''); }, 'No registrations in the last 30 days.');
  list('edgar-events', '/v1/public/events?limit=5', function (r) { return r.short_label; }, 'No 8-K events in the last 14 days.');

  /* ---- pricing: every number from site/plans.json, the copy of the one plan table ---- */
  var tiers = $('tiers');
  if (tiers) json('/plans.json').then(function (d) {
    var plans = d.data || [];
    var int = function (n) { return n == null ? 'custom' : Number(n).toLocaleString('en-US'); };
    var yes = function (v) { return v ? 'Yes' : 'No'; };
    var forWhom = function (a) { return a ? 'For ' + (/^[A-Z]{2}/.test(a) ? a : a.charAt(0).toLowerCase() + a.slice(1)) + '.' : ''; };
    tiers.replaceChildren.apply(tiers, plans.map(function (p) {
      var paid = p.price_usd_per_month > 0, custom = p.price_usd_per_month == null;
      var cta = p.name === 'free' ? node('a', { class: 'button quiet', href: '/account/', text: 'Get a free key' })
        : node('a', { class: 'button' + (p.featured ? '' : ' quiet'), href: '/contact/?plan=' + encodeURIComponent(p.name), text: custom ? 'Talk to us' : 'Ask for ' + p.label });
      return node('article', { class: 'tier' + (p.featured ? ' is-featured' : ''), 'aria-labelledby': 'tier-' + p.name }, [
        node('h3', { id: 'tier-' + p.name, text: p.label }),
        node('div', {}, [
          node('p', { class: 'tier-price' + ((p.price_display || '').length > 5 ? ' is-long' : '') }, [node('b', { text: p.price_display || '' }), node('span', { text: custom ? 'a month, yearly contract' : paid ? 'a month' : 'for ever' })]),
          node('p', { class: 'tier-year', text: paid && p.annual_price_usd_per_month ? '$' + p.annual_price_usd_per_month + ' a month, billed yearly' : (custom ? 'Priced with you' : 'No card needed') }),
          p.featured && p.commercial_use ? node('p', { class: 'tier-badge', text: 'Commercial use included' }) : null
        ]),
        node('p', { class: 'tier-for', text: forWhom(p.audience) }),
        node('ul', {}, (p.features || []).map(function (f) { return node('li', { text: f }); })),
        cta
      ]);
    }));
    var ROWS = [
      ['Use', function (p) { return p.use || ''; }],
      ['Requests a minute', function (p) { return int(p.rate_limit_per_minute); }],
      ['Requests a month', function (p) { return int(p.monthly_request_quota); }],
      ['Watched companies', function (p) { return int(p.max_watches); }],
      ['Live event streams', function (p) { return int(p.max_event_streams); }],
      ['Rows per export', function (p) { return int(p.max_export_rows); }],
      ['Chat questions a day', function (p) { return int(p.chat_questions_per_day); }],
      ['Forecasts', function (p) { return yes(p.forecasts); }],
      ['Keys', function (p) { return int(p.keys); }],
      ['Support', function (p) { return p.support || ''; }]
    ];
    var feat = function (p) { return p.featured ? 'is-featured' : ''; };
    $('compare-head').replaceChildren(node('tr', {}, [node('th', { scope: 'col', text: 'Limit' })].concat(plans.map(function (p) { return node('th', { scope: 'col', class: feat(p), text: p.label }); }))));
    $('compare-body').replaceChildren.apply($('compare-body'), ROWS.map(function (r) {
      return node('tr', {}, [node('th', { scope: 'row', text: r[0] })].concat(plans.map(function (p) { return node('td', { class: feat(p), text: r[1](p) }); })));
    }));
    $('compare').hidden = false;
    // the watch-list slider runs up to the largest self-serve plan, with its marks from the same table
    var by = {}; plans.forEach(function (p) { by[p.name] = p; });
    var range = $('follow'), ticks = document.querySelectorAll('#watch .ticks span');
    if (range && by.team && by.builder && ticks.length === 3) {
      range.max = by.team.max_watches;
      ticks[1].textContent = 'Builder ' + int(by.builder.max_watches); ticks[2].textContent = 'Team ' + int(by.team.max_watches);
    }
  }).catch(function () {
    tiers.replaceChildren(node('p', { class: 'fine' }, ['The plans could not load. ', node('a', { href: '/developers/#limits', text: 'See plans and limits' })]));
  });
})();
