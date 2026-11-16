// Local stand-in for the claude.ai dashboard runtime: loads data/*.json and gives the page the same `dash` API.
(function () {
  const DATASETS = ['skus', 'grid', 'weekly', 'test_pairs', 'test_power', 'test_plan', 'rules', 'flags', 'line_moves', 'basket', 'frontier', 'accuracy', 'seasonal', 'corrections', 'portfolio', 'portfolio_meta'];
  // price plans: the plan-specific datasets exist once per plan (<name>__<plan>.json); setPlan swaps them in place
  const PLANS = ['current', 'sweetspot'];
  const PLAN_SETS = ['skus', 'weekly', 'test_pairs', 'test_power', 'test_plan', 'rules', 'flags', 'line_moves', 'basket', 'frontier'];
  const byPlan = { current: {}, sweetspot: {} };
  let plan = 'current';
  try { if (PLANS.includes(localStorage.getItem('fp-plan'))) plan = localStorage.getItem('fp-plan'); } catch (e) { /* storage blocked */ }
  const store = {};
  const calcs = {};
  const listeners = [];
  DATASETS.forEach((id) => { store[id] = { status: 'loading', data: [] }; });

  function runCalcs() {
    Object.entries(calcs).forEach(([id, c]) => {
      const ins = c.inputs.map((i) => store[i] || calcs[i]?.result);
      if (ins.every((x) => x && x.status === 'ok')) {
        try { c.result = { status: 'ok', data: c.fn(...ins.map((x) => x.data)) }; } catch (e) { console.error('calc', id, e); c.result = { status: 'error', data: [] }; }
      } else if (ins.some((x) => x && x.status === 'error')) c.result = { status: 'error', data: [] };
      else c.result = { status: 'loading', data: [] };
    });
  }
  function notify() {
    runCalcs();
    listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    document.querySelectorAll('[data-source]').forEach((el) => {
      const ids = el.dataset.source.split(' ');
      const loading = ids.some((i) => api.data(i).status === 'loading');
      if (!loading) el.classList.remove('dash-skeleton');
    });
  }
  const api = {
    colors: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
    data(id) {
      if (store[id]) return { ...store[id], columns: store[id].data[0] ? Object.keys(store[id].data[0]) : [], refreshing: false, meta: [] };
      if (calcs[id]) return calcs[id].result || { status: 'loading', data: [] };
      return { status: 'missing', data: [] };
    },
    calc(id, c) { calcs[id] = { ...c, result: { status: 'loading', data: [] } }; },
    loader() {},
    onData(fn) { listeners.push(fn); try { fn(); } catch (e) { console.error(e); } },
    setLink(name) { history.replaceState(null, '', '#' + name); },
    params: () => ({}), setParams() {}, resetParams() {}, refresh() {},
    plan: () => plan,
    setPlan(p) {
      if (!PLANS.includes(p)) return;
      plan = p;
      try { localStorage.setItem('fp-plan', p); } catch (e) { /* storage blocked */ }
      PLAN_SETS.forEach((id) => { if (byPlan[p][id]) store[id] = byPlan[p][id]; });
      notify();
    },
  };
  window.dash = api;

  const load = (file) => fetch('data/' + file + '.json')
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((rows) => ({ status: 'ok', data: rows }))
    .catch((e) => { console.error('load', file, e); return { status: 'error', data: [] }; });
  DATASETS.filter((id) => !PLAN_SETS.includes(id)).forEach((id) => load(id).then((r) => { store[id] = r; notify(); }));
  PLAN_SETS.forEach((id) => PLANS.forEach((p) => load(p === 'current' ? id : id + '__' + p).then((r) => {
    byPlan[p][id] = r;
    if (p === plan) { store[id] = r; notify(); }
  })));

  let t;
  window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(notify, 120); });
})();
