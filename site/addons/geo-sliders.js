/* geo-sliders.js: geography and community constraint layers for the Draw toy (redistricting fork add-on).

   In short (for people): adds six sliders beside the page's state-line, river and commuting-zone sliders:
   mountains and ridges (USGS elevation), watersheds (USGS river basins), USGS rivers and lakes, drive time
   (Census road map), towns and school districts (Census). Turned up, the solver prefers to draw district lines
   along ridges, basin divides and big rivers, between places far apart by road, and along town and school-district
   lines. Each row's box draws the layer on the map. At 0 nothing changes.

   For AI agents (detailed): loaded by ensemble-panel.js on the Draw page only. Reads
   ../data/layers/geo/<ST>.json (redistricting_addons/geo_layers.py): per site edge (data.edges order, then
   data.bridges) ridge (m), river (highest Strahler order crossed, USGS 1:1M), lake (km2), travel (tenths of a minute), dist (km/100);
   per unit huc8, huc10, town, school (-1 none). Display data, loaded when a box is first ticked:
   <ST>.shapes.json (x, y rings) and <ST>.relief.png (shaded relief, bounds in the JSON's relief field).
   Each layer gives every edge a factor F in [0, 1+]: ridge min(1, ridge / 300 m); watersheds 1 when the endpoints'
   HUC8 (or HUC10) differ; rivers 1 when the link crosses a river of at least the chosen order or a lake;
   drive time min(3, max(0, r - 1)) with r = (minutes per km of the link) / (the state's median minutes per km),
   so the solver measures distance more like driving time; towns / school districts 1 when the endpoints' groups
   differ and at least one is in one. Wraps DrawEngine.penalize (the page's own function, and any other wrapper,
   is called first): CSR edge lengths are multiplied by 1 + sum(lambda_k * F_k) and the same sum is added to
   prep.edgePen, the mechanism and steps (LAM_STEPS) of the page's own sliders. Only adds: no page code changes. */
(function () {
  'use strict';
  if (typeof DX === 'undefined' || !DX || typeof DX.penalize !== 'function' || !document.getElementById('layers')) return;
  if (DX.__geoWrapped) return;
  DX.__geoWrapped = true;
  const STEPS = [0, 0.5, 1, 2, 5, 10, 20, 50, 100];
  const BASE = (typeof __RD_DATA_BASE !== 'undefined' ? __RD_DATA_BASE : '../data/') + 'layers/geo/';
  const LAYERS = [
    { key: 'ridge', label: 'mountains &amp; ridges', color: '#9a7b56', sub: 'ridge',
      title: 'USGS 3DEP elevation: the climb over the highest ground between two neighbouring block groups' },
    { key: 'water', label: 'watersheds', color: '#2a9d8f', sub: 'basin', select: [['huc8', 'river basins (8-digit)'], ['huc10', 'watersheds (10-digit)']],
      title: 'USGS Watershed Boundary Dataset: neighbours that drain to different rivers' },
    { key: 'river', label: 'USGS rivers &amp; lakes', color: '#3b82c4', sub: 'river', select: [['4', 'rivers (order 4+)'], ['5', 'large (order 5+)'], ['6', 'largest (order 6+)']],
      title: 'USGS 1:1,000,000 streams (from the NHD): links crossing a river of at least this Strahler order, or a lake or reservoir of 4 km² or more' },
    { key: 'travel', label: 'drive time', color: '#d1495b', sub: 'drive',
      title: 'Census TIGER roads: links that take longer to drive than the state\'s usual minutes per km grow longer (up to 4×)' },
    { key: 'town', label: 'towns', color: '#7b5ea7', sub: 'town', dash: [5, 3],
      title: 'Census 2020: incorporated places, else county subdivisions with their own government (towns, townships)' },
    { key: 'school', label: 'school districts', color: '#e09f3e', sub: 'school', dash: [2, 3],
      title: 'Census 2020: unified school districts, else secondary, else elementary' },
  ];
  const st = { abbr: null, data: null, shapes: null, relief: null, F: {}, lam: {}, opt: { water: 'huc8', river: '4' }, show: {} };
  LAYERS.forEach(l => { st.lam[l.key] = 0; st.show[l.key] = false; });
  window.__RD_GEO = st;
  const orig = DX.penalize;
  let csr = { base: null, map: null };
  const $ = id => document.getElementById(id);

  function factors() {
    const L = st.data; if (!L) return;
    const D = S.data, m = L.edges, b = L.bridges, n = m + b;
    const E = new Int32Array(2 * n);
    for (let t = 0; t < 2 * m; t++) E[t] = D.edges[t];
    for (let t = 0; t < 2 * b; t++) E[2 * m + t] = D.bridges[t];
    st.E = E;
    const cat = (a, c) => a.concat(c || []);
    const ridge = cat(L.ridge, L.bridge_ridge), river = cat(L.river, L.bridge_river), lake = cat(L.lake, L.bridge_lake);
    const travel = cat(L.travel, L.bridge_travel), dist = cat(L.dist, L.bridge_dist);
    const med = (L.counts && L.counts.median_minutes_per_km) || 2;
    const grp = L[st.opt.water], thr = +st.opt.river;
    const F = { ridge: new Float32Array(n), water: new Float32Array(n), river: new Float32Array(n), travel: new Float32Array(n),
      town: new Float32Array(n), school: new Float32Array(n) };
    for (let t = 0; t < n; t++) {
      const a = E[2 * t], c = E[2 * t + 1];
      F.ridge[t] = Math.min(1, ridge[t] / 300);
      F.water[t] = grp[a] !== grp[c] ? 1 : 0;
      F.river[t] = river[t] >= thr || lake[t] > 0 ? 1 : 0;
      const r = (travel[t] / 10) / Math.max(dist[t] / 100, 0.05) / med;
      F.travel[t] = Math.min(3, Math.max(0, r - 1));
      for (const k of ['town', 'school']) { const g = L[k]; F[k][t] = g[a] !== g[c] && (g[a] >= 0 || g[c] >= 0) ? 1 : 0; }
    }
    st.F = F;
  }

  function edgeMap(base) {
    // per CSR entry of the unpenalized prep, the index of its site edge (edges, then bridges), or -1
    if (csr.base === base && csr.abbr === st.abbr) return csr.map;
    const map = new Int32Array(base.indices.length).fill(-1), E = st.E, ip = base.indptr, ix = base.indices;
    if (E) for (let t = 0; t < E.length / 2; t++) {
      const a = E[2 * t], b = E[2 * t + 1];
      for (let e = ip[a]; e < ip[a + 1]; e++) if (ix[e] === b && map[e] < 0) { map[e] = t; break; }
      for (let e = ip[b]; e < ip[b + 1]; e++) if (ix[e] === a && map[e] < 0) { map[e] = t; break; }
    }
    csr = { base, abbr: st.abbr, map };
    return map;
  }

  const active = () => st.data && LAYERS.some(l => st.lam[l.key] > 0);

  DX.penalize = function (prep, lam) {
    const p0 = orig.call(this, prep, lam);
    if (!active()) return p0;
    const base = prep.base || prep, map = edgeMap(base), mm = base.indices.length;
    const elen = new Float64Array(mm), pen = new Float64Array(mm);
    const e0 = p0.elen || base.elen, pn0 = p0.edgePen;
    const on = LAYERS.filter(l => st.lam[l.key] > 0).map(l => [st.lam[l.key], st.F[l.key]]);
    for (let e = 0; e < mm; e++) {
      let f = 0; const t = map[e];
      if (t >= 0) for (const [lm, F] of on) f += lm * F[t];
      elen[e] = e0[e] * (1 + f);
      pen[e] = (pn0 ? pn0[e] : 0) + f;
    }
    const p = {};
    for (const key in p0) p[key] = p0[key];
    p.elen = elen; p.edgePen = pen; p.base = base;
    p.lam = Object.assign({}, p0.lam || { state: 0, geo: 0, cz: 0 }, { geo2: Object.assign({}, st.lam) });
    p.cache = { rcb: base.cache.rcb, ws: null, statsWs: null };
    return p;
  };

  function apply() {
    if (typeof S === 'undefined' || !S.prep) return;
    S.pprep = DX.penalize(S.prep, S.lam);
    if (S.prop && typeof recompute === 'function') { recompute(); }
    if (typeof refreshAll === 'function') refreshAll(); else redraw();
  }
  function redraw() { if (typeof drawOverlay === 'function') drawOverlay(); }

  function counts() {
    // links of the displayed map's district lines that this layer marks (factor > 0)
    if (!st.data || !st.E || typeof displayLabels !== 'function') return;
    let lab; try { lab = displayLabels().lab; } catch (e) { return; }
    if (!lab) return;
    const E = st.E, n = E.length / 2;
    for (const l of LAYERS) {
      const F = st.F[l.key], el = $('cx-g-' + l.key); if (!F || !el) continue;
      let all = 0, cut = 0;
      const min = l.key === 'ridge' ? 1 / 3 : l.key === 'travel' ? 1 : 0.5;  // ridges of 100 m+, drives twice as slow+
      for (let t = 0; t < n; t++) if (F[t] >= min) { all++; if (lab[E[2 * t]] !== lab[E[2 * t + 1]]) cut++; }
      el.textContent = cut + ' of ' + all;
      el.title = cut + ' of your district-line links are on this layer (' + all + ' links marked in the state)';
    }
  }

  function addRows() {
    if ($('ly-geo2-head')) return;
    const note = $('layernote'), card = $('layers');
    const ins = el => note ? note.parentNode.insertBefore(el, note) : card.appendChild(el);
    const head = document.createElement('div');
    head.id = 'ly-geo2-head'; head.className = 'hint'; head.style.cssText = 'display:block;margin:8px 0 2px;font-weight:600';
    head.textContent = 'Geography & communities (USGS, Census)';
    ins(head);
    for (const l of LAYERS) {
      const row = document.createElement('div');
      row.className = 'layer'; row.id = 'ly-g-' + l.key;
      const sel = l.select ? ' <select id="opt-g-' + l.key + '" style="font:inherit;font-size:12px;margin-left:4px">' +
        l.select.map(([v, t]) => '<option value="' + v + '">' + t + '</option>').join('') + '</select>' : '';
      row.innerHTML = '<label class="chk" title="' + l.title.replace(/"/g, '&quot;') + '"><input type="checkbox" id="ov-g-' + l.key + '">' +
        '<span class="sw2" style="border-color:' + l.color + (l.dash ? ';border-top-style:dashed' : '') + '"></span>' + l.label + '</label>' + sel +
        '<span class="num" id="cx-g-' + l.key + '"></span>' +
        '<div class="lam">&lambda;<sub>' + l.sub + '</sub> <input type="range" id="lam-g-' + l.key + '" min="0" max="8" step="1" value="0" aria-label="' +
        l.label.replace(/&amp;/g, 'and') + ' penalty"><output id="lam-g-' + l.key + '-v" class="num">0</output></div>';
      ins(row);
      $('lam-g-' + l.key).oninput = e => { st.lam[l.key] = STEPS[+e.target.value]; $('lam-g-' + l.key + '-v').textContent = st.lam[l.key]; apply(); };
      $('ov-g-' + l.key).onchange = e => { st.show[l.key] = e.target.checked; if (e.target.checked) loadShapes(); redraw(); };
      if (l.select) $('opt-g-' + l.key).onchange = e => { st.opt[l.key] = e.target.value; factors(); counts(); apply(); };
    }
    const hint = document.createElement('small');
    hint.className = 'hint'; hint.style.display = 'block'; hint.id = 'geo2-note';
    hint.textContent = 'Same rule as above: a marked link gets longer by 1 + λ (ridges in proportion to their height up to 300 m; drive time ' +
      'in proportion to how much slower than usual it is to drive). Numbers: your district-line links on the layer, of all marked links. ' +
      'Towns and school districts are assigned to block groups by most of their census blocks.';
    ins(hint);
  }

  async function loadShapes() {
    if (st.shapes || !st.abbr) return;
    const abbr = st.abbr;
    try {
      const r = await fetch(BASE + abbr + '.shapes.json'); if (!r.ok) throw new Error(r.status);
      const sh = await r.json(); if (st.abbr !== abbr) return;
      st.shapes = sh;
      if (st.data && st.data.relief) {
        const img = new Image(); img.onload = () => { if (st.abbr === abbr) { st.relief = img; redraw(); } };
        img.src = BASE + st.data.relief.file;
      }
      redraw();
    } catch (e) { /* shapes are optional */ }
  }

  function path(V, ring, close) {
    const pa = new Path2D();
    for (let i = 0; i + 1 < ring.length; i += 2) { const [x, y] = V.toPx(ring[i], ring[i + 1]); i ? pa.lineTo(x, y) : pa.moveTo(x, y); }
    if (close) pa.closePath();
    return pa;
  }

  function drawGeo() {
    if (typeof S === 'undefined' || !S.V || !st.data) return;
    const V = S.V, c = $('ov') && $('ov').getContext('2d'); if (!c) return;
    const sh = st.shapes, d = V.dpr;
    c.save();
    if (st.show.ridge && st.relief) {
      const R = st.data.relief, [x0, y0] = V.toPx(R.x0, R.y1), [x1, y1] = V.toPx(R.x1, R.y_bottom);
      c.globalCompositeOperation = 'destination-over';  // under the page's markers, over the district colours
      c.globalAlpha = 0.9; c.drawImage(st.relief, x0, y0, x1 - x0, y1 - y0);
      c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1;
    }
    if (sh) {
      c.lineJoin = 'round'; c.lineCap = 'round';
      if (st.show.water) { c.strokeStyle = '#2a9d8f'; c.lineWidth = (st.opt.water === 'huc8' ? 1.6 : 0.9) * d; for (const r of sh[st.opt.water] || []) c.stroke(path(V, r, false)); }
      if (st.show.river) {
        c.fillStyle = 'rgba(59,130,196,.45)'; c.strokeStyle = '#3b82c4'; c.lineWidth = 0.8 * d;
        for (const r of sh.lakes || []) { const p = path(V, r, true); c.fill(p); c.stroke(p); }
        const thr = +st.opt.river;
        for (const f of sh.rivers || []) { if (f.o < thr) continue; c.lineWidth = (f.o >= 7 ? 3.2 : f.o >= 6 ? 2.4 : f.o >= 5 ? 1.6 : 1) * d; c.stroke(path(V, f.p, false)); }
      }
      for (const k of ['town', 'school']) {
        if (!st.show[k]) continue;
        const l = LAYERS.find(x => x.key === k);
        c.strokeStyle = l.color; c.lineWidth = 1.2 * d; c.setLineDash(l.dash.map(v => v * d));
        for (const r of sh[k] || []) c.stroke(path(V, r, false));
        c.setLineDash([]);
      }
    }
    if (st.show.travel && st.F.travel) {
      const E = st.E, F = st.F.travel; c.strokeStyle = '#d1495b'; c.lineWidth = 1.6 * d;
      c.beginPath();
      for (let t = 0; t < E.length / 2; t++) if (F[t] >= 1) { const a = E[2 * t], b = E[2 * t + 1]; c.moveTo(V.ux[a], V.uy[a]); c.lineTo(V.ux[b], V.uy[b]); }
      c.stroke();
    }
    c.restore();
  }

  async function load() {
    const D = (typeof S !== 'undefined' && S.data) || null;
    if (!D || !D.abbr || /\+$/.test(D.abbr)) return;
    if (st.abbr === D.abbr) return;
    st.abbr = D.abbr; st.data = null; st.shapes = null; st.relief = null; st.F = {}; csr = { base: null };
    addRows();
    LAYERS.forEach(l => { const el = $('cx-g-' + l.key); if (el) el.textContent = '…'; });
    try {
      const r = await fetch(BASE + D.abbr + '.json'); if (!r.ok) throw new Error(r.status);
      const L = await r.json(); if (st.abbr !== D.abbr) return;
      if (L.edges * 2 !== D.edges.length) throw new Error('edge count');
      st.data = L; factors();
      LAYERS.forEach(l => { $('lam-g-' + l.key).disabled = false; $('ov-g-' + l.key).disabled = false; });
      if (LAYERS.some(l => st.show[l.key])) loadShapes();
      if (active()) apply(); else { counts(); redraw(); }
    } catch (e) {
      LAYERS.forEach(l => { $('cx-g-' + l.key).textContent = 'no data'; $('lam-g-' + l.key).disabled = true; $('ov-g-' + l.key).disabled = true; });
    }
  }

  if (typeof drawOverlay === 'function' && !window.__RD_GEO_DO) {
    window.__RD_GEO_DO = true;
    const dov = drawOverlay;
    // eslint-disable-next-line no-global-assign
    let ct = 0;
    drawOverlay = function () {
      const out = dov.apply(this, arguments);
      try { drawGeo(); } catch (e) { /* drawing is optional */ }
      clearTimeout(ct); ct = setTimeout(() => { try { counts(); } catch (e) { /* optional */ } }, 250);  // after view changes
      return out;
    };
  }
  if (typeof refreshAll === 'function' && !window.__RD_GEO_RA) {
    window.__RD_GEO_RA = true;
    const ra = refreshAll;
    // eslint-disable-next-line no-global-assign
    refreshAll = function () { const out = ra.apply(this, arguments); load(); try { counts(); } catch (e) { /* optional */ } return out; };
  }
  let tries = 0;
  const timer = setInterval(() => { tries++; if (typeof S !== 'undefined' && S.data) load(); if (tries > 120) clearInterval(timer); }, 500);
})();
