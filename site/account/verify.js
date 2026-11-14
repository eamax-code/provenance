/* Opening a sign-in link (GH #15). The token is in the address's #fragment, so it never reaches
   server logs or other sites; it is sent once, by POST, so a mail scanner that opens the link
   does not use it up. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var token = (/[#&]token=([A-Za-z0-9_-]{20,200})/.exec(location.hash) || [])[1];
  history.replaceState(null, '', location.pathname);  // the token leaves the address bar
  function fail(text) {
    $('verify-title').textContent = 'This link did not work';
    $('verify-msg').textContent = text;
    $('verify-next').hidden = false;
  }
  if (!token) { fail('The link is incomplete. Copy the whole link from the email, or ask for a new one.'); return; }
  fetch('/v1/account/verify', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ token: token })
  }).then(function (r) {
    if (r.ok) { $('verify-title').textContent = 'Signed in'; $('verify-msg').textContent = 'Taking you to your account…'; location.replace('/account/'); return; }
    return r.json().catch(function () { return {}; }).then(function (b) {
      fail((b.error && b.error.message) || 'This sign-in link has expired or was already used.');
    });
  }).catch(function () { fail('Could not reach the server. Check your connection and open the link again.'); });
})();
