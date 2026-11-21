/* Coverage: every number from the data. /v1/public/coverage when this server has it, otherwise
   the live /v1/stats counts. Metrics are grouped by statement; ratios are marked derived. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] == null) return; if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var int = function (n) { return n == null ? '—' : Number(n).toLocaleString('en-US'); };
  var dur = function (s) { return s == null ? 'not measured yet' : s < 90 ? s + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : s < 172800 ? (s / 3600).toFixed(1) + ' hours' : Math.round(s / 86400) + ' days'; };
  var set = function (k, v) { document.querySelectorAll('[data-cov="' + k + '"]').forEach(function (n) { n.textContent = v; }); };
  var GROUPS = [
    ['Income statement', ['revenue', 'cost_of_revenue', 'gross_profit', 'r_and_d', 'sga', 'operating_income', 'interest_expense', 'net_interest_income', 'pretax_income', 'income_tax', 'net_income', 'eps_basic', 'eps_diluted', 'shares_basic_weighted', 'shares_diluted_weighted', 'd_and_a']],
    ['Balance sheet', ['cash_and_equivalents', 'current_assets', 'total_assets', 'current_liabilities', 'total_liabilities', 'long_term_debt', 'long_term_debt_current', 'stockholders_equity', 'retained_earnings']],
    ['Cash flow', ['operating_cash_flow', 'capex', 'dividends_paid', 'share_repurchases', 'sbc']],
    ['Cover page', ['shares_outstanding', 'public_float']],
    ['Ratios, derived here', ['gross_margin', 'operating_margin', 'net_margin', 'return_on_assets', 'return_on_equity', 'free_cash_flow', 'debt_to_equity', 'current_ratio', 'book_value_per_share']]
  ];
  var LABEL = { revenue: 'Revenue', cost_of_revenue: 'Cost of revenue', gross_profit: 'Gross profit', r_and_d: 'Research and development', sga: 'Selling, general and administrative', operating_income: 'Operating income', interest_expense: 'Interest expense', net_interest_income: 'Net interest income', pretax_income: 'Income before taxes', income_tax: 'Income tax', net_income: 'Net income', eps_basic: 'EPS, basic', eps_diluted: 'EPS, diluted', shares_basic_weighted: 'Weighted shares, basic', shares_diluted_weighted: 'Weighted shares, diluted', d_and_a: 'Depreciation and amortization', cash_and_equivalents: 'Cash and equivalents', current_assets: 'Current assets', total_assets: 'Total assets', current_liabilities: 'Current liabilities', total_liabilities: 'Total liabilities', long_term_debt: 'Long-term debt', long_term_debt_current: 'Long-term debt, current part', stockholders_equity: "Stockholders' equity", retained_earnings: 'Retained earnings', operating_cash_flow: 'Operating cash flow', capex: 'Capital expenditure', dividends_paid: 'Dividends paid', share_repurchases: 'Share repurchases', sbc: 'Stock-based compensation', shares_outstanding: 'Shares outstanding', public_float: 'Public float', gross_margin: 'Gross margin', operating_margin: 'Operating margin', net_margin: 'Net margin', return_on_assets: 'Return on assets', return_on_equity: 'Return on equity', free_cash_flow: 'Free cash flow', debt_to_equity: 'Debt to equity', current_ratio: 'Current ratio', book_value_per_share: 'Book value per share' };

  function metrics(byMetric) {
    // byMetric: {metric: {facts, quality_ok_pct, companies, earliest}} or {metric: count}
    var box = $('cov-metrics'); box.textContent = '';
    GROUPS.forEach(function (g) {
      var derived = /derived/.test(g[0]);
      var rows = g[1].map(function (m) {
        var v = byMetric[m], o = v && typeof v === 'object' ? v : { facts: v };
        var cells = [el('th', { scope: 'row', text: LABEL[m] || m })];
        if (derived) cells.push(el('td', { colspan: '3', class: 'muted', text: 'Worked out from two reported figures; inputs listed with every value' }));
        else {
          cells.push(el('td', { class: 'n', text: o.companies != null ? int(o.companies) : (o.facts != null ? int(o.facts) : 'not yet') }));
          cells.push(el('td', { class: 'n', text: o.quality_ok_pct != null ? o.quality_ok_pct.toFixed(1) + '%' : '—' }));
          cells.push(el('td', { class: 'n', text: o.earliest ? String(o.earliest).slice(0, 4) : '—' }));
        }
        return el('tr', {}, cells);
      });
      var anyCompanies = g[1].some(function (m) { var v = byMetric[m]; return v && typeof v === 'object' && v.companies != null; });
      var head = el('tr', {}, [el('th', { scope: 'col', text: g[0] })].concat(derived ? [el('th', { scope: 'col', colspan: '3', text: '' })] :
        [el('th', { scope: 'col', class: 'n', text: anyCompanies ? 'Companies' : 'Values' }), el('th', { scope: 'col', class: 'n', text: 'Quality ok' }), el('th', { scope: 'col', class: 'n', text: 'From' })]));
      box.appendChild(el('div', { class: 'tw' }, [el('table', { class: 'cov-table' }, [el('caption', { class: 'vh', text: g[0] }), el('thead', {}, [head]), el('tbody', {}, rows)])]));
    });
  }

  // a busy server can take a while to count; say so instead of looking stuck
  var slow = setTimeout(function () { var m = $('cov-metrics'); if (m && /Loading/.test(m.textContent)) m.firstChild.textContent = 'Still counting; the service is busy re-reading filings. This fills in when it finishes.'; }, 8000);
  var STATEMENT = { income: 'Income statement', balance: 'Balance sheet', cash_flow: 'Cash flow', cover: 'Cover page' };
  var OUT = [
    [/annual|quarterly/i, 'Financial statements and cover-page facts', '/docs'],
    [/8-K|current/i, 'Events by item: results, restatements, auditor changes, mergers, officer changes', '/developers/#events'],
    [/insider/i, 'Insiders, their roles and their trades', '/app/'],
    [/13D|13G|holder/i, 'Holders above 5%', '/app/'],
    [/registration|prospectus/i, 'IPO stages and deal terms, with their sentences', '/ipos/'],
    [/exhibit 21|subsidiar/i, 'Subsidiaries, new and gone year on year', '/app/']
  ];
  function fromCoverage(c) {
    var u = c.universe || {}, f = c.freshness || {};
    set('filers', int(u.filers)); set('with_facts', int(u.with_facts)); set('facts', int(c.facts_total));
    set('latency', dur(f.acceptance_to_here_median_seconds));
    set('venues', int(c.listings && c.listings.venues)); set('instruments', int(c.listings && c.listings.instruments));
    var box = $('cov-metrics'); box.textContent = '';
    var by = {}; (c.metrics || []).forEach(function (m) { (by[m.statement] = by[m.statement] || []).push(m); });
    Object.keys(STATEMENT).forEach(function (k) {
      var rows = by[k]; if (!rows || !rows.length) return;
      var head = el('tr', {}, [el('th', { scope: 'col', text: STATEMENT[k] }), el('th', { scope: 'col', class: 'n', text: 'Companies' }), el('th', { scope: 'col', class: 'n', text: 'Quality ok' }), el('th', { scope: 'col', class: 'n', text: 'From' })]);
      var body = rows.map(function (m) {
        return el('tr', {}, [el('th', { scope: 'row', text: m.label }), el('td', { class: 'n', text: int(m.companies) }),
          el('td', { class: 'n', title: m.ambiguous_pct != null ? m.ambiguous_pct.toFixed(1) + '% have two tags in one filing (ambiguous)' : null, text: m.ok_pct != null ? m.ok_pct.toFixed(1) + '%' : '—' }),
          el('td', { class: 'n', text: m.earliest_year && m.earliest_year >= 1993 ? String(m.earliest_year) : '—' })]);
      });
      box.appendChild(el('div', { class: 'tw' }, [el('table', { class: 'cov-table' }, [el('caption', { class: 'vh', text: STATEMENT[k] }), el('thead', {}, [head]), el('tbody', {}, body)])]));
    });
    if ((c.ratios || []).length) {
      var rh = el('tr', {}, [el('th', { scope: 'col', text: 'Ratios, derived here' }), el('th', { scope: 'col', colspan: '3', text: 'Worked out as' })]);
      var rb = c.ratios.map(function (r) { return el('tr', {}, [el('th', { scope: 'row', text: r.label }), el('td', { colspan: '3', class: 'muted', text: r.formula })]); });
      box.appendChild(el('div', { class: 'tw' }, [el('table', { class: 'cov-table' }, [el('caption', { class: 'vh', text: 'Ratios' }), el('thead', {}, [rh]), el('tbody', {}, rb)])]));
    }
    if ((c.forms || []).length) {
      var tb = document.querySelector('#cov-forms-body');
      if (tb) tb.replaceChildren.apply(tb, c.forms.map(function (f) {
        var o = OUT.filter(function (x) { return x[0].test(f.label + ' ' + (f.forms || []).join(' ')); })[0];
        return el('tr', {}, [el('th', { scope: 'row' }, [f.label, el('br'), el('span', { class: 'muted small', text: (f.forms || []).join(', ') })]),
          el('td', { class: 'n', text: int(f.filings) }),
          el('td', {}, o ? [o[2] ? el('a', { href: o[2], text: o[1] }) : o[1]] : ['Listed with its form and acceptance time'])]);
      }));
      var th = document.querySelector('#cov-forms-head'); if (th) th.replaceChildren(el('tr', {}, [el('th', { scope: 'col', text: 'Forms' }), el('th', { scope: 'col', class: 'n', text: 'Filings loaded' }), el('th', { scope: 'col', text: 'What comes out' })]));
    }
    $('cov-note').textContent = (c.notes || []).join(' ') + ' Mapping version ' + (c.mapping_version || '') + ', counted ' + String(c.generated_at || '').slice(0, 10) + '.';
  }
  fetch('/v1/public/coverage', { headers: { Accept: 'application/json' } }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (c) { clearTimeout(slow); fromCoverage(c); })
    .catch(function () {
      // until the coverage endpoint is on this server: the live stats
      fetch('/v1/stats', { headers: { Accept: 'application/json' } }).then(function (r) { return r.json(); }).then(function (d) {
        var q = d.quality_snapshot, lat = q && q.latency;
        set('filers', int(d.companies.known)); set('with_facts', '—'); set('facts', int(d.facts.total));
        set('latency', dur(lat && lat.accept_to_detect_p50_seconds));
        set('venues', int(d.listings && d.listings.venues)); set('instruments', int(d.listings && d.listings.instruments));
        clearTimeout(slow); metrics(d.facts.by_metric || {});
        $('cov-note').textContent = 'Counts from the live service statistics, mapping version ' + (d.mapping_version || '') + '. Data from SEC EDGAR, ESMA and FCA FIRDS and GLEIF; Provenance is independent and not affiliated with them. Not investment advice.';
      }).catch(function () { $('cov-metrics').replaceChildren(el('p', { class: 'muted', text: 'Coverage numbers are unavailable right now.' })); });
    });
})();
