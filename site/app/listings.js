/* Explorer: Canada, Europe and UK listings. Search by ISIN, issuer name or LEI; an instrument
   view shows every venue, the issuer's identity and the event history. Loaded by app.js. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var ISIN = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/, LEI = /^[A-Z0-9]{18}[0-9]{2}$/;
  var EVENT_LABELS = { new_listing: 'New listing', ipo: 'IPO (stated by the source)', delisting: 'Delisting', modified: 'Record changed', suspended: 'Suspended', reinstated: 'Reinstated' };
  var SOURCES = { esma_firds: 'ESMA FIRDS register', fca_firds: 'FCA FIRDS register', gleif: 'GLEIF', gleif_isin_map: 'GLEIF ISIN-LEI mapping', tsx: 'TMX', cse: 'CSE' };
  var api, toast, venues = null, started = false;

  function venueMap() {
    if (venues) return Promise.resolve(venues);
    return api('/v1/markets/').then(function (res) { venues = {}; res.body.data.forEach(function (v) { venues[v.mic] = v; }); return venues; });
  }
  function venueName(mic) { var v = venues && venues[mic]; return v ? v.name + ' (' + mic + ')' : mic; }
  function src(s) { return SOURCES[s] || s; }
  function yesNo(v) { return v === true ? 'yes' : v === false ? 'no' : '—'; }
  function table(head, rows) {
    var t = el('table', {}, [el('thead', {}, [el('tr', {}, head.map(function (h) { return el('th', { text: h }); }))])]);
    var tb = el('tbody'); rows.forEach(function (r) { tb.appendChild(el('tr', {}, r.map(function (c) { return c instanceof Node ? el('td', {}, [c]) : el('td', { text: c == null ? '—' : String(c) }); }))); });
    t.appendChild(tb); return el('div', { class: 'table-wrap' }, [t]);
  }
  function busy(box, text) { box.innerHTML = ''; box.appendChild(el('p', { class: 'skeleton', text: text })); }
  function link(text, fn) { var b = el('button', { type: 'button', class: 'linkish', text: text }); b.addEventListener('click', fn); return b; }

  /* ---- search ---- */
  function search(q) {
    var box = $('l-results'); $('l-detail').hidden = true;
    q = q.trim(); var up = q.toUpperCase();
    if (ISIN.test(up)) { box.innerHTML = ''; openInstrument(up); return; }
    if (LEI.test(up)) { box.innerHTML = ''; openIssuer(up); return; }
    busy(box, 'Searching listings…');
    api('/v1/markets/instruments?limit=100&q=' + encodeURIComponent(q)).then(function (res) {
      box.innerHTML = '';
      var byIsin = {}, order = [];
      res.body.data.forEach(function (r) {
        var k = r.isin || r.listing_key;
        if (!byIsin[k]) { byIsin[k] = []; order.push(k); }
        byIsin[k].push(r);
      });
      if (!order.length) { box.appendChild(el('li', { class: 'skeleton', text: 'No listing matches. Try an ISIN, an LEI or part of the issuer name.' })); return; }
      order.forEach(function (k) {
        var rows = byIsin[k], first = rows[0];
        var listed = rows.filter(function (r) { return r.status === 'listed'; }).length;
        var li = el('li', {}, [
          el('div', {}, [el('strong', { text: first.issuer_name }), ' ', el('span', { class: 'mono', text: k })]),
          el('span', { class: 'mono', text: rows.length + (rows.length === 1 ? ' venue' : ' venues') + ' · ' + listed + ' listed' })
        ]);
        li.tabIndex = 0; li.setAttribute('role', 'button');
        var go = function () { if (first.isin) openInstrument(first.isin); else toast('This listing has no ISIN; search by its issuer instead.'); };
        li.addEventListener('click', go); li.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
        box.appendChild(li);
      });
      if (res.body.meta.has_more) box.appendChild(el('li', { class: 'skeleton', text: 'More listings match; narrow the search.' }));
    }).catch(function () { box.innerHTML = ''; });
  }

  /* ---- one instrument: venues, issuer, events ---- */
  function openInstrument(isin) {
    var d = $('l-detail'); d.hidden = false; busy(d, 'Loading ' + isin + '…');
    Promise.all([venueMap(), api('/v1/markets/instruments/' + isin), api('/v1/markets/events?limit=100&isin=' + isin)]).then(function (out) {
      var inst = out[1].body, events = out[2].body.data, first = inst.listings[0];
      d.innerHTML = '';
      d.appendChild(el('header', { class: 'company-head' }, [el('div', {}, [
        el('p', { class: 'eyebrow', text: 'ISIN ' + isin }),
        el('h2', { text: inst.issuer ? inst.issuer.legal_name : first.issuer_name }),
        el('p', { class: 'muted', text: [first.instrument_type.replace('_', ' '), first.cfi_code && 'CFI ' + first.cfi_code, first.currency].filter(Boolean).join(' · ') })
      ])]));
      d.appendChild(issuerCard(inst.issuer));
      d.appendChild(el('h3', { text: 'Venues' }));
      d.appendChild(table(['Venue', 'Status', 'First trade', 'Terminated', 'Issuer asked for admission', 'Source'], inst.listings.map(function (r) {
        return [venueName(r.mic), el('span', { class: 'badge ' + (r.status === 'listed' ? 'ok' : r.status === 'suspended' ? 'stale' : 'failed'), text: r.status }), r.first_trade_date, r.termination_date, yesNo(r.issuer_requested), src(r.source)];
      })));
      d.appendChild(el('h3', { text: 'Events' }));
      if (!events.length) d.appendChild(el('p', { class: 'muted', text: 'No lifecycle events recorded for this instrument yet.' }));
      else {
        var ol = el('ol', { class: 'timeline' });
        events.slice().sort(function (a, b) { return (b.event_date || '').localeCompare(a.event_date || ''); }).forEach(function (e) {
          var extra = [];
          if (e.details && e.details.likely_primary_listing) extra.push('likely primary listing');
          if (e.details && e.details.first_listing_for_issuer_in_our_data) extra.push('first listing of this issuer in our data');
          ol.appendChild(el('li', {}, [
            el('span', { class: 'mono', text: e.event_date || 'undated' }),
            el('strong', { text: EVENT_LABELS[e.event_type] || e.event_type }),
            el('span', { class: 'muted', text: venueName(e.mic) + (extra.length ? ' · ' + extra.join(', ') : '') + ' · detected ' + e.detected_at.slice(0, 10) })
          ]));
        });
        d.appendChild(ol);
      }
      var notes = el('ul', { class: 'notes' }); inst.notes.forEach(function (n) { notes.appendChild(el('li', { text: n })); }); d.appendChild(notes);
      d.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }).catch(function () { d.innerHTML = ''; d.appendChild(el('p', { class: 'muted', text: 'This ISIN is not among the listings loaded here.' })); });
  }

  function issuerCard(issuer) {
    var grid = el('div', { class: 'grid' });
    var kv = function (k, v) { grid.appendChild(el('div', { class: 'kv' }, [el('div', { class: 'k', text: k }), el('div', { class: 'v' }, [v instanceof Node ? v : document.createTextNode(v || '—')])])); };
    if (!issuer) { kv('Issuer', 'Not identified yet: the register gives no LEI and none is mapped to this ISIN.'); return grid; }
    kv('Legal name', issuer.legal_name);
    kv('LEI', issuer.lei ? link(issuer.lei, function () { openIssuer(issuer.lei); }) : null);
    kv('Country', issuer.country); kv('LEI registration', issuer.registration_status);
    kv('Identity from', src(issuer.source));
    return grid;
  }

  /* ---- one issuer: all its listings ---- */
  function openIssuer(lei) {
    var d = $('l-detail'); d.hidden = false; busy(d, 'Loading LEI ' + lei + '…');
    Promise.all([venueMap(), api('/v1/markets/issuers/' + lei)]).then(function (out) {
      var body = out[1].body; d.innerHTML = '';
      d.appendChild(el('header', { class: 'company-head' }, [el('div', {}, [el('p', { class: 'eyebrow', text: 'LEI ' + lei }), el('h2', { text: body.issuer.legal_name })])]));
      d.appendChild(issuerCard(body.issuer));
      d.appendChild(el('h3', { text: 'Listings' }));
      d.appendChild(table(['ISIN', 'Venue', 'Status', 'First trade', 'Name in the register'], body.listings.map(function (r) {
        return [r.isin ? link(r.isin, function () { openInstrument(r.isin); }) : r.listing_key, venueName(r.mic), r.status, r.first_trade_date, r.short_name || r.issuer_name];
      })));
    }).catch(function () { d.innerHTML = ''; d.appendChild(el('p', { class: 'muted', text: 'No issuer with this LEI is among the listings loaded here.' })); });
  }

  /* ---- first visit: recent new listings to start from ---- */
  function recent() {
    var box = $('l-recent'); busy(box, 'Loading recent new listings…');
    Promise.all([venueMap(), api('/v1/markets/events?type=new_listing&limit=12')]).then(function (out) {
      var rows = out[1].body.data.slice().sort(function (a, b) { return (b.event_date || '').localeCompare(a.event_date || ''); }); box.innerHTML = '';
      if (!rows.length) { box.appendChild(el('p', { class: 'muted', text: 'No new listings have been recorded yet.' })); return; }
      box.appendChild(table(['First trade', 'Instrument', 'Venue', 'Primary?'], rows.map(function (e) {
        return [e.event_date, e.isin ? link(e.issuer_name + ' · ' + e.isin, function () { openInstrument(e.isin); }) : e.issuer_name, venueName(e.mic), e.details && e.details.likely_primary_listing ? 'likely' : '—'];
      })));
    }).catch(function () { box.innerHTML = ''; });
  }

  window.ProvenanceListings = {
    load: function (apiFn, toastFn) {
      api = apiFn; toast = toastFn;
      if (started) return; started = true;
      $('l-form').addEventListener('submit', function (e) { e.preventDefault(); var q = $('lq').value; if (q.trim().length >= 2) search(q); });
      recent();
    }
  };
})();
