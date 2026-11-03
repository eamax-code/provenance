(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var log = $('chat-log'), form = $('chat-form'), input = $('chat-input');
  var state = { cik: null };

  try { var saved = localStorage.getItem('prov_key'); if (saved) $('chat-key').value = saved; } catch (e) { /* storage blocked */ }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function link(href, text) {
    var a = el('a', null, text);
    if (/^https:\/\//.test(href)) { a.href = href; a.target = '_blank'; a.rel = 'noopener'; }
    return a;
  }

  // Render model text safely: plain text, with [n] turned into links to the citation.
  function renderAnswer(text, citations) {
    var frag = document.createDocumentFragment();
    var byN = {};
    (citations || []).forEach(function (c) { byN[c.n] = c; });
    text.split(/(\[\d{1,3}\])/).forEach(function (part) {
      var m = /^\[(\d{1,3})\]$/.exec(part);
      if (m && byN[m[1]]) {
        var a = link(byN[m[1]].url, '[' + m[1] + ']');
        a.className = 'cite'; a.title = byN[m[1]].label;
        frag.appendChild(a);
      } else {
        part.split('\n').forEach(function (line, i) {
          if (i) frag.appendChild(document.createElement('br'));
          frag.appendChild(document.createTextNode(line));
        });
      }
    });
    return frag;
  }

  function fmtPct(p) { return p == null ? '' : (p > 0 ? '+' : '') + p.toFixed(1) + '%'; }

  function renderSide(body) {
    var side = $('chat-side');
    if (!body.company) { side.hidden = true; return; }
    side.hidden = false;
    var c = body.company;
    $('side-name').textContent = c.legal_name;
    $('side-meta').textContent = [c.ticker, c.exchange, 'CIK ' + c.cik, c.sic_description].filter(Boolean).join(' · ');
    var cov = body.brief.coverage || {};
    $('side-coverage').textContent = cov.filings
      ? 'Loaded here: ' + cov.filings + ' filings, ' + cov.first_filed + ' to ' + cov.last_filed + (cov.stale ? ' (newer filings not loaded)' : '')
      : 'No filings loaded for this company.';
    var m = $('side-metrics'); m.textContent = '';
    (body.brief.metrics || []).forEach(function (x) {
      var row = el('div', 'metric');
      var left = el('span'); left.appendChild(link(x.source_url, x.label));
      left.appendChild(el('span', 'muted small', ' FY ' + x.period_end.slice(0, 4)));
      var right = el('span', null, x.display + ' ');
      if (x.growth_pct != null) right.appendChild(el('span', x.growth_pct >= 0 ? 'up' : 'down', fmtPct(x.growth_pct)));
      row.appendChild(left); row.appendChild(right); m.appendChild(row);
    });
    if (!m.childNodes.length) m.appendChild(el('p', 'muted small', 'No annual facts loaded.'));
    var lead = $('side-leaders'); lead.textContent = '';
    (body.brief.leadership_filings || []).forEach(function (f) {
      var li = el('li'); li.appendChild(link(f.source_url, f.form_type + ' · ' + f.filing_date)); lead.appendChild(li);
    });
    if (!lead.childNodes.length) {
      var why = !cov.eight_ks_since ? 'No 8-Ks loaded since ' + cov.since + ', so unknown.'
        : cov.eight_ks_with_items < cov.eight_ks_since ? 'Some loaded 8-Ks lack item codes, so unknown.'
        : 'None among ' + cov.eight_ks_since + ' 8-Ks loaded since ' + cov.since + '.';
      lead.appendChild(el('li', 'muted', why));
    }
    var fl = $('side-filings'); fl.textContent = '';
    (body.brief.filings || []).forEach(function (f) {
      var li = el('li');
      li.appendChild(link(f.source_url, f.form_type + ' · ' + f.filing_date));
      if (f.items && f.items.length) li.appendChild(el('span', 'muted small', ' items ' + f.items.map(function (i) { return i.code; }).join(', ')));
      fl.appendChild(li);
    });
  }

  function addMsg(cls, content) {
    var empty = $('chat-empty'); if (empty) empty.remove();
    var m = el('div', 'msg ' + cls);
    if (typeof content === 'string') m.textContent = content; else m.appendChild(content);
    log.appendChild(m); m.scrollIntoView({ block: 'nearest' });
    return m;
  }

  function ask(q) {
    addMsg('user', q);
    var pending = addMsg('bot typing', 'Reading the filings…');
    var payload = { message: q };
    if (state.cik) payload.cik = state.cik; // used only when the question names no company
    var asof = $('chat-asof').value; if (asof) payload.as_of = asof;
    $('chat-send').disabled = true;
    fetch('/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': $('chat-key').value.trim() || 'demo' },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
      .then(function (res) {
        pending.remove();
        var b = res.body;
        if (res.status !== 200) { addMsg('bot', (b.error && b.error.message) || ('Error ' + res.status)); return; }
        if (!b.company) {
          var f = document.createDocumentFragment();
          f.appendChild(document.createTextNode((b.notes || [])[0] || 'Which company?'));
          (b.suggestions || []).forEach(function (s) {
            var chip = el('button', 'chip', s.legal_name + (s.ticker ? ' (' + s.ticker + ')' : ''));
            chip.type = 'button'; chip.onclick = function () { state.cik = s.cik; ask(q + ' ' + (s.ticker || s.legal_name)); };
            f.appendChild(chip);
          });
          addMsg('bot', f); return;
        }
        state.cik = b.company.cik;
        renderSide(b);
        var out = document.createDocumentFragment();
        if (b.answer) out.appendChild(renderAnswer(b.answer, b.citations));
        else out.appendChild(el('p', 'muted', 'The language model is not available right now; the data for ' + b.company.legal_name + ' is shown on the right.'));
        if (b.answer && b.checks) {
          var ok = b.checks.grounded;
          var msg = ok ? 'Numbers and citations checked against the SEC data shown.' :
            'Check carefully: ' + [b.checks.unverified_numbers && b.checks.unverified_numbers.length ? 'numbers not found in the data: ' + b.checks.unverified_numbers.join(', ') : '',
              b.checks.unknown_citations && b.checks.unknown_citations.length ? 'unknown citations: ' + b.checks.unknown_citations.join(', ') : '',
              b.checks.bare_citation_lines && b.checks.bare_citation_lines.length ? 'citations not attached to any statement' : '',
              !(b.checks.citations_used || []).length ? 'no citations given' : ''].filter(Boolean).join('; ');
          out.appendChild(el('div', 'checks ' + (ok ? 'ok' : 'warn'), msg));
        }
        var when = b.brief.as_of ? 'as of ' + b.brief.as_of : 'latest data';
        if (b.answered_by === 'data') out.appendChild(el('div', 'model', 'Answered directly from the SEC data loaded here · ' + when));
        else if (b.model) out.appendChild(el('div', 'model', 'Written by ' + b.model + ' (local) · ' + when));
        (b.notes || []).slice(1).forEach(function (n) { out.appendChild(el('div', 'model', n)); });
        addMsg('bot', out);
      })
      .catch(function () { pending.remove(); addMsg('bot', 'Network error. Try again.'); })
      .finally(function () { $('chat-send').disabled = false; });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value.trim(); if (!q) return;
    input.value = ''; ask(q);
  });
  document.querySelectorAll('.chip[data-q]').forEach(function (b) {
    b.addEventListener('click', function () { ask(b.getAttribute('data-q')); });
  });
  var qs = new URLSearchParams(location.search).get('q');
  if (qs) ask(qs.slice(0, 500));
})();
