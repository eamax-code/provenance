(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var body = document.body;
  var thread = $('cx-thread'), input = $('cx-input'), form = $('cx-form'), send = $('cx-send');
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var DEMO = 'demo';
  var state = { key: DEMO, connected: false, sessionId: null, cik: null, busy: false, controller: null };

  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function sstore(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } }
  function sload(k) { try { return JSON.parse(sessionStorage.getItem(k) || 'null'); } catch (e) { return null; } }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svg(path) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
    s.innerHTML = path; // static markup defined in this file only
    return s;
  }
  function link(href, text, cls) {
    var a = el('a', cls, text);
    if (/^https:\/\//.test(href || '')) { a.href = href; a.target = '_blank'; a.rel = 'noopener'; }
    return a;
  }
  // Runs a DOM update inside a view transition; resolves once the update has been applied.
  function transition(fn) {
    if (document.startViewTransition && !reduced) return document.startViewTransition(fn).updateCallbackDone;
    fn(); return Promise.resolve();
  }
  // SEC names are often upper case ("MICROSOFT CORP"); show them in title case.
  function displayName(n) {
    if (!n || n !== n.toUpperCase()) return n || '';
    return n.toLowerCase().replace(/\b([a-z])/g, function (m) { return m.toUpperCase(); })
      .replace(/\b(Inc|Corp|Co|Ltd|Plc|Llc|Lp)\b/g, function (m) { return m === 'Llc' || m === 'Plc' ? m.toUpperCase() : m; });
  }

  // ---- text rendering: paragraphs, bullet lists and [n] citation pills, all as text nodes ----
  function inline(text, byN, parent) {
    text.split(/(\[\d{1,3}\])/).forEach(function (part) {
      var m = /^\[(\d{1,3})\]$/.exec(part);
      if (m && byN[m[1]]) {
        var a = link(byN[m[1]].url, m[1], 'cx-cite'); a.title = byN[m[1]].label; parent.appendChild(a);
      } else if (part) parent.appendChild(document.createTextNode(part));
    });
  }
  function renderText(text, citations) {
    var byN = {}; (citations || []).forEach(function (c) { byN[c.n] = c; });
    var frag = document.createDocumentFragment(), list = null;
    text.split('\n').forEach(function (line) {
      var bullet = /^\s*(?:[•\-*]|\d+\.)\s+(.*)$/.exec(line);
      if (bullet) {
        if (!list) { list = el('ul'); frag.appendChild(list); }
        var li = el('li'); inline(bullet[1], byN, li); list.appendChild(li);
      } else {
        list = null;
        if (line.trim()) { var p = el('p'); inline(line, byN, p); frag.appendChild(p); }
      }
    });
    return frag;
  }
  // Reveal text progressively, like a streamed answer. Finishes in about 1.5 s whatever the length.
  function stream(target, text, citations, done) {
    if (reduced) { target.appendChild(renderText(text, citations)); done(); return; }
    var words = text.split(/(\s+)/), i = 0, step = Math.max(2, Math.ceil(words.length / 90));
    (function tick() {
      i = Math.min(words.length, i + step);
      target.textContent = '';
      target.appendChild(renderText(words.slice(0, i).join(''), citations));
      keepScrolled();
      if (i < words.length) requestAnimationFrame(tick); else done();
    })();
  }
  function keepScrolled(force) {
    var near = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 160;
    if (force || near) thread.scrollTop = thread.scrollHeight;
  }

  // ---- leadership answers as cards with the filing's own sentence ----
  var TAGS = {
    appointment: ['Joined', 'in'], election: ['Elected', 'in'], role_change: ['New role', 'in'],
    departure: ['Leaving', 'out'], retirement: ['Retiring', 'out'],
    not_standing_for_reelection: ['Not standing again', 'out'], compensation: ['Pay', 'pay'], other: ['Other', '']
  };
  function changeCard(f, c, byN, delay) {
    var card = el('div', 'cx-change'); card.style.animationDelay = delay + 's';
    var top = el('div', 'cx-change-top');
    var tag = TAGS[c.change] || TAGS.other;
    top.appendChild(el('span', 'cx-tag ' + tag[1], tag[0]));
    top.appendChild(el('span', 'cx-change-date', 'Filed ' + f.filing_date));
    if (!c.verified) top.appendChild(el('span', 'cx-unverified', 'Unverified'));
    card.appendChild(top);
    var who = el('div'); who.appendChild(el('span', 'cx-change-who', c.person || 'Company-wide'));
    if (c.role) { who.appendChild(document.createTextNode(' ')); who.appendChild(el('span', 'cx-change-role', c.role)); }
    card.appendChild(who);
    var facts = [];
    if (c.what) facts.push(c.what.charAt(0).toUpperCase() + c.what.slice(1));
    if (c.effective && (c.what || '').toLowerCase().indexOf(c.effective.toLowerCase().replace(/^the /, '')) < 0) facts.push('Effective ' + c.effective);
    if (c.reason) facts.push('Reason: ' + c.reason);
    if (c.successor) facts.push((/^(appointment|election|role_change)$/.test(c.change) ? 'Replaces ' : 'Successor: ') + c.successor);
    if (!facts.length) facts.push(c.change_label);
    card.appendChild(el('div', 'cx-change-text', facts.join(' · ')));
    if (c.evidence) {
      var d = el('details'), s = el('summary', null, 'From the filing');
      d.appendChild(s);
      var q = el('blockquote', null, c.evidence); d.appendChild(q);
      var src = el('div', 'cx-note'); src.appendChild(document.createTextNode('Source: '));
      inline('8-K filed ' + f.filing_date + ' [' + f.citation + ']', byN, src); d.appendChild(src);
      card.appendChild(d);
    }
    return card;
  }
  function renderLeadership(target, reply) {
    var byN = {}; (reply.citations || []).forEach(function (c) { byN[c.n] = c; });
    var lines = (reply.answer || '').split('\n');
    target.appendChild(renderText(lines[0], reply.citations));
    var box = el('div', 'cx-changes'), k = 0;
    reply.brief.leadership_filings.forEach(function (f) {
      if (f.changes && f.changes.length) {
        f.changes.forEach(function (c) { box.appendChild(changeCard(f, c, byN, (k++) * 0.06)); });
      } else {
        var card = el('div', 'cx-change'); card.style.animationDelay = (k++) * 0.06 + 's';
        var top = el('div', 'cx-change-top');
        top.appendChild(el('span', 'cx-tag', f.reading === 'ok' ? 'No named change' : 'Not read yet'));
        top.appendChild(el('span', 'cx-change-date', 'Filed ' + f.filing_date));
        card.appendChild(top);
        var t = el('div', 'cx-change-text');
        inline((f.reading === 'ok' ? 'The item names no individual director or officer change (often a pay plan or arrangement). ' : 'This filing has not been read yet. ') + '[' + f.citation + ']', byN, t);
        card.appendChild(t);
        box.appendChild(card);
      }
    });
    target.appendChild(box);
    var foot = lines.filter(function (l) { return l && !/^\s*•/.test(l); }).slice(1).join(' ');
    if (foot) target.appendChild(el('p', 'cx-note', foot));
  }
  function isLeadership(reply) {
    return reply.answered_by === 'data' && reply.brief && (reply.brief.leadership_filings || []).length > 0;
  }

  // ---- messages ----
  function addUser(q) {
    var m = el('div', 'cx-msg user'); m.appendChild(el('div', 'cx-bubble', q));
    thread.appendChild(m); keepScrolled(true);
  }
  function addBot() {
    var m = el('div', 'cx-msg bot thinking');
    m.appendChild(el('div', 'cx-mark'));
    var b = el('div', 'cx-body'); m.appendChild(b);
    thread.appendChild(m); keepScrolled(true);
    return { msg: m, body: b };
  }
  function setStatus(bot, steps) {
    var i = 0, row = el('div', 'cx-status'), dots = el('span', 'cx-dots');
    dots.appendChild(el('i')); dots.appendChild(el('i')); dots.appendChild(el('i'));
    var txt = el('span', 'cx-status-text', steps[0]);
    row.appendChild(dots); row.appendChild(txt); bot.body.appendChild(row);
    var t = setInterval(function () {
      i = Math.min(steps.length - 1, i + 1);
      var n = el('span', 'cx-status-text', steps[i]); row.replaceChild(n, row.lastChild); txt = n;
    }, 1700);
    return function () { clearInterval(t); row.remove(); };
  }
  function meta(bot, reply) {
    var row = el('div', 'cx-meta');
    var c = reply.checks || {};
    if (reply.answer) {
      var ok = reply.answered_by === 'data' || c.grounded;
      var problems = [];
      if ((c.unverified_numbers || []).length) problems.push('numbers not in the data: ' + c.unverified_numbers.join(', '));
      if ((c.unknown_citations || []).length) problems.push('unknown citations');
      if ((c.bare_citation_lines || []).length) problems.push('loose citations');
      if (reply.answered_by !== 'data' && !(c.citations_used || []).length) problems.push('no citations');
      var badge = el('span', 'cx-badge ' + (ok ? 'ok' : 'warn'), ok ? '✓ Checked against SEC data' : 'Check: ' + problems.join('; '));
      row.appendChild(badge);
    }
    var by = reply.answered_by === 'data' ? 'Read from filings' : (reply.model ? reply.model + ' (local)' : null);
    if (by) row.appendChild(el('span', null, by + (reply.brief && reply.brief.as_of ? ' · as of ' + reply.brief.as_of : '')));
    if (reply.answer) {
      var copy = el('button', 'cx-act'); copy.type = 'button'; copy.title = 'Copy answer'; copy.setAttribute('aria-label', 'Copy answer');
      copy.appendChild(svg('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>'));
      copy.onclick = function () { try { navigator.clipboard.writeText(reply.answer); copy.title = 'Copied'; } catch (e) { /* clipboard blocked */ } };
      row.appendChild(copy);
    }
    bot.body.appendChild(row);
    (reply.notes || []).slice(1).forEach(function (n) { bot.body.appendChild(el('div', 'cx-note', n)); });
  }
  function showReply(bot, reply, animate, q) {
    bot.msg.classList.remove('thinking');
    var content = el('div'); bot.body.appendChild(content);
    if (!reply.company) {
      content.appendChild(el('p', null, (reply.notes || [])[0] || 'Which company do you mean?'));
      var chips = el('div', 'cx-chips');
      (reply.suggestions || []).forEach(function (s) {
        var chip = el('button', 'cx-chip', s.legal_name + (s.ticker ? ' · ' + s.ticker : '')); chip.type = 'button';
        chip.onclick = function () { state.cik = s.cik; ask((q || '') + ' ' + (s.ticker || s.legal_name)); };
        chips.appendChild(chip);
      });
      content.appendChild(chips);
      return;
    }
    state.cik = reply.company.cik;
    renderSide(reply);
    if (!reply.answer) {
      content.appendChild(el('p', 'cx-note', 'The language model is not available right now; the figures for ' + reply.company.legal_name + ' are in the company panel.'));
      meta(bot, reply); return;
    }
    if (isLeadership(reply)) { renderLeadership(content, reply); meta(bot, reply); keepScrolled(); return; }
    if (animate) stream(content, reply.answer, reply.citations, function () { meta(bot, reply); keepScrolled(); });
    else { content.appendChild(renderText(reply.answer, reply.citations)); meta(bot, reply); }
  }

  // ---- company drawer ----
  function fmtPct(p) { return p == null ? '' : (p > 0 ? '+' : '') + p.toFixed(1) + '%'; }
  function renderSide(reply) {
    var c = reply.company, brief = reply.brief || {};
    $('side-name').textContent = displayName(c.legal_name);
    $('side-meta').textContent = [c.ticker, c.exchange, 'CIK ' + c.cik, c.sic_description].filter(Boolean).join(' · ');
    var cov = brief.coverage || {};
    $('side-coverage').textContent = cov.filings ? 'Loaded here: ' + cov.filings + ' filings, ' + cov.first_filed + ' to ' + cov.last_filed + (cov.stale ? ' (newer filings not loaded)' : '') : 'No filings loaded for this company.';
    var m = $('side-metrics'); m.textContent = '';
    (brief.metrics || []).forEach(function (x) {
      var row = el('div', 'cx-metric'), left = el('span');
      left.appendChild(link(x.source_url, x.label)); left.appendChild(el('span', 'cx-muted cx-small', ' FY' + x.period_end.slice(0, 4)));
      var right = el('span', null, x.display + ' ');
      if (x.growth_pct != null) right.appendChild(el('span', x.growth_pct >= 0 ? 'up' : 'down', fmtPct(x.growth_pct)));
      row.appendChild(left); row.appendChild(right); m.appendChild(row);
    });
    if (!m.childNodes.length) m.appendChild(el('p', 'cx-muted cx-small', 'No annual figures loaded.'));
    var lead = $('side-leaders'); lead.textContent = '';
    (brief.leadership_filings || []).forEach(function (f) {
      var li = el('li'); li.appendChild(link(f.source_url, '8-K · ' + f.filing_date));
      (f.changes || []).forEach(function (ch) { li.appendChild(el('span', 'sub', (ch.person || 'Company-wide') + ' — ' + (TAGS[ch.change] || TAGS.other)[0].toLowerCase())); });
      lead.appendChild(li);
    });
    if (!lead.childNodes.length) lead.appendChild(el('li', 'cx-muted', 'None since ' + (cov.since || 'the last three years') + '.'));
    var fl = $('side-filings'); fl.textContent = '';
    (brief.filings || []).forEach(function (f) {
      var li = el('li'); li.appendChild(link(f.source_url, f.form_type + ' · ' + f.filing_date));
      if (f.items && f.items.length) li.appendChild(el('span', 'sub', 'Items ' + f.items.map(function (i) { return i.code; }).join(', ')));
      fl.appendChild(li);
    });
    var chip = $('cx-company-chip');
    $('cx-company-chip-text').textContent = c.ticker || displayName(c.legal_name);
    chip.hidden = false;
    $('cx-title').textContent = displayName(c.legal_name);
  }
  function drawer(open) {
    body.classList.toggle('drawer-open', open);
    $('cx-drawer').setAttribute('aria-hidden', open ? 'false' : 'true');
  }

  // ---- asking ----
  var LEAD_RE = /\b(leadership|ceo|cfo|coo|chief|executives?|officers?|directors?|board|resign\w*|appoint\w*|hired?|depart\w*|succession|chair\w*)\b/i;
  function headers() { return { 'Content-Type': 'application/json', 'X-API-Key': state.key }; }

  function ask(q) {
    q = (q || '').trim().slice(0, 500);
    if (!q || state.busy) return;
    state.busy = true; send.disabled = true;
    var bot;
    var go = function () { body.dataset.state = 'chat'; addUser(q); bot = addBot(); };
    (body.dataset.state === 'home' ? transition(go) : (go(), Promise.resolve())).then(function () { request(q, bot); });
  }

  function request(q, bot) {
    var steps = LEAD_RE.test(q)
      ? ['Finding the company…', 'Reading the 8-K filings…', 'Checking names against the filing text…']
      : ['Finding the company…', 'Gathering SEC figures…', 'Writing the answer…', 'Checking every figure…'];
    var stop = setStatus(bot, steps);
    var payload = { message: q };
    if (state.cik) payload.cik = state.cik;
    if ($('cx-asof').value) payload.as_of = $('cx-asof').value;
    if (state.sessionId && state.connected) payload.session_id = state.sessionId;
    state.controller = window.AbortController ? new AbortController() : null;
    fetch('/v1/chat', { method: 'POST', headers: headers(), body: JSON.stringify(payload), signal: state.controller && state.controller.signal })
      .then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
      .then(function (res) {
        stop();
        if (res.status !== 200) {
          bot.msg.classList.remove('thinking');
          bot.body.appendChild(el('p', null, (res.body.error && res.body.error.message) || ('Error ' + res.status)));
          return;
        }
        var reply = res.body;
        showReply(bot, reply, true, q);
        if (reply.session_id && state.connected) {
          var fresh = !state.sessionId;
          state.sessionId = reply.session_id; setHash();
          if (fresh) loadSessions();
        } else if (!state.connected) {
          var log = sload('cx_demo') || []; log.push({ q: q, reply: reply }); sstore('cx_demo', log.slice(-30));
        }
      })
      .catch(function () { stop(); bot.msg.classList.remove('thinking'); bot.body.appendChild(el('p', null, 'Network error. Try again.')); })
      .finally(function () { state.busy = false; send.disabled = !input.value.trim(); state.controller = null; });
  }

  function newChat() {
    transition(function () {
      thread.textContent = ''; state.sessionId = null; state.cik = null; setHash();
      body.dataset.state = 'home'; $('cx-company-chip').hidden = true; $('cx-title').textContent = 'Company intelligence';
      drawer(false); markCurrent(); sstore('cx_demo', []);
    });
    closeSideOnMobile(); input.focus();
  }

  // ---- saved sessions (own API key only) ----
  function setHash() {
    var h = state.sessionId ? '#s=' + state.sessionId : '';
    if (location.hash !== h) history.replaceState(null, '', location.pathname + location.search + h);
  }
  function markCurrent() {
    document.querySelectorAll('.cx-session').forEach(function (li) { li.setAttribute('aria-current', li.dataset.id === state.sessionId ? 'true' : 'false'); });
  }
  function loadSessions() {
    var list = $('cx-session-list'), hint = $('cx-session-hint');
    if (!state.connected) { list.textContent = ''; hint.hidden = false; return; }
    hint.hidden = true;
    fetch('/v1/chat/sessions?limit=100', { headers: headers() }).then(function (r) { return r.ok ? r.json() : { data: [] }; }).then(function (b) {
      list.textContent = '';
      b.data.forEach(function (s, i) {
        var li = el('li', 'cx-session'); li.dataset.id = s.id; li.style.animationDelay = Math.min(i, 12) * 0.02 + 's';
        var open = el('button', 'open', s.title); open.type = 'button'; open.title = s.title;
        open.onclick = function () { openSession(s.id); };
        var del = el('button', 'del'); del.type = 'button'; del.setAttribute('aria-label', 'Delete chat'); del.title = 'Delete chat';
        del.appendChild(svg('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>'));
        del.onclick = function () {
          li.style.transition = 'opacity .2s, transform .2s'; li.style.opacity = '0'; li.style.transform = 'translateX(-8px)';
          fetch('/v1/chat/sessions/' + s.id, { method: 'DELETE', headers: headers() }).then(function () {
            li.remove(); if (state.sessionId === s.id) newChat();
          });
        };
        li.appendChild(open); li.appendChild(del); list.appendChild(li);
      });
      if (!b.data.length) { hint.textContent = 'Your chats will appear here.'; hint.hidden = false; }
      markCurrent();
    });
  }
  function openSession(id) {
    fetch('/v1/chat/sessions/' + id, { headers: headers() }).then(function (r) { return r.ok ? r.json() : null; }).then(function (s) {
      if (!s) { state.sessionId = null; setHash(); return; }
      transition(function () {
        thread.textContent = ''; state.sessionId = s.id; state.cik = s.company_cik; setHash();
        body.dataset.state = 'chat'; drawer(false);
        s.messages.forEach(function (m) {
          if (m.role === 'user') addUser(m.content);
          else if (m.reply) { var bot = addBot(); showReply(bot, m.reply, false); }
        });
        markCurrent(); keepScrolled(true);
      });
      closeSideOnMobile();
    });
  }

  // ---- account / API key ----
  function setAccount() {
    $('cx-account-name').textContent = state.connected ? 'Connected' : 'Demo mode';
    $('cx-account-sub').textContent = state.connected ? state.key.slice(0, 14) + '… · Disconnect' : 'Connect API key';
    $('cx-avatar').textContent = state.connected ? 'K' : 'D';
  }
  function connect(key) {
    return fetch('/v1/chat/sessions?limit=1', { headers: { 'X-API-Key': key } }).then(function (r) {
      if (!r.ok) throw new Error(r.status === 401 ? 'That key was not accepted.' : 'Could not check the key (HTTP ' + r.status + ').');
      state.key = key; state.connected = true; store('prov_key', key); setAccount(); loadSessions();
    });
  }
  $('cx-account').onclick = function () {
    if (state.connected) {
      state.key = DEMO; state.connected = false; store('prov_key', null); setAccount(); loadSessions(); newChat(); return;
    }
    $('cx-key-error').hidden = true; $('cx-key-input').value = ''; $('cx-key-modal').showModal();
  };
  $('cx-key-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var k = $('cx-key-input').value.trim(); if (!k) return;
    $('cx-key-save').disabled = true;
    connect(k).then(function () { $('cx-key-modal').close(); newChat(); })
      .catch(function (err) { var x = $('cx-key-error'); x.textContent = err.message; x.hidden = false; })
      .finally(function () { $('cx-key-save').disabled = false; });
  });
  $('cx-key-demo').onclick = function () { $('cx-key-modal').close(); };

  // ---- layout controls ----
  var mobile = window.matchMedia('(max-width: 860px)');
  function closeSideOnMobile() { if (mobile.matches) { body.classList.remove('side-open'); $('cx-scrim').hidden = true; } }
  $('cx-collapse').onclick = function () { if (mobile.matches) closeSideOnMobile(); else body.classList.add('side-closed'); };
  $('cx-open-side').onclick = function () {
    if (mobile.matches) { body.classList.add('side-open'); $('cx-scrim').hidden = false; } else body.classList.remove('side-closed');
  };
  $('cx-scrim').onclick = closeSideOnMobile;
  $('cx-new').onclick = newChat;
  $('cx-company-chip').onclick = function () { drawer(!body.classList.contains('drawer-open')); };
  $('cx-drawer-close').onclick = function () { drawer(false); };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { drawer(false); closeSideOnMobile(); } });
  $('cx-asof-btn').onclick = function () {
    var d = $('cx-asof'); d.hidden = !d.hidden; this.classList.toggle('on', !d.hidden);
    if (!d.hidden) d.focus(); else { d.value = ''; $('cx-asof-label').textContent = 'Latest data'; }
  };
  $('cx-asof').onchange = function () { $('cx-asof-label').textContent = this.value ? 'As of ' + this.value : 'Latest data'; };

  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 200) + 'px'; }
  input.addEventListener('input', function () { autosize(); send.disabled = state.busy || !input.value.trim(); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit')); }
  });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value; if (!q.trim() || state.busy) return;
    input.value = ''; autosize(); ask(q);
  });
  document.querySelectorAll('.cx-card[data-q]').forEach(function (b) { b.addEventListener('click', function () { ask(b.getAttribute('data-q')); }); });

  // ---- start ----
  setAccount();
  var saved = load('prov_key');
  var hashId = (/^#s=([0-9a-f-]{36})$/.exec(location.hash) || [])[1];
  var q0 = new URLSearchParams(location.search).get('q');
  var ready = saved && saved !== DEMO ? connect(saved).catch(function () { store('prov_key', null); }) : Promise.resolve();
  ready.then(function () {
    loadSessions();
    if (hashId && state.connected) openSession(hashId);
    else if (!state.connected && (sload('cx_demo') || []).length) {
      body.dataset.state = 'chat';
      sload('cx_demo').forEach(function (t) { addUser(t.q); showReply(addBot(), t.reply, false, t.q); });
      keepScrolled(true);
    }
    if (q0) ask(q0);
  });
  if (mobile.matches) { body.classList.remove('side-open'); input.placeholder = 'Ask about a company…'; }
  input.focus();
})();
