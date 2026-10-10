// Agent monitor: every screen run as a trace of model calls, with runtimes, token usage and outputs.
import { $, $$, api, esc, n, pct, ago, fmtDT, fmtTime, stampDate, gateName, sortGates, resultChip, dispChip, stackBars, dotStrip, legend, empty, skeleton, downloadCSV, waterfall } from '../lib.js';
import { setCrumbs } from '../app.js';

const STEP_COL = { extract: 'var(--st-extract)', judge: 'var(--st-judge)' };
/** @type {[string, string, number][]} */
const RANGES = [['24h', 'Last 24 hours', 864e2], ['7d', 'Last 7 days', 6048e2], ['all', 'All time', Infinity]];
const median = a => { const s = a.filter(v => v != null).sort((x, y) => x - y); return s.length ? (s.length % 2 ? s[s.length >> 1] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null; };
const p95 = a => { const s = a.filter(v => v != null).sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.floor(s.length * 0.95))] : null; };
const secs = v => v == null ? '–' : v < 1 ? (v * 1000).toFixed(0) + 'ms' : v.toFixed(1) + 's';
const model = c => c.model || (c.provider === 'anthropic' ? 'claude (model not recorded)' : c.provider || '–');

export async function render(el, r) {
  setCrumbs([['Agent monitor']]);
  el.innerHTML = `<div class="page">${skeleton(3)}${skeleton(8)}</div>`;
  const st = { tab: ['runs', 'calls', 'errors', 'server'].includes(r.query.tab) ? r.query.tab : 'runs', range: r.query.range || 'all', open: new Set(), step: '', status: '', text: '' };
  let data, sig = '', server = { events: [] };

  el.innerHTML = `<div class="page">
    <div class="ph"><div><h1>Agent monitor</h1><p>Every model call the screening agent makes: what ran, how long it took, the tokens it used, and what came back.</p></div>
      <div class="act"><div class="seg" id="range">${RANGES.map(([k, l]) => `<button data-v="${k}" class="${st.range === k ? 'on' : ''}">${l}</button>`).join('')}</div></div></div>
    <div id="live"></div><div id="kpis"></div><div id="charts"></div>
    <sl-tab-group class="tabs" id="mt" style="margin-top:6px">
      <sl-tab slot="nav" panel="runs" ${st.tab === 'runs' ? 'active' : ''}><sl-icon name="diagram-3" style="margin-right:7px"></sl-icon>Run traces</sl-tab>
      <sl-tab slot="nav" panel="calls" ${st.tab === 'calls' ? 'active' : ''}><sl-icon name="cpu" style="margin-right:7px"></sl-icon>Model calls</sl-tab>
      <sl-tab slot="nav" panel="errors" ${st.tab === 'errors' ? 'active' : ''}><sl-icon name="exclamation-octagon" style="margin-right:7px"></sl-icon>Errors<span id="errc" class="dim" style="margin-left:6px"></span></sl-tab>
      <sl-tab slot="nav" panel="server" ${st.tab === 'server' ? 'active' : ''}><sl-icon name="hdd-network" style="margin-right:7px"></sl-icon>Server</sl-tab>
      <sl-tab-panel name="runs"><div id="t-runs"></div></sl-tab-panel><sl-tab-panel name="calls"><div id="t-calls"></div></sl-tab-panel>
      <sl-tab-panel name="errors"><div id="t-errors"></div></sl-tab-panel><sl-tab-panel name="server"><div id="t-server"></div></sl-tab-panel></sl-tab-group></div>`;
  const sync = () => history.replaceState(null, '', `#/logs?tab=${st.tab}&range=${st.range}`);
  $('#mt', el).addEventListener('sl-tab-show', e => { st.tab = e.detail.name; sync(); });
  $$('#range button', el).forEach(b => b.addEventListener('click', () => { st.range = b.dataset.v; $$('#range button', el).forEach(x => x.classList.toggle('on', x === b)); sync(); draw(); }));

  const inRange = ts => { const w = RANGES.find(x => x[0] === st.range)[2]; return w === Infinity || (Date.now() / 1000 - ts) <= w; };

  function draw() {
    const runs = data.runs.filter(x => x.agentic && inRange(stampDate(x.run).getTime() / 1000));
    const calls = data.calls.filter(c => inRange(c.ts));
    const ok = calls.filter(c => c.ok), bad = calls.filter(c => !c.ok);
    const tin = calls.reduce((a, c) => a + (c.input_tokens || 0), 0), tout = calls.reduce((a, c) => a + (c.output_tokens || 0), 0);
    const byStep = s => ok.filter(c => c.step === s).map(c => c.seconds);
    const proposed = runs.reduce((a, x) => a + x.facts_proposed, 0), kept = runs.reduce((a, x) => a + x.facts_verified, 0);
    const untracked = calls.filter(c => c.backfilled && c.step === 'extract').length;
    const failedJobs = data.jobs.filter(j => j.status === 'error');

    // live jobs
    const live = data.jobs.filter(j => j.status === 'running');
    $('#live', el).innerHTML = live.length ? live.map(j => {
      const gates = [...new Set(j.steps.map(e => e.gate))].filter(g => g !== 'catalog');
      return `<div class="card" style="margin-bottom:14px;border-color:var(--accent-line)"><div class="hd"><span class="pulse"></span><h2 class="sec">${esc(j.fund)}</h2>
        <span class="sec-sub tnum">${esc(j.extractor)} → ${esc(j.judge)} · ${j.elapsed}s · ${j.steps.filter(e => e.end != null).length} steps done</span><span class="sp"></span>
        <a class="ghost-btn sm" href="#/fund/${encodeURIComponent(j.fund_id)}">Open fund<sl-icon name="arrow-right"></sl-icon></a></div>
        <div class="bd">${gates.length ? waterfall(j.steps.filter(e => e.gate !== 'catalog'), gates, j.elapsed, true) : '<div class="shimmer sk"></div>'}</div></div>`;
    }).join('') : '';

    $('#kpis', el).innerHTML = `<div class="kpis">
      <div class="kpi"><div class="l"><sl-icon name="diagram-3"></sl-icon>Agent runs</div><div class="v">${runs.length}</div><div class="f">${live.length ? `<span class="pulse"></span>&nbsp; ${live.length} running now` : 'none running'}</div></div>
      <div class="kpi"><div class="l"><sl-icon name="cpu"></sl-icon>Model calls</div><div class="v">${n(calls.length)}</div><div class="f">${n(ok.filter(c => c.step === 'extract').length)} extraction · ${n(ok.filter(c => c.step === 'judge').length)} judge</div></div>
      <div class="kpi hl"><div class="l"><sl-icon name="coin"></sl-icon>Tokens</div><div class="v">${n(tin + tout)}</div><div class="f">${n(tin)} in · ${n(tout)} out${untracked ? ` · ${untracked} extraction calls unmetered` : ''}</div></div>
      <div class="kpi"><div class="l"><sl-icon name="stopwatch"></sl-icon>Extraction latency</div><div class="v">${secs(median(byStep('extract')))}</div><div class="f">median · p95 ${secs(p95(byStep('extract')))}</div></div>
      <div class="kpi"><div class="l"><sl-icon name="stopwatch"></sl-icon>Judge latency</div><div class="v">${secs(median(byStep('judge')))}</div><div class="f">median · p95 ${secs(p95(byStep('judge')))}</div></div>
      <div class="kpi"><div class="l"><sl-icon name="exclamation-octagon"></sl-icon>Error rate</div><div class="v">${calls.length ? pct(bad.length / calls.length, 1) : '–'}</div><div class="f">${bad.length} failed calls · ${failedJobs.length} failed runs this session</div></div>
      <div class="kpi"><div class="l"><sl-icon name="patch-check"></sl-icon>Output kept</div><div class="v">${proposed ? pct(kept / proposed) : '–'}</div><div class="f">${n(kept)} of ${n(proposed)} proposed facts verified on the page</div></div></div>`;

    // charts
    const chrono = [...runs].reverse();
    const lat = ['extract', 'judge'].filter(s => byStep(s).length).map(s => ({ label: s === 'extract' ? 'Extraction' : 'Judge', color: STEP_COL[s],
      dots: ok.filter(c => c.step === s && c.seconds != null).map(c => ({ v: c.seconds, color: STEP_COL[s], tip: `<b>${esc(c.fund)}</b> · ${esc(gateName(c.gate || ''))}<br>${esc(model(c))} · ${secs(c.seconds)}${c.input_tokens != null ? `<br>${n(c.input_tokens)} in / ${n(c.output_tokens)} out` : ''}` })) }));
    const latMax = Math.max(1, ...ok.map(c => c.seconds || 0)) * 1.05;
    const models = {};
    calls.forEach(c => { const k = model(c); const m = models[k] ||= { k, provider: c.provider, calls: 0, err: 0, tin: 0, tout: 0, lat: [] }; m.calls++; m.err += !c.ok; m.tin += c.input_tokens || 0; m.tout += c.output_tokens || 0; m.lat.push(c.seconds); });
    $('#charts', el).innerHTML = runs.length ? `<div class="grid g2" style="margin-bottom:14px">
      <div class="card"><div class="hd"><h2 class="sec">Tokens per run</h2><span class="sec-sub">oldest to newest</span></div><div class="bd">
        ${stackBars(chrono.map((x, i) => ({ label: `#${i + 1}`, segs: [{ v: x.input_tokens, color: 'var(--c1)' }, { v: x.output_tokens, color: 'var(--c2)' }],
          tip: `<b>${esc(x.fund)}</b><br>${n(x.input_tokens)} in · ${n(x.output_tokens)} out<br><span class=dim>${x.calls} calls · ${secs(x.seconds)} · ${fmtDT(stampDate(x.run))}${x.traced ? '' : '<br>judge only: extraction was not metered before tracing'}</span>` })), { w: 600 })}
        ${legend([['Input tokens', 'var(--c1)'], ['Output tokens', 'var(--c2)']])}</div></div>
      <div class="card"><div class="hd"><h2 class="sec">Latency per call</h2><span class="sec-sub">seconds, one dot per model call</span></div><div class="bd">
        ${lat.length ? dotStrip(lat, { threshold: null, max: latMax, fmt: v => v.toFixed(0) + 's' }) : '<span class="dim">No calls in range.</span>'}</div></div></div>
      <div class="card" style="margin-bottom:14px"><div class="hd"><h2 class="sec">By model</h2></div><div class="bd flush"><table class="t"><tr><th>Model</th><th>Provider</th><th class="n">Calls</th><th class="n">Errors</th><th class="n">Input tokens</th><th class="n">Output tokens</th><th class="n">Median</th><th class="n">p95</th></tr>
        ${Object.values(models).map(m => `<tr><td class="mono">${esc(m.k)}</td><td class="dim">${esc(m.provider || '–')}</td><td class="n">${m.calls}</td><td class="n">${m.err || '–'}</td><td class="n">${m.tin ? n(m.tin) : '–'}</td><td class="n">${m.tout ? n(m.tout) : '–'}</td><td class="n">${secs(median(m.lat))}</td><td class="n">${secs(p95(m.lat))}</td></tr>`).join('')}</table></div></div>` : '';

    drawRuns(runs); drawCalls(calls); drawErrors(bad, failedJobs);
    $('#errc', el).textContent = bad.length + failedJobs.length || '';
  }

  // ---------- run traces ----------
  function drawRuns(runs) {
    $('#t-runs', el).innerHTML = runs.length ? `<div class="card"><div class="tbl-wrap"><table class="t"><tr><th></th><th>When</th><th>Fund</th><th>Agent</th><th class="n">Runtime</th><th class="n">Calls</th><th class="n">Tokens in / out</th><th class="n">Facts kept</th><th>Outcome</th><th>Trace</th></tr>
      ${runs.map(x => { const k = x.fund_id + x.run, open = st.open.has(k); return `<tr class="click" data-k="${esc(k)}"><td><sl-icon name="${open ? 'chevron-down' : 'chevron-right'}" class="dim"></sl-icon></td>
        <td class="tnum">${fmtDT(stampDate(x.run))}<div class="sub">${ago(stampDate(x.run))}</div></td><td class="nm">${esc(x.fund)}</td><td class="mono dim">${esc(x.extractor)} → ${esc(x.judge)}</td>
        <td class="n tnum">${secs(x.seconds)}</td><td class="n">${x.calls}${x.errors ? ` <span class="chip crit" style="height:18px">${x.errors} failed</span>` : ''}</td>
        <td class="n tnum">${n(x.input_tokens)} / ${n(x.output_tokens)}</td><td class="n tnum">${x.facts_verified}/${x.facts_proposed}</td><td>${dispChip(x.disposition)}</td>
        <td>${x.traced ? '<span class="chip good"><sl-icon name="check-lg"></sl-icon>Traced</span>' : '<span class="chip ghost" title="Run predates call tracing; rebuilt from step timings and judge usage">Backfilled</span>'}</td></tr>
        ${open ? `<tr><td colspan="10" style="background:var(--bg);padding:14px 18px">${trace(x)}</td></tr>` : ''}`; }).join('')}</table></div></div>`
      : `<div class="card">${empty('diagram-3', 'No agent runs in this range')}</div>`;
    $$('#t-runs tr[data-k]', el).forEach(tr => tr.addEventListener('click', () => { const k = tr.dataset.k; st.open.has(k) ? st.open.delete(k) : st.open.add(k); draw(); }));
    bindOutputs($('#t-runs', el));
  }
  function trace(x) {
    const gates = sortGates(x.gates);
    const steps = gates.flatMap(g => g.timeline);
    return `<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px"><b style="font-size:12.5px">Trace</b><span class="dim mono" style="font-size:11.5px">${esc(x.fund_id)}/${esc(x.run)}</span><span class="sp"></span>
      <a class="ghost-btn sm" href="#/fund/${encodeURIComponent(x.fund_id)}/screen/${x.run}">Open run<sl-icon name="arrow-right"></sl-icon></a></div>
      ${steps.length ? waterfall(steps, gates.map(g => g.gate)) : ''}
      <table class="t compact" style="margin-top:12px"><tr><th>Gate</th><th>Step</th><th>Model</th><th class="n">Latency</th><th class="n">Tokens in / out</th><th>Output</th><th>Result</th></tr>
      ${gates.map(g => {
        const rows = g.calls.length ? g.calls : [null];
        return rows.map((c, i) => `<tr>${i === 0 ? `<td rowspan="${rows.length}"><b style="font-weight:550">${esc(gateName(g.gate))}</b><div class="sub">${g.facts} facts kept${g.rejected ? `, ${g.rejected} off page` : ''}${g.not_found.length ? `, ${g.not_found.length} not found` : ''}</div></td>` : ''}
          ${c ? `<td><span class="tier" style="background:${STEP_COL[c.step] || 'var(--none)'}"></span>${esc(c.step)}</td><td class="mono" style="font-size:11.5px">${esc(model(c))}</td><td class="n tnum">${secs(c.seconds)}</td>
            <td class="n tnum">${c.input_tokens != null ? `${n(c.input_tokens)} / ${n(c.output_tokens)}` : '<span class="dim">not metered</span>'}</td><td>${outBtn(c)}</td>`
            : '<td colspan="5" class="dim">No model calls: gate not automated</td>'}
          ${i === 0 ? `<td rowspan="${rows.length}">${resultChip(g.result, g.review)}</td>` : ''}</tr>`).join('');
      }).join('')}</table>`;
  }

  // ---------- model calls ----------
  function drawCalls(calls) {
    const t = st.text.toLowerCase();
    const list = calls.filter(c => (!st.step || c.step === st.step) && (!st.status || (st.status === 'ok' ? c.ok : !c.ok)) && (!t || `${c.fund} ${c.gate} ${model(c)}`.toLowerCase().includes(t)));
    const box = $('#t-calls', el);
    if (!box.dataset.init) {
      box.dataset.init = 1;
      box.innerHTML = `<div class="bar"><div class="seg" id="cs"><button class="on" data-v="">All steps</button><button data-v="extract">Extraction</button><button data-v="judge">Judge</button></div>
        <div class="seg" id="cst"><button class="on" data-v="">Any status</button><button data-v="ok">Succeeded</button><button data-v="err">Failed</button></div>
        <sl-input id="cq" size="small" placeholder="Filter by fund, gate or model" clearable><sl-icon name="filter" slot="prefix"></sl-icon></sl-input><span class="sp"></span>
        <span class="dim" style="font-size:12px" id="cc"></span><button class="ghost-btn sm" id="ccsv"><sl-icon name="download"></sl-icon>CSV</button></div><div class="card"><div class="tbl-wrap" id="ct" style="max-height:620px"></div></div>`;
      $$('#cs button', box).forEach(b => b.addEventListener('click', () => { st.step = b.dataset.v; $$('#cs button', box).forEach(x => x.classList.toggle('on', x === b)); draw(); }));
      $$('#cst button', box).forEach(b => b.addEventListener('click', () => { st.status = b.dataset.v; $$('#cst button', box).forEach(x => x.classList.toggle('on', x === b)); draw(); }));
      $('#cq', box).addEventListener('sl-input', e => { st.text = e.target.value; draw(); });
      $('#ccsv', box).addEventListener('click', () => downloadCSV('model-calls.csv', box._list.map(({ output: _output, ...c }) => c)));
    }
    box._list = list;
    $('#cc', box).textContent = `${list.length} of ${calls.length} calls`;
    $('#ct', box).innerHTML = list.length ? `<table class="t compact"><tr><th>Time</th><th>Fund</th><th>Gate</th><th>Step</th><th>Model</th><th class="n">Latency</th><th class="n">In</th><th class="n">Out</th><th>Status</th><th>Output</th></tr>
      ${list.slice(0, 500).map(c => `<tr><td class="tnum dim">${fmtDT(new Date(c.ts * 1000))}</td><td>${esc(c.fund || '–')}</td><td>${esc(c.gate ? gateName(c.gate) : '–')}</td>
        <td><span class="tier" style="background:${STEP_COL[c.step] || 'var(--none)'}"></span>${esc(c.step || '–')}</td><td class="mono" style="font-size:11.5px">${esc(model(c))}</td><td class="n tnum">${secs(c.seconds)}</td>
        <td class="n tnum">${c.input_tokens != null ? n(c.input_tokens) : '–'}</td><td class="n tnum">${c.output_tokens != null ? n(c.output_tokens) : '–'}</td>
        <td>${c.ok ? '<span class="chip good"><sl-icon name="check-lg"></sl-icon>OK</span>' : `<span class="chip crit" title="${esc(c.error)}"><sl-icon name="x-lg"></sl-icon>Failed</span>`}${c.backfilled ? ' <span class="dim" style="font-size:11px">backfilled</span>' : ''}${c.attempts > 1 ? ` <span class="dim" style="font-size:11px">${c.attempts} tries</span>` : ''}</td>
        <td>${outBtn(c)}</td></tr>`).join('')}</table>` : empty('cpu', 'No calls match');
    bindOutputs(box);
  }

  // ---------- errors ----------
  function drawErrors(bad, failedJobs) {
    const evs = server.events.filter(e => e.level === 'error').reverse();
    $('#t-errors', el).innerHTML = bad.length + failedJobs.length + evs.length ? `
      ${failedJobs.length ? `<div class="card"><div class="hd"><h2 class="sec">Failed runs this session</h2></div><div class="bd flush"><table class="t">${failedJobs.map(j => `<tr><td class="tnum dim" style="width:160px">${fmtDT(new Date(j.started * 1000))}</td><td class="nm">${esc(j.fund)}</td><td class="mono dim">${esc(j.extractor)} → ${esc(j.judge)}</td><td class="wrap" style="color:#f08a8a">${esc(j.error)}</td></tr>`).join('')}</table></div></div>` : ''}
      ${bad.length ? `<div class="card"><div class="hd"><h2 class="sec">Failed model calls</h2></div><div class="bd flush"><table class="t">${bad.map(c => `<tr><td class="tnum dim" style="width:160px">${fmtDT(new Date(c.ts * 1000))}</td><td>${esc(c.fund || '–')}<div class="sub">${esc(c.gate ? gateName(c.gate) : '')} · ${esc(c.step || '')}</div></td><td class="mono dim">${esc(model(c))}</td><td class="n tnum">${secs(c.seconds)}</td><td class="wrap mono" style="font-size:11.5px;color:#f08a8a">${esc(c.error)}</td></tr>`).join('')}</table></div></div>` : ''}
      ${evs.length ? `<div class="card"><div class="hd"><h2 class="sec">Server errors</h2></div><div class="bd flush">${evs.map(e => `<div class="logrow error"><span class="ts">${fmtTime(e.t)}</span><span class="k">${esc(e.kind)}</span><span class="m">${esc(e.msg)}</span><span class="x"></span></div>`).join('')}</div></div>` : ''}`
      : `<div class="card">${empty('check2-circle', 'No errors', 'Failed model calls, failed runs and server errors appear here.')}</div>`;
  }

  // ---------- server events (secondary) ----------
  function drawServer() {
    const ev = server.events.filter(e => e.kind !== 'http').reverse();
    $('#t-server', el).innerHTML = `<div class="card"><div class="hd"><h2 class="sec">Server events</h2><span class="sec-sub">jobs, catalog builds, gate edits and errors since the server started · request log hidden</span></div>
      <div class="logs">${ev.length ? ev.map(e => `<div class="logrow ${e.level}"><span class="ts">${fmtTime(e.t)}</span><span class="k">${esc(e.kind)}</span><span class="m">${esc(e.msg)}</span><span class="x">${e.run ? esc(e.run) : ''}</span></div>`).join('') : empty('hdd-network', 'Nothing yet')}</div></div>`;
  }

  // ---------- outputs ----------
  const outBtn = c => c.output ? `<button class="cite" data-out="${esc(c.id || '')}" data-o="${esc(c.output)}" data-h="${esc(`${c.fund || ''} · ${c.gate ? gateName(c.gate) : ''} · ${c.step}`)}"><sl-icon name="braces"></sl-icon>${esc(summary(c))}</button>` : '<span class="dim">–</span>';
  function summary(c) {
    try {
      const o = JSON.parse(c.output);
      if (Array.isArray(o.facts)) return `${o.facts.length} facts`;
      if (o.facts_proposed != null) return `${o.facts_proposed} facts`;
      const ks = Object.keys(o); return `${ks.length} answer${ks.length === 1 ? '' : 's'}`;
    } catch { return 'view'; }
  }
  function bindOutputs(box) {
    $$('[data-o]', box).forEach(b => b.addEventListener('click', e => {
      e.stopPropagation();
      const d = $('#drawer'); d.classList.remove('wide'); d.label = 'Model output';
      let pretty = b.dataset.o; try { pretty = JSON.stringify(JSON.parse(pretty), null, 2); } catch { /* truncated output stays raw */ }
      d.innerHTML = `<div class="dim" style="margin-bottom:10px;font-size:12.5px">${esc(b.dataset.h)}</div><pre class="code" style="white-space:pre-wrap">${esc(pretty)}</pre>
        <p class="dim" style="font-size:12px">Outputs are logged up to 1,500 characters. The full brief and answers are in the run's gate files.</p>`;
      d.show();
    }));
  }

  async function tick() {
    try {
      const [a, s] = await Promise.all([api('agent'), api('logs')]);
      server = s;
      const now = JSON.stringify([a.runs.length, a.calls.length, a.jobs.map(j => [j.status, j.steps.length])]);
      data = a;
      if (now !== sig || a.jobs.some(j => j.status === 'running')) { sig = now; draw(); }
      if (st.tab === 'server' || !$('#t-server', el).innerHTML) drawServer();
    } catch (e) { $('#live', el).innerHTML = `<div class="card" style="margin-bottom:14px">${empty('wifi-off', 'Server unreachable', esc(e.message))}</div>`; }
  }
  await tick();
  draw();
  const timer = setInterval(tick, 3000);
  return () => clearInterval(timer);
}
