/* The account page (GH #15): sign in by emailed link, then keys, usage, theme and sign-out.
   The session is an HttpOnly cookie; this script never sees it. Text is set with textContent. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return n == null ? 'unlimited' : Number(n).toLocaleString('en-US'); };
  var day = function (iso) { return iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'; };
  var PLAN = { free: 'Free', builder: 'Builder', pilot: 'Builder (pilot)', team: 'Team', enterprise: 'Enterprise', internal: 'Internal' };

  function api(method, path, body) {
    var opts = { method: method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function (r) {
      if (r.status === 204) return { ok: true, status: 204, body: null };
      return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, body: b }; });
    });
  }
  function say(id, text, kind) { var el = $(id); el.textContent = text || ''; el.className = 'acct-msg' + (kind ? ' ' + kind : ''); }
  function errText(res) { return (res.body && res.body.error && res.body.error.message) || 'Something went wrong. Try again.'; }

  function showSignIn() {
    $('acct-state').hidden = true; $('acct').hidden = true; $('acct-signin').hidden = false;
  }

  function render(a) {
    $('acct-state').hidden = true; $('acct-signin').hidden = true; $('acct').hidden = false;
    $('acct-title').textContent = 'Your account';
    $('acct-lead').textContent = 'Create and revoke keys, watch this month’s usage and choose how chat and the Explorer look.';
    $('acct-email').textContent = a.email;
    $('acct-since').textContent = 'Account since ' + day(a.created_at);
    $('acct-plan').textContent = PLAN[a.plan] || a.plan;
    $('acct-used').textContent = fmt(a.requests_this_month) + ' of ' + fmt(a.monthly_request_quota);
    var pct = a.monthly_request_quota ? Math.min(100, 100 * a.requests_this_month / a.monthly_request_quota) : 0;
    $('acct-meter').style.width = pct.toFixed(1) + '%';
    $('acct-meter').classList.toggle('hot', pct >= 80);
    var active = a.keys.filter(function (k) { return k.is_active; }).length;
    $('acct-count').textContent = active + ' of ' + a.max_active_keys;
    var tb = $('keys-table').querySelector('tbody');
    tb.replaceChildren();
    if (!a.keys.length) {
      var tr0 = document.createElement('tr'), td0 = document.createElement('td');
      td0.colSpan = 7; td0.className = 'muted'; td0.textContent = 'No keys yet. Create one above.';
      tr0.appendChild(td0); tb.appendChild(tr0);
    }
    a.keys.forEach(function (k) {
      var tr = document.createElement('tr');
      var cells = [k.key_prefix + '…', k.label || '—', PLAN[k.plan] || k.plan, day(k.created_at), k.last_used_at ? day(k.last_used_at) : 'never', k.is_active ? fmt(k.requests_this_month) : 'revoked ' + day(k.revoked_at)];
      cells.forEach(function (text, i) {
        var td = document.createElement('td'); td.textContent = text;
        if (i === 0) td.className = 'mono';
        if (!k.is_active && i < 3) td.classList.add('revoked');
        tr.appendChild(td);
      });
      var act = document.createElement('td');
      if (k.is_active) {
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'btn small danger'; b.textContent = 'Revoke';
        b.setAttribute('aria-label', 'Revoke key ' + k.key_prefix + (k.label ? ' (' + k.label + ')' : ''));
        b.addEventListener('click', function () { revoke(k, b); });
        act.appendChild(b);
      }
      tr.appendChild(act);
      tb.appendChild(tr);
    });
    $('key-btn').disabled = active >= a.max_active_keys;
    if (!$('acct-theme').firstChild) {
      Shell.picker($('acct-theme'), saveTheme, { keepPage: true, value: a.ui_theme });
    }
  }

  function load() {
    return api('GET', '/v1/account').then(function (res) {
      if (res.ok) render(res.body); else showSignIn();
    }).catch(function () { $('acct-state').textContent = 'Your account could not be loaded. Check your connection and reload.'; });
  }

  $('signin-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var email = $('signin-email').value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { say('signin-msg', 'Enter an email address, like you@company.com.', 'err'); $('signin-email').focus(); return; }
    $('signin-btn').disabled = true; say('signin-msg', 'Sending…');
    api('POST', '/v1/account/sign-in', { email: email }).then(function (res) {
      if (res.ok) { say('signin-msg', res.body.message, 'ok'); return; }
      if (res.status === 503) {
        say('signin-msg', 'Sign-in by email opens soon. Until then, request a key and we will send it to you.', 'err');
        var a = document.createElement('a'); a.href = '/#contact'; a.textContent = ' Request a key';
        $('signin-msg').appendChild(a);
        return;
      }
      say('signin-msg', errText(res), 'err');
    }).catch(function () { say('signin-msg', 'Could not reach the server. Try again.', 'err'); })
      .then(function () { $('signin-btn').disabled = false; });
  });

  $('key-form').addEventListener('submit', function (e) {
    e.preventDefault();
    $('key-btn').disabled = true; say('key-msg', '');
    api('POST', '/v1/account/keys', { label: $('key-label').value.trim() || null }).then(function (res) {
      if (!res.ok) { say('key-msg', errText(res), 'err'); return; }
      $('key-secret').textContent = res.body.api_key;
      $('key-new').hidden = false; $('key-label').value = '';
      $('key-copy').focus();
      return load();
    }).then(function () { $('key-btn').disabled = false; });
  });
  $('key-copy').addEventListener('click', function () {
    var t = $('key-secret').textContent;
    (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function () {
      $('key-copy').textContent = 'Copied';
    }).catch(function () { $('key-copy').textContent = 'Select the key and copy it'; });
  });

  function revoke(k, btn) {
    if (!confirm('Revoke ' + k.key_prefix + '…? Anything using it stops working at once.')) return;
    btn.disabled = true;
    api('DELETE', '/v1/account/keys/' + k.id).then(function (res) {
      if (!res.ok) { say('key-msg', errText(res), 'err'); btn.disabled = false; return; }
      say('key-msg', 'Key ' + k.key_prefix + '… revoked.', 'ok');
      return load();
    });
  }

  function saveTheme(t) {
    api('PATCH', '/v1/account', { ui_theme: t }).then(function (res) {
      say('theme-msg', res.ok ? 'Saved. Chat and the Explorer use it on every device you sign in on.' : errText(res), res.ok ? 'ok' : 'err');
    });
  }

  $('signout').addEventListener('click', function () {
    api('POST', '/v1/account/sign-out').then(function () { location.reload(); });
  });
  $('signout-all').addEventListener('click', function () {
    if (!confirm('Sign out of every browser and device?')) return;
    api('POST', '/v1/account/sign-out-everywhere').then(function () { location.reload(); });
  });

  load();
})();
