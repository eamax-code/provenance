/* Team and Enterprise key requests: the same endpoint the account page uses for free keys. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var form = $('key-request-form'), status = $('kr-status'), submit = $('kr-submit');
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var email = $('kr-email'), use = $('kr-use');
    if (!email.checkValidity()) { status.textContent = 'Enter a valid email address.'; email.focus(); return; }
    if (use.value.trim().length < 12) { status.textContent = 'Tell us a little more about the use case, 12 characters or more.'; use.focus(); return; }
    submit.disabled = true; status.textContent = 'Sending…';
    var payload = { email: email.value.trim(), use_case: use.value.trim(), plan: $('kr-plan').value, website: $('kr-website').value };
    fetch(form.getAttribute('action'), { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, status: r.status, body: b }; }); })
      .then(function (res) {
        if (res.ok) { status.textContent = res.body.message || 'Request received.'; form.reset(); }
        else if (res.status === 429) { status.textContent = 'Too many requests from your network. Try again later.'; }
        else { status.textContent = (res.body && res.body.error && res.body.error.message) || 'Could not send the request.'; }
      })
      .catch(function () { status.textContent = 'Network error. The API may be offline.'; })
      .then(function () { submit.disabled = false; });
  });
})();
