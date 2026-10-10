import { $, $$, cached, esc, n, ago, stampDate, gateStrip, dispChip, dispShort, pipeChip, PIPE_ORDER, splitName, initials, empty, skeleton, downloadCSV, q } from '../lib.js';
import { setCrumbs, screenDialog, jobs, onJobs } from '../app.js';

/** @type {[string, string, (f: any) => any][]} */
const FILTERS = [
  ['all', 'All', () => true],
  ['unscreened', 'Not screened', f => !f.latest],
  ['screened', 'Screened', f => !!f.latest],
  ['review', 'Analyst review', f => f.latest?.flags?.any_review],
  ['fail', 'Gate not met', f => f.latest?.flags?.any_fail],
];
const COLS = {
  name: f => f.name.toLowerCase(),
  pipe: f => PIPE_ORDER.indexOf(f.pipeline?.Status ?? '') * -1,
  disp: f => dispShort(f.latest?.disposition),
  run: f => f.latest?.run || '',
  pages: f => f.catalog?.pages ?? -1,
  material: f => f.pipeline?.['Material on file'] || f.pipeline?.['Last action'] || '',
};

export async function render(el, r) {
  setCrumbs([['Screening']]);
  el.innerHTML = `<div class="page">${skeleton(10)}</div>`;
  let funds = await cached('funds');
  const st = { f: r.query.f || 'all', stage: r.query.stage || '', pipe: r.query.pipe || '', text: r.query.text || '', sort: r.query.sort || 'run', dir: r.query.dir || 'desc' };
  const sync = () => history.replaceState(null, '', '#/screening?' + q(Object.fromEntries(Object.entries(st).filter(([, v]) => v))));
  const pipeStatuses = [...new Set(funds.map(f => f.pipeline?.Status).filter(Boolean))].sort((a, b) => PIPE_ORDER.indexOf(a) - PIPE_ORDER.indexOf(b));

  el.innerHTML = `<div class="page">
    <div class="ph"><div><h1>Screening</h1><p>Every indexed data room, its pipeline status from PIPELINE.md, and the latest result of each of the five gates.</p></div>
      <div class="act"><button class="ghost-btn" id="csv"><sl-icon name="download"></sl-icon>Export CSV</button></div></div>
    <div class="bar">
      <div class="seg" id="seg">${FILTERS.map(([k, label, fn]) => `<button data-f="${k}" class="${st.f === k ? 'on' : ''}">${label}<span class="c">${funds.filter(fn).length}</span></button>`).join('')}</div>
      <span class="sp"></span>
      <sl-input id="text" size="small" placeholder="Filter funds" clearable style="width:200px" value="${esc(st.text)}"><sl-icon name="filter" slot="prefix"></sl-icon></sl-input>
      <sl-select id="stage" size="small" placeholder="All stages" clearable value="${esc(st.stage)}"><sl-option value="1-Intake">1-Intake</sl-option><sl-option value="2-Managers">2-Managers</sl-option></sl-select>
      <sl-select id="pipe" size="small" placeholder="Any pipeline status" clearable value="${esc(st.pipe.replaceAll(' ', '_'))}">${pipeStatuses.map(s => `<sl-option value="${esc(s.replaceAll(' ', '_'))}">${esc(s)}</sl-option>`).join('')}</sl-select>
    </div>
    <div class="card"><div class="tbl-wrap" id="tbl"></div></div></div>`;

  const rows = () => {
    const fn = FILTERS.find(x => x[0] === st.f)[2];
    const t = st.text.toLowerCase();
    let out = funds.filter(f => fn(f) && (!st.stage || f.stage === st.stage) && (!st.pipe || f.pipeline?.Status === st.pipe) &&
      (!t || (f.name + ' ' + (f.pipeline?.Strategy || '') + ' ' + (f.pipeline?.Owner || '')).toLowerCase().includes(t)));
    const k = COLS[st.sort] || COLS.run;
    out.sort((a, b) => { const x = k(a), y = k(b); return (x < y ? -1 : x > y ? 1 : 0) * (st.dir === 'asc' ? 1 : -1) || a.name.localeCompare(b.name); });
    return out;
  };
  const th = (key, label, cls = '') => `<th class="sort ${cls}" data-sort="${key}">${label}${st.sort === key ? `<sl-icon class="arr" name="${st.dir === 'asc' ? 'arrow-up' : 'arrow-down'}"></sl-icon>` : ''}</th>`;
  const draw = () => {
    const list = rows();
    $('#tbl', el).innerHTML = list.length ? `<table class="t">
      <tr>${th('name', 'Fund')}${th('pipe', 'Pipeline')}<th>Owner</th>${th('material', 'Latest material')}<th>Gates</th>${th('disp', 'Disposition')}${th('run', 'Last screen', 'n')}${th('pages', 'Pages', 'n')}<th></th></tr>
      ${list.map(f => {
        const s = splitName(f.name), running = jobs.get(f.id)?.state.status === 'running';
        const mat = f.pipeline?.['Material on file'];
        return `<tr class="click" data-id="${esc(f.id)}">
        <td><div style="display:flex;gap:10px;align-items:center"><span class="fund-av" style="width:28px;height:28px;border-radius:7px;display:grid;place-items:center;background:var(--s3);font-size:10.5px;font-weight:700;color:var(--ink3);flex:none">${esc(initials(s.manager))}</span>
          <div><div class="nm">${esc(s.manager)}</div><div class="sub">${esc(f.pipeline?.Strategy || s.strategy)}</div></div></div></td>
        <td>${pipeChip(f.pipeline?.Status)}<div class="sub">${esc(f.stage || '')}</div></td>
        <td class="${f.pipeline?.Owner === 'unassigned' ? 'dim' : ''}">${esc(f.pipeline?.Owner || '–')}</td>
        <td class="dim tnum" style="white-space:nowrap">${mat && /^\d{4}/.test(mat) ? `${esc(mat)}<div class="sub">${ago(new Date(mat))}</div>` : '–'}</td>
        <td>${running ? '<span class="chip accent"><span class="pulse"></span>&nbsp;Running</span>' : gateStrip(f.latest?.gates)}</td>
        <td>${f.latest ? dispChip(f.latest.disposition) : '<span class="dim">–</span>'}</td>
        <td class="n dim tnum">${f.latest ? ago(stampDate(f.latest.run)) : '–'}<div class="sub">${f.runs.length ? f.runs.length + ' run' + (f.runs.length > 1 ? 's' : '') : ''}</div></td>
        <td class="n tnum">${f.catalog ? n(f.catalog.pages) : '<span class="dim">–</span>'}</td>
        <td class="n"><button class="ghost-btn sm" data-run="${esc(f.id)}" ${running ? 'disabled' : ''} title="Run screen"><sl-icon name="play-fill"></sl-icon>Screen</button></td></tr>`;
      }).join('')}</table>` : empty('filter-circle', 'No funds match', 'Clear a filter to see more.');
    $$('tr[data-id]', el).forEach(tr => tr.addEventListener('click', e => { if (!e.target.closest('[data-run]')) location.hash = `#/fund/${encodeURIComponent(tr.dataset.id)}`; }));
    $$('[data-run]', el).forEach(b => b.addEventListener('click', () => screenDialog(funds.find(f => f.id === b.dataset.run))));
    $$('th[data-sort]', el).forEach(h => h.addEventListener('click', () => {
      const k = h.dataset.sort; st.dir = st.sort === k && st.dir === 'desc' ? 'asc' : 'desc'; st.sort = k; sync(); draw();
    }));
  };
  draw();
  $$('#seg button', el).forEach(b => b.addEventListener('click', () => { st.f = b.dataset.f; $$('#seg button', el).forEach(x => x.classList.toggle('on', x === b)); sync(); draw(); }));
  $('#text', el).addEventListener('sl-input', e => { st.text = e.target.value; sync(); draw(); });
  $('#stage', el).addEventListener('sl-change', e => { st.stage = e.target.value; sync(); draw(); });
  $('#pipe', el).addEventListener('sl-change', e => { st.pipe = e.target.value.replaceAll('_', ' '); sync(); draw(); });
  $('#csv', el).addEventListener('click', () => downloadCSV('screening-queue.csv', rows().map(f => ({
    fund: f.name, stage: f.stage, pipeline_status: f.pipeline?.Status, owner: f.pipeline?.Owner, disposition: f.latest?.disposition,
    last_run: f.latest?.run, ...Object.fromEntries(Object.entries(f.latest?.gates || {}).map(([g, v]) => [g, v.result])), pages: f.catalog?.pages,
  }))));
  let sig = '';
  return onJobs(async js => {
    const now = [...js.values()].map(j => j.fundId + j.state.status).join();
    if (now === sig) return;
    sig = now;
    funds = await cached('funds');
    draw();
  });
}
