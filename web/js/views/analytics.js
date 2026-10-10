import { $, $$, cached, esc, n, pct, fmtDT, stampDate, gateName, gateColor, GATE_ORDER, RESULT_KEYS, resultTone, toneVar, hbars, vbars, dotStrip, legend, empty, skeleton, downloadCSV, STEPS } from '../lib.js';
import { setCrumbs } from '../app.js';

export async function render(el, r) {
  setCrumbs([['Analytics']]);
  el.innerHTML = `<div class="page">${skeleton(4)}${skeleton(8)}</div>`;
  const [rows, runs] = await Promise.all([cached('analytics'), cached('runs')]);
  if (!runs.length) { el.innerHTML = `<div class="page">${empty('bar-chart-line', 'No runs to analyze', 'Run a screen first.')}</div>`; return; }
  const st = { scope: r.query.scope || 'latest' };
  const judges = [...new Set(runs.map(x => x.judge))];

  const draw = () => {
    history.replaceState(null, '', '#/analytics?' + new URLSearchParams(Object.entries(st).filter(([, v]) => v)).toString());
    let rs = [...runs];
    if (st.scope === 'latest') { const seen = new Set(); rs = rs.filter(x => !seen.has(x.fund_id) && seen.add(x.fund_id)); }
    const keep = new Set(rs.map(x => x.fund_id + x.run));
    const gr = rows.filter(x => keep.has(x.fund_id + x.run));
    const auto = gr.filter(x => x.min_confidence != null);

    // KPIs
    const conf = auto.map(x => x.min_confidence);
    const facts = gr.reduce((a, x) => a + x.facts, 0), rej = gr.reduce((a, x) => a + x.rejected, 0);
    const tokIn = gr.reduce((a, x) => a + x.tokens_in, 0), tokOut = gr.reduce((a, x) => a + x.tokens_out, 0);
    const reviewRate = auto.length ? auto.filter(x => x.review).length / auto.length : null;
    const secs = rs.map(x => x.seconds).filter(v => v != null);
    const median = a => { const s = [...a].sort((x, y) => x - y); return s.length ? (s.length % 2 ? s[s.length >> 1] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null; };

    // Outcome mix per gate
    const mix = GATE_ORDER.map(g => {
      const mine = gr.filter(x => x.gate === g);
      const c = Object.fromEntries(RESULT_KEYS.map(k => [k, mine.filter(x => x.result === k).length]));
      return { label: gateName(g), segs: RESULT_KEYS.map(k => ({ v: c[k], color: toneVar(resultTone(k)), tip: `<b>${esc(gateName(g))}</b><br>${esc(k)}: ${c[k]} of ${mine.length}` })), value: `${mine.length}` };
    });
    // Confidence strip
    const strip = GATE_ORDER.filter(g => auto.some(x => x.gate === g)).map(g => ({ label: gateName(g), color: gateColor(g),
      dots: auto.filter(x => x.gate === g).map(x => ({ v: x.min_confidence, color: toneVar(resultTone(x.result)), tip: `<b>${esc(x.fund)}</b><br>${esc(gateName(g))}: ${esc(x.result)} · ${pct(x.min_confidence)}<br><span class=dim>${esc(x.judge)} · ${fmtDT(stampDate(x.run))}</span>` })) }));
    // Extraction quality per gate
    const quality = GATE_ORDER.filter(g => gr.some(x => x.gate === g && (x.facts + x.rejected + x.not_found))).map(g => {
      const m = gr.filter(x => x.gate === g), f = m.reduce((a, x) => a + x.facts, 0), rj = m.reduce((a, x) => a + x.rejected, 0), nf = m.reduce((a, x) => a + x.not_found, 0);
      return { label: gateName(g), segs: [
        { v: f, color: 'var(--c1)', tip: `<b>${esc(gateName(g))}</b><br>${f} facts verified on the cited page` },
        { v: rj, color: 'var(--c2)', tip: `<b>${esc(gateName(g))}</b><br>${rj} quotes not on the cited page` },
        { v: nf, color: 'var(--c7)', tip: `<b>${esc(gateName(g))}</b><br>${nf} fields not found` }], value: f + rj ? pct(f / (f + rj)) : '–' };
    });
    // Mean seconds per step
    const stepAvg = STEPS.map(s => { const v = gr.map(x => x.steps[s]).filter(x => x != null); return { s, v: v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0, k: v.length }; });
    // Duration per run, chronological
    const chrono = [...rs].filter(x => x.seconds != null).reverse();
    // Judge comparison over all runs
    const jt = judges.map(j => {
      const jr = runs.filter(x => x.judge === j), ja = rows.filter(x => x.judge === j && x.min_confidence != null);
      return { j, runs: jr.length, conf: ja.length ? ja.reduce((a, x) => a + x.min_confidence, 0) / ja.length : null, review: ja.length ? ja.filter(x => x.review).length / ja.length : null,
        fail: ja.length ? ja.filter(x => x.result === 'Fail').length / ja.length : null, secs: median(jr.map(x => x.seconds).filter(v => v != null)), tok: rows.filter(x => x.judge === j).reduce((a, x) => a + x.tokens_in + x.tokens_out, 0) };
    });

    el.innerHTML = `<div class="page">
      <div class="ph"><div><h1>Analytics</h1><p>How the gates behave across runs: outcomes, judge confidence, extraction quality, and cost.</p></div>
        <div class="act"><div class="seg" id="scope"><button data-v="latest" class="${st.scope === 'latest' ? 'on' : ''}">Latest per fund</button><button data-v="all" class="${st.scope === 'all' ? 'on' : ''}">All runs</button></div></div></div>
      <div class="kpis">
        <div class="kpi"><div class="l"><sl-icon name="collection"></sl-icon>Runs in view</div><div class="v">${rs.length}</div><div class="f">${new Set(rs.map(x => x.fund_id)).size} funds · ${gr.length} gate results</div></div>
        <div class="kpi hl"><div class="l"><sl-icon name="speedometer2"></sl-icon>Median decisive confidence</div><div class="v">${conf.length ? pct(median(conf)) : '–'}</div><div class="f">over ${conf.length} automated gate results</div></div>
        <div class="kpi"><div class="l"><sl-icon name="person-check"></sl-icon>Sent to analyst</div><div class="v">${reviewRate != null ? pct(reviewRate) : '–'}</div><div class="f">below the 0.75 threshold</div></div>
        <div class="kpi"><div class="l"><sl-icon name="patch-check"></sl-icon>Quotes verified</div><div class="v">${facts + rej ? pct(facts / (facts + rej)) : '–'}</div><div class="f">${n(facts)} kept · ${n(rej)} off the cited page</div></div>
        <div class="kpi"><div class="l"><sl-icon name="stopwatch"></sl-icon>Median run time</div><div class="v">${secs.length ? median(secs).toFixed(1) + 's' : '–'}</div><div class="f">wall clock, five gates in parallel</div></div>
        <div class="kpi"><div class="l"><sl-icon name="cpu"></sl-icon>Judge tokens</div><div class="v">${n(tokIn + tokOut)}</div><div class="f">${n(tokIn)} in · ${n(tokOut)} out</div></div>
      </div>
      <div class="grid g2">
        <div class="card"><div class="hd"><h2 class="sec">Outcome by gate</h2><span class="sec-sub">count of gate results</span></div><div class="bd">${hbars(mix)}${legend(RESULT_KEYS.map(k => [k, toneVar(resultTone(k))]))}</div></div>
        <div class="card"><div class="hd"><h2 class="sec">Decisive confidence by gate</h2><span class="sec-sub">one dot per result, colored by outcome · dashed line is the review threshold</span></div><div class="bd">${strip.length ? dotStrip(strip) : '<span class="dim">No automated results in view.</span>'}</div></div>
        <div class="card"><div class="hd"><h2 class="sec">Extraction quality</h2><span class="sec-sub">share of quotes found on the cited page, right</span></div><div class="bd">${quality.length ? hbars(quality) + legend([['Verified facts', 'var(--c1)'], ['Quote off page', 'var(--c2)'], ['Field not found', 'var(--c7)']]) : '<span class="dim">No extraction in view.</span>'}</div></div>
        <div class="card"><div class="hd"><h2 class="sec">Where the time goes</h2><span class="sec-sub">mean seconds per step, per gate</span></div><div class="bd">${hbars(stepAvg.map(x => ({ label: x.s, segs: [{ v: x.v, color: `var(--st-${x.s})`, tip: `<b>${x.s}</b><br>mean ${x.v.toFixed(2)}s over ${x.k} gate runs` }], value: x.v.toFixed(2) + 's' })))}</div></div>
      </div>
      <div class="grid g-main" style="margin-top:14px">
        <div class="card"><div class="hd"><h2 class="sec">Run duration</h2><span class="sec-sub">seconds, oldest to newest</span></div><div class="bd">${chrono.length ? vbars(chrono.map((x, i) => ({ v: x.seconds, color: 'var(--c1)', label: `#${i + 1}`, tip: `<b>${esc(x.fund)}</b><br>${x.seconds}s · ${esc(x.extractor)} → ${esc(x.judge)}<br><span class=dim>${fmtDT(stampDate(x.run))}</span>` })), { yFmt: v => v.toFixed(0) + 's' }) : '<span class="dim">No timed runs.</span>'}</div></div>
        <div class="card"><div class="hd"><h2 class="sec">Judge comparison</h2><span class="sec-sub">all runs</span></div><div class="bd flush"><table class="t"><tr><th>Judge</th><th class="n">Runs</th><th class="n">Mean conf.</th><th class="n">Review</th><th class="n">Fail</th><th class="n">Median time</th></tr>
          ${jt.map(x => `<tr><td class="mono">${esc(x.j)}</td><td class="n">${x.runs}</td><td class="n">${x.conf != null ? pct(x.conf) : '–'}</td><td class="n">${x.review != null ? pct(x.review) : '–'}</td><td class="n">${x.fail != null ? pct(x.fail) : '–'}</td><td class="n">${x.secs != null ? x.secs.toFixed(1) + 's' : '–'}</td></tr>`).join('')}</table></div></div>
      </div>
      <div class="card" style="margin-top:14px"><div class="hd"><h2 class="sec">Gate results</h2><span class="sec-sub">the rows behind every chart above</span><span class="sp"></span><button class="ghost-btn sm" id="csv"><sl-icon name="download"></sl-icon>CSV</button></div>
        <div class="bd flush"><div class="tbl-wrap" style="max-height:440px"><table class="t compact"><tr><th>Run</th><th>Fund</th><th>Gate</th><th>Result</th><th class="n">Confidence</th><th class="n">Facts</th><th class="n">Off page</th><th class="n">Not found</th><th class="n">Pages</th><th class="n">Tokens</th></tr>
        ${gr.map(x => `<tr class="click" data-href="#/fund/${encodeURIComponent(x.fund_id)}/screen/${x.run}"><td class="dim tnum">${fmtDT(stampDate(x.run))}</td><td>${esc(x.fund)}</td><td>${esc(gateName(x.gate))}</td><td><span class="chip ${resultTone(x.result)}">${esc(x.result)}</span>${x.review ? ' <span class="rv-flag">Review</span>' : ''}</td>
          <td class="n">${x.min_confidence != null ? pct(x.min_confidence) : '–'}</td><td class="n">${x.facts}</td><td class="n">${x.rejected}</td><td class="n">${x.not_found}</td><td class="n">${x.pages_offered}</td><td class="n">${n(x.tokens_in + x.tokens_out)}</td></tr>`).join('')}</table></div></div></div>
    </div>`;
    $$('#scope button', el).forEach(b => b.addEventListener('click', () => { st.scope = b.dataset.v; draw(); }));
    $$('[data-href]', el).forEach(tr => tr.addEventListener('click', () => location.hash = tr.dataset.href));
    $('#csv', el).addEventListener('click', () => downloadCSV('gate-results.csv', gr.map(({ steps, ...x }) => ({ ...x, ...Object.fromEntries(Object.entries(steps).map(([k, v]) => ['sec_' + k, v])) }))));
  };
  draw();
}
