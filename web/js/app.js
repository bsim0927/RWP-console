// App shell: hash router, sidebar state, omni search, background job watcher.
import { $, $$, api, cached, bust, esc, q, initTips, setGateOrder, toast, splitName, dispTone, empty } from './lib.js';

const VIEWS = {
  overview: () => import('./views/overview.js'),
  screening: () => import('./views/screening.js'),
  fund: () => import('./views/fund.js'),
  catalogs: () => import('./views/catalogs.js'),
  files: () => import('./views/files.js'),
  search: () => import('./views/search.js'),
  analytics: () => import('./views/analytics.js'),
  logs: () => import('./views/logs.js'),
  policy: () => import('./views/policy.js'),
};

// ---------- jobs: one watcher for every screen started from this tab ----------
export const jobs = new Map(); // fundId -> {id, fund, state}
const listeners = new Set();
export const onJobs = fn => (listeners.add(fn), () => listeners.delete(fn));

export async function startScreen(fundId, extractor, judge) {
  const r = await api('screen', { method: 'POST', body: JSON.stringify({ fund: fundId, extractor, judge }) });
  jobs.set(fundId, { id: r.job, fundId, state: { status: 'running', steps: [], gates: [], elapsed: 0 } });
  toast(`Screen started for <b>${esc(splitName(fundId.replaceAll('_', ' ')).manager)}</b>`, 'accent', 'play-circle');
  pollJobs();
  return r.job;
}
// Confirm before spending model calls; remembers the last extractor/judge choice.
export function screenDialog(fund) {
  const last = JSON.parse(safeGet('sg.screenopts') || '{"extractor":"claude","judge":"jev"}');
  const d = document.createElement('sl-dialog');
  d.label = 'Run screen';
  d.innerHTML = `<div style="display:flex;flex-direction:column;gap:14px">
    <div><div class="dim" style="font-size:12px">Data room</div><div style="font-weight:600">${esc(fund.name)}</div></div>
    <sl-select id="sd-ex" label="Extractor" value="${esc(last.extractor)}" size="small"><sl-option value="claude">claude</sl-option></sl-select>
    <sl-select id="sd-jd" label="Judge" value="${esc(last.judge)}" size="small" help-text="Five gates run in parallel; each makes one extraction call and one judge call.">
      <sl-option value="jev">jev</sl-option><sl-option value="claude">claude</sl-option></sl-select></div>
    <div slot="footer" style="display:flex;gap:8px;justify-content:flex-end"><button class="ghost-btn" data-x>Cancel</button><button class="glow-btn" data-go><sl-icon name="play-fill"></sl-icon>Run screen</button></div>`;
  document.body.append(d);
  d.addEventListener('sl-after-hide', e => { if (e.target === d) d.remove(); });
  d.querySelector('[data-x]').onclick = () => d.hide();
  d.querySelector('[data-go]').onclick = async () => {
    const opts = { extractor: d.querySelector('#sd-ex').value, judge: d.querySelector('#sd-jd').value };
    safeSet('sg.screenopts', JSON.stringify(opts));
    d.hide();
    try { await startScreen(fund.id, opts.extractor, opts.judge); } catch (e) { toast('Could not start: ' + esc(e.message), 'crit'); }
  };
  customElements.whenDefined('sl-dialog').then(() => requestAnimationFrame(() => d.show()));
}
function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); } catch { /* storage blocked */ } }

let polling = false;
async function pollJobs() {
  if (polling) return;
  polling = true;
  while ([...jobs.values()].some(j => j.state.status === 'running')) {
    for (const j of jobs.values()) {
      if (j.state.status !== 'running') continue;
      try { j.state = await api('job/' + j.id); } catch (e) { j.state = { status: 'error', error: e.message, steps: [], gates: [] }; }
      if (j.state.status !== 'running') {
        bust('funds'); bust('runs'); bust('analytics'); bust('history');
        if (j.state.status === 'done') toast(`Screen finished: <b>${esc(j.fundId.replaceAll('_', ' '))}</b>`, 'good');
        else toast(`Screen failed: ${esc(j.state.error)}`, 'crit');
      }
    }
    listeners.forEach(fn => fn(jobs));
    updateNav();
    await new Promise(r => setTimeout(r, 450));
  }
  polling = false;
  listeners.forEach(fn => fn(jobs));
  updateNav();
}

async function updateNav() {
  const running = [...jobs.values()].filter(j => j.state.status === 'running').length;
  const nj = $('#nav-jobs');
  nj.hidden = !running; nj.textContent = running;
  try {
    const funds = await cached('funds');
    const rv = funds.filter(f => f.latest?.flags?.any_review).length;
    const el = $('#nav-review'); el.hidden = !rv; el.textContent = rv; el.title = `${rv} screens waiting on analyst review`;
  } catch { /* nav badges are optional */ }
}

// ---------- router ----------
let cleanup = null, seq = 0;
function parse() {
  const h = location.hash.slice(1) || '/';
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  return { name: parts[0] || 'overview', parts: parts.slice(1), query: Object.fromEntries(new URLSearchParams(qs || '')) };
}
export function setCrumbs(items) {
  $('#crumbs').innerHTML = items.map((c, i) => i < items.length - 1 ? `<a href="${c[1]}">${esc(c[0])}</a><sl-icon name="chevron-right"></sl-icon>` : `<b>${esc(c[0])}</b>`).join('');
}
async function route() {
  const r = parse();
  const my = ++seq;
  if (typeof cleanup === 'function') cleanup();
  cleanup = null;
  const navKey = r.name === 'fund' ? 'screening' : r.name;
  $$('#nav a').forEach(a => a.classList.toggle('on', a.dataset.route === navKey));
  $('#drawer').hide?.();
  const view = $('#view');
  const load = VIEWS[r.name];
  if (!load) { view.innerHTML = `<div class="page">${empty('signpost', 'Page not found', `<a href="#/">Back to overview</a>`)}</div>`; return; }
  const mod = await load();
  if (my !== seq) return;
  view.scrollTop = 0;
  try {
    cleanup = await mod.render(view, r, { isCurrent: () => my === seq });
  } catch (e) {
    console.error(e);
    if (my === seq) view.innerHTML = `<div class="page">${empty('exclamation-octagon', 'Could not load this view', `<span class="mono">${esc(e.message)}</span>`)}</div>`;
  }
}

// ---------- omni search ----------
function initOmni() {
  const inp = $('#omni-in'), list = $('#omni-list');
  let items = [], sel = 0;
  const close = () => { list.hidden = true; };
  const draw = async () => {
    const v = (inp.value || '').trim().toLowerCase();
    if (!v) return close();
    const funds = await cached('funds');
    const hits = funds.filter(f => f.name.toLowerCase().includes(v)).slice(0, 7);
    items = [
      ...hits.map(f => ({ href: `#/fund/${encodeURIComponent(f.id)}`, html: `<span class="dot ${dispTone(f.latest?.disposition)}"></span><span>${esc(f.name)}</span><span class="sp"></span><span class="dim" style="font-size:11px">${esc(f.status?.status || '')}</span>` })),
      { href: `#/search?${q({ q: inp.value.trim() })}`, html: `<sl-icon name="search"></sl-icon><span>Search all documents for <b>${esc(inp.value.trim())}</b></span><span class="sp"></span><kbd>Enter</kbd>` },
    ];
    sel = hits.length ? 0 : items.length - 1;
    list.innerHTML = (hits.length ? '<div class="g">Funds</div>' : '') + items.map((it, i) => `${i === hits.length ? '<div class="g">Documents</div>' : ''}<a href="${it.href}" class="${i === sel ? 'on' : ''}">${it.html}</a>`).join('');
    list.hidden = false;
  };
  inp.addEventListener('sl-input', draw);
  inp.addEventListener('sl-focus', draw);
  inp.addEventListener('sl-blur', () => setTimeout(close, 150));
  inp.addEventListener('keydown', e => {
    if (list.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      $$('a', list).forEach((a, i) => a.classList.toggle('on', i === sel));
    } else if (e.key === 'Enter') {
      location.hash = items[sel].href; inp.value = ''; close(); inp.blur();
    } else if (e.key === 'Escape') { close(); inp.blur(); }
  });
  list.addEventListener('click', () => { inp.value = ''; close(); });
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !/** @type {Element} */ (e.target).closest('input,textarea,sl-input,sl-textarea,[contenteditable]')) { e.preventDefault(); inp.focus(); }
  });
}

async function init() {
  initTips();
  initOmni();
  try {
    const [meta, cfg] = await Promise.all([api('meta'), cached('config', 60000)]);
    setGateOrder(cfg.gates.map(g => g.parsed.id));
    $('#nav-foot').innerHTML = `<div>${meta.rooms} indexed data rooms</div><div class="mono" title="Data root">${esc(meta.data_root)}</div>`;
  } catch (e) { toast('Server unreachable: ' + esc(e.message), 'crit'); }
  // Pick up screens still running on the server, e.g. after a page reload.
  try {
    const lg = await api('logs');
    lg.jobs.filter(j => j.status === 'running' && j.fund_id).forEach(j => jobs.set(j.fund_id, { id: j.id, fundId: j.fund_id, state: { status: 'running', steps: [], gates: [] } }));
    if (jobs.size) pollJobs();
  } catch { /* logs are optional at boot */ }
  updateNav();
  addEventListener('hashchange', route);
  route();
}
init();
