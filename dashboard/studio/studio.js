/* Fresmart Pricing Studio: all active articles. Data from scripts/build_studio_data.py (data/*.json). */
(() => {
'use strict';

// ---------------------------------------------------------------- helpers
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'style') e.style.cssText = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
};
const FX = 1050;
const fmt = {
  usd(v, d = 2) { if (v == null || isNaN(v)) return '–'; const a = Math.abs(v); const s = v < 0 ? '−' : '';
    return a >= 1e6 ? `${s}$${(a / 1e6).toFixed(d)}M` : a >= 1e3 ? `${s}$${(a / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K` : `${s}$${a.toFixed(0)}`; },
  usdSigned(v) { return v == null || isNaN(v) ? '–' : (v > 0 ? '+' : '') + fmt.usd(v); },
  n(v, d = 0) { return v == null || isNaN(v) ? '–' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }); },
  pct(v, d = 1, sign = true) { return v == null || isNaN(v) ? '–' : (sign && v > 0 ? '+' : '') + Number(v).toFixed(d) + '%'; },
  kz(v) { return v == null || isNaN(v) ? '–' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' Kz'; },
  date(s) { return d3.utcFormat('%d %b')(new Date(s)); },
};
const pill = (text, tone = '') => el('span', { class: 'pill ' + tone }, text);
const chgPill = (v) => v > 0 ? pill(fmt.pct(v), 'plum') : v < 0 ? pill(fmt.pct(v), 'warn') : pill('Hold');
const WAVE_COLOR = { 'Wave 1': 'var(--plum)', 'Review then Wave 1': 'var(--gold-400)', 'Test': 'var(--navy)', 'Hold': 'var(--plum-200)' };
const tip = $('#tip');
function showTip(ev, title, rows) {
  tip.replaceChildren(el('div', { class: 'th' }, title), ...rows.map(([k, v]) => el('div', { class: 'tr' }, el('span', {}, k), el('span', {}, v))));
  tip.hidden = false;
  const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 10), y = Math.min(ev.clientY + 14, innerHeight - tip.offsetHeight - 10);
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const hideTip = () => { tip.hidden = true; };

const ICON = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 12 10 5 10-5M2 17l10 5 10-5"/>',
  flag: '<path d="M4 22V4M4 4h13l-2.5 4.5L17 13H4"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
  flask: '<path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/><path d="M7 15h10"/>',
  grid: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="3.5"/><circle cx="8" cy="17" r="4"/><circle cx="18" cy="18" r="2"/>',
  coin: '<circle cx="12" cy="12" r="9"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .8 3 2-1.3 2-3 2c-1.4 0-2.6-.6-3-1.6M12 6v2M12 16v2"/>',
  curve: '<path d="M3 3v18h18"/><path d="M6 6c3 0 5 2 7 6s4 6 7 6"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  promo: '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12"/>',
  book: '<path d="M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4z"/><path d="M20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z"/>',
};
const svgIcon = (name) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = ICON[name]; return s; };

// ---------------------------------------------------------------- state
let M, SKUS, BY_CODE, WEEKLY, FLAGS, WSKU = null;
const PAGES = [
  ['Pricing', [['overview', 'Overview', 'overview'], ['today', 'Today’s price', 'coin'], ['elasticity', 'Price elasticity', 'curve'], ['forecast', 'Forecast & target', 'upload'],
    ['promos', 'Promotions', 'promo'], ['prices', 'Recommended price', 'tag'], ['simulator', 'Simulator', 'sliders'], ['scenarios', 'Scenarios', 'layers']]],
  ['Go-live', [['rollout', 'Rollout & test', 'flag'], ['monitoring', 'Monitoring', 'activity']]],
  ['Control', [['rules', 'Business rules', 'shield'], ['stockouts', 'Stock-outs', 'box'], ['health', 'Model health', 'flask']]],
  ['Reference', [['portfolio', 'Portfolio', 'grid'], ['method', 'Method', 'book']]],
];
const TITLES = Object.fromEntries(PAGES.flatMap(([, ps]) => ps.map(([id, t]) => [id, t])));

// ---------------------------------------------------------------- charts
function measure(box, h) { const w = Math.max(280, box.clientWidth || box.parentElement.clientWidth || 600); return { w, h }; }

/* time series: series [{name, values, color, width, dash}], band {lo, hi, color} */
function lineChart(box, { dates, series, band, yfmt = (v) => fmt.n(v), h = 280, zero = false }) {
  box.replaceChildren();
  const { w } = measure(box, h);
  const m = { t: 12, r: 16, b: 28, l: 56 };
  const x = d3.scaleUtc().domain(d3.extent(dates)).range([m.l, w - m.r]);
  const all = series.flatMap((s) => s.values).concat(band ? [...band.lo, ...band.hi] : []).filter((v) => v != null);
  const ext = d3.extent(all); if (zero) { ext[0] = Math.min(0, ext[0]); ext[1] = Math.max(0, ext[1]); }
  const pad = (ext[1] - ext[0]) * .08 || 1;
  const y = d3.scaleLinear().domain([ext[0] - (zero && ext[0] === 0 ? 0 : pad), ext[1] + pad]).nice().range([h - m.b, m.t]);
  const svg = d3.select(box).append('svg').attr('width', w).attr('height', h).attr('role', 'img').attr('aria-label', series.map((s) => s.name).join(', '));
  svg.append('g').attr('class', 'gridl').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickSize(-(w - m.l - m.r)).tickFormat(''));
  svg.append('g').attr('class', 'ax').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(yfmt).tickSize(0)).call((g) => g.select('.domain').remove()).selectAll('text').attr('dx', -6);
  svg.append('g').attr('class', 'ax').attr('transform', `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(Math.min(8, w / 110)).tickFormat(d3.utcFormat('%b %y')).tickSizeOuter(0));
  if (zero) svg.append('line').attr('x1', m.l).attr('x2', w - m.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--plum-200)');
  if (band) svg.append('path').datum(dates.map((d, i) => [d, band.lo[i], band.hi[i]])).attr('fill', band.color || 'var(--plum-100)').attr('opacity', .8)
    .attr('d', d3.area().x((d) => x(d[0])).y0((d) => y(d[1])).y1((d) => y(d[2])));
  series.forEach((s) => svg.append('path').datum(s.values).attr('fill', 'none').attr('stroke', s.color).attr('stroke-width', s.width || 2)
    .attr('stroke-dasharray', s.dash || null).attr('d', d3.line().defined((v) => v != null).x((v, i) => x(dates[i])).y((v) => y(v))));
  const cross = svg.append('line').attr('y1', m.t).attr('y2', h - m.b).attr('stroke', 'var(--plum-200)').attr('opacity', 0);
  svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', w - m.l - m.r).attr('height', h - m.t - m.b).attr('fill', 'transparent')
    .on('mousemove', (ev) => { const i = d3.minIndex(dates, (d) => Math.abs(x(d) - d3.pointer(ev)[0])); cross.attr('x1', x(dates[i])).attr('x2', x(dates[i])).attr('opacity', 1);
      showTip(ev, 'Week of ' + d3.utcFormat('%d %b %Y')(dates[i]), series.map((s) => [s.name, yfmt(s.values[i])]).concat(band ? [[band.name || 'Range', `${yfmt(band.lo[i])} – ${yfmt(band.hi[i])}`]] : [])); })
    .on('mouseleave', () => { cross.attr('opacity', 0); hideTip(); });
}

/* HTML bar list: rows [{label, value, text, cls, onclick, title}] */
function barList(rows, { max } = {}) {
  const mx = max || d3.max(rows, (r) => Math.abs(r.value)) || 1;
  return el('div', { class: 'bars' }, rows.map((r) => el('div', { class: 'bar-row', style: r.onclick ? 'cursor:pointer' : '', onclick: r.onclick, title: r.title || null },
    el('span', { class: 'bl' }, r.label), el('span', { class: 'bar-track' }, el('i', { class: r.cls || '', style: `width:${Math.max(1.5, Math.abs(r.value) / mx * 100)}%` })),
    el('span', { class: 'bv' }, r.text))));
}

/* vertical grouped bars with labels: data [{label, a, b}] */
function colChart(box, data, { h = 260, fmtv = fmt.usd, names = ['Likely', 'Cautious'] } = {}) {
  box.replaceChildren();
  const { w } = measure(box, h); const m = { t: 22, r: 8, b: 44, l: 8 };
  const x0 = d3.scaleBand().domain(data.map((d) => d.label)).range([m.l, w - m.r]).padding(.28);
  const x1 = d3.scaleBand().domain(['a', 'b']).range([0, x0.bandwidth()]).padding(.08);
  const y = d3.scaleLinear().domain([0, d3.max(data, (d) => Math.max(d.a, d.b || 0)) * 1.12]).range([h - m.b, m.t]);
  const svg = d3.select(box).append('svg').attr('width', w).attr('height', h).attr('role', 'img').attr('aria-label', 'bar chart');
  const g = svg.selectAll('g.c').data(data).join('g').attr('transform', (d) => `translate(${x0(d.label)},0)`);
  g.append('rect').attr('x', x1('a')).attr('width', x1.bandwidth()).attr('y', (d) => y(d.a)).attr('height', (d) => y(0) - y(d.a)).attr('rx', 5).attr('fill', (d) => d.color || 'var(--plum)')
    .on('mousemove', (ev, d) => showTip(ev, d.label, [[names[0], fmtv(d.a)], ...(d.b != null ? [[names[1], fmtv(d.b)]] : [])])).on('mouseleave', hideTip);
  g.filter((d) => d.b != null).append('rect').attr('x', x1('b')).attr('width', x1.bandwidth()).attr('y', (d) => y(d.b)).attr('height', (d) => y(0) - y(d.b)).attr('rx', 5).attr('fill', 'var(--plum-200)')
    .on('mousemove', (ev, d) => showTip(ev, d.label, [[names[0], fmtv(d.a)], [names[1], fmtv(d.b)]])).on('mouseleave', hideTip);
  g.append('text').attr('class', 'lbl-strong').attr('x', x1('a') + x1.bandwidth() / 2).attr('y', (d) => y(d.a) - 6).attr('text-anchor', 'middle').text((d) => fmtv(d.a));
  g.append('text').attr('class', 'lbl').attr('x', x0.bandwidth() / 2).attr('y', h - m.b + 16).attr('text-anchor', 'middle').text((d) => d.label)
    .each(function (d) { const t = d3.select(this); const words = d.label.split(' '); if (this.getComputedTextLength() > x0.bandwidth() + 20 && words.length > 1) {
      t.text(null); const half = Math.ceil(words.length / 2); t.append('tspan').attr('x', x0.bandwidth() / 2).text(words.slice(0, half).join(' '));
      t.append('tspan').attr('x', x0.bandwidth() / 2).attr('dy', 14).text(words.slice(half).join(' ')); } });
}

// ---------------------------------------------------------------- tables
function dataTable({ cols, rows, sort, onRow, hi, pageSize = 0, rowKey }) {
  const state = { sort: sort || null, page: 0 };
  const wrap = el('div', { style: 'display:grid;gap:10px' });
  const box = el('div', { class: 'tablebox' }); const table = el('table', { class: 't' }); box.append(table);
  const pager = el('div', { class: 'pager' });
  wrap.append(box); if (pageSize) wrap.append(pager);
  function draw() {
    let rs = rows.slice();
    if (state.sort) { const c = cols.find((x) => x.key === state.sort.k); const val = c.sortv || ((r) => r[c.key]);
      rs.sort((a, b) => { const va = val(a), vb = val(b); if (va == null) return 1; if (vb == null) return -1; return (va > vb ? 1 : va < vb ? -1 : 0) * state.sort.dir; }); }
    const n = rs.length; const pages = pageSize ? Math.max(1, Math.ceil(n / pageSize)) : 1; state.page = Math.min(state.page, pages - 1);
    const view = pageSize ? rs.slice(state.page * pageSize, (state.page + 1) * pageSize) : rs;
    const thead = el('thead', {}, el('tr', {}, cols.map((c) => { const sorted = state.sort && state.sort.k === c.key;
      return el('th', { class: (c.num ? 'num ' : '') + (c.key ? 'sortable' : ''), onclick: c.key ? () => { state.sort = { k: c.key, dir: sorted ? -state.sort.dir : (c.num ? -1 : 1) }; draw(); } : null },
        c.h, sorted ? el('span', { class: 'arr' }, state.sort.dir > 0 ? '↑' : '↓') : null); })));
    const tbody = el('tbody', {}, view.map((r) => el('tr', { class: (onRow ? 'click ' : '') + (hi && hi(r) ? 'hi' : ''), onclick: onRow ? () => onRow(r) : null, 'data-key': rowKey ? rowKey(r) : null },
      cols.map((c) => { const v = c.f ? c.f(r) : r[c.key]; return el('td', { class: (c.num ? 'num ' : '') + (c.cls || '') }, v instanceof Node ? v : v == null ? '–' : String(v)); }))));
    table.replaceChildren(thead, tbody);
    if (pageSize) pager.replaceChildren(el('span', {}, `${fmt.n(n)} articles · page ${state.page + 1} of ${pages}`),
      el('div', { class: 'toolbar' }, el('button', { class: 'btn', disabled: state.page === 0 || null, onclick: () => { state.page--; draw(); box.scrollTop = 0; } }, '← Previous'),
        el('button', { class: 'btn', disabled: state.page >= pages - 1 || null, onclick: () => { state.page++; draw(); box.scrollTop = 0; } }, 'Next →')));
  }
  draw();
  wrap.update = (newRows) => { rows = newRows; state.page = 0; draw(); };
  return wrap;
}

function csvDownload(name, cols, rows) {
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const text = [cols.map((c) => c[0]).join(',')].concat(rows.map((r) => cols.map((c) => esc(typeof c[1] === 'function' ? c[1](r) : r[c[1]])).join(','))).join('\n');
  const a = el('a', { href: URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv' })), download: name }); document.body.append(a); a.click(); a.remove();
}

// ---------------------------------------------------------------- model maths (own response, as the optimiser's per-SKU curve)
function simulate(s, d) {
  if (!(s.units > 0 && s.p_net > 0 && s.cost > 0 && s.e_rise != null)) return null;
  const e = d > 0 ? s.e_rise : s.e_cut;
  const k = Math.min(2, Math.max(1, (s.e_caut / s.e) || 1.5));
  const u = (ee) => s.units * Math.pow(1 + d, ee);
  const gp = (uu) => uu * (s.p_net * (1 + d) - s.cost) / FX;
  const gp0 = s.units * (s.p_net - s.cost) / FX;
  const uL = u(e), uS = u(Math.min(e * k, d > 0 ? -0.2 : -0.1)), uO = u(e * 0.67);
  return { d, units: uL, unitsPct: (uL / s.units - 1) * 100, gp0, gp: gp(uL), gain: gp(uL) - gp0, gainS: gp(uS) - gp0, gainO: gp(uO) - gp0,
    margin: (s.p_net * (1 + d) - s.cost) / (s.p_net * (1 + d)) * 100, shelf: s.price ? s.price * (1 + d) : null };
}

// ---------------------------------------------------------------- drawer
function openSku(code) {
  const s = BY_CODE.get(code); if (!s) return;
  $('#dr-code').replaceChildren(pathEl(s, s.code));
  $('#dr-name').textContent = s.name;
  $('#dr-tags').replaceChildren(...[chgPill(s.chg), pill(s.wave, s.wave === 'Hold' ? '' : 'gold'), pill(s.conf + ' confidence', s.conf === 'High' ? 'ok' : s.conf === 'Low' ? 'warn' : ''),
    s.kvi ? pill('Everyday KVI', 'plum') : null, s.shelf ? null : pill('Not on shelf', 'bad'), s.supply_risk ? pill('Supply risk', 'bad') : null].filter(Boolean));
  const body = $('#dr-body'); body.replaceChildren();
  body.append(el('div', {}, el('div', { class: 'section-t' }, 'Shelf price'),
    el('div', { class: 'price-move' }, s.chg ? el('span', { class: 'from' }, fmt.kz(s.price)) : null, el('span', { class: 'to' }, fmt.kz(s.chg ? s.new_price : s.price)), s.chg ? chgPill(s.chg) : null)));
  body.append(el('div', { class: 'reason' }, s.reason || 'No change recommended.'));
  body.append(el('dl', { class: 'kv' },
    el('dt', {}, 'Gross-profit gain, 52 weeks'), el('dd', { class: s.gain > 0 ? 'up' : '' }, fmt.usdSigned(s.gain)),
    el('dt', {}, 'Cautious case'), el('dd', {}, fmt.usdSigned(s.gain_c)),
    el('dt', {}, 'Units change'), el('dd', {}, fmt.pct(s.units_chg)),
    el('dt', {}, 'Margin after IVA, now → new'), el('dd', {}, `${fmt.pct(s.m_now, 1, false)} → ${fmt.pct(s.m_new, 1, false)}`),
    el('dt', {}, 'Gross profit now, 52 weeks'), el('dd', {}, fmt.usd(s.gp_now)),
    el('dt', {}, 'Revenue, last 52 weeks'), el('dd', {}, fmt.usd(s.rev)),
    el('dt', {}, 'Price sensitivity (rise / cut)'), el('dd', {}, s.e_rise != null ? `${s.e_rise.toFixed(2)} / ${s.e_cut.toFixed(2)}` : 'not measured'),
    el('dt', {}, 'Tested price range'), el('dd', {}, s.down != null ? `−${(s.down * 100).toFixed(0)}% to +${(s.up * 100).toFixed(0)}%` : '–'),
    el('dt', {}, 'Stock-out weeks, last 13'), el('dd', {}, s.stockout != null ? fmt.pct(s.stockout, 1, false) : '–'),
    el('dt', {}, 'Stores priced'), el('dd', {}, fmt.n(s.stores))));
  const f = FLAGS[s.code];
  if (f) body.append(el('div', {}, el('div', { class: 'section-t' }, 'Rule checks to look at'), el('div', { class: 'chips' }, f.map(([r, v]) => pill(r, v === 'FAIL' ? 'bad' : 'warn')))));
  if (simulate(s, 0)) {
    const box = el('div', { class: 'chart' }); body.append(el('div', {}, el('div', { class: 'section-t' }, 'Gross-profit gain by price change'), box,
      el('button', { class: 'btn', style: 'margin-top:10px', onclick: () => { closeDrawer(); SIM.code = s.code; SIM.d = Math.round(s.chg); go('simulator'); } }, 'Open in simulator →')));
    requestAnimationFrame(() => curveChart(box, s, Math.round(s.chg), 200));
  }
  if (s.chg) {
    const box = el('div', { class: 'chart' }); body.append(el('div', {}, el('div', { class: 'section-t' }, 'Weekly units, now vs new price'), box));
    loadWeeklySku().then(() => { const w = WSKU.skus[s.code]; if (!w) { box.append(el('p', { class: 'note' }, 'No weekly forecast for this article.')); return; }
      const dates = WSKU.weeks.slice(0, w.now.length).map((d) => new Date(d));
      lineChart(box, { dates, h: 200, series: [{ name: 'Today’s price', values: w.now, color: 'var(--plum-200)', width: 2 }, { name: 'New price', values: w.new, color: 'var(--plum)', width: 2.2 }],
        band: { lo: w.low, hi: w.high, color: 'var(--plum-50)', name: 'Cautious – optimistic' } }); });
  }
  $('#drawer').classList.add('open'); $('#drawer').setAttribute('aria-hidden', 'false'); $('#scrim').hidden = false;
}
function closeDrawer() { $('#drawer').classList.remove('open'); $('#drawer').setAttribute('aria-hidden', 'true'); $('#scrim').hidden = true; }
$('#dr-close').addEventListener('click', closeDrawer); $('#scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeDrawer(); $('#gresults').hidden = true; }
  if (e.key === '/' && document.activeElement.tagName !== 'INPUT') { e.preventDefault(); $('#gsearch').focus(); } });

function loadWeeklySku() { return WSKU ? Promise.resolve() : fetch('data/weekly_sku.json').then((r) => r.json()).then((j) => { WSKU = j; }); }

/* gain curve for one SKU, −15%..+15% */
function curveChart(box, s, mark, h = 260) {
  box.replaceChildren();
  const pts = d3.range(-15, 16).map((d) => simulate(s, d / 100)).filter(Boolean);
  const { w } = measure(box, h); const m = { t: 14, r: 14, b: 30, l: 58 };
  const x = d3.scaleLinear().domain([-15, 15]).range([m.l, w - m.r]);
  const ext = d3.extent(pts.flatMap((p) => [p.gainS, p.gainO, p.gain]).concat([0]));
  const y = d3.scaleLinear().domain(ext).nice().range([h - m.b, m.t]);
  const svg = d3.select(box).append('svg').attr('width', w).attr('height', h).attr('role', 'img').attr('aria-label', 'Gross-profit gain by price change');
  const lo = Math.max(-15, -(s.down || .05) * 100), hi = Math.min(15, (s.up || .05) * 100);
  svg.append('rect').attr('x', x(lo)).attr('width', x(hi) - x(lo)).attr('y', m.t).attr('height', h - m.t - m.b).attr('fill', 'var(--plum-50)');
  svg.append('g').attr('class', 'gridl').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickSize(-(w - m.l - m.r)).tickFormat(''));
  svg.append('g').attr('class', 'ax').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat((v) => fmt.usd(v, 1)).tickSize(0)).call((g) => g.select('.domain').remove()).selectAll('text').attr('dx', -6);
  svg.append('g').attr('class', 'ax').attr('transform', `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(7).tickFormat((v) => (v > 0 ? '+' : '') + v + '%').tickSizeOuter(0));
  svg.append('line').attr('x1', m.l).attr('x2', w - m.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--plum-200)');
  svg.append('path').datum(pts).attr('fill', 'var(--gold-100)').attr('opacity', .9).attr('d', d3.area().x((p) => x(p.d * 100)).y0((p) => y(p.gainS)).y1((p) => y(p.gainO)));
  svg.append('path').datum(pts).attr('fill', 'none').attr('stroke', 'var(--plum)').attr('stroke-width', 2.4).attr('d', d3.line().x((p) => x(p.d * 100)).y((p) => y(p.gain)));
  const rec = simulate(s, Math.round(s.chg) / 100);
  if (rec && s.chg) svg.append('circle').attr('cx', x(Math.round(s.chg))).attr('cy', y(rec.gain)).attr('r', 6).attr('fill', 'var(--gold-400)').attr('stroke', '#fff').attr('stroke-width', 2);
  if (mark != null) { const p = simulate(s, mark / 100); svg.append('line').attr('x1', x(mark)).attr('x2', x(mark)).attr('y1', m.t).attr('y2', h - m.b).attr('stroke', 'var(--plum)').attr('stroke-dasharray', '3 3');
    if (p) svg.append('circle').attr('cx', x(mark)).attr('cy', y(p.gain)).attr('r', 5).attr('fill', 'var(--plum)').attr('stroke', '#fff').attr('stroke-width', 2); }
  svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', w - m.l - m.r).attr('height', h - m.t - m.b).attr('fill', 'transparent')
    .on('mousemove', (ev) => { const d = Math.round(x.invert(d3.pointer(ev)[0])); const p = simulate(s, d / 100); if (p) showTip(ev, `Price ${fmt.pct(d, 0)}`, [['Gain, likely', fmt.usdSigned(p.gain)], ['Cautious – optimistic', `${fmt.usdSigned(p.gainS)} – ${fmt.usdSigned(p.gainO)}`], ['Units', fmt.pct(p.unitsPct)]]); })
    .on('mouseleave', hideTip);
}

// ---------------------------------------------------------------- pages
const V = {};
const head = (eyebrow, title, sub, ...actions) => el('div', { class: 'page-head' }, el('div', {}, el('div', { class: 'eyebrow' }, eyebrow), el('h1', { class: 'page-title' }, title), el('p', { class: 'page-sub' }, sub)), actions.length ? el('div', { class: 'head-actions' }, actions) : null);
const card = (title, sub, ...kids) => el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, title), sub ? el('p', { class: 'sub' }, sub) : null)), kids);
const kpi = (k, v, s, tone) => el('div', { class: 'kpi' }, el('div', { class: 'k' }, k), el('div', { class: 'v' + (tone ? ' ' + tone : '') }, v), el('div', { class: 's' }, s));
const later = (fn) => requestAnimationFrame(() => requestAnimationFrame(fn));

V.overview = () => {
  const p = M.plan; const rng = [p.cautious, p.gain, p.optimistic]; const lo = p.cautious * .9, hi = p.optimistic * 1.04, pos = (v) => (v - lo) / (hi - lo) * 100;
  const hero = el('section', { class: 'hero' },
    el('div', {}, el('div', { class: 'eyebrow' }, 'Planned gross-profit gain · next 52 weeks'),
      el('div', { class: 'hero-value' }, fmt.usd(p.gain), el('small', {}, `+${(p.gain / p.gp_now * 100).toFixed(1)}% on today`)),
      el('p', { class: 'hero-text' }, el('b', {}, fmt.n(p.rises)), ' price rises across ', el('b', {}, fmt.n(p.on_shelf)), ' articles on the shelf, a basket rise of ', el('b', {}, fmt.pct(p.basket, 2)),
        ` (${p.basket_months.toFixed(1)} months of inflation), and units down `, el('b', {}, fmt.pct(p.units_pct)), '. All business rules pass.'),
      el('div', { class: 'range' }, el('div', { class: 'range-bar' }, el('i', { style: `left:${pos(rng[0])}%;right:${100 - pos(rng[2])}%` }), el('em', { style: `left:${pos(rng[1])}%` })),
        el('div', { class: 'range-labels' }, el('span', {}, 'Cautious ', el('b', {}, fmt.usd(rng[0]))), el('span', {}, 'Likely ', el('b', {}, fmt.usd(rng[1]))), el('span', {}, 'Optimistic ', el('b', {}, fmt.usd(rng[2])))))),
    el('div', { class: 'hero-stats' },
      el('div', { class: 'hstat' }, el('div', { class: 'k' }, 'Gross profit today'), el('div', { class: 'v' }, fmt.usd(p.gp_now)), el('div', { class: 's' }, 'priced articles, after IVA')),
      el('div', { class: 'hstat' }, el('div', { class: 'k' }, 'Revenue'), el('div', { class: 'v' }, fmt.pct(p.rev_pct)), el('div', { class: 's' }, 'units ' + fmt.pct(p.units_pct))),
      el('div', { class: 'hstat' }, el('div', { class: 'k' }, 'Typical rise'), el('div', { class: 'v' }, fmt.pct(p.median_rise)), el('div', { class: 's' }, 'largest ' + fmt.pct(p.max_rise))),
      el('div', { class: 'hstat' }, el('div', { class: 'k' }, 'Model checks'), el('div', { class: 'v' }, `${M.checks.filter((c) => c.Result === 'PASS').length}/${M.checks.length}`), el('div', { class: 's' }, 'automated checks pass'))));
  const wv = ['Wave 1', 'Review then Wave 1', 'Test'].map((w) => M.waves.find((x) => x.Wave === w)).filter(Boolean);
  const held = M.waves.filter((x) => x.Wave === 'Hold');
  const waves = el('div', { class: 'waves' }, wv.map((w) => el('div', { class: 'wave', style: `--wave:${WAVE_COLOR[w.Wave]}` }, el('div', { class: 'wn' }, w.Wave), el('div', { class: 'wv' }, fmt.usd(w.GP_gain_52w)),
    el('div', { class: 'ws' }, `${fmt.n(w.SKUs)} articles · average ${fmt.pct(w.Avg_change)}`))),
    el('div', { class: 'wave', style: '--wave:var(--plum-200)' }, el('div', { class: 'wn' }, 'Hold'), el('div', { class: 'wv' }, fmt.n(d3.sum(held, (h) => h.SKUs))), el('div', { class: 'ws' }, 'articles unchanged')));
  const weeklyBox = el('div', { class: 'chart' });
  const groups = M.by_group.filter((g) => g.GP_gain_52w > 0).slice(0, 10);
  const top = SKUS.filter((s) => s.gain > 0 && s.chg).sort((a, b) => b.gain - a.gain).slice(0, 10);
  later(() => { const ds = WEEKLY.weeks.map((d) => new Date(d)); const c = WEEKLY.chain;
    lineChart(weeklyBox, { dates: ds, zero: true, yfmt: (v) => fmt.usd(v, 0), series: [{ name: 'Weekly gain, likely', values: c.map((r) => r.GP_new_L_KZ - r.GP_now_KZ), color: 'var(--plum)', width: 2.4 }],
      band: { lo: c.map((r) => r.GP_new_S_KZ - r.GP_now_KZ), hi: c.map((r) => r.GP_new_O_KZ - r.GP_now_KZ), color: 'var(--gold-100)', name: 'Cautious – optimistic' } }); });
  return [head('Fresmart price plan', 'Overview', 'New shelf prices for every active article, after IVA, with the gain, the risk range and the rollout.'), hero,
    el('div', { class: 'split' }, card('Weekly gross-profit gain', 'The likely gain each week, with the cautious to optimistic range', weeklyBox),
      card('Where the gain comes from', 'Top product groups, 52-week gain', barList(groups.map((g) => ({ label: g.MainGroup, value: g.GP_gain_52w, text: fmt.usd(g.GP_gain_52w), title: `${g.Raise} rises, average ${fmt.pct(g.Avg_change)}` }))))),
    card('Rollout waves', 'Wave 1 goes first; review-then-Wave-1 articles need a pricing check; Test articles run in the store test first', waves),
    card('Biggest single gains', 'Click an article for its detail', dataTable({ rows: top, onRow: (r) => openSku(r.code), cols: [
      { h: 'Article', f: artCell },
      { h: 'Now', num: 1, f: (r) => fmt.kz(r.price) }, { h: 'New', num: 1, f: (r) => fmt.kz(r.new_price) }, { h: 'Change', num: 1, f: (r) => chgPill(r.chg) },
      { h: 'Units', num: 1, f: (r) => fmt.pct(r.units_chg) }, { h: 'Gain', num: 1, f: (r) => el('b', {}, fmt.usdSigned(r.gain)) }, { h: 'Wave', f: (r) => r.wave }] }))];
};

// ---------------------------------------------------------------- article hierarchy: Main group › Sub group › Short description › article
const pathEl = (s, extra) => el('div', { class: 'path' }, el('span', {}, s.group), el('span', {}, s.sub), el('span', {}, s.sd), extra ? el('span', {}, extra) : null);
const artCell = (s) => el('div', { class: 'art' }, el('div', { class: 'name' }, s.name), pathEl(s, s.code));
const artCellRaw = (code, name) => { const s = BY_CODE.get(String(code)); return s ? artCell(s) : el('div', { class: 'art' }, el('div', { class: 'name' }, name), el('div', { class: 'path' }, String(code))); };
const bandOf = (e) => e == null ? 'Not measured' : e <= -2 ? 'Highly elastic' : e <= -1 ? 'Elastic' : e <= -0.5 ? 'Moderate' : 'Inelastic';
const BAND_TONE = { 'Highly elastic': 'bad', Elastic: 'warn', Moderate: 'plum', Inelastic: 'ok', 'Not measured': '' };
const uniq = (a) => [...new Set(a)].filter((x) => x != null).sort();
const store = { get(k, d) { try { const v = localStorage.getItem('fps-' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('fps-' + k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } } };

/* selection shared by Today's price and Price elasticity, so the article carries over */
const SEL = store.get('sel', { group: '', sub: '', sd: '', code: '' });
const inSel = (s, st = SEL) => (!st.group || s.group === st.group) && (!st.sub || s.sub === st.sub) && (!st.sd || s.sd === st.sd);
function hierFilter(st, onChange, { article = false, pool = SKUS } = {}) {
  const sel = (label, key, opts, all) => el('label', {}, label, el('select', { class: 'sel', onchange: (e) => { st[key] = e.target.value;
      const order = ['group', 'sub', 'sd', 'code']; order.slice(order.indexOf(key) + 1).forEach((k) => { st[k] = ''; }); store.set('sel', SEL); onChange(); } },
    el('option', { value: '' }, all), opts.map((o) => el('option', { value: o[0] ?? o, selected: (o[0] ?? o) === st[key] || null }, o[1] ?? o))));
  const g = pool, gs = uniq(g.map((s) => s.group));
  const subs = uniq(g.filter((s) => !st.group || s.group === st.group).map((s) => s.sub));
  const sds = uniq(g.filter((s) => (!st.group || s.group === st.group) && (!st.sub || s.sub === st.sub)).map((s) => s.sd));
  const kids = [sel('Main group', 'group', gs, 'All main groups'), sel('Sub group', 'sub', subs, 'All sub groups'), sel('Short description', 'sd', sds, 'All short descriptions')];
  if (article) {
    const arts = g.filter((s) => inSel(s, st)).sort((a, b) => b.rev - a.rev).slice(0, 600);
    kids.push(sel('Article', 'code', arts.map((s) => [s.code, `${s.name} (${s.code})`]), `All articles (${fmt.n(g.filter((s) => inSel(s, st)).length)})`));
  }
  return el('div', { class: 'hier' }, kids);
}

const HIST = {};
function loadHist(group) {
  const f = M.history_files[group]; if (!f) return Promise.resolve(null);
  return HIST[f] ? Promise.resolve(HIST[f]) : fetch('data/history/' + f).then((r) => r.json()).then((j) => { HIST[f] = j; return j; });
}

const articleHead = (s, ...tags) => el('div', { class: 'art-head' }, pathEl(s, s.code), el('h2', {}, s.name), el('div', { class: 'chips' }, tags.filter(Boolean)));

// ---------------------------------------------------------------- 2. Today's price
V.today = () => {
  const box = el('div', { style: 'display:grid;gap:18px' });
  const filter = el('section', { class: 'card' });
  function draw() {
    filter.replaceChildren(el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Choose articles'), el('p', { class: 'sub' }, 'Main group, then sub group, then short description, then the article'))),
      hierFilter(SEL, draw, { article: true }));
    box.replaceChildren(SEL.code && BY_CODE.get(SEL.code) ? todayArticle(BY_CODE.get(SEL.code)) : todaySelection());
  }
  draw();
  return [head('Step 2', 'Today’s price', 'Where each article stands today: shelf price, cost, margin after IVA, sales and its price history.'), filter, box];
};
function todaySelection() {
  const rows = SKUS.filter((s) => inSel(s));
  const rev = d3.sum(rows, (s) => s.rev), gp = d3.sum(rows, (s) => s.rev * (s.m_now || 0) / 100);
  const below = rows.filter((s) => s.m_now != null && s.m_now < 0).length;
  const table = dataTable({ rows, sort: { k: 'rev', dir: -1 }, pageSize: 100, onRow: (r) => { SEL.code = r.code; store.set('sel', SEL); render(); }, cols: [
    { h: 'Article', key: 'name', f: artCell }, { h: 'Shelf price today', key: 'price', num: 1, f: (r) => fmt.kz(r.price) },
    { h: 'Margin after IVA', key: 'm_now', num: 1, f: (r) => r.m_now == null ? '–' : el('span', { class: r.m_now < 0 ? 'down' : '' }, fmt.pct(r.m_now, 1, false)) },
    { h: 'Revenue, 52 wks', key: 'rev', num: 1, f: (r) => fmt.usd(r.rev) }, { h: 'Stores', key: 'stores', num: 1, f: (r) => fmt.n(r.stores) },
    { h: 'Price moved, 26 wks', key: 'repriced', num: 1, f: (r) => r.repriced == null ? '–' : fmt.pct(r.repriced) },
    { h: 'Status', key: 'shelf', f: (r) => r.shelf ? pill('On shelf', 'ok') : pill('Not on shelf', 'bad') }] });
  return el('div', { style: 'display:grid;gap:18px' },
    el('div', { class: 'kpis' }, kpi('Articles', fmt.n(rows.length), `${fmt.n(rows.filter((s) => s.shelf).length)} on the shelf`), kpi('Revenue, 52 weeks', fmt.usd(rev), 'with IVA, as recorded'),
      kpi('Margin after IVA', rev ? fmt.pct(gp / rev * 100, 1, false) : '–', 'at today’s price and cost, sales-weighted'), kpi('Sold below cost', fmt.n(below), 'articles in this selection', below ? 'down' : '')),
    card('Articles today', 'Click an article to see its price history', table));
}
function todayArticle(s) {
  const wrap = el('div', { style: 'display:grid;gap:18px' });
  const priceBox = el('div', { class: 'chart' }), unitBox = el('div', { class: 'chart' });
  const sib = SKUS.filter((x) => x.sd === s.sd && x.sub === s.sub && x.code !== s.code).sort((a, b) => b.rev - a.rev).slice(0, 15);
  wrap.append(el('section', { class: 'card' }, el('div', { class: 'card-head' }, articleHead(s, s.shelf ? pill('On shelf', 'ok') : pill('Not on shelf', 'bad'), s.kvi ? pill('Everyday KVI', 'plum') : null, pill(s.segment)),
      el('div', { class: 'toolbar' }, el('button', { class: 'btn', onclick: () => { SEL.code = ''; store.set('sel', SEL); render(); } }, '← All articles'), el('button', { class: 'btn', onclick: () => go('elasticity') }, 'Price elasticity →'), el('button', { class: 'btn primary', onclick: () => openSku(s.code) }, 'Recommendation')))),
    el('div', { class: 'kpis' }, kpi('Shelf price today', fmt.kz(s.price), `${fmt.n(s.stores)} stores priced`), kpi('Margin after IVA', fmt.pct(s.m_now, 1, false), 'sales minus IVA minus cost', s.m_now < 0 ? 'down' : ''),
      kpi('Revenue, 52 weeks', fmt.usd(s.rev), `gross profit ${fmt.usd(s.gp_now)}`), kpi('Units, next 52 weeks', fmt.n(s.units), 'forecast at today’s price'),
      kpi('Price moved, 26 weeks', s.repriced == null ? '–' : fmt.pct(s.repriced), 'regular price, last 4 weeks vs 14-26 weeks ago'), kpi('Stock-out weeks', s.stockout == null ? '–' : fmt.pct(s.stockout, 1, false), 'of store-weeks, last 13')),
    card('Price history', 'Regular shelf price, the average price customers paid, and the cost (with IVA), per sales pack; Jan 2024 to today', priceBox,
      el('div', { class: 'legend' }, el('span', {}, el('i', { style: 'background:var(--plum)' }), 'Regular shelf price'), el('span', {}, el('i', { style: 'background:var(--navy)' }), 'Price paid (after markdowns)'), el('span', {}, el('i', { style: 'background:var(--gold-400)' }), 'Cost with IVA'))),
    card('Units sold per week', 'Chain total, all stores', unitBox),
    sib.length ? card('Same short description', `Other ${s.sd} articles in ${s.sub}`, dataTable({ rows: sib, onRow: (r) => { SEL.code = r.code; store.set('sel', SEL); render(); }, cols: [
      { h: 'Article', f: artCell }, { h: 'Shelf price', num: 1, f: (r) => fmt.kz(r.price) }, { h: 'Margin', num: 1, f: (r) => fmt.pct(r.m_now, 1, false) }, { h: 'Revenue', num: 1, f: (r) => fmt.usd(r.rev) },
      { h: 'Recommended', num: 1, f: (r) => chgPill(r.chg) }] })) : null);
  loadHist(s.group).then((h) => {
    const d = h && h.skus[s.code];
    if (!d) { priceBox.append(el('p', { class: 'empty' }, 'No price history for this article.')); return; }
    const dates = h.weeks.map((w) => new Date(w));
    lineChart(priceBox, { dates, h: 300, yfmt: (v) => fmt.n(v), series: [{ name: 'Regular shelf price', values: d.reg, color: 'var(--plum)', width: 2.4 },
      { name: 'Price paid', values: d.sell, color: 'var(--navy)', width: 1.4 }, { name: 'Cost with IVA', values: d.cost, color: 'var(--gold-400)', width: 1.6, dash: '4 3' }] });
    lineChart(unitBox, { dates, h: 200, yfmt: (v) => fmt.n(v), series: [{ name: 'Units', values: d.units, color: 'var(--plum-400)', width: 1.6 }] });
  });
  return wrap;
}

// ---------------------------------------------------------------- 3. Price elasticity
V.elasticity = () => {
  const box = el('div', { style: 'display:grid;gap:18px' }); const filter = el('section', { class: 'card' });
  function draw() {
    filter.replaceChildren(el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Choose articles'), el('p', { class: 'sub' }, 'Main group, then sub group, then short description, then the article'))),
      hierFilter(SEL, draw, { article: true }));
    box.replaceChildren(SEL.code && BY_CODE.get(SEL.code) ? elasArticle(BY_CODE.get(SEL.code)) : elasSelection());
  }
  draw();
  return [head('Step 3', 'Price elasticity', 'How strongly customers react to a price change for each article: what it means, how sure we are, and where the evidence ends.'),
    el('div', { class: 'explain' }, el('b', {}, 'What the number means. '), 'Price elasticity is the % change in units for a 1% change in price. At ', el('b', {}, '−1.0'),
      ', a 10% rise loses about 10% of units. At ', el('b', {}, '−0.3'), ' customers barely react (a rise is safe for profit); at ', el('b', {}, '−2.5'),
      ' they react strongly (a rise loses profit, a cut may win it). Rises and cuts are measured apart, because customers often react more to one than the other.'), filter, box];
};
function elasSelection() {
  const rows = SKUS.filter((s) => inSel(s) && s.e != null);
  const bands = d3.rollups(rows, (v) => ({ n: v.length, rev: d3.sum(v, (s) => s.rev) }), (s) => bandOf(s.e)); const tot = d3.sum(rows, (s) => s.rev) || 1;
  const order = ['Highly elastic', 'Elastic', 'Moderate', 'Inelastic'];
  const dist = el('div', { class: 'chart' });
  later(() => { // strip chart: every article's rise elasticity, sized by revenue
    dist.replaceChildren(); const h = 150; const { w } = measure(dist, h); const m = { t: 10, r: 14, b: 30, l: 14 };
    const x = d3.scaleLinear().domain([-5, 0]).range([m.l, w - m.r]); const r = d3.scaleSqrt().domain([0, d3.max(rows, (s) => s.rev) || 1]).range([2, 14]);
    const svg = d3.select(dist).append('svg').attr('width', w).attr('height', h).attr('role', 'img').attr('aria-label', 'Price elasticity of each article');
    [-2, -1, -0.5].forEach((v) => svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', m.t).attr('y2', h - m.b).attr('stroke', 'var(--line)').attr('stroke-dasharray', '3 3'));
    svg.append('g').attr('class', 'ax').attr('transform', `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(10).tickSizeOuter(0));
    const rnd = d3.randomLcg(7);
    svg.append('g').selectAll('circle').data(rows).join('circle').attr('cx', (s) => x(Math.max(-5, s.e_rise))).attr('cy', () => m.t + 12 + rnd() * (h - m.t - m.b - 24)).attr('r', (s) => r(s.rev))
      .attr('fill', 'var(--plum-400)').attr('fill-opacity', .45).attr('stroke', 'var(--plum)').attr('stroke-opacity', .5).style('cursor', 'pointer')
      .on('mousemove', (ev, s) => showTip(ev, s.name, [['Path', `${s.sub} › ${s.sd}`], ['Rise elasticity', s.e_rise.toFixed(2)], ['Cut elasticity', s.e_cut.toFixed(2)], ['Revenue', fmt.usd(s.rev)]]))
      .on('mouseleave', hideTip).on('click', (ev, s) => { SEL.code = s.code; store.set('sel', SEL); render(); });
  });
  return el('div', { style: 'display:grid;gap:18px' },
    el('div', { class: 'kpis' }, order.map((b) => { const x = bands.find((y) => y[0] === b); return kpi(b, x ? fmt.n(x[1].n) : '0', x ? `${(x[1].rev / tot * 100).toFixed(0)}% of revenue` : 'no articles'); })),
    card('Every article in this selection', 'Rise elasticity; bigger dot = more revenue. Left = customers react strongly, right = they barely react. Click a dot for the article.', dist),
    card('Articles', 'Click a row for the full explanation', dataTable({ rows, sort: { k: 'rev', dir: -1 }, pageSize: 100, onRow: (r) => { SEL.code = r.code; store.set('sel', SEL); render(); }, cols: [
      { h: 'Article', key: 'name', f: artCell }, { h: 'Rise', key: 'e_rise', num: 1, f: (r) => r.e_rise.toFixed(2) }, { h: 'Cut', key: 'e_cut', num: 1, f: (r) => r.e_cut.toFixed(2) },
      { h: 'Band', key: 'e', f: (r) => pill(bandOf(r.e), BAND_TONE[bandOf(r.e)]) }, { h: 'Confidence', key: 'conf', f: (r) => pill(r.conf, r.conf === 'High' ? 'ok' : r.conf === 'Low' ? 'warn' : '') },
      { h: 'Stays in sub group', key: 'div', num: 1, f: (r) => fmt.pct((r.div || 0) * 100, 0, false) }, { h: 'Revenue', key: 'rev', num: 1, f: (r) => fmt.usd(r.rev) }] })));
}
function elasArticle(s) {
  const wrap = el('div', { style: 'display:grid;gap:18px' });
  const back = el('div', { class: 'toolbar' }, el('button', { class: 'btn', onclick: () => { SEL.code = ''; store.set('sel', SEL); render(); } }, '← All articles'), el('button', { class: 'btn', onclick: () => go('today') }, '← Today’s price'),
    el('button', { class: 'btn primary', onclick: () => { SIM.code = s.code; SIM.d = Math.round(s.chg); go('simulator'); } }, 'Try a price →'));
  wrap.append(el('section', { class: 'card' }, el('div', { class: 'card-head' }, articleHead(s, pill(bandOf(s.e), BAND_TONE[bandOf(s.e)]), pill(s.conf + ' confidence', s.conf === 'High' ? 'ok' : s.conf === 'Low' ? 'warn' : '')), back)));
  if (s.e == null || !simulate(s, 0.05)) { wrap.append(el('div', { class: 'banner warn' }, 'This article has no measured price elasticity (too little sales history or price variation), so the plan holds its price.')); return wrap; }
  const up = simulate(s, 0.05), dn = simulate(s, -0.05);
  const caut = (d) => (Math.pow(1 + d, Math.min((d > 0 ? s.e_rise : s.e_cut) * Math.min(2, Math.max(1, (s.e_caut / s.e) || 1.5)), -0.1)) - 1) * 100;
  const opt = (d) => (Math.pow(1 + d, (d > 0 ? s.e_rise : s.e_cut) * 0.67) - 1) * 100;
  const curve = el('div', { class: 'chart' });
  wrap.append(el('section', { class: 'card' }, el('p', { class: 'big-sentence' }, 'If the price goes ', el('b', {}, 'up 5%'), ', units fall about ', el('b', {}, fmt.pct(-up.unitsPct, 1, false)),
      ` (between ${fmt.pct(-opt(0.05), 1, false)} and ${fmt.pct(-caut(0.05), 1, false)}). If it goes `, el('b', {}, 'down 5%'), ', units rise about ', el('b', {}, fmt.pct(dn.unitsPct, 1, false)), '.'),
    el('p', { class: 'note' }, s.e_rise > -0.5 ? 'Customers barely react: a modest rise keeps almost all units and lifts profit.' : s.e_rise > -1 ? 'Customers react moderately: small rises usually pay; large ones cost volume.'
      : s.e_rise > -2 ? 'Customers react about one-for-one: a rise pays only when the margin is thin.' : 'Customers react strongly: rises cost profit; this article competes on price.')),
    el('div', { class: 'kpis' }, kpi('Rise elasticity', s.e_rise.toFixed(2), 'used for price rises'), kpi('Cut elasticity', s.e_cut.toFixed(2), 'used for price cuts'),
      kpi('Cautious case', s.e_caut.toFixed(2), 'customers react more than expected'), kpi('Switching', fmt.pct((s.div || 0) * 100, 0, false), 'of lost sales stay with sub-group rivals'),
      kpi('Tested price range', s.down != null ? `−${(s.down * 100).toFixed(0)}% / +${(s.up * 100).toFixed(0)}%` : '–', 'past price moves seen in the data')),
    card('Units at every price', 'Likely change in units (line), cautious to optimistic range (shaded), tested range (light band). Outside the tested range the model extrapolates.', curve));
  later(() => {
    curve.replaceChildren(); const h = 300; const { w } = measure(curve, h); const m = { t: 14, r: 14, b: 30, l: 52 };
    const ds = d3.range(-15, 16); const x = d3.scaleLinear().domain([-15, 15]).range([m.l, w - m.r]);
    const pts = ds.map((d) => ({ d, l: (Math.pow(1 + d / 100, d > 0 ? s.e_rise : s.e_cut) - 1) * 100, c: caut(d / 100), o: opt(d / 100) }));
    const y = d3.scaleLinear().domain(d3.extent(pts.flatMap((p) => [p.l, p.c, p.o]))).nice().range([h - m.b, m.t]);
    const svg = d3.select(curve).append('svg').attr('width', w).attr('height', h).attr('role', 'img').attr('aria-label', 'Units change by price change');
    const lo = -(s.down || .05) * 100, hi = (s.up || .05) * 100;
    svg.append('rect').attr('x', x(Math.max(-15, lo))).attr('width', x(Math.min(15, hi)) - x(Math.max(-15, lo))).attr('y', m.t).attr('height', h - m.t - m.b).attr('fill', 'var(--plum-50)');
    svg.append('g').attr('class', 'gridl').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickSize(-(w - m.l - m.r)).tickFormat(''));
    svg.append('g').attr('class', 'ax').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickFormat((v) => (v > 0 ? '+' : '') + v + '%').tickSize(0)).call((g) => g.select('.domain').remove()).selectAll('text').attr('dx', -6);
    svg.append('g').attr('class', 'ax').attr('transform', `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(7).tickFormat((v) => (v > 0 ? '+' : '') + v + '% price').tickSizeOuter(0));
    svg.append('line').attr('x1', m.l).attr('x2', w - m.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--plum-200)');
    svg.append('path').datum(pts).attr('fill', 'var(--gold-100)').attr('opacity', .9).attr('d', d3.area().x((p) => x(p.d)).y0((p) => y(Math.min(p.c, p.o))).y1((p) => y(Math.max(p.c, p.o))));
    svg.append('path').datum(pts).attr('fill', 'none').attr('stroke', 'var(--plum)').attr('stroke-width', 2.6).attr('d', d3.line().x((p) => x(p.d)).y((p) => y(p.l)));
    svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', w - m.l - m.r).attr('height', h - m.t - m.b).attr('fill', 'transparent')
      .on('mousemove', (ev) => { const d = Math.round(x.invert(d3.pointer(ev)[0])); const p = pts.find((q) => q.d === d); if (p) showTip(ev, `Price ${fmt.pct(d, 0)}`, [['Units, likely', fmt.pct(p.l)], ['Range', `${fmt.pct(Math.min(p.c, p.o))} to ${fmt.pct(Math.max(p.c, p.o))}`]]); })
      .on('mouseleave', hideTip);
  });
  return wrap;
}

// ---------------------------------------------------------------- 4. Forecast and target
const FC = { source: 'current', upload: null, info: null, result: null,
  t: store.get('target', { target: '', maxRise: 8, lowRise: 5, unitCap: 15, basket: 1.8, holdKvi: true, cuts: true }) };
function planWith(t, units) {
  const pool = SKUS.filter((s) => s.shelf && simulate(s, 0) && !(t.holdKvi && s.kvi));
  const revAll = d3.sum(SKUS, (s) => s.rev) || 1;
  const cand = pool.map((s) => {
    const base = units && units.has(s.code) ? units.get(s.code) : s.units; const ss = { ...s, units: base };
    const up = Math.min(s.conf === 'Low' ? t.lowRise : t.maxRise, Math.max(3, (s.up || .05) * 100));
    const dn = t.cuts && !s.supply_risk ? Math.min(10, Math.max(3, (s.down || .05) * 100)) : 0;
    const opts = [];
    for (let d = -Math.floor(dn); d <= Math.floor(up); d++) {
      if (d > 0 && s.repriced >= 15) continue;
      if (d < 0 && s.p_net * (1 + d / 100) < s.cost) continue;
      const p = simulate(ss, d / 100); if (!p) continue;
      if (d > 0 && (p.unitsPct < -t.unitCap || (s.conf === 'Low' && (Math.pow(1 + d / 100, Math.min(s.e_rise * Math.min(2, Math.max(1, (s.e_caut / s.e) || 1.5)), -0.2)) - 1) * 100 < -t.unitCap))) continue;
      opts.push({ d, gain: p.gain, gainS: p.gainS, unitsPct: p.unitsPct, w: s.rev * d / 100 });
    }
    return { s, base, opts };
  });
  const run = (lam) => { let gain = 0, gainS = 0, bw = 0; const pick = new Map();
    cand.forEach(({ s, opts }) => { let best = null; opts.forEach((o) => { if (o.d === 0) return; const v = o.gain - lam * o.w * 1; if (o.gain > 200 && (!best || v > best.v)) best = { ...o, v }; });
      if (best && best.v > 0) { pick.set(s.code, best); gain += best.gain; gainS += best.gainS; bw += best.w; } });
    return { pick, gain, gainS, basket: bw / revAll * 100, lam }; };
  let r = run(0);
  if (r.basket > t.basket) { let lo = 0, hi = 5; for (let i = 0; i < 30; i++) { const mid = (lo + hi) / 2; const x = run(mid); if (x.basket > t.basket) lo = mid; else { hi = mid; r = x; } } }
  const target = parseFloat(t.target);
  let met = null;
  if (target > 0) { met = r.gain >= target; if (met) { let lo = r.lam, hi = r.lam + 5, best = r; for (let i = 0; i < 30; i++) { const mid = (lo + hi) / 2; const x = run(mid); if (x.gain >= target) { lo = mid; best = x; } else hi = mid; } r = best; } }
  const units0 = d3.sum(cand, (c) => c.base); const units1 = d3.sum(cand, (c) => c.base * (1 + ((r.pick.get(c.s.code) || {}).unitsPct || 0) / 100));
  return { ...r, met, target, rises: [...r.pick.values()].filter((o) => o.d > 0).length, cuts: [...r.pick.values()].filter((o) => o.d < 0).length, unitsPct: (units1 / units0 - 1) * 100, t: { ...t }, source: units ? 'upload' : 'current' };
}
function parseForecast(text) {
  const lines = text.replace(/\r/g, '').split('\n').filter((l) => l.trim()); if (lines.length < 2) throw new Error('the file is empty');
  const sep = lines[0].includes(';') && !lines[0].includes(',') ? ';' : ',';
  const hdr = lines[0].split(sep).map((h) => h.trim().replace(/^"|"$/g, '').toLowerCase());
  const ci = hdr.findIndex((h) => ['sku_code', 'code', 'article', 'article_code', 'articlecode'].includes(h));
  const wi = hdr.findIndex((h) => ['week_start', 'week'].includes(h));
  const ui = hdr.findIndex((h) => ['units_52w', 'units', 'forecast', 'qty'].includes(h));
  if (ci < 0 || ui < 0) throw new Error('need a code column (SKU_Code) and a units column (Units_52w, or Week_Start + Units)');
  const out = new Map(); let bad = 0;
  lines.slice(1).forEach((l) => { const c = l.split(sep).map((x) => x.trim().replace(/^"|"$/g, '')); const code = String(c[ci] || '').replace(/^0+/, ''); const u = parseFloat(c[ui]);
    if (!code || isNaN(u)) { bad++; return; } out.set(code, (out.get(code) || 0) + u); });
  return { map: out, weekly: wi >= 0, rows: lines.length - 1, bad };
}
V.forecast = () => {
  const t = FC.t; const out = el('div', { style: 'display:grid;gap:18px' });
  const chart = el('div', { class: 'chart' });
  const seg = el('div', { class: 'seg' }, ['current', 'upload'].map((k) => el('button', { 'aria-pressed': String(FC.source === k), onclick: () => { FC.source = k; render(); } }, k === 'current' ? 'Use the current forecast' : 'Upload my forecast')));
  const fcCard = el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Forecast'), el('p', { class: 'sub' }, 'Units each article will sell in the next 52 weeks at today’s price')), seg));
  if (FC.source === 'current') {
    fcCard.append(el('div', { class: 'banner info' }, `Our forecast: ${fmt.n(SKUS.filter((s) => s.units > 0).length)} articles, a blend of machine learning and the seasonal path (weekly error about ${fmt.pct(M.forecast[0].Mean_WAPE_week, 0, false)}, 13-week error ${fmt.pct(M.forecast[0].Mean_WAPE_13w, 0, false)}).`), chart);
    later(() => { const ds = WEEKLY.weeks.map((d) => new Date(d)); lineChart(chart, { dates: ds, h: 240, yfmt: (v) => fmt.n(v / 1000, 0) + 'K', series: [{ name: 'Units, all articles', values: WEEKLY.chain.map((r) => r.Units_now), color: 'var(--plum)', width: 2.4 }] }); });
  } else {
    const file = el('input', { type: 'file', accept: '.csv,text/csv', hidden: true, onchange: (e) => readFile(e.target.files[0]) });
    const drop = el('div', { class: 'drop', onclick: () => file.click(), ondragover: (e) => { e.preventDefault(); drop.classList.add('over'); }, ondragleave: () => drop.classList.remove('over'),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove('over'); readFile(e.dataTransfer.files[0]); } },
      el('b', {}, 'Drop a CSV here or click to choose'), el('div', { class: 'note', style: 'margin-top:6px' }, 'Columns: SKU_Code and Units_52w (one row per article), or SKU_Code, Week_Start and Units (weekly rows, added up). Same units as the template.'));
    const tmpl = el('button', { class: 'btn', onclick: () => csvDownload('fresmart_forecast_template.csv', [['SKU_Code', 'code'], ['Article', 'name'], ['MainGroup', 'group'], ['SubGroup', 'sub'], ['ShortDesc', 'sd'], ['Units_52w', (r) => Math.round(r.units)]], SKUS.filter((s) => s.shelf && s.units > 0)) }, '↓ Template with our forecast');
    fcCard.append(drop, file, el('div', { class: 'toolbar' }, tmpl, FC.upload ? el('button', { class: 'btn', onclick: () => { FC.upload = null; FC.info = null; render(); } }, 'Clear upload') : null));
    if (FC.info) { const i = FC.info;
      fcCard.append(el('div', { class: 'banner ' + (i.matched ? 'ok' : 'warn') }, `${i.name}: ${fmt.n(i.rows)} rows, ${fmt.n(i.matched)} articles matched, ${fmt.n(i.unmatched)} codes not found${i.bad ? `, ${fmt.n(i.bad)} rows unreadable` : ''}. Matched articles: ${fmt.n(i.theirs)} units vs ${fmt.n(i.ours)} in our forecast (${fmt.pct((i.theirs / i.ours - 1) * 100)}).`));
      if (i.diff.length) fcCard.append(dataTable({ rows: i.diff, cols: [{ h: 'Article', f: (r) => artCell(r.s) }, { h: 'Our forecast', num: 1, f: (r) => fmt.n(r.ours) }, { h: 'Yours', num: 1, f: (r) => fmt.n(r.theirs) }, { h: 'Difference', num: 1, f: (r) => fmt.pct((r.theirs / r.ours - 1) * 100) }] })); }
    if (FC.error) fcCard.append(el('div', { class: 'banner warn' }, FC.error));
  }
  function readFile(f) { if (!f) return; const rd = new FileReader(); rd.onload = () => { try { const p = parseForecast(String(rd.result)); const m = new Map(); let unmatched = 0;
      p.map.forEach((u, c) => { if (BY_CODE.has(c)) m.set(c, u); else unmatched++; });
      const diff = [...m.entries()].map(([c, u]) => ({ s: BY_CODE.get(c), ours: BY_CODE.get(c).units, theirs: u })).filter((r) => r.ours > 0).sort((a, b) => Math.abs(b.theirs - b.ours) - Math.abs(a.theirs - a.ours)).slice(0, 10);
      FC.upload = m; FC.error = null; FC.info = { name: f.name, rows: p.rows, bad: p.bad, matched: m.size, unmatched, theirs: d3.sum([...m.entries()].filter(([c]) => BY_CODE.get(c).units > 0), ([, u]) => u), ours: d3.sum([...m.keys()], (c) => BY_CODE.get(c).units || 0) || 1, diff };
    } catch (e) { FC.error = `Could not read ${f.name}: ${e.message}.`; } render(); }; rd.readAsText(f); }
  const num = (key, label, hint, step = 1) => el('label', { class: 'field' }, label, el('input', { class: 'inp', type: 'number', step, min: 0, value: t[key], oninput: (e) => { t[key] = e.target.value === '' ? '' : +e.target.value; store.set('target', t); } }), el('span', { class: 'hint' }, hint));
  const chk = (key, label) => el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: t[key] || null, onchange: (e) => { t[key] = e.target.checked; store.set('target', t); } }), label);
  const tgCard = el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Target and limits'), el('p', { class: 'sub' }, 'Set the profit you want and the limits; leave the target empty to get the most profit within the limits'))),
    el('div', { class: 'form-grid' }, el('label', { class: 'field' }, 'Profit gain target, US$ per year', el('input', { class: 'inp', type: 'number', step: 50000, min: 0, placeholder: 'e.g. 1500000', value: t.target, oninput: (e) => { t.target = e.target.value; store.set('target', t); } }), el('span', { class: 'hint' }, `the official plan gains ${fmt.usd(M.plan.gain)}`)),
      num('maxRise', 'Biggest price rise, %', 'any article'), num('lowRise', 'Biggest rise, low-confidence articles, %', 'less evidence, smaller steps'), num('unitCap', 'Most units an article may lose, %', 'per article, likely case'),
      num('basket', 'Basket rise cap, %', 'sales-weighted, all articles', 0.1)),
    el('div', { class: 'toolbar' }, chk('holdKvi', 'Hold everyday KVIs (112 articles)'), chk('cuts', 'Allow price cuts'),
      el('button', { class: 'btn primary', style: 'margin-left:auto', onclick: () => { FC.result = planWith(t, FC.source === 'upload' ? FC.upload : null); render(); } }, 'Build my plan')));
  out.append(fcCard, tgCard);
  if (FC.result) { const r = FC.result;
    out.append(el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Your plan'), el('p', { class: 'sub' }, `${r.source === 'upload' ? 'Your uploaded forecast' : 'Current forecast'} · rises ≤ ${r.t.maxRise}% (low confidence ≤ ${r.t.lowRise}%) · units ≤ −${r.t.unitCap}% · basket ≤ ${r.t.basket}%`)),
        el('button', { class: 'btn primary', onclick: () => { PL.plan = 'custom'; go('prices'); } }, 'See it in Recommended price →')),
      r.met === false ? el('div', { class: 'banner warn' }, `The target of ${fmt.usd(r.target)} cannot be reached within these limits; the best is ${fmt.usd(r.gain)}. Loosen a limit or lower the target.`)
        : r.met ? el('div', { class: 'banner ok' }, `Target of ${fmt.usd(r.target)} reached with the gentlest prices that still get there.`) : null,
      el('div', { class: 'kpis' }, kpi('Gain, likely', fmt.usd(r.gain), `official plan ${fmt.usd(M.plan.gain)}`), kpi('Gain, cautious', fmt.usd(r.gainS), 'customers react 1.5x'), kpi('Price rises', fmt.n(r.rises), `${fmt.n(r.cuts)} cuts`),
        kpi('Basket rise', fmt.pct(r.basket, 2), `cap ${r.t.basket}%`), kpi('Units', fmt.pct(r.unitsPct), 'articles priced')),
      el('p', { class: 'note' }, 'Your plan is built here in the browser from each article’s own sales: it leaves out shoppers switching between brands, the sub-group profit check and shelf-price endings, so it differs a little from the official plan. To make it official, the optimiser is re-run in Python with your forecast and limits.'))); }
  return [head('Step 4', 'Forecast & target', 'Use our forecast or upload your own, set the profit you want and the limits, and build a plan.'), out];
};

// ---------------------------------------------------------------- 5. Promotions
const PROMO = store.get('promo', { items: [], disc: 10, weeks: 2, start: '' });
const PSEL = { group: '', sub: '', sd: '', code: '', q: '' };
function promoCalc(s, disc, weeks) {
  if (!simulate(s, 0)) return null;
  const wk = s.units / 52, d = -disc / 100;
  const u = (e) => wk * Math.pow(1 + d, e);
  const uL = u(s.e_cut), uLo = u(s.e_cut * 0.67), uHi = u(s.e_cut * 1.5);
  const m0 = s.p_net - s.cost, m1 = s.p_net * (1 + d) - s.cost;
  const own = (uu) => (uu * m1 - wk * m0) * weeks / FX;
  const cannib = (uu) => (s.div || 0) * Math.max(0, uu - wk) * m0 * weeks / FX;
  return { wk, units: uL * weeks, extra: (uL - wk) * weeks, extraPct: (uL / wk - 1) * 100, promoPrice: s.price * (1 + d), own: own(uL), net: own(uL) - cannib(uL),
    netLo: own(uLo) - cannib(uLo), netHi: own(uHi) - cannib(uHi), revExtra: (uL * s.p_net * (1 + d) - wk * s.p_net) * weeks / FX, giveaway: wk * s.p_net * disc / 100 * weeks / FX, belowCost: m1 < 0 };
}
V.promos = () => {
  const out = el('div', { style: 'display:grid;gap:18px' });
  const save = () => store.set('promo', PROMO);
  const add = (codes) => { codes.forEach((c) => { if (!PROMO.items.some((i) => i.code === c)) PROMO.items.push({ code: c, disc: PROMO.disc, weeks: PROMO.weeks }); }); save(); render(); };
  const pick = el('section', { class: 'card' }); out.append(pick);
  function drawPick() {
    const pool = SKUS.filter((s) => s.shelf && simulate(s, 0) && inSel(s, PSEL) && (!PSEL.q || s.name.toLowerCase().includes(PSEL.q) || s.code.includes(PSEL.q))).sort((a, b) => b.rev - a.rev);
    pick.replaceChildren(el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Choose articles'), el('p', { class: 'sub' }, 'Filter, then add articles to the promotion'))),
      hierFilter(PSEL, drawPick), el('input', { class: 'inp', type: 'search', placeholder: 'Search name or code', value: PSEL.q, oninput: (e) => { PSEL.q = e.target.value.trim().toLowerCase(); drawPick(); } }),
      el('div', { class: 'tablebox short' }, el('table', { class: 't' }, el('tbody', {}, pool.slice(0, 40).map((s) => el('tr', {}, el('td', {}, artCell(s)), el('td', { class: 'num' }, fmt.kz(s.price)),
        el('td', { class: 'num' }, pill(bandOf(s.e_cut), BAND_TONE[bandOf(s.e_cut)])), el('td', { class: 'num' }, PROMO.items.some((i) => i.code === s.code) ? pill('Added', 'ok') : el('button', { class: 'btn', onclick: () => add([s.code]) }, '+ Add'))))))),
      el('div', { class: 'toolbar' }, el('span', { class: 'note' }, `${fmt.n(pool.length)} articles on the shelf match${pool.length > 40 ? '; showing the 40 biggest' : ''}`),
        pool.length ? el('button', { class: 'btn', style: 'margin-left:auto', onclick: () => add(pool.slice(0, 25).map((s) => s.code)) }, `+ Add top ${Math.min(25, pool.length)}`) : null));
  }
  drawPick();
  const rows = PROMO.items.map((i) => ({ ...i, s: BY_CODE.get(i.code) })).filter((r) => r.s).map((r) => ({ ...r, c: promoCalc(r.s, r.disc, r.weeks) })).filter((r) => r.c);
  const T = { own: d3.sum(rows, (r) => r.c.own), net: d3.sum(rows, (r) => r.c.net), lo: d3.sum(rows, (r) => r.c.netLo), hi: d3.sum(rows, (r) => r.c.netHi), extra: d3.sum(rows, (r) => r.c.extra), rev: d3.sum(rows, (r) => r.c.revExtra), give: d3.sum(rows, (r) => r.c.giveaway) };
  const warn = (r) => [r.c.belowCost ? pill('Below cost', 'bad') : null, r.s.kvi ? pill('Everyday KVI', 'plum') : null, (r.s.supply_risk || r.s.stockout >= 20) ? pill('Short supply', 'bad') : null,
    r.s.chg > 0 ? pill('Rise planned', 'warn') : null, r.s.conf === 'Low' ? pill('Low confidence', 'warn') : null].filter(Boolean);
  const setAll = el('div', { class: 'toolbar' }, el('label', { class: 'field' }, 'Discount, %', el('input', { class: 'inp', type: 'number', min: 1, max: 60, value: PROMO.disc, oninput: (e) => { PROMO.disc = +e.target.value; save(); } })),
    el('label', { class: 'field' }, 'Weeks', el('input', { class: 'inp', type: 'number', min: 1, max: 12, value: PROMO.weeks, oninput: (e) => { PROMO.weeks = +e.target.value; save(); } })),
    el('label', { class: 'field' }, 'Start', el('input', { class: 'inp', type: 'date', value: PROMO.start, onchange: (e) => { PROMO.start = e.target.value; save(); } })),
    el('button', { class: 'btn', style: 'align-self:end', onclick: () => { PROMO.items.forEach((i) => { i.disc = PROMO.disc; i.weeks = PROMO.weeks; }); save(); render(); } }, 'Apply to all'),
    rows.length ? el('button', { class: 'btn', style: 'align-self:end', onclick: () => csvDownload('fresmart_promotion.csv', [['Code', (r) => r.code], ['Article', (r) => r.s.name], ['MainGroup', (r) => r.s.group], ['SubGroup', (r) => r.s.sub], ['ShortDesc', (r) => r.s.sd],
      ['Shelf price Kz', (r) => r.s.price], ['Promo price Kz', (r) => r.c.promoPrice.toFixed(2)], ['Discount %', 'disc'], ['Weeks', 'weeks'], ['Start', () => PROMO.start], ['Extra units', (r) => Math.round(r.c.extra)], ['GP change own USD', (r) => Math.round(r.c.own)], ['GP change net USD', (r) => Math.round(r.c.net)]], rows) }, '↓ Export CSV') : null,
    rows.length ? el('button', { class: 'btn', style: 'align-self:end', onclick: () => { PROMO.items = []; save(); render(); } }, 'Clear list') : null);
  out.append(el('section', { class: 'card' }, el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Promotion'), el('p', { class: 'sub' }, `${fmt.n(rows.length)} articles${PROMO.start ? ' · from ' + PROMO.start : ''}`))), setAll,
    rows.length ? el('div', { class: 'kpis' }, kpi('Extra units', fmt.n(T.extra), 'over the promotion'), kpi('Extra revenue', fmt.usdSigned(T.rev), 'after IVA'), kpi('Discount given away', fmt.usd(T.give), 'on the units you would sell anyway'),
      kpi('Gross profit, own', fmt.usdSigned(T.own), 'these articles only', T.own < 0 ? 'down' : 'up'), kpi('Gross profit, net', fmt.usdSigned(T.net), `after switching from rivals; range ${fmt.usdSigned(Math.min(T.lo, T.hi))} to ${fmt.usdSigned(Math.max(T.lo, T.hi))}`, T.net < 0 ? 'down' : 'up')) : el('p', { class: 'empty' }, 'Add articles above to plan a promotion.'),
    rows.length ? dataTable({ rows, cols: [{ h: 'Article', f: (r) => artCell(r.s) }, { h: 'Price → promo', num: 1, f: (r) => el('div', {}, el('div', { class: 'muted', style: 'text-decoration:line-through' }, fmt.kz(r.s.price)), el('b', {}, fmt.kz(r.c.promoPrice))) },
      { h: 'Discount %', num: 1, f: (r) => el('input', { class: 'inline-inp', type: 'number', min: 1, max: 60, value: r.disc, onchange: (e) => { PROMO.items.find((i) => i.code === r.code).disc = +e.target.value; save(); render(); } }) },
      { h: 'Weeks', num: 1, f: (r) => el('input', { class: 'inline-inp', type: 'number', min: 1, max: 12, value: r.weeks, onchange: (e) => { PROMO.items.find((i) => i.code === r.code).weeks = +e.target.value; save(); render(); } }) },
      { h: 'Units lift', num: 1, f: (r) => fmt.pct(r.c.extraPct, 0) }, { h: 'GP, own', num: 1, f: (r) => el('span', { class: r.c.own < 0 ? 'down' : 'up' }, fmt.usdSigned(r.c.own)) },
      { h: 'GP, net', num: 1, f: (r) => el('b', { class: r.c.net < 0 ? 'down' : 'up' }, fmt.usdSigned(r.c.net)) }, { h: 'Watch', f: (r) => el('div', { class: 'chips' }, warn(r)) },
      { h: '', f: (r) => el('button', { class: 'btn', onclick: () => { PROMO.items = PROMO.items.filter((i) => i.code !== r.code); save(); render(); } }, 'Remove') }] }) : null,
    el('p', { class: 'note' }, 'Estimated from each article’s price-cut elasticity; the range uses customers reacting a third less to 1.5x more. Fresmart’s promotion history is not in the data yet, so short promotions may lift more (stock-up buying) or less than shown. "Net" takes off the profit of sales that switch over from sub-group rivals.')));
  return [head('Step 5', 'Promotions', 'Try a promotion: pick articles, a discount and the weeks, and see units and profit before it runs.'), out];
};

const PL = { q: '', wave: '', group: '', sub: '', sd: '', code: '', conf: '', dir: 'changed', plan: 'official' };
/* the plan shown: official (pipeline) or the user's own (Forecast & target page), as per-article rows */
function planRows() {
  if (PL.plan !== 'custom' || !FC.result) return SKUS;
  return SKUS.map((s) => { const o = FC.result.pick.get(s.code); const d = o ? o.d : 0;
    return { ...s, chg: d, new_price: s.price ? s.price * (1 + d / 100) : s.price, gain: o ? o.gain : 0, gain_c: o ? o.gainS : 0, units_chg: o ? o.unitsPct : 0,
      m_new: s.p_net ? (s.p_net * (1 + d / 100) - s.cost) / (s.p_net * (1 + d / 100)) * 100 : s.m_now, wave: o ? 'Your plan' : 'Hold', reason: o ? `Your plan: ${fmt.pct(d, 0)} (built on the Forecast & target page)` : 'Your plan: no change' }; });
}
V.prices = () => {
  if (PL.plan === 'custom' && !FC.result) PL.plan = 'official';
  const all = planRows();
  const count = el('span', { class: 'count' });
  const filt = () => all.filter((s) => (!PL.q || s.name.toLowerCase().includes(PL.q) || s.code.includes(PL.q)) && inSel(s, PL) && (!PL.wave || s.wave === PL.wave)
    && (!PL.conf || s.conf === PL.conf) && (PL.dir === 'all' || (PL.dir === 'changed' && s.chg !== 0) || (PL.dir === 'held' && s.chg === 0 && s.shelf) || (PL.dir === 'flags' && s.flags > 0 && s.chg !== 0) || (PL.dir === 'off' && !s.shelf)));
  const cols = [
    { h: 'Article', key: 'name', f: artCell },
    { h: 'Today', key: 'price', num: 1, f: (r) => fmt.kz(r.price) }, { h: 'Recommended', key: 'new_price', num: 1, f: (r) => r.chg ? el('b', {}, fmt.kz(r.new_price)) : fmt.kz(r.price) },
    { h: 'Change', key: 'chg', num: 1, f: (r) => chgPill(r.chg) }, { h: 'Units', key: 'units_chg', num: 1, f: (r) => r.chg ? fmt.pct(r.units_chg) : '–' },
    { h: 'Margin now → new', key: 'm_now', num: 1, f: (r) => r.m_now == null ? '–' : r.chg ? `${r.m_now.toFixed(1)}% → ${r.m_new.toFixed(1)}%` : `${r.m_now.toFixed(1)}%` },
    { h: 'Gain', key: 'gain', num: 1, f: (r) => r.gain ? fmt.usdSigned(r.gain) : '–' },
    { h: 'Confidence', key: 'conf', f: (r) => pill(r.conf || '–', r.conf === 'High' ? 'ok' : r.conf === 'Low' ? 'warn' : '') },
    { h: 'Wave', key: 'wave', f: (r) => el('span', { class: 'muted', style: 'white-space:nowrap' }, r.wave) }];
  const table = dataTable({ cols, rows: filt(), sort: { k: 'gain', dir: -1 }, onRow: (r) => openSku(r.code), pageSize: 100 });
  const refresh = () => { const rs = filt(); table.update(rs); count.textContent = `${fmt.n(rs.length)} articles · their gain ${fmt.usd(d3.sum(rs, (r) => r.gain))} a year`; };
  const chip = (key, val, label, n) => { const b = el('button', { class: 'chip', 'aria-pressed': String(PL[key] === val), onclick: () => { PL[key] = val; b.parentElement.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true'); refresh(); } }, label, n != null ? el('span', { class: 'n' }, fmt.n(n)) : null); return b; };
  const sel = (key, label, opts) => el('select', { class: 'sel', 'aria-label': label, onchange: (e) => { PL[key] = e.target.value; refresh(); } }, el('option', { value: '' }, label), opts.map((o) => el('option', { value: o, selected: PL[key] === o || null }, o)));
  const exportBtn = el('button', { class: 'btn', onclick: () => csvDownload(PL.plan === 'custom' ? 'fresmart_recommended_prices_your_plan.csv' : 'fresmart_recommended_prices.csv', [['Code', 'code'], ['Article', 'name'], ['MainGroup', 'group'], ['SubGroup', 'sub'],
    ['ShortDesc', 'sd'], ['Shelf price today Kz', 'price'], ['Recommended price Kz', (r) => (r.chg ? r.new_price : r.price)], ['Change %', (r) => r.chg.toFixed(2)], ['Units change %', 'units_chg'], ['Margin now %', 'm_now'], ['Margin new %', 'm_new'],
    ['GP gain 52w USD', 'gain'], ['GP gain cautious USD', 'gain_c'], ['Confidence', 'conf'], ['Wave', 'wave'], ['Reason', 'reason']], filt()) }, '↓ Export CSV');
  const planSeg = el('div', { class: 'seg' }, el('button', { 'aria-pressed': String(PL.plan === 'official'), onclick: () => { PL.plan = 'official'; render(); } }, 'Official plan'),
    el('button', { 'aria-pressed': String(PL.plan === 'custom'), disabled: FC.result ? null : true, title: FC.result ? null : 'Build a plan on the Forecast & target page first', onclick: () => { PL.plan = 'custom'; render(); } }, 'Your plan'));
  const hier = el('div', {});
  const drawHier = () => { hier.replaceChildren(hierFilter(PL, () => { drawHier(); refresh(); })); };
  drawHier();
  const dirChips = el('div', { class: 'chips' }, chip('dir', 'changed', 'Price changes', all.filter((s) => s.chg).length), chip('dir', 'held', 'On shelf, held', all.filter((s) => !s.chg && s.shelf).length),
    chip('dir', 'flags', 'Changes with flags', all.filter((s) => s.chg && s.flags > 0).length), chip('dir', 'off', 'Not on shelf', all.filter((s) => !s.shelf).length), chip('dir', 'all', 'All', all.length));
  later(refresh);
  return [head('Step 6', 'Recommended price', 'Today’s shelf price and the recommended price for every active article, with its expected effect. Click a row for the full detail.', planSeg, exportBtn),
    PL.plan === 'custom' ? el('div', { class: 'banner info' }, `Showing your plan from the Forecast & target page: ${fmt.n(FC.result.rises)} rises, gain ${fmt.usd(FC.result.gain)} a year. It is built from each article’s own sales, without brand switching or price endings.`) : null,
    el('section', { class: 'card' }, hier, dirChips,
      el('div', { class: 'toolbar' }, el('input', { class: 'inp grow', type: 'search', placeholder: 'Search name or code', value: PL.q, oninput: (e) => { PL.q = e.target.value.trim().toLowerCase(); refresh(); } }),
        sel('wave', 'All waves', PL.plan === 'custom' ? ['Your plan', 'Hold'] : ['Wave 1', 'Review then Wave 1', 'Test', 'Hold']), sel('conf', 'Any confidence', ['High', 'Medium', 'Low']), count),
      table)];
};

const SIM = { code: null, d: 0 };
V.simulator = () => {
  const pool = SKUS.filter((s) => s.shelf && simulate(s, 0)).sort((a, b) => b.rev - a.rev);
  if (!SIM.code || !BY_CODE.get(SIM.code) || !simulate(BY_CODE.get(SIM.code), 0)) { SIM.code = (pool.find((s) => s.chg) || pool[0]).code; SIM.d = Math.round(BY_CODE.get(SIM.code).chg); }
  const out = el('div', { class: 'sim-grid' });
  const left = el('section', { class: 'card' }); const right = el('section', { class: 'card' });
  const chart = el('div', { class: 'chart' });
  out.append(left, right);
  const input = el('input', { class: 'inp', type: 'search', placeholder: 'Pick an article', autocomplete: 'off', style: 'width:100%' });
  const res = el('div', { class: 'results', hidden: true });
  input.addEventListener('input', () => { const q = input.value.trim().toLowerCase(); if (!q) { res.hidden = true; return; }
    const m = pool.filter((s) => s.name.toLowerCase().includes(q) || s.code.includes(q)).slice(0, 8);
    res.replaceChildren(...(m.length ? m.map((s) => el('button', { class: 'result', onclick: () => { SIM.code = s.code; SIM.d = Math.round(s.chg); input.value = ''; res.hidden = true; draw(); } },
      el('span', { class: 'r-name' }, s.name), el('span', { class: 'r-sub' }, `${s.group} › ${s.sub} › ${s.sd} · ${s.code}`), el('span', { class: 'r-chg' }, chgPill(s.chg)))) : [el('div', { class: 'note', style: 'padding:8px' }, 'No article on the shelf matches')])); res.hidden = false; });
  function draw() {
    const s = BY_CODE.get(SIM.code); const p = simulate(s, SIM.d / 100);
    const slider = el('input', { class: 'slider', type: 'range', min: -15, max: 15, step: 1, value: SIM.d, 'aria-label': 'Price change', oninput: (e) => { SIM.d = +e.target.value; draw(); } });
    left.replaceChildren(el('div', { class: 'combo' }, input, res),
      el('div', {}, pathEl(s, s.code), el('h2', { style: 'font-family:var(--f-display);font-weight:500;font-size:21px;margin:4px 0 6px;color:var(--ink)' }, s.name),
        el('div', { class: 'chips' }, chgPill(s.chg), pill(s.conf + ' confidence', s.conf === 'High' ? 'ok' : s.conf === 'Low' ? 'warn' : ''), s.kvi ? pill('Everyday KVI', 'plum') : null)),
      el('div', {}, el('div', { class: 'note' }, 'Price change'), el('div', { class: 'sim-big' }, fmt.pct(SIM.d, 0)), slider,
        el('div', { class: 'toolbar', style: 'margin-top:6px' }, el('button', { class: 'btn', onclick: () => { SIM.d = 0; draw(); } }, 'Today'), s.chg ? el('button', { class: 'btn primary', onclick: () => { SIM.d = Math.round(s.chg); draw(); } }, `Plan ${fmt.pct(s.chg, 1)}`) : null)),
      el('dl', { class: 'kv' }, el('dt', {}, 'Shelf price'), el('dd', {}, p.shelf ? fmt.kz(p.shelf) : '–'), el('dt', {}, 'Units, 52 weeks'), el('dd', {}, `${fmt.n(p.units)} (${fmt.pct(p.unitsPct)})`),
        el('dt', {}, 'Margin after IVA'), el('dd', {}, fmt.pct(p.margin, 1, false)), el('dt', {}, 'Gross profit, 52 weeks'), el('dd', {}, fmt.usd(p.gp)),
        el('dt', {}, 'Gain, likely'), el('dd', { class: p.gain >= 0 ? 'up' : 'down' }, el('b', {}, fmt.usdSigned(p.gain))), el('dt', {}, 'Gain, cautious'), el('dd', {}, fmt.usdSigned(p.gainS)), el('dt', {}, 'Gain, optimistic'), el('dd', {}, fmt.usdSigned(p.gainO))),
      el('p', { class: 'note' }, `Tested range ${s.down != null ? `−${(s.down * 100).toFixed(0)}% to +${(s.up * 100).toFixed(0)}%` : 'unknown'} (shaded). Outside it the model has no evidence. This view counts the article's own sales only; the plan also counts shoppers switching between brands.`));
    right.replaceChildren(el('div', { class: 'card-head' }, el('div', {}, el('h2', {}, 'Gross-profit gain at every price'), el('p', { class: 'sub' }, 'Likely gain (line), cautious to optimistic range (gold), the plan’s price (gold dot) and your price (dashed)'))), chart,
      el('div', { class: 'legend' }, el('span', {}, el('i', { style: 'background:var(--plum)' }), 'Likely'), el('span', {}, el('i', { style: 'background:var(--gold-100)' }), 'Cautious – optimistic'), el('span', {}, el('i', { style: 'background:var(--plum-50);border:1px solid var(--line)' }), 'Tested range')));
    later(() => curveChart(chart, s, SIM.d, 360));
  }
  draw();
  return [head('Try a price', 'Price simulator', 'Move the price of any article on the shelf and see units, margin and gross profit over 52 weeks.'), out];
};

V.scenarios = () => {
  const L = M.limits; const lim = el('div', { class: 'chart' });
  const lab = (s) => s.replace(/ \(penalty [0-9.]+\)/, '').replace(' (rise <= 10%, Low confidence <= 10%)', '').replace('Before the step-3 limits', 'No new limits').replace('<=', '≤');
  later(() => colChart(lim, L.map((r) => ({ label: lab(r.Step).replace(/^\+ /, ''), a: r['GP_gain_likely_$'], b: r['GP_gain_cautious_$'] })), { h: 290 }));
  const fr = el('div', { class: 'chart' });
  later(() => colChart(fr, M.frontier.map((r) => ({ label: `Units ≤ −${r['Unit_loss_cap_%']}%`, a: r['GP_gain_likely_$'], b: r['GP_gain_cautious_$'] })), { h: 250 }));
  const sc = M.scenarios;
  return [head('Plan options', 'Scenarios', 'How the gain changes with the limits on price rises, the unit loss we accept, costs and the everyday-article rule.'),
    card('What each limit on price rises costs', 'Each limit added in turn, before shelf-price rounding; dark = likely, light = cautious', lim,
      el('p', { class: 'note' }, 'The limits are proposals for the charter: rises at most 8%, low-confidence articles at most 5%, at most 60% of a sub-group raised, basket rise at most 1.8%.')),
    el('div', { class: 'grid-2' }, card('Profit against units given up', 'The most any article may lose in units', fr),
      card('Cost and rule scenarios', 'Same prices, different conditions', dataTable({ rows: sc, cols: [{ h: 'Scenario', f: (r) => r.Scenario }, { h: 'Gain', num: 1, f: (r) => el('b', {}, fmt.usd(r['GP_gain_likely_$'])) },
        { h: 'Rises', num: 1, f: (r) => r.Raise == null ? '–' : fmt.n(r.Raise) }, { h: 'Units', num: 1, f: (r) => r['Units_%'] == null ? '–' : fmt.pct(r['Units_%']) }], hi: (r) => r.Scenario === 'Plan, likely' }),
        el('p', { class: 'note' }, 'Everyday KVIs (112 articles, 26% of sales) are held in the plan. Unlocking them adds gain but raises the price of what customers buy most; it is the business’s call.'))),
    card('When to start', 'Gain in the first 13 weeks by start date', barList(M.timing.map((t) => ({ label: 'Start ' + fmt.date(t.Start), value: t['GP_gain_13w_$'], text: fmt.usd(t['GP_gain_13w_$']) }))))];
};

V.rollout = () => {
  const ctrl = M.store_list.filter((s) => s.Role.startsWith('Control')); const chg = M.store_list.filter((s) => !s.Role.startsWith('Control'));
  const chosen = M.store_size.find((r) => r.Chosen); const old = M.store_size.find((r) => r.Control_stores === 30);
  const gp4 = M.store_power.find((r) => r.Metric === 'GP' && r.Weeks === 4);
  const lab = Object.fromEntries(M.labels.map((l) => [l.Wave, l]));
  const wv = ['Wave 1', 'Review then Wave 1', 'Test'].map((w) => M.waves.find((x) => x.Wave === w)).filter(Boolean);
  const byZone = d3.groups(ctrl, (s) => s.Zone).sort((a, b) => b[1].length - a[1].length);
  const size = el('div', { class: 'chart' });
  later(() => colChart(size, M.store_size.map((r) => ({ label: r.Control_stores + ' stores', a: r['Gain_given_up_8w_$'], color: r.Chosen ? 'var(--plum)' : 'var(--plum-200)' })), { h: 230, names: ['Gain given up'] }));
  return [head('Go-live', 'Rollout & test', 'Rollout waves, the store test that proves the gain, and the rules for pausing or rolling back.'),
    el('div', { class: 'waves' }, wv.map((w) => el('div', { class: 'wave', style: `--wave:${WAVE_COLOR[w.Wave]}` }, el('div', { class: 'wn' }, w.Wave), el('div', { class: 'wv' }, fmt.usd(w.GP_gain_52w)),
      el('div', { class: 'ws' }, `${fmt.n(w.SKUs)} articles · average ${fmt.pct(w.Avg_change)}`), el('div', { class: 'ws' }, `about ${fmt.n(lab[w.Wave] ? lab[w.Wave].median : null)} shelf labels per store`)))),
    el('div', { class: 'kpis' }, kpi('Control stores', fmt.n(chosen.Control_stores), `${fmt.n(chosen.Changed_stores)} stores take the new prices`), kpi('Smallest change it can show', fmt.pct(chosen['GP_MDE_4w_%'], 1, false), `after 4 weeks; plan expects ${fmt.pct(gp4['Expected_change_%'])}`),
      kpi('Gain given up', fmt.usd(chosen['Gain_given_up_8w_$']), `8 weeks; ${fmt.usd(old['Gain_given_up_8w_$'])} with 30 pairs`), kpi('Read-outs', 'Week 4 · 8', 'gross profit of the changed articles')),
    el('div', { class: 'grid-2' }, card('Control stores', 'They keep today’s prices for 8 weeks; chosen to match the other stores over the last 26 weeks',
      el('div', { style: 'display:grid;gap:10px' }, byZone.map(([z, ss]) => el('div', {}, el('div', { class: 'note', style: 'margin-bottom:4px' }, z), el('div', { class: 'zone-list' }, ss.map((s) => pill(`${s.Store} · ${fmt.usd(s['Weekly_Sales_13w_$'], 0)}/wk`, 'plum'))))))),
      card('How many control stores', 'Gain given up for 8 weeks; the chosen size is the smallest that still shows half the expected gain', size)),
    card('Pause and rollback rules', 'Checked every week from week 2', dataTable({ rows: M.rollback, cols: [{ h: 'Level', key: 'Level' }, { h: 'What', key: 'Check' }, { h: 'Pause the next wave if', f: (r) => r['Pause next wave if'] }, { h: 'Roll back if', f: (r) => r['Roll back the wave if'] }] })),
    card('Gain by date window', 'From the weekly plan', dataTable({ rows: M.windows, cols: [{ h: 'From', f: (r) => fmt.date(r.Start) }, { h: 'To', f: (r) => fmt.date(r.End) }, { h: 'Weeks', num: 1, key: 'Weeks' },
      { h: 'Gain, likely', num: 1, f: (r) => el('b', {}, fmt.usd(r['GP_gain_likely_$'])) }, { h: 'Cautious', num: 1, f: (r) => fmt.usd(r['GP_gain_cautious_$']) }, { h: 'Units', num: 1, f: (r) => fmt.pct(r['Units_change_%']) }] }))];
};

V.monitoring = () => {
  const ds = WEEKLY.weeks.map((d) => new Date(d)); const c = WEEKLY.chain;
  const units = el('div', { class: 'chart' }), gp = el('div', { class: 'chart' }), one = el('div', { class: 'chart' });
  later(() => {
    lineChart(units, { dates: ds, yfmt: (v) => fmt.n(v / 1000, 0) + 'K', series: [{ name: 'Today’s prices', values: c.map((r) => r.Units_now), color: 'var(--plum-200)', width: 2 }, { name: 'New prices', values: c.map((r) => r.Units_new_L), color: 'var(--plum)', width: 2.4 }],
      band: { lo: c.map((r) => r.Units_new_S), hi: c.map((r) => r.Units_new_O), color: 'var(--plum-50)', name: 'Cautious – optimistic' } });
    lineChart(gp, { dates: ds, yfmt: (v) => fmt.usd(v, 0), series: [{ name: 'Today’s prices', values: c.map((r) => r.GP_now_KZ), color: 'var(--plum-200)', width: 2 }, { name: 'New prices', values: c.map((r) => r.GP_new_L_KZ), color: 'var(--gold)', width: 2.4 }] });
  });
  const changed = SKUS.filter((s) => s.chg).sort((a, b) => b.gain - a.gain);
  const pick = el('select', { class: 'sel', 'aria-label': 'Article', onchange: (e) => drawOne(e.target.value) }, changed.map((s) => el('option', { value: s.code }, `${s.group} › ${s.sub} › ${s.sd} › ${s.name} (${fmt.pct(s.chg)})`)));
  function drawOne(code) { loadWeeklySku().then(() => { const w = WSKU.skus[code]; if (!w) return; lineChart(one, { dates: WSKU.weeks.slice(0, w.now.length).map((d) => new Date(d)), yfmt: (v) => fmt.n(v),
    series: [{ name: 'Today’s price', values: w.now, color: 'var(--plum-200)' }, { name: 'New price', values: w.new, color: 'var(--plum)', width: 2.4 }], band: { lo: w.low, hi: w.high, color: 'var(--plum-50)', name: 'Cautious – optimistic' } }); }); }
  later(() => drawOne(changed[0].code));
  const legend = el('div', { class: 'legend' }, el('span', {}, el('i', { style: 'background:var(--plum-200)' }), 'Today’s prices'), el('span', {}, el('i', { style: 'background:var(--plum)' }), 'New prices'), el('span', {}, el('i', { style: 'background:var(--plum-50);border:1px solid var(--line)' }), 'Cautious – optimistic'));
  return [head('Track the plan', 'Monitoring', 'Expected weekly units and gross profit at the new prices. A week outside the range is a reason to look.'),
    card('Weekly units, all articles', 'Chain total; the forecast includes Christmas and the seasonal path', units, legend),
    el('div', { class: 'grid-2' }, card('Weekly gross profit after IVA', 'All priced articles', gp), card('One article, week by week', 'Every changed article', pick, one))];
};

V.rules = () => {
  const rc = M.rules.filter((r) => r.FLAG + r.FAIL > 0).sort((a, b) => b.FLAG - a.FLAG);
  const R = { rule: '' };
  const flagged = SKUS.filter((s) => FLAGS[s.code] && s.chg);
  const table = dataTable({ rows: flagged, sort: { k: 'gain', dir: -1 }, onRow: (r) => openSku(r.code), pageSize: 50, cols: [
    { h: 'Article', key: 'name', f: artCell }, { h: 'Change', key: 'chg', num: 1, f: (r) => chgPill(r.chg) },
    { h: 'Flags', f: (r) => el('div', { class: 'chips' }, FLAGS[r.code].map(([k, v]) => pill(k.replace(/^R\d+ /, ''), v === 'FAIL' ? 'bad' : 'warn'))) }, { h: 'Gain', key: 'gain', num: 1, f: (r) => fmt.usdSigned(r.gain) }, { h: 'Wave', key: 'wave' }] });
  const chips = el('div', { class: 'chips' });
  const setRule = (r) => { R.rule = r; chips.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.r === r))); table.update(flagged.filter((s) => !r || FLAGS[s.code].some(([k]) => k === r))); };
  chips.append(el('button', { class: 'chip', 'data-r': '', 'aria-pressed': 'true', onclick: () => setRule('') }, 'All', el('span', { class: 'n' }, fmt.n(flagged.length))),
    ...rc.map((r) => el('button', { class: 'chip', 'data-r': r.Rule, 'aria-pressed': 'false', onclick: () => setRule(r.Rule) }, r.Rule.replace(/^R\d+ /, ''), el('span', { class: 'n' }, fmt.n(r.FLAG + r.FAIL)))));
  const all = M.rules;
  return [head('Guardrails', 'Business rules', 'Every price change checked against the rule catalogue. A FAIL blocks the price; a FLAG needs a person to look.'),
    el('div', { class: 'kpis' }, kpi('Rules checked', fmt.n(all.length), 'per article'), kpi('Failures', fmt.n(d3.sum(all, (r) => r.FAIL)), 'no price change breaks a hard rule', d3.sum(all, (r) => r.FAIL) ? 'down' : 'up'),
      kpi('Changes with flags', fmt.n(flagged.length), 'reviewed before release'), kpi('Held articles', fmt.n(M.plan.held), 'no price change')),
    el('div', { class: 'grid-2' }, card('Flags by rule', 'How many price changes each rule flags', barList(rc.map((r) => ({ label: r.Rule, value: r.FLAG, text: fmt.n(r.FLAG), cls: 'gold' })))),
      card('Why articles are held', 'No price change', barList(M.holds.map((h) => ({ label: h.Hold_Reason, value: h.SKUs, text: fmt.n(h.SKUs), cls: 'soft' }))))),
    card('Price changes with flags', 'Filter by rule; click an article for its detail', chips, table)];
};

V.stockouts = () => {
  const s = M.stockouts;
  return [head('Supply', 'Stock-outs', 'Weeks when a store that normally sells an article sold none: an estimate from sales, since stock is only recorded monthly.'),
    el('div', { class: 'kpis' }, kpi('Store-weeks out of stock', fmt.pct(s.gap_pct, 1, false), `plus ${fmt.pct(s.edge_pct, 1, false)} ran out mid-week`), kpi('Lost sales', '$' + s.lost_sales_m.toFixed(1) + 'M', fmt.pct(s.lost_sales_pct, 1, false) + ' of sales, last 52 weeks', 'down'),
      kpi('Lost gross profit', '$' + s.lost_gp_m.toFixed(2) + 'M', fmt.pct(s.lost_gp_pct, 1, false) + ' of gross profit after IVA', 'down'), kpi('Articles affected', fmt.n(s.skus), 'at least one stock-out week')),
    el('div', { class: 'grid-2' }, card('Lost sales by group', 'Last 52 weeks', barList(M.stock_groups.map((g) => ({ label: g.MainGroup, value: g.Lost_sales_USD, text: fmt.usd(g.Lost_sales_USD), title: `${fmt.pct(g['Lost_units_%'], 1, false)} of units` })))),
      card('What the plan does about it', null, el('ul', { class: 'step-list' },
        el('li', {}, el('div', {}, el('b', {}, 'Cleaner price effects'), el('span', {}, 'Weeks where a store ran out mid-week are left out of the price model.'))),
        el('li', {}, el('div', {}, el('b', {}, 'No cuts on short supply'), el('span', {}, 'Articles out of stock in 20% or more of store-weeks get no price cut.'))),
        el('li', {}, el('div', {}, el('b', {}, 'Realistic forecast'), el('span', {}, 'The forecast stays on what can really be sold with today’s supply.'))),
        el('li', {}, el('div', {}, el('b', {}, 'For the supply team'), el('span', {}, 'The lost sales below are worth more than many price moves.')))))),
    card('Articles losing most sales', 'Click an article for its detail', dataTable({ rows: M.stock_skus, onRow: (r) => openSku(String(r.Code)), cols: [
      { h: 'Article', f: (r) => artCellRaw(r.Code, r.Name) }, { h: 'Out-of-stock weeks', num: 1, f: (r) => fmt.pct(r['Stock-out_weeks_%'], 1, false) },
      { h: 'Units lost', num: 1, f: (r) => fmt.pct(r['Lost_units_%'], 1, false) }, { h: 'Lost sales', num: 1, f: (r) => el('b', {}, fmt.usd(r.Lost_sales_USD)) }, { h: 'Lost gross profit', num: 1, f: (r) => fmt.usd(r.Lost_GP_net_USD) }] }))];
};

V.health = () => {
  const pass = M.checks.filter((c) => c.Result === 'PASS').length, fail = M.checks.filter((c) => c.Result === 'FAIL').length;
  const ev8 = M.events.find((r) => r.Window_weeks === 8 && r.Direction === 'All'), best = M.holdout.find((r) => r.Chosen);
  const steps = el('div', { class: 'chart' });
  later(() => colChart(steps, M.steps.map((r) => ({ label: r.stage, a: r.gain, b: r.cautious })), { h: 260 }));
  return [head('Quality', 'Model health', 'Automated checks and the tests the price effects had to pass.'),
    el('div', { class: 'kpis' }, kpi('Automated checks', `${pass}/${M.checks.length}`, fail ? `${fail} failing` : 'all pass', fail ? 'down' : 'up'), kpi('Unseen months: size match', best.Calib_slope_hold.toFixed(2), `1.00 is exact · ${fmt.n(best.SKUs)} articles`),
      kpi('Past price changes: size match', ev8.Calibration_slope.toFixed(2), `± ${ev8.Calibration_SE.toFixed(2)} on ${fmt.n(ev8.Events)} changes`), kpi('Rule failures', fmt.n(M.plan.fails), 'in the final price list', M.plan.fails ? 'down' : 'up')),
    card('Planned gain after each fix', 'Dark = likely, light = cautious; after shelf-price rounding', steps, el('p', { class: 'note' }, 'Stock-outs fixed: 247 articles were dropped by mistake, fixed in the next step. Price effects re-checked: overstated effects pulled toward the average. Limits + checks: stricter limits on rises and a rounding fix.')),
    el('div', { class: 'grid-2' }, card('Test 1 · unseen months', 'Estimated to May 2026, re-measured on May–Nov 2026', dataTable({ rows: M.holdout, hi: (r) => r.Chosen, cols: [{ h: 'Method', f: (r) => r.Method + (r.Chosen ? ' ✓' : '') },
      { h: 'Error', num: 1, f: (r) => r.Pred_error_RMSE.toFixed(2) }, { h: 'Size match', num: 1, f: (r) => r.Corr_hold == null ? '–' : r.Calib_slope_hold.toFixed(2) }, { h: 'Correlation', num: 1, f: (r) => r.Corr_hold == null ? '–' : r.Corr_hold.toFixed(2) }] })),
      card('Test 2 · real lasting price changes', 'Fresmart’s own price changes, 2024–2026', dataTable({ rows: M.events, hi: (r) => r === ev8, cols: [{ h: 'Window', f: (r) => r.Window_weeks + ' wks' }, { h: 'Change', key: 'Direction' },
        { h: 'Events', num: 1, f: (r) => fmt.n(r.Events) }, { h: 'Real', num: 1, f: (r) => r.Event_elasticity.toFixed(2) }, { h: 'Model', num: 1, f: (r) => r.Model_avg_elasticity.toFixed(2) },
        { h: 'Size match', num: 1, f: (r) => `${r.Calibration_slope.toFixed(2)} ± ${r.Calibration_SE.toFixed(2)}` }] }))),
    card('Automated checks', 'python scripts/allsku_checks.py --deep', dataTable({ rows: M.checks, cols: [{ h: '#', key: 'Check' }, { h: 'What it checks', key: 'What' }, { h: 'Result', f: (r) => pill(r.Result, r.Result === 'PASS' ? 'ok' : r.Result === 'FAIL' ? 'bad' : 'warn') },
      { h: 'Detail', f: (r) => el('span', { class: 'muted' }, r.Detail) }] }))];
};

V.portfolio = () => {
  const seg = d3.rollups(SKUS, (v) => ({ n: v.length, rev: d3.sum(v, (s) => s.rev), gp: d3.sum(v, (s) => s.rev * (s.m_now || 0) / 100), shelf: v.filter((s) => s.shelf).length }), (s) => s.segment)
    .map(([k, v]) => ({ k, ...v })).sort((a, b) => b.rev - a.rev);
  const tot = d3.sum(seg, (s) => s.rev);
  const scat = el('div', { class: 'chart' });
  later(() => {
    const pts = SKUS.filter((s) => s.rev > 0 && s.m_now != null && s.shelf); const box = scat; box.replaceChildren(); const h = 380; const { w } = measure(box, h); const m = { t: 10, r: 14, b: 34, l: 50 };
    const x = d3.scaleLog().domain(d3.extent(pts, (s) => s.rev)).range([m.l, w - m.r]).nice(); const y = d3.scaleLinear().domain([-30, 60]).range([h - m.b, m.t]);
    const segs = seg.map((s) => s.k); const col = d3.scaleOrdinal(segs, ['#3F7A1C', '#235787', '#72BD44', '#F28C28', '#8A8F86', '#B9DDA1', '#B23A3A']);
    const svg = d3.select(box).append('svg').attr('width', w).attr('height', h).attr('role', 'img').attr('aria-label', 'Revenue against margin, articles on the shelf');
    svg.append('g').attr('class', 'gridl').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickSize(-(w - m.l - m.r)).tickFormat(''));
    svg.append('g').attr('class', 'ax').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickFormat((v) => v + '%').tickSize(0)).call((g) => g.select('.domain').remove()).selectAll('text').attr('dx', -6);
    svg.append('g').attr('class', 'ax').attr('transform', `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(6, '$~s').tickSizeOuter(0));
    svg.append('line').attr('x1', m.l).attr('x2', w - m.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--bad)').attr('stroke-dasharray', '3 3').attr('opacity', .5);
    svg.append('g').selectAll('circle').data(pts).join('circle').attr('cx', (s) => x(s.rev)).attr('cy', (s) => y(Math.max(-30, Math.min(60, s.m_now)))).attr('r', 3.4).attr('fill', (s) => col(s.segment)).attr('opacity', .62)
      .style('cursor', 'pointer').on('mousemove', (ev, s) => showTip(ev, s.name, [['Revenue', fmt.usd(s.rev)], ['Margin after IVA', fmt.pct(s.m_now, 1, false)], ['Group', s.segment], ['Change', s.chg ? fmt.pct(s.chg) : 'hold']])).on('mouseleave', hideTip).on('click', (ev, s) => openSku(s.code));
    box.append(el('div', { class: 'legend' }, segs.map((s) => el('span', {}, el('i', { style: `background:${col(s)}` }), s))));
  });
  return [head('Reference', 'Portfolio', 'Every active article by its role: revenue, margin after IVA and the group it belongs to.'),
    el('div', { class: 'kpis' }, kpi('Active articles', fmt.n(SKUS.length), `${fmt.n(M.plan.on_shelf)} on the shelf now`), kpi('Revenue, 52 weeks', fmt.usd(tot), 'with IVA, as recorded'),
      kpi('Net margin today', fmt.pct(+M.before.find((b) => b.KPI.startsWith('Net margin')).Value, 1, false), 'after IVA'), kpi('Sales below cost', fmt.pct(+M.before.find((b) => b.KPI.startsWith('Share of sales sold below')).Value, 1, false), 'of sales, last 52 weeks', 'down')),
    el('div', { class: 'split' }, card('Revenue against margin', 'Articles on the shelf; click a dot for its detail. Below the red line = sold below cost.', scat),
      card('Seven groups', 'Share of revenue and margin after IVA', dataTable({ rows: seg, cols: [{ h: 'Group', f: (r) => el('b', {}, r.k) }, { h: 'Articles', num: 1, f: (r) => fmt.n(r.n) },
        { h: 'Revenue', num: 1, f: (r) => fmt.pct(r.rev / tot * 100, 1, false) }, { h: 'Margin', num: 1, f: (r) => fmt.pct(r.gp / r.rev * 100, 1, false) }] })))];
};

V.method = () => {
  const fc = M.forecast; const fs = Object.fromEntries(M.forecast_summary.map((r) => [r.Item, r.Value]));
  const q = el('div', { class: 'chart' });
  later(() => lineChart(q, { dates: M.by_quarter.map((r) => { const [y, qq] = r.Quarter.split('Q'); return new Date(Date.UTC(+y, (+qq - 1) * 3, 15)); }), yfmt: (v) => v.toFixed(0) + '%', h: 220,
    series: [{ name: 'Net margin after IVA', values: M.by_quarter.map((r) => r['Net_margin_%']), color: 'var(--plum)', width: 2.4 }, { name: 'Sales below cost', values: M.by_quarter.map((r) => r['Sales_below_cost_%']), color: 'var(--bad)', width: 2 }] }));
  return [head('Reference', 'Method', 'How the prices were set, from raw sales to the price list, and how good each part is.'),
    el('div', { class: 'grid-2' }, card('How the prices were set', null, el('ol', { class: 'step-list' },
      el('li', {}, el('div', {}, el('b', {}, 'Clean data'), el('span', {}, 'Sales, costs and prices from Azure SQL, Jan 2023 – Nov 2026; active articles only; IVA taken out of sales.'))),
      el('li', {}, el('div', {}, el('b', {}, 'Stock-outs'), el('span', {}, 'Weeks a store ran out found from sales and left out of the price model.'))),
      el('li', {}, el('div', {}, el('b', {}, 'Forecast'), el('span', {}, `52-week demand at today’s prices: ${fs['Benchmark winner (E3/E4)'] || 'blend'}.`))),
      el('li', {}, el('div', {}, el('b', {}, 'Price effects'), el('span', {}, 'How units react to price, per article, pooled within its sub-group and checked on unseen months and past price changes.'))),
      el('li', {}, el('div', {}, el('b', {}, 'Optimiser'), el('span', {}, 'Best price per article (MILP) within the limits, keeping each sub-group’s cautious profit up.'))),
      el('li', {}, el('div', {}, el('b', {}, 'Rules and rounding'), el('span', {}, 'Fresmart price endings, 20 business rules, waves and the store test.'))))),
      card('Net margin over time', 'All active articles, by quarter', q, el('div', { class: 'legend' }, el('span', {}, el('i', { style: 'background:var(--plum)' }), 'Net margin after IVA'), el('span', {}, el('i', { style: 'background:var(--bad)' }), 'Share of sales below cost')))),
    el('div', { class: 'grid-2' }, card('Forecast accuracy', 'Weekly error on past forecasts (lower is better)', dataTable({ rows: fc, hi: (r) => r.Method === fs['Benchmark winner (E3/E4)'], cols: [{ h: 'Method', key: 'Method' },
      { h: 'Weekly error', num: 1, f: (r) => fmt.pct(r.Mean_WAPE_week, 1, false) }, { h: '13-week error', num: 1, f: (r) => fmt.pct(r.Mean_WAPE_13w, 1, false) }, { h: 'Bias', num: 1, f: (r) => fmt.pct(r.Mean_abs_bias, 1, false) }] })),
      card('Price sensitivity', 'How strongly units react to a 1% price change', barList(M.bands.map((b) => ({ label: b.Band, title: `median ${b.Median.toFixed(2)}`, value: b.Rev_Pct, text: `${fmt.n(b.SKUs)} · ${b.Rev_Pct.toFixed(0)}% of sales` }))),
        el('p', { class: 'note' }, M.conf.map((c) => `${c.Confidence}: ${fmt.n(c.SKUs)} articles (${c.Rev_Pct.toFixed(0)}% of sales)`).join(' · '))))];
};

// ---------------------------------------------------------------- router, nav, search
function buildNav() {
  const nav = $('#nav');
  nav.replaceChildren(...PAGES.map(([g, ps]) => el('div', { class: 'nav-group' }, el('div', { class: 'nav-label' }, g),
    ps.map(([id, t, ic]) => { const b = el('button', { class: 'nav-btn', 'data-page': id, onclick: () => go(id) }, svgIcon(ic), t);
      if (id === 'prices') b.append(el('span', { class: 'nav-count' }, fmt.n(M.plan.rises)));
      if (id === 'rules') b.append(el('span', { class: 'nav-count' }, fmt.n(M.plan.flagged)));
      return b; }))));
}
function go(id) { if (!V[id]) id = 'overview'; location.hash = id; }
function render() {
  const id = V[location.hash.slice(1)] ? location.hash.slice(1) : 'overview';
  document.querySelectorAll('.nav-btn').forEach((b) => b.setAttribute('aria-current', b.dataset.page === id ? 'page' : 'false'));
  $('#crumb').textContent = TITLES[id];
  const c = $('#content'); c.replaceChildren(...V[id]().filter(Boolean)); window.scrollTo(0, 0); $('.side').classList.remove('open');
}
let rT; addEventListener('resize', () => { clearTimeout(rT); rT = setTimeout(render, 180); });
addEventListener('hashchange', render);
$('#menu').addEventListener('click', () => $('.side').classList.toggle('open'));

const gs = $('#gsearch'), gr = $('#gresults'); let gsel = 0, gm = [];
function gdraw() { const q = gs.value.trim().toLowerCase(); if (!q) { gr.hidden = true; return; }
  gm = SKUS.filter((s) => s.name.toLowerCase().includes(q) || s.code.includes(q)).sort((a, b) => b.rev - a.rev).slice(0, 8); gsel = Math.min(gsel, Math.max(0, gm.length - 1));
  gr.replaceChildren(...(gm.length ? gm.map((s, i) => el('button', { class: 'result', 'aria-selected': String(i === gsel), onclick: () => { openSku(s.code); gs.value = ''; gr.hidden = true; } },
    el('span', { class: 'r-name' }, s.name), el('span', { class: 'r-sub' }, `${s.group} › ${s.sub} › ${s.sd} · ${s.code}`), el('span', { class: 'r-chg' }, chgPill(s.chg)))) : [el('div', { class: 'note', style: 'padding:10px' }, 'No article matches')]));
  gr.hidden = false; }
gs.addEventListener('input', () => { gsel = 0; gdraw(); });
gs.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown') { gsel = Math.min(gsel + 1, gm.length - 1); gdraw(); e.preventDefault(); } else if (e.key === 'ArrowUp') { gsel = Math.max(gsel - 1, 0); gdraw(); e.preventDefault(); }
  else if (e.key === 'Enter' && gm[gsel]) { openSku(gm[gsel].code); gs.value = ''; gr.hidden = true; } });
document.addEventListener('click', (e) => { if (!e.target.closest('.search')) gr.hidden = true; });

// ---------------------------------------------------------------- boot
Promise.all(['meta', 'skus', 'weekly', 'flags'].map((n) => fetch(`data/${n}.json`).then((r) => { if (!r.ok) throw new Error(n + ' ' + r.status); return r.json(); })))
  .then(([meta, skus, weekly, flags]) => {
    M = meta; WEEKLY = weekly; FLAGS = flags;
    SKUS = skus.rows.map((row) => Object.fromEntries(skus.columns.map((c, i) => [c, row[i]])));
    SKUS.forEach((s) => { s.code = String(s.code); s.chg = s.chg || 0; });
    BY_CODE = new Map(SKUS.map((s) => [s.code, s]));
    $('#asof').textContent = M.as_of;
    const fail = M.checks.filter((c) => c.Result === 'FAIL').length;
    $('#side-status').className = 'status' + (fail || M.plan.fails ? ' bad' : '');
    $('#side-status').lastChild.textContent = fail ? `${fail} checks failing` : M.plan.fails ? `${M.plan.fails} rule failures` : 'Plan checked · ready for review';
    buildNav(); render();
    const deep = new URLSearchParams(location.search).get('sku'); if (deep) openSku(deep);   // ?sku=<code> opens an article
  })
  .catch((e) => { $('#loading').textContent = 'Could not load the data (' + e.message + '). Run scripts/build_studio_data.py and serve the dashboard folder.'; console.error(e); });
})();
