"""Model Health page for the local dashboard (dashboard/health.html), in the Pricing Studio look.

Reads the pipeline outputs directly (checks, price list and the archived copies before each step, optimiser limits
waterfall, hold-out slope test, event check, store test size, stock-outs) and embeds them as JSON. The studio's own
styles and icons are copied from dashboard/page.html, so the two pages look the same.

Run after the pipeline and allsku_checks.py:  python scripts/build_health_dashboard.py
Serve: python -m http.server 8050 -d dashboard, then open http://localhost:8050/health.html
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
A, DASH = ROOT / "analysis" / "allsku", ROOT / "dashboard"


def records(df):
    return json.loads(df.to_json(orient="records"))


def load():
    d = {"checks": records(pd.read_excel(A / "checks.xlsx"))}
    stages = [("Start, before the fixes", A / "_before_stockout"), ("Step 1: stock-out weeks", A / "_before_step2"),
              ("Step 2: price effects re-checked", A / "_before_step3"), ("Steps 3-4 + checks (now)", A)]
    rows = []
    for name, folder in stages:
        f = folder / "price_list.xlsx"
        br = pd.read_excel(f, sheet_name="Profit bridge").iloc[:, 1].tolist()     # by position: 8 after rounding, 9 cautious
        sm = pd.read_excel(f, sheet_name="Summary").set_index("Item").Value
        rows.append({"Stage": name, "Plan": br[8], "Cautious": br[9], "Rises": int(sm["Raise"]),
                     "Basket": float(sm["Basket price change % (sales weighted)"]), "Fails": int(sm["Rule FAILs"])})
    d["steps"] = rows
    w = pd.read_excel(A / "optimisation.xlsx", sheet_name="G6 limits waterfall")
    d["limits"] = records(w[["Step", "GP_gain_likely_$", "GP_gain_cautious_$", "Raise", "Basket_%", "Rises_7pct_plus"]].set_axis(
        ["Step", "Gain", "Cautious", "Rises", "Basket", "Big"], axis=1))
    h = pd.read_excel(A / "elasticity.xlsx", sheet_name="D7b hold-out slope test").rename(columns={"Unnamed: 0": "Method"})
    sm = pd.read_excel(A / "elasticity.xlsx", sheet_name="Summary").set_index("Item").Value
    chosen = f"{sm['Pooling chosen (D3/D7b)']}, spread calibrated (cross-fitted)"
    h = h[~h.Method.str.startswith("Phase 1")]
    d["holdout"] = records(h.assign(Chosen=h.Method.eq(chosen))[["Method", "SKUs", "Pred_error_RMSE", "Calib_slope_hold", "Corr_hold", "Chosen"]])
    e = pd.read_excel(A / "event_check.xlsx", sheet_name="Summary")
    d["events"] = records(e[e.Control == "clean"][["Window_weeks", "Direction", "Events", "Event_elasticity", "Model_avg_elasticity",
                                                   "Calibration_slope", "Calibration_SE"]])
    s = pd.read_excel(A / "price_list.xlsx", sheet_name="H7 holdout size")
    d["store"] = records(s.set_axis([c.replace("%", "pct").replace("$", "usd") for c in s.columns], axis=1))
    d["rollback"] = records(pd.read_excel(A / "price_list.xlsx", sheet_name="H8 rollback rules"))
    so = pd.read_excel(A / "stockouts.xlsx", sheet_name="Summary")
    keys = ["selling_weeks", "gap_weeks", "gap_pct", "edge_weeks", "edge_pct", "lost_units_pct", "lost_sales_m", "lost_sales_pct",
            "lost_gp_m", "lost_gp_pct", "scope_sales_m", "skus"]
    d["stockouts"] = dict(zip(keys, so.iloc[:, 1].astype(float).tolist()))
    d["stock_groups"] = records(pd.read_excel(A / "stockouts.xlsx", sheet_name="By MainGroup").head(8)[
        ["MainGroup", "Lost_sales_USD", "Lost_GP_net_USD", "Lost_units_%"]].set_axis(["Group", "Sales", "GP", "Units_pct"], axis=1))
    return d


PAGE = r"""
<div class="fp" id="fp">
<div class="fp-app">
  <aside class="fp-side">
    <div class="fp-brand">
      <div class="fp-logo">F</div>
      <div><div class="fp-brand-name">Model Health</div><div class="fp-brand-sub">Fresmart · all active SKUs</div></div>
    </div>
    <div>
      <div class="fp-navlabel">Review</div>
      <nav class="fp-nav" role="tablist" aria-label="Model health pages">
        <button class="fp-tab" role="tab" id="tab-overview" data-tab="overview" aria-selected="true"><span class="fp-ico" data-icon="overview"></span>Overview</button>
        <button class="fp-tab" role="tab" id="tab-steps" data-tab="steps" aria-selected="false"><span class="fp-ico" data-icon="trend"></span>Plan by step</button>
        <button class="fp-tab" role="tab" id="tab-limits" data-tab="limits" aria-selected="false"><span class="fp-ico" data-icon="sliders"></span>Price-rise limits</button>
        <button class="fp-tab" role="tab" id="tab-tests" data-tab="tests" aria-selected="false"><span class="fp-ico" data-icon="flask"></span>Model tests</button>
        <button class="fp-tab" role="tab" id="tab-store" data-tab="store" aria-selected="false"><span class="fp-ico" data-icon="flag"></span>Store test</button>
        <button class="fp-tab" role="tab" id="tab-stock" data-tab="stock" aria-selected="false"><span class="fp-ico" data-icon="box"></span>Stock-outs</button>
        <button class="fp-tab" role="tab" id="tab-checks" data-tab="checks" aria-selected="false"><span class="fp-ico" data-icon="shield"></span>Automated checks</button>
        <button class="fp-tab" role="tab" id="tab-open" data-tab="open" aria-selected="false"><span class="fp-ico" data-icon="alert"></span>Still open</button>
      </nav>
    </div>
    <div class="fp-sidefoot">
      <span class="fp-live" id="side-status">Checks</span>
      <span>Data to <b>2 Nov 2026</b>, net of IVA, in US dollars</span>
      <span><a href="index.html" style="color:inherit">Open the Pricing Studio</a></span>
    </div>
  </aside>

  <main class="fp-main">
    <div class="fp-top">
      <div class="fp-crumb"><span>Price optimisation</span><span>/</span><b id="crumb">Overview</b></div>
    </div>
    <div class="fp-body">
      <div class="fp-pagehead">
        <div><h1 id="page-title">Overview</h1><p class="fp-pagesub" id="page-sub"></p></div>
      </div>

      <section class="fp-page" id="pg-overview">
        <div class="fp-take"><span class="fp-ico" data-icon="spark"></span><p id="take"></p></div>
        <div class="fp-kpis" id="kpis"></div>
        <div class="fp-grid-wide">
          <div class="fp-card"><div class="fp-cardhead"><h2>Planned gain after each fix</h2><span class="fp-tag">per year</span></div>
            <div class="fp-chart" id="ov-steps"></div>
            <div class="fp-legend"><span><i class="fp-sw" style="background:var(--fp-accent)"></i>Planned gain</span><span><i class="fp-sw" style="background:var(--cds-chart-muted)"></i>Cautious case</span></div></div>
          <div class="fp-card"><div class="fp-cardhead"><h2>Checks</h2><span class="fp-tag" id="ov-ck-tag"></span></div>
            <div class="fp-tablebox fp-table-flat"><table class="fp-table" id="ov-checks"></table></div></div>
        </div>
      </section>

      <section class="fp-page" id="pg-steps" hidden>
        <div class="fp-card"><div class="fp-cardhead"><h2>Planned gain after each fix</h2><span class="fp-tag">gross profit after IVA, after rounding</span></div>
          <div class="fp-chart" id="st-chart"></div>
          <p class="fp-note">Step 1 dropped 247 SKUs with no own price effect by mistake (fixed in step 2), so its figure was too low. Step 2 pulled overstated price effects toward the average. Steps 3-4 added stricter limits on rises and fixed rounding.</p></div>
        <div class="fp-card"><div class="fp-tablebox"><table class="fp-table" id="st-table"></table></div></div>
      </section>

      <section class="fp-page" id="pg-limits" hidden>
        <div class="fp-card"><div class="fp-cardhead"><h2>What each limit costs</h2><span class="fp-tag">before shelf-price rounding</span></div>
          <div class="fp-chart" id="lm-chart"></div></div>
        <div class="fp-card"><div class="fp-tablebox"><table class="fp-table" id="lm-table"></table></div>
          <p class="fp-note">The limits are proposals: rise at most 8%, low-confidence SKUs at most 5%, at most 60% of a sub-group raised, basket rise at most 1.8%. The business still has to agree them.</p></div>
      </section>

      <section class="fp-page" id="pg-tests" hidden>
        <div class="fp-kpis" id="ts-kpis"></div>
        <div class="fp-grid-wide">
          <div class="fp-card"><div class="fp-cardhead"><h2>Test 1 · unseen months</h2><span class="fp-tag">May-Nov 2026</span></div>
            <p class="fp-note">Price effects estimated on data to May 2026, then measured again from scratch on May-Nov 2026. Size match 1.00 is exactly right; lower error is better.</p>
            <div class="fp-tablebox"><table class="fp-table" id="ts-hold"></table></div></div>
          <div class="fp-card"><div class="fp-cardhead"><h2>Test 2 · real lasting price changes</h2><span class="fp-tag">2024-2026</span></div>
            <p class="fp-note">Fresmart's own price changes, against sub-group SKUs whose price stayed put. Real reaction vs the model's, and size match = real sales change ÷ predicted.</p>
            <div class="fp-tablebox"><table class="fp-table" id="ts-events"></table></div></div>
        </div>
      </section>

      <section class="fp-page" id="pg-store" hidden>
        <div class="fp-kpis" id="sr-kpis"></div>
        <div class="fp-card"><div class="fp-cardhead"><h2>How many control stores</h2><span class="fp-tag">8-week test</span></div>
          <div class="fp-chart" id="sr-chart"></div>
          <div class="fp-tablebox"><table class="fp-table" id="sr-table"></table></div></div>
        <div class="fp-card"><div class="fp-cardhead"><h2>Pause and rollback rules</h2></div>
          <div class="fp-tablebox"><table class="fp-table" id="sr-roll"></table></div></div>
      </section>

      <section class="fp-page" id="pg-stock" hidden>
        <div class="fp-kpis" id="so-kpis"></div>
        <div class="fp-card"><div class="fp-cardhead"><h2>Lost sales by group</h2><span class="fp-tag">last 52 weeks</span></div>
          <div class="fp-chart" id="so-chart"></div>
          <p class="fp-note">A stock-out week: a store that normally sells the SKU (10 of the last 13 weeks, 3+ units) sold none. Estimated from sales, since stock is only recorded monthly. The price model now leaves these weeks out, and SKUs out of stock in 20%+ of store-weeks get no price cut.</p></div>
      </section>

      <section class="fp-page" id="pg-checks" hidden>
        <div class="fp-card"><div class="fp-cardhead"><h2>Automated checks</h2><span class="fp-tag">python scripts/allsku_checks.py --deep</span></div>
          <p class="fp-note">A = the logic, on small made-up data. B = the real outputs. Run after every change; it stops with an error if any check fails.</p>
          <div class="fp-tablebox"><table class="fp-table" id="ck-table"></table></div></div>
      </section>

      <section class="fp-page" id="pg-open" hidden>
        <div class="fp-card"><div class="fp-tablebox fp-table-flat"><table class="fp-table">
          <thead><tr><th>Who</th><th>What is open</th><th>Effect</th></tr></thead>
          <tbody>
            <tr><td><span class="fp-delta down">Finance</span></td><td>IVA treatment and the 14% IVA gap (657 SKUs, about $30M of sales) not confirmed</td><td>Many margins change if the answer differs</td></tr>
            <tr><td><span class="fp-delta down">Business</span></td><td>Limits (8%, 5%, 60%, 1.8%), everyday-article rules and the number of control stores not agreed</td><td>Plan stays provisional</td></tr>
            <tr><td><span class="fp-delta warn">Proof</span></td><td>Past price changes back the model; only the store test proves the gain on new prices</td><td>Read after 4 and 8 weeks</td></tr>
            <tr><td><span class="fp-delta warn">Price image</span></td><td>Rises only, no cuts; store traffic and price image are not in the model</td><td>Watch tickets and basket in the store test</td></tr>
            <tr><td><span class="fp-delta">Documents</span></td><td>Method report, questions file and the Pricing Studio still show older figures</td><td>Update before sign-off</td></tr>
            <tr><td><span class="fp-delta">To do</span></td><td>Independent review, risk review (FMEA), Cpk, rule for SKUs with no recommendation</td><td>Six Sigma steps still open</td></tr>
          </tbody></table></div></div>
      </section>
    </div>
  </main>
</div>
</div>
"""

SCRIPT = r"""
<script>
const D = __DATA__;
__ICONS__
document.querySelectorAll('.fp [data-icon]').forEach((e) => { e.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[e.dataset.icon] || ''}</svg>`; });
const ACC = '#2a78d6';
document.getElementById('fp').style.setProperty('--fp-accent', ACC);
const $ = (s) => document.querySelector(s);
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; };
const M = (v) => '$' + (v / 1e6).toFixed(2) + 'M';
const K = (v) => '$' + Math.round(v / 1000).toLocaleString('en-US') + 'K';
const N = (v) => Math.round(v).toLocaleString('en-US');
const P = (v, d = 1) => (v > 0 ? '+' : '') + v.toFixed(d) + '%';

function table(id, cols, rows, hi) {
  const t = document.getElementById(id); t.replaceChildren();
  const tr = el('tr'); cols.forEach((c) => tr.appendChild(el('th', c.num ? 'num' : '', c.h)));
  const th = el('thead'); th.appendChild(tr); const tb = el('tbody');
  rows.forEach((r) => { const row = el('tr'); if (hi && hi(r)) row.style.fontWeight = '600';
    cols.forEach((c) => { const td = el('td', c.num ? 'num' : ''); const v = c.f ? c.f(r) : r[c.k];
      if (v instanceof Node) td.appendChild(v); else td.textContent = v == null ? '–' : v;
      if (hi && hi(r)) td.style.background = 'var(--fp-softer)'; row.appendChild(td); }); tb.appendChild(row); });
  t.append(th, tb);
}
function kpi(box, items) {
  const b = document.getElementById(box); b.replaceChildren();
  items.forEach(([label, value, sub, icon, tone]) => {
    const k = el('div', 'fp-kpi'); const top = el('div', 'fp-kpi-top'); top.appendChild(el('span', 'fp-kpi-label', label));
    const bd = el('span', 'fp-badge'); const ic = el('span', 'fp-ico'); ic.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[icon] || ''}</svg>`; bd.appendChild(ic); top.appendChild(bd);
    const s = el('div', 'fp-kpi-sub'); if (tone) s.appendChild(el('span', 'fp-delta ' + tone, sub)); else s.textContent = sub;
    k.append(top, el('div', 'fp-kpi-value', value), s); b.appendChild(k); });
}
const pill = (r) => el('span', 'fp-delta ' + (r === 'PASS' ? 'up' : r === 'FAIL' ? 'down' : 'warn'), r);

// horizontal bars: rows [{label, a, b}], a = main, b = muted (optional)
function hbars(id, rows, fmt, opt = {}) {
  const box = document.getElementById(id); box.replaceChildren();
  const W = Math.max(box.clientWidth, 320), lw = Math.min(opt.lw || 250, W * 0.42), bh = opt.b ? 30 : 22, gap = 12;
  const H = rows.length * (bh + gap);
  const mx = d3.max(rows, (r) => Math.max(r.a, r.b || 0)) || 1;
  const x = d3.scaleLinear().domain([0, mx]).range([0, W - lw - (opt.rw || 90)]);
  const svg = d3.select(box).append('svg').attr('width', W).attr('height', H).attr('role', 'img').attr('aria-label', opt.aria || 'bar chart');
  const g = svg.selectAll('g').data(rows).join('g').attr('transform', (r, i) => `translate(0,${i * (bh + gap)})`);
  g.append('text').attr('class', 'fp-tick').attr('x', 0).attr('y', bh / 2 + 4).text((r) => r.label);
  g.append('rect').attr('x', lw).attr('y', 0).attr('height', opt.b ? 16 : bh).attr('rx', 4).attr('width', (r) => x(r.a)).style('fill', (r) => r.color || ACC);
  if (opt.b) g.append('rect').attr('x', lw).attr('y', 19).attr('height', 9).attr('rx', 3).attr('width', (r) => x(r.b)).style('fill', 'var(--cds-chart-muted)');
  g.append('text').attr('class', 'fp-tick-strong').attr('x', (r) => lw + x(r.a) + 8).attr('y', opt.b ? 13 : bh / 2 + 4).text((r) => fmt(r));
}

const now = D.steps[D.steps.length - 1];
const passN = D.checks.filter((c) => c.Result === 'PASS').length, failN = D.checks.filter((c) => c.Result === 'FAIL').length;
const ev8 = D.events.find((r) => r.Window_weeks === 8 && r.Direction === 'All');
const chosen = D.store.find((r) => r.Chosen);
$('#side-status').textContent = failN ? `${failN} checks failing` : `${passN} of ${D.checks.length} checks pass`;

const HEAD = {
  overview: ['Overview', 'Where the price model stands after the four fixes: checks, plan and tests.'],
  steps: ['Plan by step', 'The yearly gain after each fix to the data and the model.'],
  limits: ['Price-rise limits', 'The optimiser re-run with each new limit on price rises added in turn.'],
  tests: ['Model tests', 'Do the price effects predict what really happened?'],
  store: ['Store test', 'Control stores keep today’s prices for 8 weeks, so the gain can be measured.'],
  stock: ['Stock-outs', 'Weeks when a store ran out, and what they cost in the last 52 weeks.'],
  checks: ['Automated checks', 'Run after every change to the data or the code.'],
  open: ['Still open', 'What the model cannot settle on its own.'],
};
const DRAW = {
  overview() {
    $('#take').innerHTML = '';
    $('#take').append(`${passN} of ${D.checks.length} automated checks pass. The plan gains `, el('b', null, M(now.Plan)),
      ` a year (cautious `, el('b', null, M(now.Cautious)), `) from `, el('b', null, N(now.Rises)), ` price rises, and Fresmart's past price changes moved sales `,
      el('b', null, Math.round(ev8.Calibration_slope * 100) + '%'), ` as much as the model predicts.`);
    kpi('kpis', [['Checks passed', `${passN}/${D.checks.length}`, failN ? `${failN} failing` : 'none failing', 'shield', failN ? 'down' : 'up'],
      ['Planned gain', M(now.Plan), 'per year, after rounding', 'dollar'], ['Cautious case', M(now.Cautious), 'customers react 1.5x', 'dollar'],
      ['Price rises', N(now.Rises), `${now.Fails} rule failures`, 'tag', now.Fails ? 'down' : 'up'],
      ['Basket rise', P(now.Basket, 2), 'limit +1.8%', 'basket', now.Basket <= 1.8 ? 'up' : 'down'],
      ['Model size match', ev8.Calibration_slope.toFixed(2), `± ${ev8.Calibration_SE.toFixed(2)}, ${N(ev8.Events)} changes`, 'flask']]);
    hbars('ov-steps', D.steps.map((r) => ({ label: r.Stage, a: r.Plan, b: r.Cautious })), (r) => M(r.a), { b: true, aria: 'Planned gain after each fix' });
    $('#ov-ck-tag').textContent = `${passN} pass`;
    table('ov-checks', [{ h: 'Check', k: 'Check' }, { h: 'What', k: 'What' }, { h: 'Result', f: (r) => pill(r.Result) }], D.checks);
  },
  steps() {
    hbars('st-chart', D.steps.map((r) => ({ label: r.Stage, a: r.Plan, b: r.Cautious })), (r) => M(r.a), { b: true, aria: 'Planned gain after each fix' });
    table('st-table', [{ h: 'Stage', k: 'Stage' }, { h: 'Planned gain', num: 1, f: (r) => M(r.Plan) }, { h: 'Cautious', num: 1, f: (r) => M(r.Cautious) },
      { h: 'Price rises', num: 1, f: (r) => N(r.Rises) }, { h: 'Basket', num: 1, f: (r) => P(r.Basket, 2) }, { h: 'Rule failures', num: 1, k: 'Fails' }], D.steps, (r) => r === now);
  },
  limits() {
    hbars('lm-chart', D.limits.map((r) => ({ label: r.Step.replace(/ \(penalty [0-9.]+\)/, '').replace(' (rise <= 10%, Low confidence <= 10%)', ''), a: r.Gain, b: r.Cautious })),
      (r) => M(r.a), { b: true, lw: 300, aria: 'Gain after each limit' });
    table('lm-table', [{ h: 'Limit added', f: (r) => r.Step.replace(/ \(penalty [0-9.]+\)/, '') }, { h: 'Gain', num: 1, f: (r) => M(r.Gain) },
      { h: 'Cautious', num: 1, f: (r) => M(r.Cautious) }, { h: 'Rises', num: 1, f: (r) => N(r.Rises) }, { h: 'Rises 7%+', num: 1, f: (r) => N(r.Big) },
      { h: 'Basket', num: 1, f: (r) => P(r.Basket, 2) }], D.limits, (r) => r === D.limits[D.limits.length - 1]);
  },
  tests() {
    const best = D.holdout.find((r) => r.Chosen), rise = D.events.find((r) => r.Window_weeks === 8 && r.Direction === 'Rise');
    kpi('ts-kpis', [['Unseen months: size match', best.Calib_slope_hold.toFixed(2), `${N(best.SKUs)} SKUs, method used`, 'flask', 'up'],
      ['Unseen months: correlation', best.Corr_hold.toFixed(2), 'per-SKU effects carry real signal', 'trend'],
      ['Past changes: size match', ev8.Calibration_slope.toFixed(2), `± ${ev8.Calibration_SE.toFixed(2)} on ${N(ev8.Events)} changes`, 'activity', 'up'],
      ['Past rises: size match', rise.Calibration_slope.toFixed(2), 'rises hurt less than the model says', 'activity', 'warn']]);
    table('ts-hold', [{ h: 'Method', f: (r) => r.Method + (r.Chosen ? '  ✓' : '') }, { h: 'Error', num: 1, f: (r) => r.Pred_error_RMSE.toFixed(2) },
      { h: 'Size match', num: 1, f: (r) => r.Corr_hold == null ? '–' : r.Calib_slope_hold.toFixed(2) }, { h: 'Correlation', num: 1, f: (r) => r.Corr_hold == null ? '–' : r.Corr_hold.toFixed(2) }],
      D.holdout, (r) => r.Chosen);
    table('ts-events', [{ h: 'Window', f: (r) => r.Window_weeks + ' wks' }, { h: 'Change', k: 'Direction' }, { h: 'Events', num: 1, f: (r) => N(r.Events) },
      { h: 'Real', num: 1, f: (r) => r.Event_elasticity.toFixed(2) }, { h: 'Model', num: 1, f: (r) => r.Model_avg_elasticity.toFixed(2) },
      { h: 'Size match', num: 1, f: (r) => r.Calibration_slope.toFixed(2) + ' ± ' + r.Calibration_SE.toFixed(2) }], D.events, (r) => r === ev8);
  },
  store() {
    const old = D.store.find((r) => r.Control_stores === 30);
    kpi('sr-kpis', [['Control stores', N(chosen.Control_stores), `${N(chosen.Changed_stores)} stores change`, 'flag'],
      ['Smallest gain it shows', chosen.GP_MDE_4w_pct.toFixed(1) + '%', `expected ${P(chosen.Expected_GP_change_pct)} gross profit`, 'gauge', 'up'],
      ['Gain given up', K(chosen.Gain_given_up_8w_usd), `vs ${K(old.Gain_given_up_8w_usd)} with 30 pairs`, 'dollar', 'up']]);
    hbars('sr-chart', D.store.map((r) => ({ label: r.Control_stores + ' control stores', a: r.Gain_given_up_8w_usd, color: r.Chosen ? ACC : 'var(--cds-chart-muted)', m: r.GP_MDE_4w_pct })),
      (r) => `${K(r.a)} given up · shows ${r.m.toFixed(1)}%`, { lw: 150, rw: 230, aria: 'Gain given up by number of control stores' });
    table('sr-table', [{ h: 'Control stores', num: 1, k: 'Control_stores' }, { h: 'Share of sales', num: 1, f: (r) => r.Control_share_of_sales_pct.toFixed(0) + '%' },
      { h: 'Smallest change shown (4 wks)', num: 1, f: (r) => r.GP_MDE_4w_pct.toFixed(1) + '%' },
      { h: 'Shows half the gain', f: (r) => el('span', 'fp-delta ' + (r.Detects_half_the_expected_at_4w ? 'up' : 'warn'), r.Detects_half_the_expected_at_4w ? 'yes' : 'no') },
      { h: 'Gain given up', num: 1, f: (r) => K(r.Gain_given_up_8w_usd) }], D.store, (r) => r.Chosen);
    table('sr-roll', [{ h: 'Level', k: 'Level' }, { h: 'Check', k: 'Check' }, { h: 'Pause next wave if', k: 'Pause next wave if' }, { h: 'Roll back if', k: 'Roll back the wave if' }], D.rollback);
  },
  stock() {
    const s = D.stockouts;
    kpi('so-kpis', [['Store-weeks out of stock', s.gap_pct.toFixed(1) + '%', `+ ${s.edge_pct.toFixed(1)}% ran out mid-week`, 'box', 'warn'],
      ['Lost sales', '$' + s.lost_sales_m.toFixed(1) + 'M', `${s.lost_sales_pct.toFixed(1)}% of sales`, 'receipt', 'down'],
      ['Lost gross profit', '$' + s.lost_gp_m.toFixed(2) + 'M', `${s.lost_gp_pct.toFixed(1)}% of GP after IVA`, 'dollar', 'down'],
      ['SKUs affected', N(s.skus), 'at least one stock-out week', 'tag']]);
    hbars('so-chart', D.stock_groups.map((r) => ({ label: r.Group, a: r.Sales, u: r.Units_pct })), (r) => `${M(r.a)} · ${r.u.toFixed(1)}% of units`, { lw: 150, rw: 190, aria: 'Lost sales by group' });
  },
  checks() {
    table('ck-table', [{ h: '#', k: 'Check' }, { h: 'What it checks', k: 'What' }, { h: 'Result', f: (r) => pill(r.Result) }, { h: 'Detail', k: 'Detail' }], D.checks);
  },
  open() {},
};
const TABS = Object.keys(HEAD);
function show(t) {
  if (!TABS.includes(t)) t = 'overview';
  TABS.forEach((x) => { document.getElementById('pg-' + x).hidden = x !== t; document.getElementById('tab-' + x).setAttribute('aria-selected', String(x === t)); });
  $('#page-title').textContent = HEAD[t][0]; $('#page-sub').textContent = HEAD[t][1];
  $('#crumb').textContent = HEAD[t][0];
  history.replaceState(null, '', '#' + t);
  DRAW[t]();
}
document.querySelectorAll('.fp-tab').forEach((b) => b.addEventListener('click', () => show(b.dataset.tab)));
let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => show(location.hash.slice(1)), 150); });
show(location.hash.slice(1));
</script>
"""


def main():
    page = (DASH / "page.html").read_text(encoding="utf-8")
    style = re.search(r"<style>.*?</style>", page, re.S).group(0)
    icons = re.search(r"const ICONS = \{.*?\n\};", page, re.S).group(0)
    shell = (DASH / "index.html").read_text(encoding="utf-8")
    head = shell[: shell.index('<div id="dash-root">')].replace('<script src="dash-local.js"></script>\n', "")
    head = head.replace("<title>Fresmart Pricing Studio</title>", "<title>Fresmart Model Health</title>")
    body = PAGE + SCRIPT.replace("__DATA__", json.dumps(load())).replace("__ICONS__", icons)
    out = head + '<div id="dash-root">\n' + style + body + "</div>\n</body>\n</html>\n"
    (DASH / "health.html").write_text(out, encoding="utf-8")
    print("built", DASH / "health.html", f"{len(out) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
