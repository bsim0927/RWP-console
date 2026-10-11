import {
  $, $$, api, cached, bust, esc, n, pct, ago, fmtDT, stampDate, gateName, sortGates, resultChip, flagChips, clockChip, day, fmtDate, resultTone, resultIcon, dispChip, dispTone, dispIcon, dispShort, dispNote,
  pipeChip, splitName, initials, waterfall, stepMatrix, lineChart, legend, hbars, markdown, openPreview, empty, skeleton, TIERS, TIER_COL, gateColor, GATE_ORDER, toast,
} from '../lib.js';
import { setCrumbs, screenDialog, jobs, onJobs } from '../app.js';
import { browser } from './files.js';
import { searchPanel } from './search.js';

const TABS = [['screen', 'Screen', 'funnel'], ['catalog', 'Catalog', 'journal-text'], ['files', 'Files', 'folder2-open'], ['search', 'Search', 'search'], ['history', 'History', 'clock-history'], ['report', 'Report', 'file-earmark-text']];

export async function render(el, r) {
  const id = r.parts[0];
  let tab = TABS.some(t => t[0] === r.parts[1]) ? r.parts[1] : 'screen';
  let runId = r.parts[2] || null;
  el.innerHTML = `<div class="page">${skeleton(3)}${skeleton(6)}</div>`;
  let funds = await cached('funds');
  let fund = funds.find(f => f.id === id);
  if (!fund) { el.innerHTML = `<div class="page">${empty('question-circle', 'Unknown fund', esc(id))}</div>`; return; }
  const s = splitName(fund.name), p = fund.pipeline || {}, it = fund.intake || {};
  const owner = it.owner || p.Owner;
  const dt = v => (v ? fmtDate(day(v)) : '–');
  setCrumbs([['Screening', '#/screening'], [fund.name]]);
  runId = runId || fund.runs[0] || null;
  const setHash = () => history.replaceState(null, '', `#/fund/${encodeURIComponent(id)}/${tab}${runId && ['screen', 'report'].includes(tab) ? '/' + runId : ''}`);

  el.innerHTML = `<div class="page">
    <div class="fund-hd"><div class="av">${esc(initials(s.manager))}</div>
      <div style="min-width:0"><div class="eyebrow">${esc(fund.stage || 'Data room')}</div><h1>${esc(s.manager)}</h1>
        <div class="meta"><span>${esc(p.Strategy || s.strategy || '')}</span>${pipeChip(p.Status)}${owner ? `<span class="chip ghost"><sl-icon name="person"></sl-icon>${esc(owner)}</span>` : ''}${clockChip(fund.clock)}
        ${fund.catalog ? `<span class="chip ghost"><sl-icon name="files"></sl-icon>${n(fund.catalog.files)} files · ${n(fund.catalog.pages)} pages</span>` : ''}</div></div>
      <div class="act"><a class="ghost-btn" href="#/files?path=${encodeURIComponent(fund.vpath)}"><sl-icon name="folder2-open"></sl-icon>Open folder</a>
        <button class="glow-btn" id="run"><sl-icon name="play-fill"></sl-icon>Run screen</button></div></div>
    <div class="card" style="margin-bottom:16px" id="intake"><div class="hd"><h2 class="sec">Intake</h2><span class="sec-sub">entered by the analyst when the fund is filed</span><span class="sp"></span>
      <button class="ghost-btn sm" id="intake-edit"><sl-icon name="pencil"></sl-icon>Edit intake</button></div><div class="facts3 rows">
      <div><div class="k">Referred by</div><div class="v">${esc(it.referred_by || '–')}</div></div>
      <div><div class="k">Owner</div><div class="v">${esc(it.owner || '–')}</div></div>
      <div><div class="k">Share class screened</div><div class="v">${esc(it.share_class || 'Cheapest class open to individuals')}</div></div>
      <div><div class="k">Filed</div><div class="v">${dt(it.filed_on)}</div></div>
      <div><div class="k">Screen due</div><div class="v">${fund.clock ? dt(fund.clock.due) : '–'}</div></div>
      <div><div class="k">Sponsor deadline</div><div class="v">${dt(it.sponsor_deadline)}</div></div></div></div>
    ${fund.pipeline ? `<div class="card" style="margin-bottom:16px"><div class="facts3">
      <div><div class="k">${p['Last action'] != null ? 'Last action' : 'Material on file'}</div><div class="v">${esc(p['Last action'] ?? p['Material on file'] ?? '–')}</div></div>
      <div style="grid-column:span 2"><div class="k">Next action</div><div class="v">${esc(p['Next action'] || '–')}</div></div></div></div>` : ''}
    <sl-tab-group class="tabs" id="tabs">${TABS.map(([k, label, icon]) => `<sl-tab slot="nav" panel="${k}" ${k === tab ? 'active' : ''}><sl-icon name="${icon}" style="margin-right:7px"></sl-icon>${label}${k === 'history' && fund.runs.length ? `<span class="dim" style="margin-left:6px">${fund.runs.length}</span>` : ''}</sl-tab>`).join('')}
      ${TABS.map(([k]) => `<sl-tab-panel name="${k}"><div id="p-${k}"></div></sl-tab-panel>`).join('')}</sl-tab-group></div>`;

  const done = new Set();
  const show = async (k, force) => {
    tab = k; setHash();
    if (done.has(k) && !force) return;
    done.add(k);
    const box = $('#p-' + k, el);
    if (k === 'screen') return screenTab(box);
    if (k === 'catalog') return catalogTab(box, fund);
    if (k === 'files') return browser(box, { root: fund.vpath, path: fund.vpath, embedded: true });
    if (k === 'search') return searchPanel(box, { fund: fund.id });
    if (k === 'history') return historyTab(box);
    if (k === 'report') return reportTab(box);
  };
  $('#tabs', el).addEventListener('sl-tab-show', e => show(e.detail.name));
  $('#run', el).addEventListener('click', () => screenDialog(fund));
  $('#intake-edit', el).addEventListener('click', () => intakeDialog(fund, async () => { bust('funds'); await render(el, r); }));

  // ---------- screen ----------
  let data = null;
  async function screenTab(box) {
    const job = jobs.get(id);
    const running = job?.state.status === 'running';
    if (!fund.runs.length && !running) {
      box.innerHTML = `<div class="card">${empty('funnel', 'Not screened yet', `Run the five gates against this data room.<br><br><button class="glow-btn" data-go><sl-icon name="play-fill"></sl-icon>Run screen</button>`)}</div>`;
      $('[data-go]', box)?.addEventListener('click', () => screenDialog(fund));
      return;
    }
    if (runId && (!data || data.summary.run !== runId)) {
      box.innerHTML = skeleton(6);
      data = await api(`run/${encodeURIComponent(id)}/${runId}`);
    }
    const sm = data?.summary;
    const gates = data ? sortGates(data.gates) : [];
    const facts = gates.reduce((a, g) => a + (g.brief?.facts?.length || 0), 0);
    const rej = gates.reduce((a, g) => a + (g.rejected?.length || 0), 0);
    const tok = gates.reduce((a, g) => a + (g.answers?._meta?.usage?.input_tokens || 0) + (g.answers?._meta?.usage?.output_tokens || 0), 0);
    const steps = gates.flatMap(g => g.timeline || []);
    const tone = dispTone(sm?.disposition);
    box.innerHTML = `
      <div id="live"></div>
      ${sm ? `<div class="bar">
        <sl-select id="runsel" size="small" value="${esc(runId)}" style="min-width:300px">${fund.runs.map(x => `<sl-option value="${x}">${fmtDT(stampDate(x))}${x === fund.runs[0] ? ' · latest' : ''}</sl-option>`).join('')}</sl-select>
        <span class="chip ghost mono">${esc(sm.extractor)} → ${esc(sm.judge)}</span><span class="sp"></span>
        <a class="ghost-btn sm" href="#/fund/${encodeURIComponent(id)}/report/${runId}"><sl-icon name="file-earmark-text"></sl-icon>Run report</a></div>
      <div class="verdict ${tone}"><div class="ic"><sl-icon name="${dispIcon(sm.disposition)}"></sl-icon></div>
        <div><div class="t">${esc(dispShort(sm.disposition))}</div><div class="s">${esc(dispNote(sm.disposition))} · run ${ago(stampDate(sm.run))}</div></div>
        <div class="r"><div class="m"><b>${facts}</b><span>facts verified</span></div><div class="m"><b>${rej}</b><span>quotes off page</span></div>
          <div class="m"><b>${tok ? n(tok) : '–'}</b><span>judge tokens</span></div><div class="m"><b>${sm.seconds != null ? sm.seconds + 's' : '–'}</b><span>duration</span></div></div></div>
      <div class="flow">${gates.map((g, i) => {
        const t = resultTone(g.result), c = g.min_confidence;
        return `<button class="gcard ${t}" data-g="${esc(g.gate)}"><div class="n">Gate ${GATE_ORDER.indexOf(g.gate) + 1 || i + 1}</div><div class="t">${esc(gateName(g.gate))}</div>${resultChip(g.result, g.review)}${g.flags?.length ? `<div class="flags">${flagChips(g.flags)}</div>` : ''}
          ${c != null ? `<div class="conf"><span class="meter"><span style="width:${c * 100}%"></span><i style="left:75%"></i></span><span class="tnum">${pct(c)}</span></div>` : `<div class="conf">${esc(g.note || 'Not automated')}</div>`}
          ${g.brief ? `<div class="ev"><span>${g.brief.facts.length} facts</span><span>${g.brief.not_found.length} not found</span>${g.rejected?.length ? `<span>${g.rejected.length} off page</span>` : ''}</div>` : ''}</button>`;
      }).join('')}</div>
      <div class="legend" style="margin:8px 0 16px"><span class="dim">Bar shows the lowest confidence among decisive judge answers. The tick marks the 0.75 review threshold. Click a gate for its evidence.</span></div>
      <div class="card"><div class="hd"><h2 class="sec">Run timeline</h2><span class="sec-sub">${sm.seconds ?? ''}s total</span><span class="sp"></span>
        <div class="seg" id="tlseg"><button class="on" data-v="w">Timeline</button><button data-v="m">Step table</button></div></div>
        <div class="bd" id="tl">${steps.length ? waterfall(steps, gates.map(g => g.gate)) : '<span class="dim">This run predates step timing.</span>'}</div></div>` : ''}`;
    $('#runsel', box)?.addEventListener('sl-change', e => { runId = e.target.value; setHash(); screenTab(box); });
    $$('.gcard', box).forEach(b => b.addEventListener('click', () => gateDrawer(gates.find(g => g.gate === b.dataset.g))));
    $$('#tlseg button', box).forEach(b => b.addEventListener('click', () => {
      $$('#tlseg button', box).forEach(x => x.classList.toggle('on', x === b));
      $('#tl', box).innerHTML = b.dataset.v === 'w' ? waterfall(steps, gates.map(g => g.gate)) : stepMatrix(steps, gates.map(g => g.gate));
    }));
    if (running) drawLive();
  }

  function drawLive() {
    const box = $('#p-screen #live', el);
    const j = jobs.get(id);
    if (!box || !j) return;
    if (j.state.status !== 'running') { box.innerHTML = ''; return; }
    const st = j.state, total = Math.max(1, (st.gates?.length || 5) * 5);
    const fin = (st.steps || []).filter(e => e.end != null && e.gate !== 'catalog').length;
    box.innerHTML = `<div class="card" style="margin-bottom:14px;border-color:var(--accent-line)"><div class="hd"><span class="pulse"></span><h2 class="sec">Screen running</h2><span class="sec-sub tnum">${(st.elapsed || 0).toFixed?.(1) ?? st.elapsed}s · ${fin} steps finished</span></div>
      <div class="bd"><sl-progress-bar value="${Math.min(100, Math.round(100 * fin / total))}" style="--height:5px;--indicator-color:var(--accent);margin-bottom:14px"></sl-progress-bar>
      ${st.gates?.length ? waterfall(st.steps, st.gates, st.elapsed, true) + '<div style="margin-top:12px"></div>' + stepMatrix(st.steps, st.gates, st.elapsed) : '<div class="shimmer sk"></div>'}</div></div>`;
  }

  function gateDrawer(g) {
    const d = $('#drawer');
    d.classList.remove('wide');
    d.label = `${gateName(g.gate)}`;
    const room = data.room_path;
    const reopen = () => gateDrawer(g);
    if (!g.brief) {
      d.innerHTML = `${resultChip(g.result)}<p class="muted">${esc(g.note || 'This gate is not automated in the prototype.')}</p>`;
      return d.show();
    }
    const b = g.brief;
    const cite = f => `<button class="cite" data-file="${esc(f.file)}" data-page="${f.page}" data-quote="${esc(f.quote)}"><sl-icon name="file-earmark-pdf"></sl-icon>${esc(f.file.split('/').pop())} · p.${f.page}</button>${f.match === 'reflowed' ? '<div class="dim" style="font-size:11px">matched across layout</div>' : ''}`;
    const answers = Object.entries(g.answers || {}).filter(([k]) => k !== '_meta');
    const meta = g.answers?._meta;
    d.innerHTML = `<div class="bar">${resultChip(g.result, g.review)}<span class="sp"></span><span class="dim mono">gate v${esc(g.gate_version)} · brief ${esc(g.brief_sha || '')}</span></div>
      ${g.flags?.length ? `<div class="flags" style="margin-bottom:14px">${flagChips(g.flags)}</div>` : ''}
      ${g.review ? `<sl-alert variant="warning" open style="margin-bottom:14px"><sl-icon slot="icon" name="person-check"></sl-icon>Low confidence on <b>${esc((g.low_confidence || []).join(', '))}</b>. An analyst confirms this gate.</sl-alert>` : ''}
      <div class="card"><div class="hd"><h2 class="sec">Judge answers</h2><span class="sec-sub">${esc(g.judge)}${meta ? ` · ${esc(meta.model)} · ${n(meta.usage?.input_tokens)} in / ${n(meta.usage?.output_tokens)} out` : ''}</span></div><div class="bd">
        ${(g.questions || []).map(qq => `<div style="margin-bottom:12px"><div style="margin-bottom:4px">${esc(qq.q)} <span class="dim mono">${esc(qq.id)} · ${esc(qq.type)}</span></div>
          ${Object.entries(g.answers?.[qq.id] || {}).map(([k, v]) => `<div class="prob"><span class="lab">${esc(k)}</span><span class="bar"><span style="width:${(v * 100).toFixed(0)}%"></span></span><span class="pct">${(v * 100).toFixed(0)}%</span></div>`).join('')}</div>`).join('') || (answers.length ? '' : '<span class="dim">No questions.</span>')}
        <dl class="kv" style="margin-top:10px"><dt>Derived result</dt><dd><b>${esc(g.result)}</b></dd>
        ${Object.entries(g.env_for_rules || {}).map(([k, v]) => `<dt class="mono">${esc(k)}</dt><dd class="mono">${v == null ? '–' : esc(typeof v === 'number' ? +v.toFixed(3) : v)}</dd>`).join('')}</dl></div></div>
      <div class="card"><div class="hd"><h2 class="sec">Facts extracted</h2><span class="sec-sub">${b.facts.length} verified on the cited page</span></div><div class="bd flush">
        ${b.facts.length ? `<table class="t"><tr><th>Field</th><th>Value and quote</th><th>Source</th></tr>${b.facts.map(f => `<tr><td class="mono" style="white-space:nowrap">${esc(f.field)}</td>
          <td class="wrap"><div style="margin-bottom:5px">${esc(f.value || '')}</div><div class="quote">“${esc(f.quote)}”</div></td><td style="min-width:180px">${cite(f)}</td></tr>`).join('')}</table>` : '<div class="empty" style="padding:20px">No facts verified.</div>'}
        ${b.not_found.length ? `<div style="padding:10px 16px;display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="dim" style="font-size:12px">Not found:</span>${b.not_found.map(x => `<span class="chip warn"><sl-icon name="question-circle"></sl-icon>${esc(x)}</span>`).join('')}</div>` : ''}
        ${b.checks?.total_pct != null ? `<div style="padding:4px 16px 12px;font-size:12.5px" class="muted">Code check, counted fee layers summed: <b style="color:var(--ink)">${b.checks.total_pct}%</b></div>` : ''}
        ${Object.entries(b.checks?.fee_conflicts || {}).map(([k, v]) => `<div style="padding:4px 16px 12px;font-size:12.5px" class="muted">Documents disagree on <span class="mono">${esc(k)}</span>: <b style="color:var(--ink)">${v.map(x => esc(x) + '%').join(', ')}</b></div>`).join('')}</div></div>
      ${g.rejected?.length ? `<div class="card"><div class="hd"><h2 class="sec">Quotes not found on the cited page</h2><span class="sec-sub">${g.rejected.length} dropped before judging</span></div><div class="bd flush"><table class="t">
        ${g.rejected.map(f => `<tr><td class="mono">${esc(f.field)}</td><td class="wrap"><div class="quote">“${esc(f.quote)}”</div></td><td>${cite(f)}</td></tr>`).join('')}</table></div></div>` : ''}
      ${g.routing?.length ? `<div class="card"><div class="hd"><h2 class="sec">What the extractor read</h2><span class="sec-sub">${g.pages_offered?.length || 0} pages offered</span></div><div class="bd flush"><table class="t compact">
        <tr><th>Document</th><th>Section</th><th>Pages</th><th>Why</th></tr>${g.routing.map(x => `<tr><td>${esc(x.doc)}<div class="sub">${esc(x.doc_type || '')}</div></td><td>${esc(x.section)}</td>
        <td class="mono">${x.pages?.length ? `p.${x.pages[0]}${x.pages[1] > x.pages[0] ? '–' + x.pages[1] : ''}` : ''}${x.truncated ? ' <span class="dim">(cut)</span>' : ''}</td><td class="dim">${esc(x.why)}</td></tr>`).join('')}</table></div></div>` : ''}`;
    $$('.cite', d).forEach(c => c.addEventListener('click', () => openPreview(room + '/' + c.dataset.file, { page: +c.dataset.page, quote: c.dataset.quote, back: { label: gateName(g.gate), fn: reopen } })));
    d.show();
  }

  // ---------- history ----------
  async function historyTab(box) {
    if (!fund.runs.length) { box.innerHTML = `<div class="card">${empty('clock-history', 'No runs yet')}</div>`; return; }
    box.innerHTML = skeleton(5);
    const rows = await api('history/' + encodeURIComponent(id));
    const ids = GATE_ORDER.filter(g => rows.some(r => r.gates[g]?.min_confidence != null));
    const xs = rows.map((r, i) => `#${i + 1}`);
    const series = ids.map(g => ({ label: gateName(g), color: gateColor(g), pts: rows.map((r, i) => [i, r.gates[g]?.min_confidence, `<b>${esc(gateName(g))}</b> · run #${i + 1}<br>${esc(r.gates[g]?.result || '')} · ${pct(r.gates[g]?.min_confidence)}<br><span class=dim>${esc(r.judge)} judge · ${fmtDT(stampDate(r.run))}</span>`]).filter(p => p[1] != null) }));
    box.innerHTML = `<div class="card"><div class="hd"><h2 class="sec">Decisive confidence across runs</h2><span class="sec-sub">lowest decisive-answer confidence per gate · dashed line is the 0.75 review threshold</span></div>
      <div class="bd">${ids.length ? lineChart(series, xs) + legend([...series.map(se => [se.label, se.color, true]), ['Review threshold 0.75', 'var(--ink2)', true]]) : '<span class="dim">Older runs carry no confidence values.</span>'}</div></div>
      <div class="card"><div class="hd"><h2 class="sec">Runs</h2></div><div class="bd flush"><table class="t"><tr><th>#</th><th>When</th><th>Extractor → judge</th>${GATE_ORDER.map(g => `<th>${esc(gateName(g))}</th>`).join('')}<th>Disposition</th><th class="n">Time</th></tr>
      ${rows.map((r, i) => ({ r, i })).reverse().map(({ r, i }) => `<tr class="click" data-run="${r.run}"><td class="dim">${i + 1}</td><td class="tnum">${fmtDT(stampDate(r.run))}</td><td class="mono dim">${esc(r.extractor)} → ${esc(r.judge)}</td>
        ${GATE_ORDER.map(g => `<td>${r.gates[g] ? `<span class="chip ${resultTone(r.gates[g].result)}" style="padding:0 6px"><sl-icon name="${resultIcon(r.gates[g].result)}"></sl-icon>${r.gates[g].min_confidence != null ? pct(r.gates[g].min_confidence) : ''}</span>` : ''}</td>`).join('')}
        <td>${dispChip(r.disposition)}</td><td class="n dim tnum">${r.seconds != null ? r.seconds + 's' : ''}</td></tr>`).join('')}</table></div></div>`;
    $$('tr[data-run]', box).forEach(tr => tr.addEventListener('click', () => { runId = tr.dataset.run; done.delete('screen'); done.delete('report'); $('#tabs', el).show('screen'); }));
  }

  // ---------- report ----------
  async function reportTab(box) {
    if (!runId) { box.innerHTML = `<div class="card">${empty('file-earmark-text', 'No run report', 'Reports are written when a screen runs.')}</div>`; return; }
    if (!data || data.summary.run !== runId) data = await api(`run/${encodeURIComponent(id)}/${runId}`);
    box.innerHTML = `<div class="bar"><span class="chip ghost">Run ${fmtDT(stampDate(runId))}</span><span class="dim mono" style="font-size:11.5px">runs/${esc(id)}/${esc(runId)}/summary.md</span><span class="sp"></span>
      <button class="ghost-btn sm" id="cp"><sl-icon name="clipboard"></sl-icon>Copy markdown</button></div><div class="card"><div class="bd">${markdown(data.markdown || '')}</div></div>`;
    $('#cp', box).addEventListener('click', () => navigator.clipboard.writeText(data.markdown).then(() => toast('Markdown copied', 'good')));
  }

  show(tab);

  // Live job updates and refresh when a run lands.
  let wasRunning = jobs.get(id)?.state.status === 'running';
  return onJobs(async () => {
    const j = jobs.get(id);
    const running = j?.state.status === 'running';
    if (running) {
      if (!wasRunning && tab === 'screen') { done.delete('screen'); await screenTab($('#p-screen', el)); }
      drawLive();
    } else if (wasRunning) {
      bust('funds');
      funds = await cached('funds');
      fund = funds.find(f => f.id === id) || fund;
      if (j?.state.run) runId = j.state.run;
      data = null; done.clear();
      show(tab, true);
    }
    wasRunning = running;
  });
}

// ---------- catalog (also used by the catalogs page) ----------
export async function catalogTab(box, fund, rebuild) {
  box.innerHTML = rebuild ? `<div class="card">${empty('arrow-repeat', 'Rebuilding catalog', 'Reading every document in the data room.')}</div>` : skeleton(8);
  let c;
  try {
    if (rebuild) { await api(`catalog/${encodeURIComponent(fund.id)}/rebuild`, { method: 'POST' }); bust('funds'); toast('Catalog rebuilt', 'good'); }
    c = await api('catalog/' + encodeURIComponent(fund.id));
  } catch (e) { box.innerHTML = `<div class="card">${empty('exclamation-octagon', 'Catalog failed', `<span class="mono">${esc(e.message)}</span>`)}</div>`; return; }
  c.docs.forEach(d => { d.sections = d.sections || []; d.structure = d.structure || { method: 'catalog predates the section index; rebuild', coverage: 0 }; });
  const S = c.summary, D = c.docs, byId = Object.fromEntries(D.map(d => [d.doc_id, d]));
  const st = { tier: 'all', all: true, text: '', open: new Set() };
  const funnel = [
    { label: 'All pages', segs: [{ v: S.pages, color: 'var(--ink4)', tip: `${n(S.pages)} pages in ${S.files} files` }] },
    { label: 'Exact duplicates', segs: [{ v: S.exact_duplicates.pages, color: 'var(--crit)', tip: `${S.exact_duplicates.pages} pages in ${S.exact_duplicates.files} duplicate files` }] },
    { label: 'Superseded versions', segs: [{ v: S.superseded.pages, color: 'var(--warn)', tip: `${S.superseded.pages} pages in ${S.superseded.files} superseded files` }] },
    { label: 'Canonical, by tier', segs: TIERS.filter(t => S.by_tier[t]).map(t => ({ v: S.by_tier[t].pages, color: TIER_COL[t], tip: `<b>${t}</b><br>${S.by_tier[t].files} files · ${n(S.by_tier[t].pages)} pages` })) },
  ];
  box.innerHTML = `<div class="kpis">
      <div class="kpi"><div class="l"><sl-icon name="files"></sl-icon>Pages</div><div class="v">${n(S.pages)}</div><div class="f">in ${S.files} files</div></div>
      <div class="kpi hl"><div class="l"><sl-icon name="bullseye"></sl-icon>Core pages for the gates</div><div class="v">${n(S.core_pages)}</div><div class="f">${pct(S.core_pages / Math.max(1, S.pages))} of all pages</div></div>
      <div class="kpi"><div class="l"><sl-icon name="check2-square"></sl-icon>Canonical</div><div class="v">${n(S.canonical.pages)}</div><div class="f">${S.canonical.files} files</div></div>
      <div class="kpi"><div class="l"><sl-icon name="copy"></sl-icon>Duplicates</div><div class="v">${n(S.exact_duplicates.pages)}</div><div class="f">${S.exact_duplicates.files} files</div></div>
      <div class="kpi"><div class="l"><sl-icon name="clock-history"></sl-icon>Superseded</div><div class="v">${n(S.superseded.pages)}</div><div class="f">${S.superseded.files} files</div></div>
      <div class="kpi"><div class="l"><sl-icon name="list-nested"></sl-icon>Sections</div><div class="v">${n(S.sections ?? 0)}</div><div class="f">${S.with_toc ?? 0} ToC · ${S.with_bookmarks} bookmarks · ${S.with_terms ?? 0} term sheets</div></div></div>
    <div class="card" style="margin-bottom:14px"><div class="hd"><h2 class="sec">Where the pages go</h2><span class="sec-sub">types from ${S.type_sources.filename} filenames, ${S.type_sources.folder} folders, ${S.type_sources.none} unknown · ${S.scan_pages} scan-like pages</span></div>
      <div class="bd">${hbars(funnel, { total: S.pages })}${legend(TIERS.filter(t => S.by_tier[t]).map(t => [`${t} · ${S.by_tier[t].files} files`, TIER_COL[t]]))}</div></div>
    <div class="bar"><div class="seg" id="tiers"><button class="on" data-t="all">All</button>${TIERS.filter(t => S.by_tier[t]).map(t => `<button data-t="${t}"><span class="tier" style="background:${TIER_COL[t]}"></span>${t}<span class="c">${S.by_tier[t].files}</span></button>`).join('')}</div>
      <sl-input id="ct" size="small" placeholder="Filter documents" clearable><sl-icon name="filter" slot="prefix"></sl-icon></sl-input>
      <sl-switch id="ca" size="small" checked>Show duplicates and superseded</sl-switch><span class="sp"></span>
      <button class="ghost-btn sm" id="rb"><sl-icon name="arrow-repeat"></sl-icon>Rebuild catalog</button></div>
    <div class="card"><div class="tbl-wrap" id="ctbl"></div></div>`;
  const draw = () => {
    const t = st.text.toLowerCase();
    const rows = D.filter(d => (st.tier === 'all' || d.tier === st.tier) && (st.all || d.canonical) && (!t || (d.name + d.folder + d.doc_type).toLowerCase().includes(t)))
      .sort((a, b) => TIERS.indexOf(a.tier) - TIERS.indexOf(b.tier) || a.doc_type.localeCompare(b.doc_type) || a.name.localeCompare(b.name));
    $('#ctbl', box).innerHTML = rows.length ? `<table class="t"><tr><th>Document</th><th>Type</th><th>Status</th><th>As of</th><th class="n">Pages</th><th>Relation</th><th>Structure</th></tr>${rows.map(d => {
      let rel = '<span class="dim">–</span>';
      if (d.duplicate_of) rel = `<span class="chip crit"><sl-icon name="copy"></sl-icon>Duplicate</span><div class="sub">of ${esc(byId[d.duplicate_of]?.folder || 'root')}/…</div>`;
      else if (d.superseded_by) rel = `<span class="chip warn"><sl-icon name="clock-history"></sl-icon>Superseded</span><div class="sub">by ${esc(byId[d.superseded_by]?.name || '')}</div>`;
      else if (d.version_group && (d.group_reason || '').includes('review')) rel = `<span class="chip serious"><sl-icon name="question-diamond"></sl-icon>Which is current?</span>`;
      else if (d.version_group) rel = `<span class="chip good"><sl-icon name="check-lg"></sl-icon>Current version</span><div class="sub">${esc(d.group_reason || '')}</div>`;
      else if (d.series) rel = '<span class="chip ghost">Series</span>';
      const open = st.open.has(d.doc_id);
      return `<tr class="${d.sections.length ? 'click' : ''} ${d.canonical ? '' : 'dimrow'}" data-doc="${d.doc_id}">
        <td><div style="display:flex;align-items:flex-start;gap:4px"><span class="tier" style="background:${TIER_COL[d.tier] || 'var(--none)'};margin-top:6px" title="${esc(d.tier)}"></span>
          <div><button class="cite" style="color:var(--ink);font:550 13px var(--sans)" data-path="${esc(d.path)}">${esc(d.name)}</button><div class="sub">${esc(d.folder || '(root)')}</div></div></div></td>
        <td>${esc(d.doc_type)}<div class="sub">${esc(d.type_source)}</div></td><td>${esc(d.status)}</td>
        <td class="tnum">${esc(d.as_of || '–')}${d.date_source && d.date_source !== 'filename' ? `<div class="sub">${esc(d.date_source)}</div>` : ''}</td>
        <td class="n tnum">${d.pages}${d.scan_pages ? `<div class="sub">${d.scan_pages} scan</div>` : ''}</td><td>${rel}</td>
        <td>${d.sections.length ? `<span class="dim"><sl-icon name="${open ? 'chevron-down' : 'chevron-right'}"></sl-icon> ${d.sections.length} sections · ${Math.round(100 * d.structure.coverage)}%</span><div class="sub">${esc(d.structure.method)}</div>` : '<span class="dim">–</span>'}</td></tr>
        ${open ? `<tr><td colspan="7" style="background:var(--bg)"><div class="secs">${d.sections.slice(0, 300).map(x => `<div style="padding-left:${(x.level - 1) * 14}px"><button class="cite" style="color:var(--ink2);font:12px var(--sans)" data-path="${esc(d.path)}" data-page="${x.start}">${esc(x.title)}</button> <span class="dim mono" style="font-size:10.5px">p.${x.start}${x.end > x.start ? '–' + x.end : ''}${x.located && x.located !== 'body heading' ? ' est.' : ''}</span></div>`).join('')}</div></td></tr>` : ''}`;
    }).join('')}</table>` : empty('filter-circle', 'No documents match');
    $$('tr[data-doc]', box).forEach(tr => tr.addEventListener('click', e => {
      if (e.target.closest('.cite')) return;
      const k = tr.dataset.doc; if (!byId[k].sections.length) return;
      st.open.has(k) ? st.open.delete(k) : st.open.add(k); draw();
    }));
    $$('.cite[data-path]', box).forEach(b => b.addEventListener('click', () => openPreview(c.room_path + '/' + b.dataset.path, { page: +b.dataset.page || undefined })));
  };
  draw();
  $$('#tiers button', box).forEach(b => b.addEventListener('click', () => { st.tier = b.dataset.t; $$('#tiers button', box).forEach(x => x.classList.toggle('on', x === b)); draw(); }));
  $('#ct', box).addEventListener('sl-input', e => { st.text = e.target.value; draw(); });
  $('#ca', box).addEventListener('sl-change', e => { st.all = e.target.checked; draw(); });
  $('#rb', box).addEventListener('click', () => catalogTab(box, fund, true));
}

// Intake (decisions F2, B5, G4): who referred the fund, who owns it, when it was filed, the sponsor's
// deadline and the share class RWP screens.
function intakeDialog(fund, done) {
  const it = fund.intake || {};
  const fields = [['referred_by', 'Referred by', 'text'], ['owner', 'Owner', 'text'], ['share_class', 'Share class to screen', 'text', 'Blank screens the cheapest class open to individuals'],
    ['filed_on', 'Filed', 'date', 'Starts the five-business-day screen clock'], ['sponsor_deadline', 'Sponsor deadline', 'date']];
  const d = document.createElement('sl-dialog');
  d.label = 'Intake';
  d.innerHTML = `<div style="display:flex;flex-direction:column;gap:12px">${fields.map(([k, label, type, help]) => `<sl-input size="small" data-k="${k}" type="${type}" label="${label}" value="${esc(it[k] || '')}" ${help ? `help-text="${esc(help)}"` : ''}></sl-input>`).join('')}</div>
    <div slot="footer" style="display:flex;gap:8px;justify-content:flex-end"><button class="ghost-btn" data-x>Cancel</button><button class="glow-btn" data-go><sl-icon name="check-lg"></sl-icon>Save intake</button></div>`;
  document.body.append(d);
  d.addEventListener('sl-after-hide', e => { if (e.target === d) d.remove(); });
  d.querySelector('[data-x]').onclick = () => d.hide();
  d.querySelector('[data-go]').onclick = async () => {
    const body = Object.fromEntries($$('sl-input[data-k]', d).map(i => [i.dataset.k, i.value]));
    try { await api('intake/' + encodeURIComponent(fund.id), { method: 'PUT', body: JSON.stringify(body) }); d.hide(); toast('Intake saved', 'good'); done(); }
    catch (e) { toast(esc(e.message), 'crit'); }
  };
  customElements.whenDefined('sl-dialog').then(() => requestAnimationFrame(() => d.show()));
}
