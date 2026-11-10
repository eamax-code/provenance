/* Gamification prototype: credits, levels, quests and achievements over the real public API.
   Progress is kept in this browser only; the reward amounts are placeholders. */
(function () {
  'use strict';
  var X = window.Poc, $ = X.$, el = X.el;
  X.switcher($('themes'));
  var AMZN = '0001018724', MSFT = '0000789019', KEY = 'poc-game';
  var LEVELS = [
    { k: 'V', name: 'Visitor', unlock: 'the demo: 10 questions a day, no key' },
    { k: 'R', name: 'Researcher', unlock: 'a free key: 25 questions a day, 10,000 API requests a month, 5 watches' },
    { k: 'A', name: 'Analyst', unlock: '+25 questions a day and 10 watches' },
    { k: 'B', name: 'Builder', unlock: '+5,000 API requests this month' },
    { k: 'I', name: 'Integrator', unlock: '20 watches and webhook delivery logs' }
  ];
  var QUESTS = [
    { id: 'ask', name: 'Ask a question', reward: 2 },
    { id: 'cite', name: 'Open a cited filing', reward: 2 },
    { id: 'compare', name: 'Compare two companies', reward: 2 },
    { id: 'watch', name: 'Watch a company', reward: 2 }
  ];
  var ACH = [
    { id: 'ok', m: '200', name: 'First 200', how: 'A successful request' },
    { id: 'overview', m: 'CO', name: 'Read a company', how: 'Call the overview endpoint' },
    { id: 'fixed', m: 'FX', name: 'Fixed an error', how: 'A 4xx, then a 200' },
    { id: 'listings', m: 'LS', name: 'Listings', how: 'Read the listings feed' },
    { id: 'code', m: '{}', name: 'From your code', how: 'Copy as curl or Python' },
    { id: 'asof', m: 'PT', name: 'Point in time', how: 'An as_of query; needs a key', locked: true },
    { id: 'page', m: 'PG', name: 'Paginated', how: 'Follow a cursor; needs a key', locked: true },
    { id: 'hook', m: 'WH', name: 'Webhook verified', how: 'At Integrator', locked: true }
  ];
  var BUILDER_NEEDS = 3;
  var fresh = function () { return { used: 0, bonus: 0, quests: {}, ach: {}, companies: [AMZN], month: 1284, errored: false }; };
  var S = fresh();
  try { S = Object.assign(fresh(), JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) {}
  var save = function () { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} };
  var mins = [], data = {};

  var questsDone = function () { return QUESTS.filter(function (q) { return S.quests[q.id]; }).length; };
  var achDone = function () { return ACH.filter(function (a) { return !a.locked && S.ach[a.id]; }).length; };
  var level = function () { var l = 1; if (questsDone() === QUESTS.length) { l = 2; if (achDone() >= BUILDER_NEEDS) l = 3; } return l; };
  var cap = function () { return 25 + (level() >= 2 ? 25 : 0) + S.bonus; };
  var left = function () { return Math.max(0, cap() - S.used); };
  var monthCap = function () { return 10000 + (level() >= 3 ? 5000 : 0); };

  function render() {
    var L = level(), lv = LEVELS[L], nx = LEVELS[L + 1];
    $('h-badge').textContent = lv.k; $('h-level').textContent = lv.name; $('t-lvl').textContent = lv.name;
    $('h-left').textContent = left() + ' questions left';
    var toNext = L === 1 ? questsDone() / QUESTS.length : L === 2 ? Math.min(1, achDone() / BUILDER_NEEDS) : 1;
    $('h-meter').style.setProperty('--v', Math.round(100 * toNext) + '%');
    var ld = $('ladder'); ld.textContent = '';
    LEVELS.forEach(function (x, i) { ld.appendChild(el('span', { class: 'step' + (i < L ? ' done' : i === L ? ' now' : '') }, [el('i'), x.name])); });
    var stepsLeft = L === 1 ? QUESTS.length - questsDone() : L === 2 ? Math.max(0, BUILDER_NEEDS - achDone()) : 0;
    $('lvl-next').textContent = nx ? stepsLeft + (stepsLeft === 1 ? ' step' : ' steps') + ' to ' + nx.name + (L === 2 ? ', in the playground' : '') : '';
    var ql = $('quests'); ql.textContent = '';
    QUESTS.forEach(function (q) { ql.appendChild(el('li', { class: 'quest' + (S.quests[q.id] ? ' done' : '') }, [el('span', { class: 'tick', 'aria-hidden': 'true', text: '✓' }), el('span', { class: 'nm', text: q.name }), el('span', { class: 'rw', text: (S.quests[q.id] ? 'got ' : '') + '+' + q.reward + ' questions' })])); });
    $('unlocks').textContent = '';
    $('unlocks').appendChild(el('span', {}, [nx ? el('b', { text: nx.name + ' unlocks ' }) : el('b', { text: 'Top level. ' }), nx ? nx.unlock + '.' : 'Thanks for building on Provenance.']));
    $('c-left').textContent = left(); $('c-left2').textContent = left(); $('c-cap').textContent = cap(); $('ring-n').textContent = left();
    $('ring').style.setProperty('--v', Math.round(100 * left() / cap()));
    $('plan-name').textContent = 'Free plan · ' + lv.name;
    $('ask-btn').disabled = !left();
    var cov = $('cover'); cov.textContent = '';
    var sectors = {};
    S.companies.forEach(function (c) { var d = data[c]; if (!d) return; cov.appendChild(el('span', { class: 'chip', text: d.company.ticker || d.company.display_name })); if (d.company.sic_description) sectors[d.company.sic_description] = 1; });
    Object.keys(sectors).forEach(function (s) { cov.appendChild(el('span', { class: 'chip accent', text: s.toLowerCase() })); });
    $('cov-n').textContent = S.companies.length + (S.companies.length === 1 ? ' company' : ' companies') + ', ' + Object.keys(sectors).length + (Object.keys(sectors).length === 1 ? ' industry' : ' industries');
    // playground
    var used = S.month, mc = monthCap();
    $('u-month').textContent = X.int(used) + ' of ' + X.int(mc); $('m-month').style.setProperty('--v', (100 * used / mc).toFixed(1) + '%');
    var day = new Date().getUTCDate(), pace = Math.round(used / day * 30);
    $('u-note').textContent = 'Day ' + day + ' of the month; at this pace about ' + X.int(pace) + ' requests. The minute allowance is 60.';
    var ag = $('ach'); ag.textContent = '';
    ACH.forEach(function (a) {
      var got = S.ach[a.id];
      ag.appendChild(el('div', { class: 'tile' + (got ? ' got' : '') + (a.locked ? ' locked' : '') + (got && a.id === S.lastAch ? ' pop' : ''), 'data-id': a.id }, [el('span', { class: 'm', 'aria-hidden': 'true', text: a.m }), el('b', { text: a.name }), el('span', { text: got ? 'Earned ' + X.date(got) : a.how })]));
    });
    $('ach-n').textContent = achDone() + ' of ' + ACH.filter(function (a) { return !a.locked; }).length + ' open';
    $('pg-next').textContent = '';
    $('pg-next').appendChild(el('span', {}, [el('b', { text: 'Builder' }), ' needs ' + BUILDER_NEEDS + ' achievements' + (L < 2 ? ' after Analyst' : '') + ' and unlocks ' + LEVELS[3].unlock + '.']));
    S.lastAch = null;
  }
  function minuteMeter() {
    var now = Date.now(); mins = mins.filter(function (t) { return now - t < 60000; });
    $('u-min').textContent = mins.length + ' of 60'; $('m-min').style.setProperty('--v', (100 * mins.length / 60).toFixed(1) + '%');
  }
  function resetIn() {
    var n = new Date(), mid = Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate() + 1), s = Math.floor((mid - n) / 1000);
    $('reset-in').textContent = Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm';
  }
  function levelCheck(before) {
    var after = level();
    if (after > before) X.toast(LEVELS[after].k, 'You are now ' + LEVELS[after].name, 'Unlocked ' + LEVELS[after].unlock + '.');
  }
  function quest(id) {
    if (S.quests[id]) return;
    var before = level(), q = QUESTS.filter(function (x) { return x.id === id; })[0];
    S.quests[id] = Date.now(); S.bonus += q.reward; save();
    X.toast('✓', q.name, '+' + q.reward + ' questions today. ' + (QUESTS.length - questsDone() ? (QUESTS.length - questsDone()) + ' more to Analyst.' : ''));
    levelCheck(before); render();
  }
  function achieve(id) {
    if (S.ach[id]) return;
    var before = level(), a = ACH.filter(function (x) { return x.id === id; })[0];
    S.ach[id] = new Date().toISOString(); S.lastAch = id; save();
    X.toast(a.m, 'Achievement: ' + a.name, a.how + '.');
    if (level() === before && before < 2 && achDone() >= BUILDER_NEEDS) X.toast('B', 'Builder is ready', 'It unlocks once you reach Analyst in chat.');
    levelCheck(before); render();
  }

  /* ---- chat ---- */
  var cite = function (n, url) { var a = X.link(String(n), url); if (a.tagName === 'A') a.addEventListener('click', function () { quest('cite'); }); return el('sup', {}, [a]); };
  var sources = function (list) {
    var p = el('p', { class: 'small muted' }, ['Sources: ']);
    list.forEach(function (s, i) { if (i) p.appendChild(document.createTextNode(' · ')); var a = X.link('[' + (i + 1) + '] ' + s[0], s[1]); if (a.tagName === 'A') a.addEventListener('click', function () { quest('cite'); }); p.appendChild(a); });
    return p;
  };
  var fig = function (d, m) { return d.key_figures.filter(function (k) { return k.metric === m; })[0]; };
  var ANSWERS = {
    revenue: function () {
      var d = data[AMZN], r = fig(d, 'revenue'), y = d.years, last = y[y.length - 1], prev = y[y.length - 2];
      return [el('p', {}, ['Amazon reported revenue of ' + X.money(r.value) + ' for ' + r.fiscal_label + ', up ' + X.pct(r.change_pct) + ' on the year before', cite(1, r.source_url), '. Operating margin ' + (last.operating_margin_pct >= prev.operating_margin_pct ? 'rose' : 'fell') + ' to ' + X.pct(last.operating_margin_pct) + ' from ' + X.pct(prev.operating_margin_pct), cite(2, last.sources.operating_income), '.']), sources([['10-K filed ' + X.date(r.filed_date), r.source_url], ['the same 10-K, operating income', last.sources.operating_income]])];
    },
    compare: function () {
      var a = data[AMZN], m = data[MSFT], ra = fig(a, 'revenue'), rm = fig(m, 'revenue'), la = a.years[a.years.length - 1], lm = m.years[m.years.length - 1];
      if (S.companies.indexOf(MSFT) < 0) S.companies.push(MSFT);
      return [el('p', {}, ['Amazon’s revenue was ' + X.money(ra.value) + ' in ' + ra.fiscal_label, cite(1, ra.source_url), '; Microsoft’s was ' + X.money(rm.value) + ' in ' + rm.fiscal_label, cite(2, rm.source_url), '. Microsoft keeps far more of each dollar: an operating margin of ' + X.pct(lm.operating_margin_pct) + ' against Amazon’s ' + X.pct(la.operating_margin_pct) + '.']), el('p', { class: 'small muted', text: 'Their fiscal years end in different months (' + a.company.fiscal_year_end_month + ' and ' + m.company.fiscal_year_end_month + '), so the years do not line up exactly.' }), sources([['Amazon 10-K filed ' + X.date(ra.filed_date), ra.source_url], ['Microsoft 10-K filed ' + X.date(rm.filed_date), rm.source_url]])];
    },
    leadership: function () {
      var d = data[AMZN], ch = d.leadership.changes[0];
      if (!ch) return [el('p', { text: 'No leadership change has been read from Amazon’s 8-K filings yet.' })];
      return [el('p', {}, ['Amazon’s latest leadership filing, an 8-K filed ' + X.date(ch.filing_date) + ', records ' + (ch.person || 'an officer') + (ch.role ? ' (' + ch.role + ')' : '') + ': ' + ch.change_label, cite(1, ch.source_url), '.']), ch.verified ? null : el('p', { class: 'small muted', text: 'Marked unverified: the reading has not yet been matched to the filing text.' }), sources([['8-K filed ' + X.date(ch.filing_date), ch.source_url]])].filter(Boolean);
    }
  };
  var SUGS = [['revenue', 'How did Amazon’s revenue change last year?'], ['compare', 'Compare Amazon with Microsoft'], ['leadership', 'Who joined Amazon’s board recently?']];
  function ask(kind, text) {
    if (!left()) { X.toast('0', 'No questions left today', 'Reach Analyst for +25 a day, or upgrade.'); return; }
    var before = level();
    S.used += 1; save();
    var msgs = $('msgs');
    msgs.appendChild(el('p', { class: 'q', text: text }));
    var body = ANSWERS[kind]();
    var after = el('div', { class: 'after' });
    if (!S.quests.watch) { var w = el('button', { class: 'btn small', type: 'button', text: 'Watch Amazon for new filings' }); w.addEventListener('click', function () { w.disabled = true; w.textContent = 'Watching Amazon'; quest('watch'); }); after.appendChild(w); }
    after.appendChild(el('a', { class: 'btn small', href: '/companies/' + AMZN + '#figure=revenue', text: 'Open the revenue chart' }));
    after.appendChild(el('span', { class: 'small muted', text: 'used 1 credit' }));
    msgs.appendChild(el('div', { class: 'a' }, body.concat([after])));
    msgs.lastChild.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    quest('ask'); if (kind === 'compare') quest('compare');
    levelCheck(before); render();
  }
  SUGS.forEach(function (s) { var b = el('button', { class: 'sug', type: 'button' }, [s[1], el('span', { class: 'cost', text: '1 credit' })]); b.addEventListener('click', function () { ask(s[0], s[1]); }); $('sugs').appendChild(b); });
  $('ask-form').addEventListener('submit', function (e) {
    e.preventDefault(); var t = $('ask').value.trim(); if (!t) return;
    var kind = /compar|microsoft|msft|versus|\bvs\b/i.test(t) ? 'compare' : /board|ceo|cfo|director|officer|leader|join/i.test(t) ? 'leadership' : 'revenue';
    $('ask').value = ''; ask(kind, t);
  });

  /* ---- playground ---- */
  var EPS = [['overview', '/v1/public/companies/{cik}/overview', 'Company overview: everything on the company page'], ['company', '/v1/public/companies/{cik}', 'Company with its filings and figures'], ['listings', '/v1/public/listings/events', 'New listings in Canada, the UK and the EU'], ['plans', '/v1/public/plans', 'Plans and their limits']];
  EPS.forEach(function (e) { $('ep').appendChild(el('option', { value: e[0], text: e[1] + ' · ' + e[2] })); });
  var url = function () { var e = EPS.filter(function (x) { return x[0] === $('ep').value; })[0]; return e[1].replace('{cik}', encodeURIComponent($('cik').value.trim())); };
  $('ep').addEventListener('change', function () { $('cik').disabled = url().indexOf('/companies/') < 0; });
  function paint(json) {
    var pre = $('json'); pre.textContent = '';
    var text = JSON.stringify(json, null, 2).split('\n'), cut = text.length > 90;
    (cut ? text.slice(0, 90).concat(['  … ' + (text.length - 90) + ' more lines']) : text).join('\n').split(/("(?:[^"\\]|\\.)*"(?:\s*:)?|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/).forEach(function (part) {
      if (!part) return;
      var cls = /^"[^]*":$/.test(part.replace(/\s+$/, '')) ? 'k' : part[0] === '"' ? 's' : /^-?\d/.test(part) ? 'd' : null;
      pre.appendChild(cls ? el('span', { class: cls, text: part }) : document.createTextNode(part));
    });
  }
  $('send').addEventListener('click', function () {
    var u = url(), t0 = performance.now(), btn = $('send');
    btn.disabled = true;
    fetch(u, { headers: { Accept: 'application/json' } }).then(function (r) {
      return r.text().then(function (txt) {
        var ms = Math.round(performance.now() - t0), body = null; try { body = JSON.parse(txt); } catch (e) {}
        S.month += 1; mins.push(Date.now()); minuteMeter();
        $('resp-meta').textContent = r.status + ' · ' + ms + ' ms · ' + (txt.length / 1024).toFixed(1) + ' KB';
        paint(body || txt);
        var hint = $('hint');
        if (r.ok) {
          hint.hidden = true;
          achieve('ok');
          if (S.errored) { S.errored = false; achieve('fixed'); }
          if (u.indexOf('/overview') > 0) achieve('overview');
          if (u.indexOf('/listings/') > 0) achieve('listings');
        } else {
          S.errored = true;
          var code = body && body.error && body.error.code;
          hint.hidden = false; hint.textContent = '';
          hint.appendChild(el('span', {}, [el('b', { text: r.status + (code ? ' ' + code : '') + '. ' }), r.status === 422 ? 'A CIK is up to ten digits. Try 0001018724 (Amazon) or 0000789019 (Microsoft).' : r.status === 404 ? 'That company is not in the public showcase; a free key opens every company.' : 'Check the request and send again.']));
        }
        save(); render();
      });
    }).catch(function () { $('resp-meta').textContent = 'network error'; }).then(function () { btn.disabled = false; });
  });
  function copy(text) {
    var done = function () { achieve('code'); };
    try { navigator.clipboard.writeText(text).then(done, done); } catch (e) { done(); }
  }
  $('copy-curl').addEventListener('click', function () { copy('curl -s "' + location.origin + url() + '"'); });
  $('copy-py').addEventListener('click', function () { copy('import httpx\n\nprint(httpx.get("' + location.origin + url() + '").json())'); });

  /* ---- views ---- */
  function show(pg) {
    $('v-chat').hidden = pg; $('v-pg').hidden = !pg;
    $('tab-chat').setAttribute('aria-selected', String(!pg)); $('tab-pg').setAttribute('aria-selected', String(pg));
    $('nav-chat').removeAttribute('aria-current'); $('nav-pg').removeAttribute('aria-current');
    $(pg ? 'nav-pg' : 'nav-chat').setAttribute('aria-current', 'page');
    try { history.replaceState(null, '', location.pathname + location.search + (pg ? '#playground' : '')); } catch (e) {}
  }
  $('tab-chat').addEventListener('click', function () { show(false); });
  $('tab-pg').addEventListener('click', function () { show(true); });
  $('reset').addEventListener('click', function () { S = fresh(); save(); $('msgs').querySelectorAll('.q, .a').forEach(function (n) { n.remove(); }); render(); X.toast('↺', 'Progress reset', 'Back to Researcher with 25 questions.'); });
  show(location.hash === '#playground');
  Promise.all([X.overview(AMZN), X.overview(MSFT)]).then(function (r) { data[AMZN] = r[0]; data[MSFT] = r[1]; render(); }).catch(function () { $('msgs').appendChild(el('p', { class: 'muted', text: 'The overview API is not answering; start the local server.' })); });
  render(); minuteMeter(); resetIn();
  setInterval(minuteMeter, 1000); setInterval(resetIn, 30000);
})();
