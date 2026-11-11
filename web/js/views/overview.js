import { cached, esc, n, pct, ago, stampDate, gateStrip, dispChip, gateName, hbars, legend, PIPE_ORDER, pipeChip, splitName, empty, skeleton, GATE_ORDER, resultTone, RESULT_KEYS, toneVar } from '../lib.js';
import { setCrumbs } from '../app.js';

export async function render(el) {
  setCrumbs([['Overview']]);
  el.innerHTML = `<div class="page">${skeleton(3)}${skeleton(8)}</div>`;
  const [funds, runs] = await Promise.all([cached('funds'), cached('runs')]);
  const screened = funds.filter(f => f.latest);
  const review = screened.filter(f => f.latest.flags?.any_review);
  const failed = screened.filter(f => f.latest.flags?.any_fail);
  const catd = funds.filter(f => f.catalog);
  const pages = catd.reduce((a, f) => a + f.catalog.pages, 0);
  const pastIntake = funds.filter(f => !['Not reviewed', 'Triaged'].includes(f.status?.status)).length;
  const lastRun = runs[0];

  // Gate outcome mix across the latest screen of each fund.
  const mix = GATE_ORDER.map(g => {
    const c = Object.fromEntries(RESULT_KEYS.map(k => [k, 0]));
    screened.forEach(f => { const r = f.latest.gates[g]?.result; if (r) c[r] = (c[r] || 0) + 1; });
    return { label: gateName(g), segs: RESULT_KEYS.map(k => ({ v: c[k], color: toneVar(resultTone(k)), tip: `<b>${esc(gateName(g))}</b><br>${esc(k)}: ${c[k]} of ${screened.length}` })), value: `${c.Pass}/${screened.length}` };
  });

  // Pipeline status counts, in process order.
  const byStatus = {};
  funds.forEach(f => { const s = f.status?.status || 'Not reviewed'; byStatus[s] = (byStatus[s] || 0) + 1; });
  const statuses = [...PIPE_ORDER.filter(s => byStatus[s]), ...Object.keys(byStatus).filter(s => !PIPE_ORDER.includes(s))];

  // Intake aging from each room's newest dated document.
  const today = new Date();
  const buckets = [['Under 2 weeks', 0, 14], ['2 to 4 weeks', 14, 30], ['1 to 2 months', 30, 60], ['Over 2 months', 60, 1e9]];
  const ages = funds.map(f => f.material_on).filter(Boolean).map(d => (today.getTime() - new Date(d + 'T00:00:00').getTime()) / 864e5);
  const aging = buckets.map(([label, lo, hi]) => { const c = ages.filter(a => a >= lo && a < hi).length; return { label, segs: [{ v: c, color: 'var(--c1)', tip: `${label}: ${c} data rooms` }], value: n(c) }; });

  const active = funds.filter(f => ['Under review', 'Deep DD', 'IC ready'].includes(f.status?.status));
  const attention = [
    ...review.map(f => ({ f, why: 'Analyst review', detail: Object.entries(f.latest.gates).filter(([, g]) => g.review).map(([k]) => gateName(k)).join(', '), tone: 'warn', icon: 'person-check' })),
    ...failed.filter(f => !f.latest.flags.any_review).map(f => ({ f, why: 'Gate not met', detail: Object.entries(f.latest.gates).filter(([, g]) => g.result === 'Fail').map(([k]) => gateName(k)).join(', '), tone: 'crit', icon: 'x-octagon' })),
  ];

  el.innerHTML = `<div class="page">
  <div class="ph"><div><h1>Overview</h1>
    <p>Where every data room stands against the five screening gates, and what needs an analyst next.</p></div>
    <div class="act"><a class="ghost-btn" href="#/analytics"><sl-icon name="bar-chart-line"></sl-icon>Analytics</a><a class="glow-btn" href="#/screening"><sl-icon name="funnel"></sl-icon>Screening queue</a></div></div>

  <div class="kpis">
    <a class="kpi" href="#/screening"><div class="l"><sl-icon name="folder2"></sl-icon>Indexed data rooms</div><div class="v">${funds.length}</div><div class="f">${pastIntake} past intake</div></a>
    <a class="kpi hl" href="#/screening?f=screened"><div class="l"><sl-icon name="funnel"></sl-icon>Screened</div><div class="v">${screened.length}<small>/ ${funds.length}</small></div><div class="f">${pct(screened.length / Math.max(1, funds.length))} coverage of indexed rooms</div></a>
    <a class="kpi" href="#/screening?f=review"><div class="l"><sl-icon name="person-check"></sl-icon>Awaiting analyst</div><div class="v">${review.length}</div><div class="f">Low judge confidence on a decisive question</div></a>
    <a class="kpi" href="#/screening?f=fail"><div class="l"><sl-icon name="x-octagon"></sl-icon>With a gate not met</div><div class="v">${failed.length}</div><div class="f">Latest screen per fund</div></a>
    <a class="kpi" href="#/logs?tab=runs"><div class="l"><sl-icon name="clock-history"></sl-icon>Runs logged</div><div class="v">${runs.length}</div><div class="f">Last ${lastRun ? ago(stampDate(lastRun.run)) : 'never'}</div></a>
    <a class="kpi" href="#/catalogs"><div class="l"><sl-icon name="journal-text"></sl-icon>Pages catalogued</div><div class="v">${n(pages)}</div><div class="f">${catd.length} of ${funds.length} rooms catalogued</div></a>
  </div>

  <div class="grid g-main">
    <div class="card"><div class="hd"><h2 class="sec">Latest screen, gate by gate</h2><span class="sec-sub">${screened.length} funds</span><span class="sp"></span><a class="ghost-btn sm" href="#/screening">All funds<sl-icon name="arrow-right"></sl-icon></a></div>
      <div class="bd flush">${screened.length ? `<div class="tbl-wrap"><table class="t">
        <tr><th>Fund</th><th>Gates</th><th>Disposition</th><th class="n">Run</th></tr>
        ${screened.sort((a, b) => b.latest.run.localeCompare(a.latest.run)).map(f => { const s = splitName(f.name); return `<tr class="click" data-href="#/fund/${encodeURIComponent(f.id)}">
          <td><div class="nm">${esc(s.manager)}</div><div class="sub">${esc(s.strategy || '')}</div></td>
          <td>${gateStrip(f.latest.gates)}</td><td>${dispChip(f.latest.disposition)}</td>
          <td class="n dim">${ago(stampDate(f.latest.run))}</td></tr>`; }).join('')}</table></div>` : empty('funnel', 'No screens yet', 'Run one from the screening queue.')}</div></div>
    <div class="stack">
      <div class="card"><div class="hd"><h2 class="sec">Gate outcomes</h2><span class="sec-sub">latest screen per fund · passes shown right</span></div>
        <div class="bd">${hbars(mix, { total: Math.max(1, screened.length) })}${legend(RESULT_KEYS.map(k => [k, toneVar(resultTone(k))]))}</div></div>
      <div class="card"><div class="hd"><h2 class="sec">Pipeline by status</h2><span class="sec-sub">${funds.length} data rooms</span></div>
        <div class="bd">${hbars(statuses.map(s => ({ label: s, labelHtml: pipeChip(s), segs: [{ v: byStatus[s], color: 'var(--c1)', tip: `${esc(s)}: ${byStatus[s]}` }] })))}</div></div>
      <div class="card"><div class="hd"><h2 class="sec">Intake aging</h2><span class="sec-sub">days since the latest material on file</span></div>
        <div class="bd">${ages.length ? hbars(aging) : '<span class="dim">No dated documents yet.</span>'}</div></div>
    </div>
  </div>

  <div class="grid g2" style="margin-top:14px">
    <div class="card"><div class="hd"><h2 class="sec">Needs attention</h2><span class="sec-sub">${attention.length}</span></div>
      <div class="bd flush">${attention.length ? `<table class="t">${attention.map(a => `<tr class="click" data-href="#/fund/${encodeURIComponent(a.f.id)}">
        <td style="width:34px"><span class="chip ${a.tone}" style="padding:0 5px"><sl-icon name="${a.icon}"></sl-icon></span></td>
        <td><div class="nm">${esc(a.f.name)}</div><div class="sub">${esc(a.why)} · ${esc(a.detail)}</div></td>
        <td class="n dim">${ago(stampDate(a.f.latest.run))}</td></tr>`).join('')}</table>` : empty('check2-circle', 'Nothing waiting', 'No screens need review.')}</div></div>
    <div class="card"><div class="hd"><h2 class="sec">Active in the pipeline</h2><span class="sec-sub">${active.length} under review or further</span></div>
      <div class="bd flush">${active.length ? `<table class="t">${active.map(f => { const s = splitName(f.name);
        return `<tr class="click" data-href="#/fund/${encodeURIComponent(f.id)}"><td><div class="nm">${esc(s.manager)}</div><div class="sub">${esc(s.strategy)}</div></td><td>${pipeChip(f.status.status)}</td>
        <td class="wrap"><div class="sub" style="color:var(--ink2)">${esc(f.actions?.next || '')}</div></td></tr>`; }).join('')}</table>` : empty('signpost-split', 'Nothing active', 'Funds show here once the CIO moves them past triage.')}</div></div>
  </div>

  <div class="card" style="margin-top:14px"><div class="hd"><h2 class="sec">Recent runs</h2><span class="sp"></span><a class="ghost-btn sm" href="#/logs?tab=runs">Run traces<sl-icon name="arrow-right"></sl-icon></a></div>
    <div class="bd flush"><table class="t">${runs.slice(0, 6).map(r => `<tr class="click" data-href="#/fund/${encodeURIComponent(r.fund_id)}/screen/${r.run}">
      <td class="dim tnum" style="width:150px">${ago(stampDate(r.run))}</td><td><span class="nm">${esc(r.fund)}</span></td><td>${gateStrip(r.gates)}</td><td>${dispChip(r.disposition)}</td>
      <td class="dim mono">${esc(r.extractor)} → ${esc(r.judge)}</td><td class="n dim tnum">${r.seconds != null ? r.seconds + 's' : ''}</td></tr>`).join('')}</table></div></div>
  </div>`;
  el.querySelectorAll('[data-href]').forEach(tr => tr.addEventListener('click', () => location.hash = tr.dataset.href));
}
