/* Provenance Explorer, Connections tab: a company's insiders (Forms 3, 4, 5), the other
   companies those insiders report on, its 5% holders (13D/G) and its subsidiaries (exhibit 21),
   drawn as one graph from GET /v1/companies/{cik}/graph. Every edge links its filing. Text from
   the API is set with textContent only. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var VIEW = { x: -640, y: -400, w: 1280, h: 800 };
  var CLUSTER_AT = 24, EXPANDED_MAX = 60; // more subsidiaries than this are grouped by jurisdiction
  var S = { company: null, data: null, view: VIEW, mode: 'graph', expanded: {}, selected: null, polls: 0, timer: null, tx: null, pos: {}, cur: {}, lw: {}, userMoved: false, matches: null };
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (k === 'text') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  };
  var sv = function (tag, attrs) { var n = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); }); return n; };
  var money = function (v) {
    if (v == null) return '—'; var a = Math.abs(v);
    if (a >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B'; if (a >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M'; if (a >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'K';
    return '$' + Math.round(v).toLocaleString('en-US');
  };
  var shares = function (v) { return v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }); };
  var short = function (s, n) { s = s || ''; return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  var link = function (ev, text) { return ev && ev.source_url ? el('a', { href: ev.source_url, target: '_blank', rel: 'noopener', text: text || (ev.form_type + ' · ' + ev.filing_date + ' ↗') }) : el('span', { class: 'muted', text: '—' }); };
  var X = function () { return window.ProvenanceExplorer; };

  var EDGE = { // the legend's order
    officer: { label: 'Officer', cls: 'e-officer' },
    director: { label: 'Director', cls: 'e-director' },
    ten_percent_owner: { label: '10% owner (Form 4)', cls: 'e-owner' },
    other_insider: { label: 'Other insider', cls: 'e-director' },
    holder: { label: '5% holder (13D/G)', cls: 'e-holder' },
    interlock: { label: 'Also reports at', cls: 'e-interlock' },
    subsidiary: { label: 'Subsidiary (exhibit 21)', cls: 'e-sub' }
  };

  /* ---- data ---- */
  function layers() { return ['insiders', 'interlocks', 'holders', 'subsidiaries'].filter(function (k) { return $('g-' + k).checked; }); }
  function load(company) {
    if (company) { if (!S.company || S.company.cik !== company.cik) { S.expanded = {}; S.selected = null; S.view = VIEW; S.tx = null; S.cur = {}; S.userMoved = false; S.matches = null; $('g-find').value = ''; $('g-find-n').textContent = ''; clearDetail(); } S.company = company; }
    if (!S.company) return;
    clearTimeout(S.timer);
    var q = ['include=' + encodeURIComponent(layers().join(',') || 'insiders')];
    if ($('g-former').checked) q.push('former=true');
    if ($('g-asof').value) q.push('as_of=' + $('g-asof').value);
    $('g-summary').textContent = 'Loading connections…';
    X().api('/v1/companies/' + S.company.cik + '/graph?' + q.join('&')).then(function (res) {
      S.data = res.body;
      render();
      if (res.body.refreshing && S.polls < 5) {
        S.polls += 1;
        $('g-summary').textContent += ' Reading exhibit 21, 13D/G and the newest Forms 4 from EDGAR; this view updates in a few seconds.';
        S.timer = setTimeout(load, 7000);
      } else S.polls = 0;
    }).catch(function () { $('g-summary').textContent = 'Connections are unavailable right now.'; });
  }

  /* ---- layout ----
     Lanes, left to right: the other companies the insiders report at; 5% holders, then insiders
     (officers before directors); the company; its subsidiaries (grouped by jurisdiction when
     many). Columns are straight so a lane reads as a list; edges are curves between them. */
  var STEP = 36, COL = 280, OUTER = 340, ROLE_GAP = 12, LANE_GAP = 52;
  function laneOf(items, x, side, gaps) {
    var y = 0, ys = [];
    items.forEach(function (it, i) { ys.push(y); y += (it.kind === 'cluster' ? 40 : STEP) + (gaps[i] || 0); });
    var half = (ys.length ? ys[ys.length - 1] : 0) / 2;
    items.forEach(function (it, i) { S.pos[it.id] = { x: x, y: ys[i] - half, side: side }; });
  }
  function spread(list, x, side) { // [{it, y}] sorted by wanted y; kept STEP apart around their mean
    if (!list.length) return;
    list.sort(function (a, b) { return a.y - b.y; });
    var want = list.reduce(function (s, p) { return s + p.y; }, 0) / list.length;
    for (var i = 1; i < list.length; i++) if (list[i].y - list[i - 1].y < STEP) list[i].y = list[i - 1].y + STEP;
    var got = list.reduce(function (s, p) { return s + p.y; }, 0) / list.length;
    list.forEach(function (p) { S.pos[p.it.id] = { x: x, y: p.y + want - got, side: side }; });
  }
  function layout(d) {
    var byId = {}, center = null, toCenter = {};
    d.nodes.forEach(function (n) { byId[n.id] = n; if (n.group === 'center') center = n; });
    d.edges.forEach(function (e) { if (e.target === center.id) (toCenter[e.source] = toCenter[e.source] || []).push(e); });
    var nodes = [], edges = [], lanes = [], L_open = null;
    S.pos = {};
    S.pos[center.id] = { x: 0, y: 0, side: 0 };
    nodes.push({ id: center.id, n: center, kind: 'center', sub: 'CIK ' + center.cik });
    var role = function (n) { var es = toCenter[n.id] || []; var r = es.filter(function (e) { return e.type !== 'holder'; })[0]; return r || es[0] || {}; };
    var holders = d.nodes.filter(function (n) { return n.group === 'holders'; }).map(function (n) {
      var e = role(n); return { id: n.id, n: n, kind: 'holder', sub: (e.percent != null ? e.percent + '% stake' : 'Above 5%') + (n.detail && n.detail.holder_type ? ' · ' + n.detail.holder_type : '') };
    });
    var insiders = d.nodes.filter(function (n) { return n.group === 'insiders'; }).map(function (n) {
      var e = role(n), stake = (toCenter[n.id] || []).filter(function (x) { return x.type === 'holder' && x.percent != null; })[0];
      return { id: n.id, n: n, kind: 'insider', role: e.type, sub: (e.label || 'Insider') + (stake ? ' · ' + stake.percent + '%' : '') + (e.current === false ? ' · former' : '') };
    });
    var subs = d.nodes.filter(function (n) { return n.group === 'subsidiaries'; });
    var clusters = [];
    if (subs.length > CLUSTER_AT) {
      var groups = {};
      subs.forEach(function (n) { var g = (n.detail && n.detail.jurisdiction_group) || 'Not stated'; (groups[g] = groups[g] || []).push(n); });
      clusters = Object.keys(groups).sort(function (a, b) { return groups[b].length - groups[a].length || a.localeCompare(b); }).map(function (g) {
        return { id: 'cluster:' + g, kind: 'cluster', label: g, members: groups[g], fresh: groups[g].filter(function (m) { return m.detail && m.detail.new_this_year; }).length };
      });
      if (clusters.length > 16) { // the largest 15, then one group for the rest
        var rest = clusters.slice(15), members = [].concat.apply([], rest.map(function (c) { return c.members; }));
        clusters = clusters.slice(0, 15).concat([{ id: 'cluster:other', kind: 'cluster', other: true, label: 'Other jurisdictions (' + rest.length + ')', members: members, fresh: rest.reduce(function (s, c) { return s + c.fresh; }, 0) }]);
      }
      clusters.forEach(function (c) { c.sub = c.members.length + ' subsidiar' + (c.members.length === 1 ? 'y' : 'ies') + (c.fresh ? ' · ' + c.fresh + ' new' : ''); });
    }
    var subSub = function (n) { var det = n.detail || {}; return (det.new_this_year ? 'New this year · ' : '') + (det.jurisdiction || 'Jurisdiction not stated'); };
    var left = holders.concat(insiders), gaps = {};
    if (holders.length && insiders.length) gaps[holders.length - 1] = LANE_GAP;
    insiders.forEach(function (it, i) { if (i && it.role !== insiders[i - 1].role) gaps[holders.length + i - 1] = (gaps[holders.length + i - 1] || 0) + ROLE_GAP; });
    var right = clusters.length ? clusters : subs.map(function (n) { return { id: n.id, n: n, kind: 'sub', sub: subSub(n) }; });
    laneOf(left, -COL, -1, gaps);
    laneOf(right, COL, 1, {});
    if (holders.length) lanes.push({ x: -COL, y: S.pos[holders[0].id].y, side: -1, text: '5% holders', n: holders.length });
    if (insiders.length) lanes.push({ x: -COL, y: S.pos[insiders[0].id].y, side: -1, text: 'Insiders', n: insiders.length });
    if (right.length) lanes.push({ x: COL, y: S.pos[right[0].id].y, side: 1, text: clusters.length ? 'Subsidiaries by jurisdiction' : 'Subsidiaries', n: (d.sources.subsidiaries && d.sources.subsidiaries.count) || subs.length });
    nodes = nodes.concat(left, right);
    // an opened jurisdiction: its subsidiaries in columns beside it
    clusters.forEach(function (c) {
      if (!S.expanded[c.id]) return;
      // up to 60 on the graph (names found by the search first); the panel lists them all
      var hit = function (m) { return S.matches && S.matches[m.id] ? 0 : 1; };
      var shown = c.members.slice().sort(function (a, b) { return hit(a) - hit(b); }).slice(0, EXPANDED_MAX), per = 20;
      if (S.selected && !shown.some(function (m) { return m.id === S.selected; })) { var want = c.members.filter(function (m) { return m.id === S.selected; })[0]; if (want) shown[shown.length - 1] = want; }
      shown.forEach(function (m, i) {
        var col = Math.floor(i / per), row = i % per, rows = Math.min(per, shown.length - col * per);
        S.pos[m.id] = { x: COL + OUTER + col * 300, y: S.pos[c.id].y + (row - (rows - 1) / 2) * STEP, side: 1 };
        nodes.push({ id: m.id, n: m, kind: 'sub', parent: c.id, sub: subSub(m) });
        edges.push({ source: c.id, target: m.id, type: 'subsidiary', e: null, hidden: col > 0 }); // one fan, not lines across the names
      });
      var top = Math.min.apply(null, shown.slice(0, per).map(function (m) { return S.pos[m.id].y; }));
      lanes.push({ x: COL + OUTER, y: top, side: 1, text: c.label + (c.members.length > shown.length ? ' · ' + shown.length + ' of' : ''), n: c.members.length });
      L_open = { id: c.id, ids: [c.id].concat(shown.map(function (m) { return m.id; })) };
    });
    // the other companies of the insiders: level with the insiders who link them
    var inter = d.nodes.filter(function (n) { return n.group === 'interlocks'; }).map(function (n) {
      var via = d.edges.filter(function (e) { return e.target === n.id && S.pos[e.source]; });
      var ys = via.map(function (e) { return S.pos[e.source].y; });
      var who = via.map(function (e) { return byId[e.source] ? byId[e.source].label.split(' ').slice(-1)[0] : ''; });
      return { it: { id: n.id, n: n, kind: 'interlock', parent: via.length ? via[0].source : null, sub: (via[0] ? via[0].label : 'Insider') + ' · via ' + who.slice(0, 2).join(', ') + (who.length > 2 ? ' +' + (who.length - 2) : '') }, y: ys.length ? ys.reduce(function (a, b) { return a + b; }, 0) / ys.length : 0 };
    });
    spread(inter, -(COL + OUTER), -1);
    inter.forEach(function (p) { nodes.push(p.it); });
    if (inter.length) lanes.push({ x: -(COL + OUTER), y: Math.min.apply(null, inter.map(function (p) { return S.pos[p.it.id].y; })), side: -1, text: 'Also reports at', n: inter.length });
    d.edges.forEach(function (e) {
      var s = e.source, t = e.target;
      if (clusters.length && e.type === 'subsidiary') {
        var c = clusters.filter(function (c) { return c.members.some(function (m) { return m.id === t; }); })[0];
        if (c && !S.pos[t]) { if (!edges.some(function (x) { return x.target === c.id; })) edges.push({ source: s, target: c.id, type: 'subsidiary', e: null, cluster: c }); return; }
        if (c) s = c.id;
      }
      if (S.pos[s] && S.pos[t]) edges.push({ source: s, target: t, type: e.type, e: e });
    });
    var index = {}; nodes.forEach(function (it) { index[it.id] = it; });
    return { nodes: nodes, edges: edges, byId: byId, clusters: clusters, lanes: lanes, index: index, open: L_open };
  }
  function bounds(ids, withLanes) {
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    ids.forEach(function (id) {
      var p = S.pos[id]; if (!p) return;
      var lw = (S.lw[id] || 150) + 22;
      var half = p.side === 0 ? lw / 2 : 30; // the company's name sits centred under it
      minX = Math.min(minX, p.x - (p.side < 0 ? lw : half)); maxX = Math.max(maxX, p.x + (p.side > 0 ? lw : half));
      minY = Math.min(minY, p.y - (p.side === 0 ? 30 : 22)); maxY = Math.max(maxY, p.y + (p.side === 0 ? 56 : 26));
    });
    if (withLanes && S.L) { // room for the lane titles, and for the zoom buttons below
      S.L.lanes.forEach(function (l) {
        if (l.x < minX - 400 || l.x > maxX + 400) return;
        minY = Math.min(minY, l.y - 60);
        if (l.side > 0) maxX = Math.max(maxX, l.x + (l.w || 0) + 8); else minX = Math.min(minX, l.x - (l.w || 0) - 8);
      });
      maxY += 44;
    }
    return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }
  function viewFor(b, pad) { // a box around b that has the canvas's shape
    var svg = $('g-svg'), aspect = svg.clientWidth && svg.clientHeight ? svg.clientWidth / svg.clientHeight : 1.6;
    var w = b.w + pad * 2, h = b.h + pad * 2;
    if (w / h > aspect) h = w / aspect; else w = h * aspect;
    w = Math.max(w, 420); h = w / aspect;
    return { x: b.x + b.w / 2 - w / 2, y: b.y + b.h / 2 - h / 2, w: w, h: h };
  }
  function fitView(ids) {
    var b = bounds(ids || Object.keys(S.pos), true), svg = $('g-svg');
    if (!phone()) {
      svg.style.aspectRatio = String(Math.max(1.3, Math.min(2.3, (b.w + 40) / (b.h + 40))).toFixed(3)); // the canvas takes the graph's shape
    }
    return viewFor(b, 20);
  }

  var phone = function () { return window.matchMedia && window.matchMedia('(max-width: 640px)').matches; };
  function startView() { // a phone opens on the company and its insiders, readable; Fit shows all
    if (!phone() || !S.L) return fitView();
    var ids = S.L.nodes.filter(function (it) { return it.kind === 'center' || it.kind === 'insider' || it.kind === 'holder'; }).map(function (it) { return it.id; });
    return viewFor(bounds(ids, false), 12);
  }

  /* ---- drawing ---- */
  function shape(it) {
    var n = it.n || {}, k = it.kind;
    if (k === 'center') {
      var tk = (n.detail && n.detail.ticker) || 'CIK', w = Math.max(46, tk.length * 10 + 22);
      var g = sv('g', { class: 'g-shape-wrap' });
      g.appendChild(sv('circle', { r: 30, class: 'g-halo' }));
      g.appendChild(sv('rect', { x: -w / 2, y: -15, width: w, height: 30, rx: 15, class: 'g-shape g-center' }));
      var t = sv('text', { y: 5, 'text-anchor': 'middle', class: 'g-ticker' }); t.textContent = tk; g.appendChild(t);
      return g;
    }
    if (k === 'cluster') return sv('circle', { r: clusterR(it), class: 'g-shape g-cluster' + (S.expanded[it.id] ? ' g-open' : '') });
    if (n.type === 'company') return sv('rect', { x: -8, y: -8, width: 16, height: 16, rx: 4, class: 'g-shape g-company' });
    if (k === 'sub') return sv('rect', { x: -6, y: -6, width: 12, height: 12, rx: 3, class: 'g-shape g-sub' + (n.detail && n.detail.new_this_year ? ' g-new' : '') });
    if (k === 'holder') return sv('path', { d: 'M0 -11 L11 0 L0 11 L-11 0 Z', class: 'g-shape g-holder' });
    return sv('circle', { r: 8.5, class: 'g-shape ' + (n.type === 'person' ? 'g-person' : 'g-org') + (it.role ? ' r-' + it.role : '') });
  }
  function clusterR(it) { return Math.min(15, 6 + Math.sqrt(it.members.length) * 1.2); }
  function radius(it) { return it.kind === 'cluster' ? clusterR(it) : it.kind === 'holder' ? 11 : 9; }
  function nodeLabel(it) { return it.kind === 'cluster' ? it.label : it.n.label; }
  function anchor(id, toward) { // where an edge leaves a node: past the end of its label when it heads that way
    var p = S.cur[id] || S.pos[id], q = S.cur[toward] || S.pos[toward], side = (S.pos[id] || {}).side;
    if (!p || !q) return p || { x: 0, y: 0 };
    if (side && Math.sign(q.x - p.x) === side && S.lw[id]) return { x: p.x + side * (S.lw[id] + 20), y: p.y };
    return p;
  }
  function curve(a, b) {
    var mx = (a.x + b.x) / 2;
    return 'M' + a.x.toFixed(1) + ',' + a.y.toFixed(1) + 'C' + mx.toFixed(1) + ',' + a.y.toFixed(1) + ' ' + mx.toFixed(1) + ',' + b.y.toFixed(1) + ' ' + b.x.toFixed(1) + ',' + b.y.toFixed(1);
  }
  var reduced = function () { return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; };
  var ease = function (t) { return 1 - Math.pow(1 - t, 3); };

  function render() {
    var d = S.data; if (!d) return;
    summary(d); notes(d); legend(); counts(d);
    $('g-stage').hidden = S.mode !== 'graph'; $('g-lists').hidden = S.mode !== 'list';
    if (S.mode === 'list') { lists(d); return; }
    var L = layout(d); S.L = L;
    var svg = $('g-svg'), title = $('g-svg-title');
    title.textContent = (d.company.name || 'Company') + ': ' + d.nodes.length + ' connected people, companies and subsidiaries. The Lists view has the same data as tables.';
    // nodes that are going away fade where they stand
    var leaving = sv('g', { class: 'g-leaving', 'aria-hidden': 'true' });
    svg.querySelectorAll('.g-nodes .g-node').forEach(function (g) { if (!L.index[g.getAttribute('data-id')]) { g.removeAttribute('tabindex'); leaving.appendChild(g); } });
    var oldEdges = {}; svg.querySelectorAll('.g-edge').forEach(function (p) { oldEdges[p.getAttribute('data-s') + '>' + p.getAttribute('data-t')] = true; });
    Array.prototype.slice.call(svg.childNodes).forEach(function (c) { if (c !== title) svg.removeChild(c); });
    var first = !Object.keys(S.cur).length;
    var gL = sv('g', { class: 'g-lanes', 'aria-hidden': 'true' }), gE = sv('g', { class: 'g-edges' }), gN = sv('g', { class: 'g-nodes' });
    L.lanes.forEach(function (l) {
      var t = sv('text', { x: l.x + l.side * 2, y: l.y - 38, 'text-anchor': l.side < 0 ? 'end' : 'start', class: 'g-lane' });
      t.textContent = l.text;
      var c = sv('tspan', { class: 'g-lane-n', dx: '8' }); c.textContent = String(l.n); t.appendChild(c); gL.appendChild(t); l.el = t;
    });
    var recs = [];
    L.nodes.forEach(function (it) {
      var p = S.pos[it.id];
      var g = sv('g', { class: 'g-node k-' + it.kind + (S.selected === it.id ? ' g-sel' : ''), 'data-id': it.id, tabindex: '0', role: 'button', 'aria-label': nodeLabel(it) + (it.sub ? ', ' + it.sub : '') });
      g.appendChild(sv('circle', { r: 16, class: 'g-hit' }));
      g.appendChild(shape(it));
      var right = p.side >= 0, center = it.kind === 'center';
      var off = radius(it) + 7;
      var text = sv('text', center ? { y: 38, 'text-anchor': 'middle', class: 'g-label g-center-label' } : { x: (right ? 1 : -1) * off, y: it.sub ? -1 : 5, 'text-anchor': right ? 'start' : 'end', class: 'g-label' });
      text.textContent = center ? short(it.n.label, 44) : short(nodeLabel(it), 32);
      g.appendChild(text);
      if (it.sub) {
        var sub = sv('text', center ? { y: 54, 'text-anchor': 'middle', class: 'g-sublabel' } : { x: (right ? 1 : -1) * off, y: 14, 'text-anchor': right ? 'start' : 'end', class: 'g-sublabel' + (it.n && it.n.detail && it.n.detail.new_this_year ? ' g-sub-new' : '') });
        sub.textContent = short(it.sub, 40); g.appendChild(sub);
      }
      wireNode(g, it);
      gN.appendChild(g);
      // start from where it was, else from the node it grows out of
      var from = S.cur[it.id] || S.cur[it.parent] || S.cur['company:' + d.company.cik] || { x: 0, y: 0 };
      var fresh = !S.cur[it.id];
      if (fresh && !reduced()) { g.classList.add('g-enter'); g.style.animationDelay = (first ? Math.min(260, Math.abs(p.x) * 0.4) : 60) + 'ms'; }
      recs.push({ id: it.id, g: g, from: { x: from.x, y: from.y }, to: p, delay: first ? Math.min(260, Math.abs(p.x) * 0.4) : 0 });
    });
    var erecs = [];
    L.edges.forEach(function (e) {
      if (e.hidden) return;
      var cls = 'g-edge ' + (EDGE[e.type] ? EDGE[e.type].cls : '') + (e.e && !e.e.current ? ' e-former' : '');
      var path = sv('path', { class: cls, 'data-s': e.source, 'data-t': e.target, 'data-type': e.type });
      if (e.type === 'holder' && e.e && e.e.percent) path.style.strokeWidth = Math.max(1.5, Math.min(7, e.e.percent / 2)); // line width follows the stake
      if (!oldEdges[e.source + '>' + e.target] && !reduced()) { path.classList.add('g-enter'); path.style.animationDelay = (first ? 120 : 140) + 'ms'; }
      gE.appendChild(path); erecs.push({ p: path, s: e.source, t: e.target });
    });
    if (first && !reduced()) { gL.classList.add('g-enter'); gL.style.animationDelay = '350ms'; }
    svg.appendChild(gL); svg.appendChild(gE); svg.appendChild(leaving); svg.appendChild(gN);
    setTimeout(function () { if (leaving.parentNode) leaving.parentNode.removeChild(leaving); }, 320);
    // label widths, so edges heading outwards start past the text
    L.lanes.forEach(function (l) { try { l.w = l.el.getComputedTextLength(); } catch (err) { l.w = l.text.length * 8.6; } });
    S.lw = {};
    gN.querySelectorAll('.g-node').forEach(function (g) {
      var w = 0; g.querySelectorAll('text').forEach(function (t) { try { w = Math.max(w, t.getComputedTextLength()); } catch (err) { /* hidden */ } });
      var it = L.index[g.getAttribute('data-id')]; S.lw[it.id] = w + radius(it) - 2;
    });
    var target = S.userMoved ? null : startView();
    if (S.openFocus && L.open) { // frame the jurisdictions and the one just opened
      target = fitView(L.open.ids.concat(L.clusters.map(function (c) { return c.id; }))); S.userMoved = true;
    }
    S.openFocus = false;
    animate(recs, erecs, target);
    if (S.selected) { var cur = L.index[S.selected]; if (cur) { detail(cur, L); focusOn(cur.id); } else { S.selected = null; clearDetail(); } }
    if ($('g-find').value) { matchesFor($('g-find').value); lightMatches(); }
  }
  function animate(recs, erecs, view) {
    cancelAnimationFrame(S.anim);
    var dur = reduced() ? 0 : 700, t0 = performance.now(), v0 = S.view;
    S.recs = recs; S.erecs = erecs;
    function frame(now) {
      var done = true;
      recs.forEach(function (r) {
        var t = dur ? Math.max(0, Math.min(1, (now - t0 - r.delay) / dur)) : 1; if (t < 1) done = false;
        var k = ease(t), x = r.from.x + (r.to.x - r.from.x) * k, y = r.from.y + (r.to.y - r.from.y) * k;
        S.cur[r.id] = { x: x, y: y };
        r.g.setAttribute('transform', 'translate(' + x.toFixed(1) + ',' + y.toFixed(1) + ')');
      });
      erecs.forEach(function (r) { r.p.setAttribute('d', curve(anchor(r.s, r.t), anchor(r.t, r.s))); });
      if (view) { var t2 = dur ? Math.min(1, (now - t0) / dur) : 1, k2 = ease(t2); S.view = { x: v0.x + (view.x - v0.x) * k2, y: v0.y + (view.y - v0.y) * k2, w: v0.w + (view.w - v0.w) * k2, h: v0.h + (view.h - v0.h) * k2 }; applyView(); }
      if (!done) S.anim = requestAnimationFrame(frame);
    }
    // keep only the nodes on the page now
    var keep = {}; recs.forEach(function (r) { keep[r.id] = true; }); Object.keys(S.cur).forEach(function (id) { if (!keep[id]) delete S.cur[id]; });
    S.anim = requestAnimationFrame(frame);
  }
  function tweenView(to) {
    cancelAnimationFrame(S.vanim);
    var v0 = S.view, dur = reduced() ? 0 : 420, t0 = performance.now();
    function frame(now) {
      var t = dur ? Math.min(1, (now - t0) / dur) : 1, k = ease(t);
      S.view = { x: v0.x + (to.x - v0.x) * k, y: v0.y + (to.y - v0.y) * k, w: v0.w + (to.w - v0.w) * k, h: v0.h + (to.h - v0.h) * k }; applyView();
      if (t < 1) S.vanim = requestAnimationFrame(frame);
    }
    S.vanim = requestAnimationFrame(frame);
  }
  function zoomTo(id) {
    var ids = Object.keys(neighbours(id)); S.userMoved = true;
    var v = viewFor(bounds(ids), 40); if (v.w < 760) { var c = { x: v.x + v.w / 2, y: v.y + v.h / 2 }; v.h *= 760 / v.w; v.w = 760; v.x = c.x - v.w / 2; v.y = c.y - v.h / 2; }
    tweenView(v);
  }

  /* ---- hover, focus and selection ---- */
  function neighbours(id) {
    var set = {}; set[id] = true;
    (S.L ? S.L.edges : []).forEach(function (e) { if (e.source === id) set[e.target] = true; if (e.target === id) set[e.source] = true; });
    return set;
  }
  function light(nodeSet, edgeTest) {
    var svg = $('g-svg');
    svg.classList.toggle('g-focus', !!nodeSet);
    if (!nodeSet) { svg.querySelectorAll('.g-on').forEach(function (x) { x.classList.remove('g-on'); }); return; }
    svg.querySelectorAll('.g-nodes .g-node').forEach(function (g) { g.classList.toggle('g-on', !!nodeSet[g.getAttribute('data-id')]); });
    svg.querySelectorAll('.g-edge').forEach(function (l) { l.classList.toggle('g-on', edgeTest(l)); });
  }
  function focusOn(id) {
    if (!id) { light(null); return; }
    light(neighbours(id), function (l) { return l.getAttribute('data-s') === id || l.getAttribute('data-t') === id; });
  }
  function rest() { if (S.matches) lightMatches(); else focusOn(S.selected); }
  function select(it) {
    S.selected = it.id;
    $('g-svg').querySelectorAll('.g-node').forEach(function (g) { g.classList.toggle('g-sel', g.getAttribute('data-id') === it.id); });
    if (it.kind === 'cluster') { var open = !S.expanded[it.id]; S.expanded = {}; if (open) S.expanded[it.id] = true; S.userMoved = false; S.openFocus = open; render(); return; }
    detail(it, S.L); focusOn(it.id);
  }
  function deselect() { S.selected = null; $('g-svg').querySelectorAll('.g-sel').forEach(function (g) { g.classList.remove('g-sel'); }); clearDetail(); rest(); }
  function clearDetail() {
    var box = $('g-detail'); box.innerHTML = '';
    // nothing selected: the panel folds to a "How to read it" note (open on the first visit) and the graph widens
    var stage = box.closest('.g-stage'); if (stage) stage.classList.add('is-idle');
    var seen = false; try { seen = localStorage.getItem('prv-graph-help') === 'seen'; } catch (e) {}
    var how = el('details', { class: 'g-howto' });
    if (!seen) how.setAttribute('open', '');
    // only a reader's own click marks it seen (opening it here fires a toggle event too)
    how.querySelector ? setTimeout(function () { how.addEventListener('toggle', function () { try { localStorage.setItem('prv-graph-help', 'seen'); } catch (e) {} }); }, 0) : null;
    how.appendChild(el('summary', { text: 'How to read it' }));
    box.appendChild(how);
    how.appendChild(el('ul', { class: 'g-help' }, [
      el('li', { text: 'Hover a name to preview it and light up its links.' }),
      el('li', { text: 'Click for the role, the dates and the filing behind each line.' }),
      el('li', { text: 'Double-click to zoom into its connections; Fit returns.' }),
      el('li', { text: 'Click a jurisdiction to open its subsidiaries.' })
    ]));
  }
  function wireNode(g, it) {
    g.addEventListener('pointerenter', function (ev) { if (ev.pointerType === 'mouse') { focusOn(it.id); tip(it); } });
    g.addEventListener('pointerleave', function () { tip(null); rest(); });
    g.addEventListener('focus', function () { focusOn(it.id); tip(it); });
    g.addEventListener('blur', function () { tip(null); rest(); });
    g.addEventListener('click', function (ev) { ev.stopPropagation(); tip(null); select(it); });
    g.addEventListener('dblclick', function (ev) { ev.stopPropagation(); if (it.kind !== 'cluster') zoomTo(it.id); });
    g.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(it); } });
  }
  function tip(it) {
    var box = $('g-tip');
    if (!it) { box.hidden = true; return; }
    var p = S.cur[it.id] || S.pos[it.id], v = S.view, svg = $('g-svg');
    var sx = (p.x - v.x) / v.w * svg.clientWidth, sy = (p.y - v.y) / v.h * svg.clientHeight;
    box.innerHTML = '';
    var n = it.n || {}, det = n.detail || {}, facts = [];
    var kind = { center: 'This company', holder: '5% holder', insider: n.type === 'person' ? 'Insider' : 'Insider (entity)', interlock: 'Connected company', sub: 'Subsidiary', cluster: 'Jurisdiction' }[it.kind];
    if (it.sub) facts.push(it.sub);
    if (det.shares_held != null) facts.push(shares(det.shares_held) + ' shares held');
    var om = det.open_market_12m;
    if (om && (om.buys || om.sells)) facts.push('12 months: ' + (om.buys ? 'bought ' + money(om.bought_value) : '') + (om.buys && om.sells ? ', ' : '') + (om.sells ? 'sold ' + money(om.sold_value) : ''));
    box.appendChild(el('span', { class: 'g-tip-kind', text: kind }));
    box.appendChild(el('strong', { text: nodeLabel(it) }));
    facts.forEach(function (f) { box.appendChild(el('span', { text: f })); });
    box.appendChild(el('span', { class: 'g-tip-hint', text: it.kind === 'cluster' ? (S.expanded[it.id] ? 'Click to close' : 'Click to open') : 'Click for filings' }));
    box.hidden = false;
    var left = sx + (p.side < 0 ? -box.offsetWidth - 18 : 18);
    box.style.left = Math.max(6, Math.min(svg.clientWidth - box.offsetWidth - 6, left)) + 'px';
    box.style.top = Math.max(6, Math.min(svg.clientHeight - box.offsetHeight - 6, sy - box.offsetHeight / 2)) + 'px';
  }

  /* ---- find ---- */
  function matchesFor(q) {
    q = (q || '').trim().toLowerCase();
    var out = $('g-find-n');
    if (!q || !S.data) { S.matches = null; out.textContent = ''; return []; }
    var hits = S.data.nodes.filter(function (n) { return n.group !== 'center' && (n.label || '').toLowerCase().indexOf(q) !== -1; });
    out.textContent = hits.length ? hits.length + ' found' : 'none';
    S.matches = {}; hits.forEach(function (n) { S.matches[n.id] = true; });
    // a hit inside a closed jurisdiction lights the jurisdiction
    (S.L ? S.L.clusters : []).forEach(function (c) { if (c.members.some(function (m) { return S.matches[m.id]; })) S.matches[c.id] = true; });
    return hits;
  }
  function find(q, go) {
    var hits = matchesFor(q);
    if (!S.matches) { lightMatches(); rest(); return; }
    // an open jurisdiction shows the names found first
    if (S.L && S.L.open && hits.some(function (h) { return !S.L.index[h.id] && S.L.clusters.some(function (c) { return c.id === S.L.open.id && c.members.some(function (m) { return m.id === h.id; }); }); })) render();
    else lightMatches();
    if (go && hits.length) {
      var h = hits[0], c = (S.L.clusters || []).filter(function (c) { return c.members.some(function (m) { return m.id === h.id; }); })[0];
      if (c && !S.L.index[h.id]) { S.expanded = {}; S.expanded[c.id] = true; S.selected = h.id; S.openFocus = true; render(); return; }
      var it = S.L.index[h.id]; if (it) { select(it); zoomTo(h.id); }
    }
  }
  function lightMatches() {
    var m = S.matches;
    $('g-svg').querySelectorAll('.g-nodes .g-node').forEach(function (g) { g.classList.toggle('g-match', !!(m && m[g.getAttribute('data-id')])); });
    if (!m) return;
    light(m, function (l) { return !!(m[l.getAttribute('data-s')] && m[l.getAttribute('data-t')]); });
  }

  /* ---- details ---- */
  function kv(k, v) { return el('div', { class: 'g-kv' }, [el('dt', { text: k }), el('dd', {}, [typeof v === 'string' ? document.createTextNode(v) : v])]); }
  function openBtn(cik, name) {
    var b = el('button', { type: 'button', class: 'btn small', text: 'Open ' + short(name || 'CIK ' + cik, 28) });
    b.addEventListener('click', function () { X().open(cik); });
    return b;
  }
  function detail(it, L) {
    var stage0 = $('g-detail').closest('.g-stage'); if (stage0) stage0.classList.remove('is-idle');
    var box = $('g-detail'); box.innerHTML = '';
    box.classList.remove('g-pop'); void box.offsetWidth; box.classList.add('g-pop');
    var close = el('button', { type: 'button', class: 'g-close', 'aria-label': 'Clear the selection', text: '×' });
    close.addEventListener('click', deselect); box.appendChild(close);
    var d = S.data, n = it.n || {};
    if (it.kind === 'cluster') {
      box.appendChild(el('p', { class: 'eyebrow', text: 'Subsidiaries · jurisdiction' }));
      box.appendChild(el('h3', { text: it.label }));
      box.appendChild(el('p', { class: 'small', text: it.members.length + ' subsidiaries listed in ' + (d.sources.subsidiaries.exhibit || 'exhibit 21') + (it.fresh ? '; ' + it.fresh + ' new since the year before.' : '.') }));
      var ul = el('ul', { class: 'g-names' });
      it.members.slice(0, 60).forEach(function (m) { ul.appendChild(el('li', {}, [m.label + (it.other && m.detail && m.detail.jurisdiction ? ' · ' + m.detail.jurisdiction : ''), m.detail && m.detail.new_this_year ? el('span', { class: 'badge ok', text: 'new' }) : null])); });
      if (it.members.length > 60) ul.appendChild(el('li', { class: 'muted', text: '+' + (it.members.length - 60) + ' more in the Lists view' }));
      box.appendChild(ul);
      var col = el('button', { type: 'button', class: 'btn small', text: S.expanded[it.id] ? 'Collapse' : 'Show on the graph' });
      col.addEventListener('click', function () { var open = !S.expanded[it.id]; S.expanded = {}; if (open) S.expanded[it.id] = true; S.userMoved = false; S.openFocus = open; render(); });
      box.appendChild(el('div', { class: 'row' }, [col, link(d.sources.subsidiaries.filing, 'Exhibit source ↗')]));
      return;
    }
    var edges = d.edges.filter(function (e) { return e.source === it.id || e.target === it.id; });
    var kindText = it.kind === 'center' ? 'This company' : it.kind === 'holder' ? '5% holder' : it.kind === 'sub' ? 'Subsidiary' : it.kind === 'interlock' ? 'Connected company' : n.type === 'company' ? 'Company (insider)' : n.type === 'person' ? 'Insider' : 'Insider (entity)';
    box.appendChild(el('p', { class: 'eyebrow', text: kindText }));
    box.appendChild(el('h3', { text: n.label }));
    var dl = el('dl', { class: 'g-kvs' });
    var det = n.detail || {};
    if (n.cik) dl.appendChild(kv('CIK', n.cik));
    if (det.name_as_filed && det.name_as_filed !== n.label) dl.appendChild(kv('Name as filed', det.name_as_filed));
    if (it.kind === 'center') {
      var src = d.sources;
      if (src.insiders) dl.appendChild(kv('Insiders', src.insiders.current + ' current of ' + src.insiders.count));
      if (src.holders) dl.appendChild(kv('5% holders', String(src.holders.count)));
      if (src.subsidiaries) dl.appendChild(kv('Subsidiaries', String(src.subsidiaries.count)));
      if (src.interlocks) dl.appendChild(kv('Connected companies', String(src.interlocks.companies)));
    }
    if (det.jurisdiction !== undefined) dl.appendChild(kv('Jurisdiction', det.jurisdiction || 'not stated'));
    if (det.new_this_year) dl.appendChild(kv('Change', 'New since the previous exhibit 21'));
    if (det.holder_type) dl.appendChild(kv('Holder type', det.holder_type));
    if (det.shares_held != null) dl.appendChild(kv('Shares held', shares(det.shares_held) + ' after the latest report'));
    if (det.open_market_12m) {
      var om = det.open_market_12m;
      dl.appendChild(kv('Open market, 12 months', om.buys || om.sells ? 'bought ' + money(om.bought_value) + ' (' + om.buys + '), sold ' + money(om.sold_value) + ' (' + om.sells + ')' : 'no purchases or sales'));
    }
    if (det.group && det.group.length) dl.appendChild(kv('Filed with', det.group.join(', ')));
    box.appendChild(dl);
    if (it.kind !== 'center' && edges.length) {
      var list = el('ul', { class: 'g-edges-list' });
      edges.slice(0, 40).forEach(function (e) {
        var other = e.source === it.id ? e.target : e.source;
        var on = L.byId[other] ? L.byId[other].label : '';
        var when = e.type === 'subsidiary' ? '' : (e.since && e.since !== e.last ? ' · since ' + e.since : '') + (e.last ? ' · last filed ' + e.last : '');
        list.appendChild(el('li', {}, [
          el('span', { class: 'g-dot ' + (EDGE[e.type] ? EDGE[e.type].cls : '') }),
          el('span', {}, [el('strong', { text: e.label }), ' ', e.type === 'interlock' || e.type === 'subsidiary' ? (e.type === 'interlock' ? 'at ' : '') + on : '', el('span', { class: 'muted small', text: (e.current ? '' : ' · former') + when }), ' ', link(e.evidence)])
        ]));
      });
      box.appendChild(el('h4', { text: 'Connections and their filings' }));
      box.appendChild(list);
    }
    var zb = el('button', { type: 'button', class: 'btn small', text: it.kind === 'center' ? 'Fit the graph' : 'Zoom to its connections' });
    zb.addEventListener('click', function () { if (it.kind === 'center') { S.userMoved = false; tweenView(fitView()); } else zoomTo(it.id); });
    box.appendChild(el('div', { class: 'row' }, [n.cik && it.kind !== 'center' ? openBtn(n.cik, n.label) : null, zb]));
  }

  /* ---- summary, notes, legend ---- */
  function summary(d) {
    var s = d.sources, parts = [];
    if (s.insiders) parts.push(s.insiders.current + ' current insider' + (s.insiders.current === 1 ? '' : 's'));
    if (s.interlocks) parts.push(s.interlocks.companies + ' other compan' + (s.interlocks.companies === 1 ? 'y' : 'ies') + ' through them');
    if (s.holders) parts.push(s.holders.count + ' holder' + (s.holders.count === 1 ? '' : 's') + ' above 5%');
    if (s.subsidiaries) {
      var sub = s.subsidiaries.count + ' subsidiar' + (s.subsidiaries.count === 1 ? 'y' : 'ies');
      if (s.subsidiaries.added && s.subsidiaries.added.length && s.subsidiaries.previous) sub += ' (' + s.subsidiaries.added.length + ' new, ' + s.subsidiaries.removed.length + ' gone since ' + s.subsidiaries.previous.filing_date.slice(0, 4) + ')';
      parts.push(sub);
    }
    $('g-summary').textContent = (d.as_of ? 'As of ' + d.as_of + ': ' : '') + parts.join(' · ') + '.';
  }
  function notes(d) {
    var ul = $('g-notes'); ul.innerHTML = '';
    var s = d.sources;
    if (s.insiders) ul.appendChild(el('li', { text: 'Insiders: ' + s.insiders.note + (s.insiders.through ? ' Quarterly SEC data through ' + s.insiders.through + ', newer Forms 4 read from each filing.' : '') }));
    if (s.holders) ul.appendChild(el('li', { text: '5% holders: ' + s.holders.note + ' Line width follows the stake.' }));
    if (s.subsidiaries) {
      var li = el('li', { text: 'Subsidiaries: ' + s.subsidiaries.note + ' ' });
      if (s.subsidiaries.filing) li.appendChild(link(s.subsidiaries.filing, s.subsidiaries.exhibit + ' of the ' + s.subsidiaries.filing.form_type + ' filed ' + s.subsidiaries.filing.filing_date + ' ↗'));
      ul.appendChild(li);
    }
    if (s.interlocks) ul.appendChild(el('li', { text: 'Board interlocks: ' + s.interlocks.note }));
  }
  function legend() {
    var ul = $('g-legend'); if (ul.childNodes.length) return;
    var item = function (key, text, test) {
      var li = el('li', {}, [key, text]);
      if (test) { // hovering a key lights what it stands for
        li.classList.add('g-legend-live');
        li.addEventListener('mouseenter', function () {
          var on = {}, svg = $('g-svg');
          svg.querySelectorAll('.g-edge').forEach(function (l) { if (test.edge && test.edge(l)) { on[l.getAttribute('data-s')] = on[l.getAttribute('data-t')] = true; } });
          svg.querySelectorAll('.g-nodes .g-node').forEach(function (g) { if (test.node && test.node(g)) on[g.getAttribute('data-id')] = true; });
          light(on, function (l) { return !!(test.edge && test.edge(l)); });
        });
        li.addEventListener('mouseleave', rest);
      }
      ul.appendChild(li);
    };
    var kind = function (k) { return { node: function (g) { return g.classList.contains(k); } }; };
    var type = function (t) { return { edge: function (l) { return l.getAttribute('data-type') === t; } }; };
    item(el('span', { class: 'g-key g-center' }), 'This company', kind('k-center'));
    item(el('span', { class: 'g-key g-person' }), 'Person', { node: function (g) { return !!g.querySelector('.g-person'); } });
    item(el('span', { class: 'g-key g-company' }), 'Company in this API', { node: function (g) { return !!g.querySelector('.g-company'); } });
    item(el('span', { class: 'g-key g-holder' }), '5% holder', kind('k-holder'));
    item(el('span', { class: 'g-key g-sub' }), 'Subsidiary', { node: function (g) { return g.classList.contains('k-sub') || g.classList.contains('k-cluster'); } });
    ['officer', 'director', 'ten_percent_owner', 'holder', 'interlock'].forEach(function (k) { item(el('span', { class: 'g-key-line ' + EDGE[k].cls }), EDGE[k].label, type(k)); });
    item(el('span', { class: 'g-key g-new' }), 'New this year', { node: function (g) { return !!g.querySelector('.g-sub.g-new'); } });
  }
  function counts(d) { // the layer switches show how many each one adds
    var s = d.sources, n = { insiders: s.insiders && ($('g-former').checked ? s.insiders.count : s.insiders.current), interlocks: s.interlocks && s.interlocks.companies, holders: s.holders && s.holders.count, subsidiaries: s.subsidiaries && s.subsidiaries.count };
    S.counts = S.counts && S.counts.cik === d.company.cik ? S.counts : { cik: d.company.cik };
    Object.keys(n).forEach(function (k) { if (n[k] != null) S.counts[k] = n[k]; var c = document.querySelector('[data-count="' + k + '"]'); if (c) c.textContent = S.counts[k] != null ? String(S.counts[k]) : ''; });
  }

  /* ---- lists ---- */
  function table(head, rows, num) {
    var t = el('table', {}, [el('thead', {}, [el('tr', {}, head.map(function (h, i) { return el('th', { class: num && num.indexOf(i) !== -1 ? 'num' : '', text: h }); }))])]);
    var tb = el('tbody'); rows.forEach(function (r) { tb.appendChild(el('tr', {}, r.map(function (c, i) { var td = el('td', { class: num && num.indexOf(i) !== -1 ? 'num' : '' }); td.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); return td; }))); });
    t.appendChild(tb);
    return el('div', { class: 'table-wrap' }, [t]);
  }
  function nameCell(n) {
    if (n && n.cik) { var b = el('button', { type: 'button', class: 'linkish', text: n.label }); b.addEventListener('click', function () { X().open(n.cik); }); return b; }
    return document.createTextNode(n ? n.label : '');
  }
  function lists(d) {
    var box = $('g-lists'); box.innerHTML = '';
    var byId = {}; d.nodes.forEach(function (n) { byId[n.id] = n; });
    var cid = 'company:' + d.company.cik;
    var ins = d.edges.filter(function (e) { return e.target === cid && e.type !== 'holder'; });
    if (ins.length) {
      box.appendChild(el('h3', { text: 'Insiders' }));
      box.appendChild(table(['Name', 'Role', 'Since', 'Last filed', 'Shares held', 'Bought, 12m', 'Sold, 12m', 'Also at', 'Filing'], ins.map(function (e) {
        var n = byId[e.source], det = n.detail || {}, om = det.open_market_12m;
        var also = d.edges.filter(function (x) { return x.source === e.source && x.type === 'interlock'; }).map(function (x) { return byId[x.target].label; });
        return [nameCell(n), e.label + (e.current ? '' : ' (former)'), e.since || '—', e.last || '—', shares(det.shares_held), om ? money(om.bought_value) : '—', om ? money(om.sold_value) : '—', short(also.join('; '), 60) || '—', link(e.evidence)];
      }), [4, 5, 6]));
    }
    var hs = d.edges.filter(function (e) { return e.type === 'holder'; });
    if (hs.length) {
      box.appendChild(el('h3', { text: 'Holders above 5%' }));
      box.appendChild(table(['Holder', 'Stake', 'Shares', 'Last filed', 'Filing'], hs.map(function (e) { return [nameCell(byId[e.source]), e.percent != null ? e.percent + '%' : '—', shares(e.shares), e.last, link(e.evidence)]; }), [1, 2]));
    }
    var inter = d.edges.filter(function (e) { return e.type === 'interlock'; });
    if (inter.length) {
      box.appendChild(el('h3', { text: 'Board interlocks and other roles' }));
      box.appendChild(table(['Insider', 'Company', 'Role there', 'Last filed', 'Filing'], inter.map(function (e) { return [byId[e.source].label, nameCell(byId[e.target]), e.label, e.last, link(e.evidence)]; })));
    }
    var subs = d.edges.filter(function (e) { return e.type === 'subsidiary'; });
    if (subs.length) {
      var s = d.sources.subsidiaries;
      box.appendChild(el('h3', { text: 'Subsidiaries (' + s.count + (s.count > s.shown ? ', first ' + s.shown + ' shown' : '') + ')' }));
      box.appendChild(table(['Name', 'Jurisdiction', 'Group', 'Change'], subs.map(function (e) { var n = byId[e.target], det = n.detail || {}; return [nameCell(n), det.jurisdiction || '—', det.jurisdiction_group || '—', det.new_this_year ? 'new' : '']; })));
      if (s.removed && s.removed.length) box.appendChild(el('p', { class: 'small muted', text: 'No longer listed since ' + s.previous.filing_date + ': ' + s.removed.join('; ') }));
    }
    var txBox = el('div'); box.appendChild(el('h3', { text: 'Recent insider transactions' })); box.appendChild(txBox);
    var q = '/v1/companies/' + d.company.cik + '/insider-transactions?limit=20' + (d.as_of ? '&as_of=' + d.as_of : '');
    X().api(q).then(function (res) {
      var rows = res.body.data;
      if (!rows.length) { txBox.appendChild(el('p', { class: 'muted small', text: 'No transactions loaded for this company yet.' })); return; }
      txBox.appendChild(table(['Date', 'Insider', 'Role', 'Transaction', 'Shares', 'Price', 'Value', 'Held after', '10b5-1', 'Filing'], rows.map(function (t) {
        return [t.trans_date || '—', t.owner_name, short(t.role, 34), (t.trans_code_label || t.trans_code || '—') + (t.is_derivative ? ' (derivative)' : ''), shares(t.shares), t.price != null ? '$' + Number(t.price).toFixed(2) : '—', money(t.value), shares(t.shares_after), t.plan_10b5_1 ? 'yes' : '', link({ source_url: t.source_url, form_type: t.form_type, filing_date: t.filing_date })];
      }), [4, 5, 6, 7]));
    }).catch(function () {});
  }

  /* ---- pan and zoom ---- */
  function applyView() { var v = S.view; $('g-svg').setAttribute('viewBox', [v.x, v.y, v.w, v.h].map(function (n) { return n.toFixed(1); }).join(' ')); }
  function zoomed(f, cx, cy) {
    var v = S.view, w = Math.max(160, Math.min(8000, v.w * f)), h = w * v.h / v.w;
    if (cx == null) { cx = v.x + v.w / 2; cy = v.y + v.h / 2; }
    return { x: cx - (cx - v.x) * w / v.w, y: cy - (cy - v.y) * h / v.h, w: w, h: h };
  }
  function zoom(f, cx, cy) { S.userMoved = true; S.view = zoomed(f, cx, cy); applyView(); }
  function point(svg, ev) { var r = svg.getBoundingClientRect(), v = S.view; return { x: v.x + (ev.clientX - r.left) / r.width * v.w, y: v.y + (ev.clientY - r.top) / r.height * v.h }; }
  function wire() {
    var svg = $('g-svg'); if (!svg) return;
    var drag = null, touches = {}, pinch = null, hintT = null;
    var dist = function () { var k = Object.keys(touches); if (k.length < 2) return 0; var a = touches[k[0]], b = touches[k[1]]; return Math.hypot(a.x - b.x, a.y - b.y); };
    svg.addEventListener('pointerdown', function (ev) { touches[ev.pointerId] = { x: ev.clientX, y: ev.clientY }; if (Object.keys(touches).length === 2) { drag = null; pinch = dist(); } });
    svg.addEventListener('pointermove', function (ev) {
      if (!touches[ev.pointerId]) return; touches[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      if (pinch) { var now = dist(); if (now > 0) { var k = Object.keys(touches), mid = { clientX: (touches[k[0]].x + touches[k[1]].x) / 2, clientY: (touches[k[0]].y + touches[k[1]].y) / 2 }, p = point(svg, mid); zoom(pinch / now, p.x, p.y); pinch = now; } }
    });
    var lift = function (ev) { delete touches[ev.pointerId]; if (Object.keys(touches).length < 2) pinch = null; };
    svg.addEventListener('pointerup', lift); svg.addEventListener('pointercancel', lift);
    svg.addEventListener('wheel', function (ev) {
      if (!ev.ctrlKey && !ev.metaKey && !ev.altKey) { // the page scrolls; say how to zoom
        var h = $('g-wheel'); h.hidden = false; h.classList.add('g-show'); clearTimeout(hintT);
        hintT = setTimeout(function () { h.classList.remove('g-show'); }, 1100); return;
      }
      ev.preventDefault(); cancelAnimationFrame(S.vanim); var p = point(svg, ev); zoom(ev.deltaY > 0 ? 1.12 : 1 / 1.12, p.x, p.y);
    }, { passive: false });
    svg.addEventListener('pointerdown', function (ev) {
      if (ev.target.closest('.g-node') || pinch) return;
      cancelAnimationFrame(S.vanim);
      drag = { x: ev.clientX, y: ev.clientY, v: S.view, moved: false }; svg.setPointerCapture(ev.pointerId);
    });
    svg.addEventListener('pointermove', function (ev) {
      if (!drag || pinch) return; var r = svg.getBoundingClientRect();
      if (!drag.moved && Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < 4) return;
      drag.moved = true; S.userMoved = true; svg.classList.add('g-dragging');
      S.view = { x: drag.v.x - (ev.clientX - drag.x) / r.width * drag.v.w, y: drag.v.y - (ev.clientY - drag.y) / r.height * drag.v.h, w: drag.v.w, h: drag.v.h }; applyView();
    });
    var end = function () { if (drag && drag.moved) S.dragged = Date.now(); drag = null; svg.classList.remove('g-dragging'); };
    svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);
    svg.addEventListener('click', function (ev) { if (!ev.target.closest('.g-node') && !(S.dragged && Date.now() - S.dragged < 250)) deselect(); });
    svg.addEventListener('dblclick', function (ev) { if (ev.target.closest('.g-node')) return; var p = point(svg, ev); S.userMoved = true; tweenView(zoomed(1 / 1.6, p.x, p.y)); });
    $('g-zin').addEventListener('click', function () { S.userMoved = true; tweenView(zoomed(1 / 1.35)); });
    $('g-zout').addEventListener('click', function () { S.userMoved = true; tweenView(zoomed(1.35)); });
    $('g-zreset').addEventListener('click', function () { S.userMoved = false; tweenView(fitView()); });
    ['g-insiders', 'g-interlocks', 'g-holders', 'g-subsidiaries', 'g-former', 'g-asof'].forEach(function (id) { $(id).addEventListener('change', function () { S.polls = 0; S.userMoved = false; load(); }); });
    var findT = null;
    $('g-find').addEventListener('input', function () { clearTimeout(findT); var v = this.value; findT = setTimeout(function () { find(v, false); }, 120); });
    $('g-find').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); find(this.value, true); } if (ev.key === 'Escape') { this.value = ''; find('', false); } });
    $('g-stage').addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && ev.target.id !== 'g-find') { deselect(); if (S.userMoved) { S.userMoved = false; tweenView(startView()); } } });
    document.querySelectorAll('[data-gview]').forEach(function (b) {
      b.addEventListener('click', function () {
        S.mode = b.getAttribute('data-gview');
        document.querySelectorAll('[data-gview]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
        $('g-find-wrap').hidden = S.mode !== 'graph';
        if (S.mode === 'graph') { S.cur = {}; S.userMoved = false; }
        render();
      });
    });
    var resizeT = null;
    window.addEventListener('resize', function () { clearTimeout(resizeT); resizeT = setTimeout(function () { if (S.mode === 'graph' && S.L && !S.userMoved) { S.view = startView(); applyView(); } }, 150); });
    clearDetail();
  }
  wire();
  if (window.matchMedia && window.matchMedia('(max-width: 640px)').matches) {
    S.mode = 'list'; $('g-find-wrap').hidden = true;
    document.querySelectorAll('[data-gview]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.getAttribute('data-gview') === 'list')); });
  }
  window.ProvenanceGraph = { load: load };
})();
