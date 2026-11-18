/* Provenance Explorer, Connections tab: a company's insiders (Forms 3, 4, 5), the other
   companies those insiders report on, its 5% holders (13D/G) and its subsidiaries (exhibit 21),
   drawn as one graph from GET /v1/companies/{cik}/graph. Every edge links its filing. Text from
   the API is set with textContent only. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var VIEW = { x: -640, y: -400, w: 1280, h: 800 };
  var CLUSTER_AT = 24; // more subsidiaries than this are grouped by jurisdiction
  var S = { company: null, data: null, view: VIEW, mode: 'graph', expanded: {}, selected: null, polls: 0, timer: null, tx: null, pos: {} };
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

  var EDGE = {
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
    if (company) { if (!S.company || S.company.cik !== company.cik) { S.expanded = {}; S.selected = null; S.view = VIEW; S.tx = null; } S.company = company; }
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
     Upstream on the left (5% holders, then insiders; the other companies those insiders serve
     further left), downstream on the right (subsidiaries, grouped by jurisdiction when many).
     Columns keep every label horizontal and apart; the view is then fitted to the content. */
  var STEP = 19, COL = 250, OUTER = 330;
  function column(items, side, gapAfter) {
    var ys = [], y = 0, step = items.length && items[0].kind === 'cluster' ? 30 : STEP;
    items.forEach(function (it, i) { ys.push(y); y += step + (gapAfter != null && i === gapAfter ? STEP : 0); });
    var half = (y - step) / 2 || 1;
    items.forEach(function (it, i) {
      var yy = ys[i] - half, t = yy / Math.max(half, 130);
      S.pos[it.id] = { x: side * (COL - 70 * t * t), y: yy, side: side };
    });
  }
  function spread(list, x, side) { // [{it, y}] sorted by wanted y; keep STEP apart around their mean
    if (!list.length) return;
    list.sort(function (a, b) { return a.y - b.y; });
    var want = list.reduce(function (s, p) { return s + p.y; }, 0) / list.length;
    for (var i = 1; i < list.length; i++) if (list[i].y - list[i - 1].y < STEP) list[i].y = list[i - 1].y + STEP;
    var got = list.reduce(function (s, p) { return s + p.y; }, 0) / list.length;
    list.forEach(function (p) { S.pos[p.it.id] = { x: x, y: p.y + want - got, side: side }; });
  }
  function layout(d) {
    var byId = {}, center = null;
    d.nodes.forEach(function (n) { byId[n.id] = n; if (n.group === 'center') center = n; });
    var nodes = [], edges = [];
    S.pos = {};
    S.pos[center.id] = { x: 0, y: 0, side: 0 };
    nodes.push({ id: center.id, n: center, kind: 'center' });
    var holders = d.nodes.filter(function (n) { return n.group === 'holders'; }).map(function (n) { return { id: n.id, n: n, kind: 'holder' }; });
    var insiders = d.nodes.filter(function (n) { return n.group === 'insiders'; }).map(function (n) { return { id: n.id, n: n, kind: 'insider' }; });
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
    }
    var left = holders.concat(insiders);
    var right = clusters.length ? clusters : subs.map(function (n) { return { id: n.id, n: n, kind: 'sub' }; });
    column(left, -1, holders.length && insiders.length ? holders.length - 1 : null);
    column(right, 1, null);
    nodes = nodes.concat(left, right);
    // expanded jurisdiction: its subsidiaries in an outer column beside it
    clusters.forEach(function (c) {
      if (!S.expanded[c.id]) return;
      var shown = c.members.slice(0, 120), per = 30, cols = Math.ceil(shown.length / per);
      shown.forEach(function (m, i) {
        var col = Math.floor(i / per), row = i % per, rows = Math.min(per, shown.length - col * per);
        S.pos[m.id] = { x: COL + OUTER + col * 270, y: S.pos[c.id].y + (row - (rows - 1) / 2) * STEP, side: 1 };
      });
      if (cols > 1) S.expandedCols = cols;
      shown.forEach(function (m) { nodes.push({ id: m.id, n: m, kind: 'sub' }); edges.push({ source: c.id, target: m.id, type: 'subsidiary', e: null }); });
    });
    // other companies of the insiders: an outer column level with the insiders who link them
    var inter = d.nodes.filter(function (n) { return n.group === 'interlocks'; }).map(function (n) {
      var ys = d.edges.filter(function (e) { return e.target === n.id && S.pos[e.source]; }).map(function (e) { return S.pos[e.source].y; });
      return { it: { id: n.id, n: n, kind: 'interlock' }, y: ys.length ? ys.reduce(function (a, b) { return a + b; }, 0) / ys.length : 0 };
    });
    spread(inter, -(COL + OUTER), -1);
    inter.forEach(function (p) { nodes.push(p.it); });
    d.edges.forEach(function (e) {
      var s = e.source, t = e.target;
      if (clusters.length && e.type === 'subsidiary') {
        var c = clusters.filter(function (c) { return c.members.some(function (m) { return m.id === t; }); })[0];
        if (c && !S.pos[t]) { if (!edges.some(function (x) { return x.target === c.id; })) edges.push({ source: s, target: c.id, type: 'subsidiary', e: null, cluster: c }); return; }
        if (c) s = c.id;
      }
      if (S.pos[s] && S.pos[t]) edges.push({ source: s, target: t, type: e.type, e: e });
    });
    return { nodes: nodes, edges: edges, byId: byId, clusters: clusters };
  }
  function fit() {
    var minX = -140, maxX = 140, minY = -60, maxY = 60;
    Object.keys(S.pos).forEach(function (id) {
      var p = S.pos[id];
      minX = Math.min(minX, p.x - (p.side < 0 ? 245 : 20)); maxX = Math.max(maxX, p.x + (p.side > 0 ? 245 : 20));
      minY = Math.min(minY, p.y - 24); maxY = Math.max(maxY, p.y + 40);
    });
    var svg = $('g-svg'), aspect = svg.clientWidth && svg.clientHeight ? svg.clientWidth / svg.clientHeight : 1.6;
    var w = maxX - minX, h = maxY - minY;
    if (w / h > aspect) h = w / aspect; else w = h * aspect;
    S.fitView = { x: (minX + maxX) / 2 - w / 2, y: (minY + maxY) / 2 - h / 2, w: w, h: h };
    S.view = S.fitView;
  }

  /* ---- drawing ---- */
  function shape(it) {
    var n = it.n || {}, k = it.kind;
    if (k === 'center') return sv('rect', { x: -15, y: -15, width: 30, height: 30, rx: 6, class: 'g-shape g-center' });
    if (k === 'cluster') return sv('circle', { r: clusterR(it), class: 'g-shape g-cluster' });
    if (n.type === 'company') return sv('rect', { x: -8, y: -8, width: 16, height: 16, rx: 3, class: 'g-shape g-company' });
    if (k === 'sub') return sv('rect', { x: -5, y: -5, width: 10, height: 10, rx: 2, class: 'g-shape g-sub' + (n.detail && n.detail.new_this_year ? ' g-new' : '') });
    if (k === 'holder') return sv('path', { d: 'M0 -10 L10 0 L0 10 L-10 0 Z', class: 'g-shape g-holder' });
    return sv('circle', { r: n.type === 'person' ? 7 : 8, class: 'g-shape ' + (n.type === 'person' ? 'g-person' : 'g-org') });
  }
  function clusterR(it) { return Math.min(13, 5 + Math.sqrt(it.members.length) * 1.1); }
  function nodeLabel(it) {
    if (it.kind === 'cluster') return it.label + ' · ' + it.members.length + (it.fresh ? ' (+' + it.fresh + ' new)' : '');
    return it.n.label;
  }
  function render() {
    var d = S.data; if (!d) return;
    summary(d); notes(d); legend();
    $('g-stage').hidden = S.mode !== 'graph'; $('g-lists').hidden = S.mode !== 'list';
    if (S.mode === 'list') { lists(d); return; }
    var L = layout(d); S.L = L;
    var svg = $('g-svg'); var title = $('g-svg-title');
    while (svg.lastChild && svg.lastChild !== title) svg.removeChild(svg.lastChild);
    while (svg.firstChild !== title) svg.removeChild(svg.firstChild);
    title.textContent = (d.company.name || 'Company') + ': ' + d.nodes.length + ' connected people, companies and subsidiaries. The Lists view has the same data as tables.';
    var gE = sv('g', { class: 'g-edges' }), gN = sv('g', { class: 'g-nodes' });
    L.edges.forEach(function (e) {
      var a = S.pos[e.source], b = S.pos[e.target];
      var cls = 'g-edge ' + (EDGE[e.type] ? EDGE[e.type].cls : '') + (e.e && !e.e.current ? ' e-former' : '');
      var w = e.type === 'holder' && e.e && e.e.percent ? Math.max(1.5, Math.min(7, e.e.percent / 2)) : null;
      var line = sv('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: cls, 'data-s': e.source, 'data-t': e.target });
      if (w) line.setAttribute('stroke-width', w);
      gE.appendChild(line);
    });
    L.nodes.forEach(function (it) {
      var p = S.pos[it.id];
      var g = sv('g', { class: 'g-node k-' + it.kind + (it.quiet ? ' g-quiet' : '') + (S.selected === it.id ? ' g-sel' : ''), transform: 'translate(' + p.x.toFixed(1) + ',' + p.y.toFixed(1) + ')', 'data-id': it.id });
      var t = sv('title', {}); t.textContent = nodeLabel(it); g.appendChild(t);
      g.appendChild(shape(it));
      var right = p.side >= 0;
      var text = sv('text', it.kind === 'center' ? { y: 34, 'text-anchor': 'middle', class: 'g-label g-center-label' } : { x: (right ? 1 : -1) * (it.kind === 'cluster' ? clusterR(it) + 6 : 13), y: 4, 'text-anchor': right ? 'start' : 'end', class: 'g-label' });
      text.textContent = it.kind === 'center' ? short(it.n.label, 40) : short(nodeLabel(it), 30);
      g.appendChild(text);
      g.addEventListener('mouseenter', function () { focusOn(it.id, L); });
      g.addEventListener('mouseleave', function () { focusOn(S.selected, L); });
      g.addEventListener('click', function (ev) { ev.stopPropagation(); select(it, L); });
      gN.appendChild(g);
    });
    svg.appendChild(gE); svg.appendChild(gN);
    if (S.refit !== false) fit();
    S.refit = true;
    applyView();
    if (S.selected) { var cur = L.nodes.filter(function (n) { return n.id === S.selected; })[0]; if (cur) { detail(cur, L); focusOn(cur.id, L); } else S.selected = null; }
  }
  function neighbours(id, L) {
    var set = {}; set[id] = true;
    L.edges.forEach(function (e) { if (e.source === id) set[e.target] = true; if (e.target === id) set[e.source] = true; });
    return set;
  }
  function focusOn(id, L) {
    var svg = $('g-svg');
    svg.classList.toggle('g-focus', !!id);
    if (!id) return;
    var near = neighbours(id, L);
    svg.querySelectorAll('.g-node').forEach(function (g) { g.classList.toggle('g-on', !!near[g.getAttribute('data-id')]); });
    svg.querySelectorAll('.g-edge').forEach(function (l) { l.classList.toggle('g-on', l.getAttribute('data-s') === id || l.getAttribute('data-t') === id); });
  }
  function select(it, L) {
    S.selected = it.id;
    $('g-svg').querySelectorAll('.g-node').forEach(function (g) { g.classList.toggle('g-sel', g.getAttribute('data-id') === it.id); });
    if (it.kind === 'cluster' && !S.expanded[it.id]) { S.expanded = {}; S.expanded[it.id] = true; render(); return; }
    detail(it, L); focusOn(it.id, L);
  }

  /* ---- details ---- */
  function kv(k, v) { return el('div', { class: 'g-kv' }, [el('dt', { text: k }), el('dd', {}, [typeof v === 'string' ? document.createTextNode(v) : v])]); }
  function openBtn(cik, name) {
    var b = el('button', { type: 'button', class: 'btn small', text: 'Open ' + short(name || 'CIK ' + cik, 28) });
    b.addEventListener('click', function () { X().open(cik); });
    return b;
  }
  function detail(it, L) {
    var box = $('g-detail'); box.innerHTML = '';
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
      col.addEventListener('click', function () { if (S.expanded[it.id]) delete S.expanded[it.id]; else { S.expanded = {}; S.expanded[it.id] = true; } render(); });
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
    if (n.cik && it.kind !== 'center') box.appendChild(el('div', { class: 'row' }, [openBtn(n.cik, n.label)]));
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
    [['g-center', 'This company'], ['g-person', 'Person'], ['g-company', 'Company in this API'], ['g-holder', '5% holder'], ['g-sub', 'Subsidiary'], ['g-cluster', 'Subsidiaries by jurisdiction']].forEach(function (x) {
      ul.appendChild(el('li', {}, [el('span', { class: 'g-key ' + x[0] }), x[1]]));
    });
    ['officer', 'director', 'ten_percent_owner', 'holder', 'interlock'].forEach(function (k) {
      ul.appendChild(el('li', {}, [el('span', { class: 'g-key-line ' + EDGE[k].cls }), EDGE[k].label]));
    });
    ul.appendChild(el('li', { class: 'g-hint', text: 'Drag to move; pinch, Ctrl or ⌘ + scroll, or the buttons to zoom.' }));
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
  function zoom(f, cx, cy) {
    var v = S.view, w = Math.max(160, Math.min(6000, v.w * f)), h = w * v.h / v.w;
    if (cx == null) { cx = v.x + v.w / 2; cy = v.y + v.h / 2; }
    S.view = { x: cx - (cx - v.x) * w / v.w, y: cy - (cy - v.y) * h / v.h, w: w, h: h }; applyView();
  }
  function point(svg, ev) { var r = svg.getBoundingClientRect(), v = S.view; return { x: v.x + (ev.clientX - r.left) / r.width * v.w, y: v.y + (ev.clientY - r.top) / r.height * v.h }; }
  function wire() {
    var svg = $('g-svg'); if (!svg) return;
    var drag = null, touches = {}, pinch = null;
    var dist = function () { var k = Object.keys(touches); if (k.length < 2) return 0; var a = touches[k[0]], b = touches[k[1]]; return Math.hypot(a.x - b.x, a.y - b.y); };
    svg.addEventListener('pointerdown', function (ev) { touches[ev.pointerId] = { x: ev.clientX, y: ev.clientY }; if (Object.keys(touches).length === 2) { drag = null; pinch = dist(); } });
    svg.addEventListener('pointermove', function (ev) {
      if (!touches[ev.pointerId]) return; touches[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      if (pinch) { var now = dist(); if (now > 0) { var k = Object.keys(touches), mid = { clientX: (touches[k[0]].x + touches[k[1]].x) / 2, clientY: (touches[k[0]].y + touches[k[1]].y) / 2 }, p = point(svg, mid); zoom(pinch / now, p.x, p.y); pinch = now; } }
    });
    var lift = function (ev) { delete touches[ev.pointerId]; if (Object.keys(touches).length < 2) pinch = null; };
    svg.addEventListener('pointerup', lift); svg.addEventListener('pointercancel', lift);
    svg.addEventListener('wheel', function (ev) { if (!ev.ctrlKey && !ev.metaKey && !ev.altKey) return; ev.preventDefault(); var p = point(svg, ev); zoom(ev.deltaY > 0 ? 1.15 : 1 / 1.15, p.x, p.y); }, { passive: false });
    svg.addEventListener('pointerdown', function (ev) { if (ev.target.closest('.g-node') || pinch) return; drag = { x: ev.clientX, y: ev.clientY, v: S.view }; svg.setPointerCapture(ev.pointerId); svg.classList.add('g-dragging'); });
    svg.addEventListener('pointermove', function (ev) { if (!drag || pinch) return; var r = svg.getBoundingClientRect(); S.view = { x: drag.v.x - (ev.clientX - drag.x) / r.width * drag.v.w, y: drag.v.y - (ev.clientY - drag.y) / r.height * drag.v.h, w: drag.v.w, h: drag.v.h }; applyView(); });
    var end = function () { drag = null; svg.classList.remove('g-dragging'); };
    svg.addEventListener('pointerup', end); svg.addEventListener('pointercancel', end);
    svg.addEventListener('click', function (ev) { if (!ev.target.closest('.g-node')) { S.selected = null; focusOn(null); } });
    $('g-zin').addEventListener('click', function () { zoom(1 / 1.3); });
    $('g-zout').addEventListener('click', function () { zoom(1.3); });
    $('g-zreset').addEventListener('click', function () { S.view = S.fitView || VIEW; applyView(); });
    ['g-insiders', 'g-interlocks', 'g-holders', 'g-subsidiaries', 'g-former', 'g-asof'].forEach(function (id) { $(id).addEventListener('change', function () { S.polls = 0; load(); }); });
    document.querySelectorAll('[data-gview]').forEach(function (b) {
      b.addEventListener('click', function () {
        S.mode = b.getAttribute('data-gview');
        document.querySelectorAll('[data-gview]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
        render();
      });
    });
  }
  wire();
  if (window.matchMedia && window.matchMedia('(max-width: 640px)').matches) {
    S.mode = 'list';
    document.querySelectorAll('[data-gview]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.getAttribute('data-gview') === 'list')); });
  }
  window.ProvenanceGraph = { load: load };
})();
