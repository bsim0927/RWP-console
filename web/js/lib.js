// Shared helpers: data access, formatting, status vocabulary, charts, previews.

/** @param {string} s @param {ParentNode} [el] @returns {any} Shoelace elements carry props the DOM types do not know */
export const $ = (s, el = document) => el.querySelector(s);
/** @param {string} s @param {ParentNode} [el] @returns {any[]} */
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------- api ----------
export async function api(path, opts) {
  const r = await fetch('/api/' + path, opts);
  if (r.status === 401) { location.href = '/login'; throw new Error('sign in first'); } // the session ran out
  const body = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || (body && body.error && !Array.isArray(body))) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}
const cache = new Map();
export function cached(path, ttl = 15000) {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.t < ttl) return hit.p;
  const p = api(path).catch(e => { cache.delete(path); throw e; });
  cache.set(path, { t: Date.now(), p });
  return p;
}
export const bust = (prefix = '') => { for (const k of cache.keys()) if (k.startsWith(prefix)) cache.delete(k); };
export const q = (o) => new URLSearchParams(o).toString();

// ---------- formatting ----------
export const n = (v, d = 0) => v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
export const pct = (v, d = 0) => v == null ? '–' : (100 * v).toFixed(d) + '%';
export const bytes = b => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(0) + ' KB' : (b / 1048576).toFixed(1) + ' MB';
export const stampDate = s => s ? new Date(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(9, 11)}:${s.slice(11, 13)}:${s.slice(13, 15)}`) : null;
export function ago(d) {
  if (!d) return '–';
  const s = (Date.now() - (d instanceof Date ? d : new Date(d)).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  if (s < 86400 * 120) return Math.floor(s / 86400) + 'd ago';
  return fmtDate(d);
}
// A calendar date (YYYY-MM-DD) at local midnight, so it never shows as the day before.
export const day = s => new Date(s + 'T00:00:00');
export const fmtDate = d => (d instanceof Date ? d : new Date(d)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
export const fmtDT = d => (d instanceof Date ? d : new Date(d)).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
export const fmtTime = t => new Date(t * 1000).toLocaleTimeString('en-US', { hour12: false });
export const initials = s => s.split(/[\s-]+/).filter(w => /^[A-Za-z]/.test(w)).slice(0, 2).map(w => w[0]).join('').toUpperCase();
export const splitName = name => { const [m, ...r] = name.split(' - '); return { manager: m, strategy: r.join(' - ') }; };

// ---------- gates & status vocabulary ----------
export let GATE_ORDER = ['investor_eligibility', 'total_annual_cost', 'operability', 'track_record', 'disclosure_history'];
export const setGateOrder = ids => { if (ids?.length) GATE_ORDER = ids; };
export const gateName = g => { const s = String(g).replaceAll('_', ' '); return s[0].toUpperCase() + s.slice(1); };
export const gateColor = g => `var(--c${(GATE_ORDER.indexOf(g) % 8 + 8) % 8 + 1})`;
export const sortGates = arr => [...arr].sort((a, b) => GATE_ORDER.indexOf(a.gate ?? a) - GATE_ORDER.indexOf(b.gate ?? b));

export function resultTone(r) {
  if (!r) return 'none';
  if (r === 'Pass') return 'good';
  if (r === 'Fail') return 'crit';
  if (r === 'Incomplete') return 'warn';
  if (r.startsWith('Route')) return 'serious'; // runs from before decision B6 dropped this result
  return 'none';
}
const RESULT_ICON = { good: 'check-lg', crit: 'x-lg', warn: 'hourglass-split', serious: 'signpost-split', none: 'dash' };
export const resultIcon = r => RESULT_ICON[resultTone(r)];
export const RESULT_KEYS = ['Pass', 'Incomplete', 'Fail', 'Not yet run'];
export const toneVar = t => ({ good: 'var(--good)', crit: 'var(--crit)', warn: 'var(--warn)', serious: 'var(--serious)', none: 'var(--none)' }[t]);

export function resultChip(r, review) {
  const t = resultTone(r);
  return `<span class="chip ${t}"><sl-icon name="${RESULT_ICON[t]}"></sl-icon>${esc(r || 'Not run')}</span>${review ? ` <span class="rv-flag" title="Low judge confidence, goes to an analyst"><sl-icon name="person-check"></sl-icon>Review</span>` : ''}`;
}
// The five-business-day screen clock from /api/funds (decision G4).
export function clockChip(c) {
  if (!c) return '';
  const due = fmtDate(day(c.due));
  if (c.done) return c.late ? `<span class="chip crit" title="Due ${due}"><sl-icon name="alarm"></sl-icon>Screened late</span>` : `<span class="chip good" title="Due ${due}"><sl-icon name="check2"></sl-icon>On time</span>`;
  if (c.late) return `<span class="chip crit"><sl-icon name="alarm"></sl-icon>Late · due ${due}</span>`;
  return `<span class="chip ${c.days_left <= 1 ? 'warn' : 'ghost'}"><sl-icon name="clock"></sl-icon>Due ${due} · ${c.days_left} business day${c.days_left === 1 ? '' : 's'} left</span>`;
}
// What a gate wants the analyst to know beyond its result, e.g. QP-only.
export const flagChips = flags => (flags || []).map(f => `<span class="chip ghost flag"><sl-icon name="flag"></sl-icon>${esc(f)}</span>`).join('');
// One square per gate, in policy order, with a tooltip.
export function gateStrip(gates) {
  if (!gates) return '<span class="dim">Not screened</span>';
  return `<span class="gs">${GATE_ORDER.map(g => {
    const x = gates[g] || {};
    const t = resultTone(x.result);
    return `<i class="${t} ${x.review ? 'rv' : ''}" data-tip="<b>${esc(gateName(g))}</b><br>${esc(x.result || 'No result')}${x.min_confidence != null ? ` <span class=dim>· confidence ${pct(x.min_confidence)}</span>` : ''}${(x.flags || []).map(f => `<br><span class=dim>Flag:</span> ${esc(f)}`).join('')}${x.review ? '<br><span class=dim>Analyst review</span>' : ''}"><sl-icon name="${RESULT_ICON[t]}"></sl-icon></i>`;
  }).join('')}</span>`;
}

export function dispTone(d) {
  if (!d) return 'none';
  if (d.startsWith('Coverable') || d.startsWith('Covered')) return 'good';
  if (d.startsWith('Reviewed and not covered')) return 'crit';
  if (d.startsWith('Under review')) return 'warn';
  return 'none';
}
export const dispShort = d => d ? d.replace(/\s*\(.*\)$/, '') : 'Not screened';
export const dispNote = d => (d && d.match(/\((.*)\)$/)?.[1]) || '';
const DISP_ICON = { good: 'shield-check', crit: 'slash-circle', warn: 'hourglass-split', none: 'circle' };
export const dispChip = (d, lg) => { const t = dispTone(d); return `<span class="chip ${t} ${lg ? 'lg' : ''}" title="${esc(d || '')}"><sl-icon name="${DISP_ICON[t]}"></sl-icon>${esc(dispShort(d))}</span>`; };
export const dispIcon = d => DISP_ICON[dispTone(d)];
// Where a disposition stands (decision F5): a draft until an analyst confirms it; "not covered" also needs the CIO.
const DECISION = { draft: ['ghost', 'pencil-square', 'Draft'], confirmed: ['good', 'patch-check', 'Confirmed'], awaiting_signoff: ['warn', 'hourglass-split', 'Awaiting CIO sign-off'], signed_off: ['good', 'patch-check', 'Signed off'] };
export const decisionChip = d => { if (!d) return ''; const [t, icon, label] = DECISION[d.state] || DECISION.draft; return `<span class="chip ${t}"><sl-icon name="${icon}"></sl-icon>${label}</span>`; };

// Pipeline statuses (sg/fund_status.STATUSES), in process order. Only the CIO moves them.
export const PIPE_ORDER = ['Not reviewed', 'Triaged', 'Under review', 'Deep DD', 'IC ready', 'Covered', 'Watch', 'Reviewed and not covered'];
const PIPE_TONE = { 'Not reviewed': 'none', Triaged: 'ghost', 'Under review': 'warn', 'Deep DD': 'accent', 'IC ready': 'accent', Covered: 'good', Watch: 'serious', 'Reviewed and not covered': 'crit' };
const PIPE_ICON = { 'Not reviewed': 'inbox', Triaged: 'list-check', 'Under review': 'hourglass-split', 'Deep DD': 'search', 'IC ready': 'people', Covered: 'shield-check', Watch: 'eye', 'Reviewed and not covered': 'slash-circle' };
export const pipeChip = s => s ? `<span class="chip ${PIPE_TONE[s] || 'ghost'}"><sl-icon name="${PIPE_ICON[s] || 'circle'}"></sl-icon>${esc(s)}</span>` : '<span class="chip ghost"><sl-icon name="question-circle"></sl-icon>Not in pipeline</span>';

export const TIERS = ['core', 'supporting', 'review', 'noise', 'external'];
export const TIER_COL = { core: 'var(--c1)', supporting: 'var(--c3)', review: 'var(--c4)', noise: 'var(--none)', external: 'var(--c7)' };

// ---------- toast & tooltip ----------
export function toast(msg, tone = 'accent', icon) {
  const el = document.createElement('div');
  el.className = 'toast ' + tone;
  el.innerHTML = `<sl-icon name="${icon || { good: 'check-circle', crit: 'exclamation-octagon', accent: 'info-circle' }[tone]}"></sl-icon><div>${msg}</div>`;
  $('#toasts').append(el);
  setTimeout(() => el.remove(), 5200);
}
export function initTips() {
  const tip = $('#tip');
  document.addEventListener('pointerover', e => {
    const t = /** @type {Element} */ (e.target).closest?.('[data-tip]');
    if (!t) return;
    tip.innerHTML = /** @type {HTMLElement} */ (t).dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener('pointermove', e => {
    if (tip.hidden) return;
    if (!/** @type {Element} */ (e.target).closest?.('[data-tip]')) { tip.hidden = true; return; }
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 14;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  });
  document.addEventListener('pointerout', e => {
    const from = /** @type {Element} */ (e.target), to = /** @type {Element | null} */ (e.relatedTarget);
    if (from.closest?.('[data-tip]') && !to?.closest?.('[data-tip]')) tip.hidden = true;
  });
}

// ---------- charts (plain SVG, recessive axes, thin marks, hover on every mark) ----------
/** @param {any[]} rows @param {{ total?: number }} [opts] */
export function hbars(rows, { total } = {}) {
  // rows: [{label, segs:[{v, color, tip}], value}]
  const max = total || Math.max(1, ...rows.map(r => r.segs.reduce((a, s) => a + s.v, 0)));
  return rows.map(r => {
    const sum = r.segs.reduce((a, s) => a + s.v, 0);
    return `<div class="hbar"><span class="l" title="${esc(r.label)}">${r.labelHtml || esc(r.label)}</span>
      <span class="track" style="background:${sum ? 'var(--s3)' : 'var(--s2)'}"><span style="display:flex;gap:2px;width:${(100 * sum / max).toFixed(2)}%">${r.segs.filter(s => s.v).map(s => `<span style="flex:${s.v};background:${s.color};border-radius:2px" data-tip="${esc(s.tip || '')}"></span>`).join('')}</span></span>
      <span class="v">${r.value ?? n(sum)}</span></div>`;
  }).join('');
}

export function legend(items) {
  return `<div class="legend">${items.map(([label, color, line]) => `<span><i class="${line ? 'ln' : ''}" style="background:${color}"></i>${esc(label)}</span>`).join('')}</div>`;
}

// Vertical bars over an ordinal x axis. bars: [{x, v, color, tip, label}]
/** @param {any[]} bars @param {{ h?: number, yFmt?: (v: number) => string, yMax?: number, w?: number }} [opts] */
export function vbars(bars, { h = 180, yFmt = v => n(v), yMax, w = 760 } = {}) {
  const W = w, L = 44, R = 8, T = 10, B = 26, H = h;
  const max = yMax || Math.max(1e-9, ...bars.map(b => b.v)) * 1.1;
  const bw = (W - L - R) / Math.max(1, bars.length);
  const y = v => T + (H - T - B) * (1 - v / max);
  let s = `<svg class="chart" style="max-width:${W}px" viewBox="0 0 ${W} ${H}" role="img">`;
  s += '<g class="grid">' + [0, .25, .5, .75, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}"/><text x="${L - 8}" y="${y(max * f) + 4}" text-anchor="end">${yFmt(max * f)}</text>`).join('') + '</g>';
  bars.forEach((b, i) => {
    const x = L + i * bw, w = Math.max(2, Math.min(28, bw - 4)), cx = x + bw / 2;
    const top = y(b.v), base = y(0), hh = Math.max(0, base - top);
    const r = Math.min(4, w / 2, hh);
    s += `<path d="M${cx - w / 2},${base} V${top + r} q0,-${r} ${r},-${r} H${cx + w / 2 - r} q${r},0 ${r},${r} V${base} Z" fill="${b.color}"/>`;
    s += `<rect class="hit" x="${x}" y="${T}" width="${bw}" height="${H - T - B}" data-tip="${esc(b.tip)}"/>`;
    if (b.label && (bars.length < 16 || i % Math.ceil(bars.length / 12) === 0)) s += `<text x="${cx}" y="${H - 8}" text-anchor="middle">${esc(b.label)}</text>`;
  });
  return s + '</svg>';
}

// Stacked vertical bars. bars: [{label, tip, segs:[{v, color}]}]; 2px gap between segments.
export function stackBars(bars, { h = 190, yFmt = v => n(v), w = 760 } = {}) {
  const W = w, L = 50, R = 8, T = 10, B = 26, H = h;
  const max = Math.max(1e-9, ...bars.map(b => b.segs.reduce((a, x) => a + x.v, 0))) * 1.1;
  const bw = (W - L - R) / Math.max(1, bars.length), y = v => T + (H - T - B) * (1 - v / max);
  let s = `<svg class="chart" style="max-width:${W}px" viewBox="0 0 ${W} ${H}" role="img">`;
  s += '<g class="grid">' + [0, .25, .5, .75, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}"/><text x="${L - 8}" y="${y(max * f) + 4}" text-anchor="end">${yFmt(max * f)}</text>`).join('') + '</g>';
  bars.forEach((b, i) => {
    const bwid = Math.max(3, Math.min(26, bw - 5)), x0 = L + i * bw + (bw - bwid) / 2;
    let acc = 0;
    b.segs.filter(sg => sg.v > 0).forEach((sg, k, arr) => {
      const top = y(acc + sg.v), bot = y(acc) - (k ? 2 : 0), hh = Math.max(1, bot - top);
      const r = k === arr.length - 1 ? Math.min(3, hh) : 0;
      s += `<path d="M${x0},${top + hh} V${top + r} q0,-${r} ${r},-${r} H${x0 + bwid - r} q${r},0 ${r},${r} V${top + hh} Z" fill="${sg.color}"/>`;
      acc += sg.v;
    });
    s += `<rect class="hit" x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T - B}" data-tip="${esc(b.tip)}"/>`;
    if (b.label && (bars.length < 16 || i % Math.ceil(bars.length / 12) === 0)) s += `<text x="${L + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(b.label)}</text>`;
  });
  return s + '</svg>';
}

// Dot strip: one row per category, dots on a 0..1 scale, with a threshold line.
export function dotStrip(rows, { threshold = 0.75, max = 1, fmt = v => v.toFixed(2), w = 600 } = {}) {
  const W = w, L = 130, R = 16, rowH = 34, T = 8, H = rows.length * rowH + T + 24;
  const x = v => L + (W - L - R) * Math.min(1, v / max);
  let s = `<svg class="chart" style="max-width:${W}px" viewBox="0 0 ${W} ${H}" role="img">`;
  s += '<g class="grid">' + [0, .25, .5, .75, 1].map(f => `<line x1="${x(f * max)}" x2="${x(f * max)}" y1="${T}" y2="${H - 22}"/><text x="${x(f * max)}" y="${H - 6}" text-anchor="middle">${fmt(f * max)}</text>`).join('') + '</g>';
  if (threshold != null) s += `<line x1="${x(threshold)}" x2="${x(threshold)}" y1="${T - 4}" y2="${H - 22}" stroke="var(--ink2)" stroke-dasharray="3 3" stroke-width="1.5"/>`;
  rows.forEach((r, i) => {
    const cy = T + i * rowH + rowH / 2;
    s += `<text class="lbl" x="${L - 12}" y="${cy + 4}" text-anchor="end">${esc(r.label)}</text>`;
    s += `<line x1="${L}" x2="${W - R}" y1="${cy}" y2="${cy}" stroke="var(--line)"/>`;
    r.dots.forEach((d, j) => {
      const jitter = ((j * 37) % 9 - 4) * 1.4;
      s += `<circle cx="${x(d.v)}" cy="${cy + jitter}" r="5" fill="${d.color || r.color}" stroke="var(--s1)" stroke-width="2" data-tip="${esc(d.tip)}"/>`;
    });
  });
  return s + '</svg>';
}

// Multi-series line on 0..1 with threshold. series: [{label,color,pts:[[i,v,tip]]}], xs: labels
export function lineChart(series, xs, { threshold = 0.75, h = 200, w = 1100 } = {}) {
  const W = w, L = 40, R = 14, T = 10, B = 28, H = h, nn = xs.length;
  const x = i => nn === 1 ? L + (W - L - R) / 2 : L + (W - L - R) * i / (nn - 1), y = v => T + (H - T - B) * (1 - v);
  let s = `<svg class="chart" style="max-width:${W}px" viewBox="0 0 ${W} ${H}" role="img">`;
  s += '<g class="grid">' + [0, .25, .5, .75, 1].map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join('') + '</g>';
  s += `<line x1="${L}" x2="${W - R}" y1="${y(threshold)}" y2="${y(threshold)}" stroke="var(--ink2)" stroke-dasharray="3 3" stroke-width="1.5"/>`;
  xs.forEach((lab, i) => { if (nn < 14 || i % Math.ceil(nn / 12) === 0) s += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${esc(lab)}</text>`; });
  series.forEach(se => {
    if (se.pts.length > 1) s += `<polyline fill="none" stroke="${se.color}" stroke-width="2" stroke-linejoin="round" points="${se.pts.map(p => x(p[0]) + ',' + y(p[1])).join(' ')}"/>`;
    se.pts.forEach(p => s += `<circle cx="${x(p[0])}" cy="${y(p[1])}" r="4.5" fill="${se.color}" stroke="var(--s1)" stroke-width="2" data-tip="${esc(p[2])}"/>`);
  });
  return s + '</svg>';
}

// Gantt-style step timeline per gate.
export function waterfall(steps, gates, now = 0, active = false) {
  const W = 1100, L = 150, R = 10, rowH = 26, H = gates.length * rowH + 34;
  const tmax = Math.max(1, ...steps.map(e => e.end ?? now), active ? now : 0) * 1.04;
  const x = t => L + (W - L - R) * t / tmax;
  let s = `<svg class="chart" style="max-width:${W}px" viewBox="0 0 ${W} ${H}" role="img" aria-label="Pipeline steps per gate over time">`;
  s += '<g class="grid">';
  for (let i = 0; i <= 5; i++) { const t = tmax * i / 5; s += `<line x1="${x(t)}" x2="${x(t)}" y1="6" y2="${H - 22}"/><text x="${x(t)}" y="${H - 8}" text-anchor="middle">${t.toFixed(1)}s</text>`; }
  s += '</g>';
  gates.forEach((g, i) => {
    const y = 10 + i * rowH;
    s += `<text class="lbl" x="${L - 10}" y="${y + 12}" text-anchor="end">${esc(gateName(g))}</text>`;
    steps.filter(e => e.gate === g).forEach(e => {
      const end = e.end ?? now, w = Math.max(3, x(end) - x(e.start));
      s += `<rect x="${x(e.start)}" y="${y}" width="${w}" height="16" rx="3" fill="var(--st-${e.step})" opacity="${e.end == null ? .5 : 1}" data-tip="<b>${esc(e.step)}</b> · ${(end - e.start).toFixed(2)}s<br><span class=dim>${esc(e.detail || '')}</span>"/>`;
    });
  });
  s += '</svg>';
  const used = [...new Set(steps.map(e => e.step))].filter(x => x !== 'catalog');
  return s + legend(used.map(u => [u, `var(--st-${u})`]));
}

export const STEPS = ['retrieve', 'extract', 'verify', 'judge', 'derive'];
export function stepMatrix(steps, gates, now = 0) {
  return `<div class="tbl-wrap"><table class="t compact mx"><tr><th>Gate</th>${STEPS.map(x => `<th>${x}</th>`).join('')}</tr>` + gates.map(g => {
    const mine = steps.filter(e => e.gate === g);
    if (mine.length === 1 && mine[0].step === 'skipped') return `<tr><td>${esc(gateName(g))}</td><td colspan="5"><span class="dim">${esc(mine[0].detail)}, not automated</span></td></tr>`;
    return `<tr><td>${esc(gateName(g))}</td>${STEPS.map(st => {
      const e = mine.find(x => x.step === st);
      if (!e) return '<td><span class="cell">·</span></td>';
      if (e.end == null) return `<td><span class="cell run">${(now - e.start).toFixed(1)}s</span></td>`;
      return `<td><span class="cell done" data-tip="${esc(e.detail)}">${(e.end - e.start).toFixed(1)}s</span></td>`;
    }).join('')}</tr>`;
  }).join('') + '</table></div>';
}

// ---------- markdown (enough for run reports and repo docs) ----------
export function markdown(src) {
  const inline = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  const lines = src.split('\n'); let out = '', i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (/^#{1,4} /.test(l)) { const k = l.match(/^#+/)[0].length; out += `<h${Math.min(3, k)}>${inline(l.slice(k + 1))}</h${Math.min(3, k)}>`; i++; continue; }
    if (/^\|/.test(l)) {
      const rows = []; while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      const body = rows.slice(1).filter(r => !/^\|[\s:|-]+\|?$/.test(r));
      out += `<div class="tbl-wrap"><table><tr>${cells(rows[0]).map(c => `<th>${inline(c)}</th>`).join('')}</tr>${body.map(r => `<tr>${cells(r).map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</table></div>`; continue;
    }
    if (/^\s*[-*] /.test(l)) { out += '<ul>'; while (i < lines.length && /^\s*[-*] /.test(lines[i])) out += `<li>${inline(lines[i++].replace(/^\s*[-*] /, ''))}</li>`; out += '</ul>'; continue; }
    if (/^\s*\d+\. /.test(l)) { out += '<ol>'; while (i < lines.length && /^\s*\d+\. /.test(lines[i])) out += `<li>${inline(lines[i++].replace(/^\s*\d+\. /, ''))}</li>`; out += '</ol>'; continue; }
    if (/^---+$/.test(l.trim())) { out += '<hr>'; i++; continue; }
    if (!l.trim()) { i++; continue; }
    const para = []; while (i < lines.length && lines[i].trim() && !/^(#|\||\s*[-*] |\s*\d+\. |---)/.test(lines[i])) para.push(lines[i++]);
    out += `<p>${inline(para.join(' '))}</p>`;
  }
  return `<div class="md">${out}</div>`;
}

// ---------- file preview drawer ----------
const EXT = { pdf: 'pdf', md: 'md', txt: 'md', xlsx: 'xls', xls: 'xls', csv: 'xls', docx: 'doc', doc: 'doc', pptx: 'doc', png: 'img', jpg: 'img', jpeg: 'img', webp: 'img', gif: 'img', svg: 'img' };
export const extOf = name => (name.split('.').pop() || '').toLowerCase();
export function fileIcon(name, dir) {
  if (dir) return '<sl-icon class="ficon dir" name="folder-fill"></sl-icon>';
  const k = EXT[extOf(name)];
  const ic = { pdf: 'file-earmark-pdf', md: 'file-earmark-text', xls: 'file-earmark-spreadsheet', doc: 'file-earmark-richtext', img: 'file-earmark-image' }[k] || 'file-earmark';
  return `<sl-icon class="ficon ${k || ''}" name="${ic}"></sl-icon>`;
}
export const rawUrl = (path, page) => `/api/raw?${q({ path })}${page ? '#page=' + page : ''}`;

function highlight(text, quote) {
  const t = esc(text);
  if (!quote) return t;
  // Prefer the exact phrase, tolerant of line breaks and spacing; fall back to key words.
  const toks = esc(quote).split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (toks.length > 2) {
    const re = new RegExp(toks.join('\\s+'), 'i');
    if (re.test(t)) return t.replace(re, m => `<mark>${m}</mark>`);
  }
  const words = quote.split(/\s+/).filter(w => w.length > 3).slice(0, 6).map(w => w.replace(/[^\w$%.]/g, '')).filter(Boolean);
  if (!words.length) return t;
  return t.replace(new RegExp(`(${words.map(w => w.replace(/[.$]/g, '\\$&')).join('|')})`, 'gi'), '<mark>$1</mark>');
}

/** @param {string} path @param {{ page?: number, quote?: string, title?: string, back?: { label: string, fn: () => void } }} [opts] */
export async function openPreview(path, { page, quote, title, back } = {}) {
  const d = $('#drawer');
  const name = path.split('/').pop();
  const ext = extOf(name);
  d.classList.add('wide');
  d.label = title || name;
  const dirPath = path.split('/').slice(0, -1).join('/');
  const head = `<div class="bar" style="margin-bottom:14px">
    ${back ? `<button class="ghost-btn sm" data-back><sl-icon name="arrow-left"></sl-icon>${esc(back.label)}</button>` : ''}
    <span class="path dim mono" style="font-size:11.5px">${esc(dirPath)}</span><span class="sp"></span>
    ${page ? `<span class="chip ghost">Page ${page}</span>` : ''}
    <a class="ghost-btn sm" href="#/files?${q({ path: dirPath })}" data-close><sl-icon name="folder2-open"></sl-icon>Show in folder</a>
    <a class="ghost-btn sm" href="${rawUrl(path, page)}" target="_blank" rel="noopener"><sl-icon name="box-arrow-up-right"></sl-icon>Open</a></div>`;
  let doc;
  if (ext === 'pdf') doc = '<div id="pv-pdf"></div>';
  else if (EXT[ext] === 'img') doc = `<img src="${rawUrl(path)}" alt="${esc(name)}">`;
  else if (['md', 'txt', 'csv', 'json', 'yaml', 'yml'].includes(ext)) doc = '<div id="pv-text"><div class="shimmer sk"></div></div>';
  else doc = `<div class="empty"><sl-icon name="file-earmark"></sl-icon><b>No inline preview for .${esc(ext)}</b>Open it in its own application, or read the extracted text.</div>`;
  d.innerHTML = head + `<sl-tab-group class="tabs" id="pv-tabs"><sl-tab slot="nav" panel="doc">Document</sl-tab><sl-tab slot="nav" panel="text">Extracted text</sl-tab>
    <sl-tab-panel name="doc"><div class="preview">${doc}</div></sl-tab-panel><sl-tab-panel name="text"><div id="pv-pages"><div class="shimmer sk"></div></div></sl-tab-panel></sl-tab-group>`;
  d.show();
  $$('[data-close]', d).forEach(a => a.addEventListener('click', () => d.hide()));
  if (back) $('[data-back]', d).addEventListener('click', back.fn);
  if (ext === 'pdf') import('./pdfview.js').then(m => m.pdfViewer($('#pv-pdf', d), rawUrl(path), { page: page || 1, quote }));
  if ($('#pv-text', d)) fetch(rawUrl(path)).then(r => r.text()).then(t => {
    $('#pv-text', d).innerHTML = ext === 'md' ? markdown(t) : ext === 'csv' ? csvTable(t) : `<pre class="pagetext">${esc(t)}</pre>`;
  });
  try {
    const fp = await api('filepages?' + q({ path }));
    const el = $('#pv-pages', d);
    if (!fp.pages.length) { el.innerHTML = `<div class="empty"><sl-icon name="file-earmark-x"></sl-icon><b>Not in a page index</b>This file is outside an indexed data room.</div>`; return; }
    el.innerHTML = `<div class="dim" style="font-size:12px;margin-bottom:8px">${fp.pages.length} pages indexed in ${esc(fp.room)}</div>` +
      fp.pages.map(p => `<div class="pg-h" id="pg-${p.page}">Page ${p.page}</div><pre class="pagetext ${p.page === page ? 'hit' : ''}">${p.page === page ? highlight(p.text, quote) : esc(p.text)}</pre>`).join('');
    if (page) $('#pv-tabs', d).addEventListener('sl-tab-show', e => { if (e.detail.name === 'text') setTimeout(() => $('#pg-' + page, d)?.scrollIntoView({ block: 'start' }), 50); });
  } catch (e) { $('#pv-pages', d).innerHTML = `<p class="dim">${esc(e.message)}</p>`; }
}

function csvTable(t) {
  const rows = t.trim().split('\n').slice(0, 500).map(r => r.split(','));
  return `<div class="tbl-wrap"><table class="t compact"><tr>${rows[0].map(c => `<th>${esc(c)}</th>`).join('')}</tr>${rows.slice(1).map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table></div>`;
}

export function downloadCSV(name, rows) {
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const cell = v => { const s = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s; };
  const blob = new Blob([[cols.join(','), ...rows.map(r => cols.map(c => cell(r[c])).join(','))].join('\n')], { type: 'text/csv' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export const empty = (icon, title, body = '') => `<div class="empty"><sl-icon name="${icon}"></sl-icon><b>${esc(title)}</b>${body}</div>`;
export const skeleton = (rows = 6) => `<div class="card"><div class="bd">${Array.from({ length: rows }, (_, i) => `<div class="shimmer sk" style="width:${92 - (i * 13) % 40}%"></div>`).join('')}</div></div>`;
