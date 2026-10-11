// Gates and policy: read the policy, and add, edit, reorder, remove or restore gates.
import { $, $$, api, bust, esc, gateName, gateColor, setGateOrder, skeleton, toast, fmtDT, stampDate } from '../lib.js';
import { setCrumbs } from '../app.js';

const WHEN = { any_review: 'Any gate needs analyst review', any_incomplete: 'Any gate is incomplete or not yet run', any_fail: 'Any gate is not met', otherwise: 'Otherwise' };
const RESULTS = ['Pass', 'Fail', 'Incomplete']; // sg/gate_store.RESULTS; anything more is a flag
const CHECK_NAMES = ['total_pct', 'fees_disagree']; // sg/gate_store.CHECK_NAMES
const DOC_TYPES = ['terms', 'offering document', 'governing agreement', 'subscription', 'ddq', 'deck', 'track record', 'policies/compliance', 'financial statements'];
const TEMPLATE = () => ({
  id: 'new_gate', version: 1,
  extractor: { sources: { doc_types: ['terms', 'offering document'], sections: [] }, keywords: [], rules: '', fields: [{ name: '', description: '' }] },
  questions: [{ id: 'sufficient', type: 'bool', q: '' }],
  derive: [{ if: 'sufficient < 0.7', then: 'Incomplete' }, { then: 'Pass' }],
});
let yamlLib;
const YAML = async () => (yamlLib ||= await import('/vendor/js-yaml/js-yaml.mjs'));
const clone = o => JSON.parse(JSON.stringify(o));

export async function render(el) {
  setCrumbs([['Gates and policy']]);
  el.innerHTML = `<div class="page">${skeleton(8)}</div>`;
  const [cfg, hist, people] = await Promise.all([api('config'), api('gates/history'), api('reviewers')]);
  setGateOrder(cfg.gates.map(g => g.parsed.id));
  const pol = cfg.policy.parsed;
  const reload = async () => { bust('config'); bust('funds'); await render(el); };

  el.innerHTML = `<div class="page">
    <div class="ph"><div><h1>Gates and policy</h1><p>Five hard gates, no weighted score. Each gate extracts quoted facts, a judge answers typed questions, and rules derive the result. Every edit is versioned and the previous file is kept, so any change can be restored.</p></div>
      <div class="act"><button class="glow-btn" id="new"><sl-icon name="plus-lg"></sl-icon>New gate</button></div></div>
    <div class="card" style="margin-bottom:14px" id="policy"><div class="hd"><h2 class="sec">Disposition policy</h2><span class="chip ghost mono">v${esc(cfg.policy.id)}</span><span class="sec-sub">ordered, first match wins</span><span class="sp"></span>
      <button class="ghost-btn sm" id="pol-hist"><sl-icon name="clock-history"></sl-icon>History</button>
      <button class="ghost-btn sm" id="pol-edit"><sl-icon name="pencil"></sl-icon>Edit</button></div><div class="bd flush">
      ${pol.rules.map((r, i) => `<div class="rule"><span class="i">${i + 1}</span><div style="flex:1"><code>${esc(r.when)}</code> <span class="dim">· ${esc(WHEN[r.when] || '')}</span></div><sl-icon name="arrow-right" class="dim"></sl-icon><div style="flex:1.3;font-weight:550">${esc(r.disposition)}</div></div>`).join('')}</div></div>
    <div class="stack">${cfg.gates.map((g, i) => gateCard(g, i, cfg.gates.length)).join('')}</div>
    <div class="card" style="margin-top:14px" id="reviewers"><div class="hd"><h2 class="sec">Reviewers</h2><span class="sec-sub">who reviews screen runs; the CIO also signs off "not covered"</span></div><div class="bd flush">
      <table class="t compact"><tr><th>Name</th><th>Role</th><th>Active</th><th></th></tr>${people.map(p => `<tr data-rid="${esc(p.id)}"><td><input class="fi" data-f="name" aria-label="Reviewer name" value="${esc(p.name)}" style="max-width:240px"></td>
        <td><select class="fi" data-f="role" aria-label="Role" style="max-width:140px"><option value="analyst" ${p.role === 'analyst' ? 'selected' : ''}>Analyst</option><option value="cio" ${p.role === 'cio' ? 'selected' : ''}>CIO</option></select></td>
        <td><input type="checkbox" class="fi-cb" data-f="active" aria-label="Active" ${p.active ? 'checked' : ''}></td><td class="n"><button class="ghost-btn sm" data-save-rv><sl-icon name="check-lg"></sl-icon>Save</button></td></tr>`).join('')}
      <tr><td><input class="fi" id="rv-new" aria-label="New reviewer name" placeholder="Add a reviewer by name" style="max-width:240px"></td><td></td><td></td><td class="n"><button class="ghost-btn sm" id="rv-add"><sl-icon name="plus-lg"></sl-icon>Add</button></td></tr></table></div></div>
    <div class="card" style="margin-top:14px"><div class="hd"><h2 class="sec">Change history</h2><span class="sec-sub">${hist.length} saved versions</span></div><div class="bd flush">
      ${hist.length ? `<table class="t compact"><tr><th>Saved</th><th>Gate</th><th>Version</th><th>Why</th><th></th></tr>${hist.slice(0, 40).map(h => `<tr><td class="tnum dim">${fmtDT(stampDate(h.stamp))}</td><td>${esc(gateName(h.id || h.gate_file))}</td><td class="mono">v${esc(h.version)}</td>
        <td>${h.reason === 'deleted' ? '<span class="chip crit"><sl-icon name="trash"></sl-icon>Removed</span>' : '<span class="chip ghost">Before an edit</span>'}</td>
        <td class="n"><button class="ghost-btn sm" data-view="${esc(h.file)}"><sl-icon name="eye"></sl-icon>View</button> <button class="ghost-btn sm" data-restore="${esc(h.file)}"><sl-icon name="arrow-counterclockwise"></sl-icon>Restore</button></td></tr>`).join('')}</table>`
        : '<div class="empty" style="padding:22px">No edits yet. Each save keeps the previous version here.</div>'}</div></div></div>`;

  $('#new', el).addEventListener('click', () => editor(null, TEMPLATE(), '', reload));
  const saveReviewer = async body => {
    try { await api('reviewers', { method: 'POST', body: JSON.stringify(body) }); bust('reviewers'); toast('Reviewer saved', 'good'); reload(); } catch (e) { toast(esc(e.message), 'crit'); }
  };
  $$('[data-save-rv]', el).forEach(b => b.addEventListener('click', () => {
    const tr = b.closest('tr');
    saveReviewer({ id: tr.dataset.rid, name: $('[data-f="name"]', tr).value, role: $('[data-f="role"]', tr).value, active: $('[data-f="active"]', tr).checked });
  }));
  $('#rv-add', el).addEventListener('click', () => saveReviewer({ name: $('#rv-new', el).value, role: 'analyst' }));
  $('#pol-edit', el).addEventListener('click', () => policyEditor(cfg.policy, reload));
  $('#pol-hist', el).addEventListener('click', () => policyHistory(reload));
  $$('[data-edit]', el).forEach(b => b.addEventListener('click', () => { const g = cfg.gates.find(x => x.file === b.dataset.edit); editor(g.file, g.parsed, g.text, reload); }));
  $$('[data-del]', el).forEach(b => b.addEventListener('click', () => confirmDelete(cfg.gates.find(x => x.file === b.dataset.del), reload)));
  $$('[data-move]', el).forEach(b => b.addEventListener('click', async () => {
    const order = cfg.gates.map(g => g.file), i = order.indexOf(b.dataset.move), j = i + +b.dataset.dir;
    [order[i], order[j]] = [order[j], order[i]];
    try { await api('gates/reorder', { method: 'POST', body: JSON.stringify({ order }) }); toast('Gate order saved', 'good'); reload(); } catch (e) { toast(esc(e.message), 'crit'); }
  }));
  $$('[data-restore]', el).forEach(b => b.addEventListener('click', async () => {
    try { const r = await api('gates/restore', { method: 'POST', body: JSON.stringify({ file: b.dataset.restore }) }); toast(`Restored as <b>${esc(r.file)}</b>`, 'good'); reload(); } catch (e) { toast(esc(e.message), 'crit'); }
  }));
  $$('[data-view]', el).forEach(b => b.addEventListener('click', () => {
    const h = hist.find(x => x.file === b.dataset.view), d = $('#drawer');
    d.classList.remove('wide'); d.label = `${h.gate_file} · v${h.version}`;
    d.innerHTML = `<pre class="code">${esc(h.text)}</pre>`; d.show();
  }));
}

function gateCard(g, i, total) {
  const p = g.parsed, ex = p.extractor || {};
  return `<div class="card"><div class="hd"><span class="tier" style="background:${gateColor(p.id)};width:10px;height:10px"></span><h2 class="sec">Gate ${i + 1} · ${esc(gateName(p.id))}</h2><span class="chip ghost mono">v${esc(p.version)}</span>
    ${p.static_result ? `<span class="chip warn"><sl-icon name="hand-index"></sl-icon>Manual: ${esc(p.static_result)}</span>` : ''}<span class="dim mono" style="font-size:11.5px">${esc(g.file)}</span><span class="sp"></span>
    <button class="ghost-btn sm" data-move="${esc(g.file)}" data-dir="-1" ${i === 0 ? 'disabled' : ''} title="Move up"><sl-icon name="arrow-up"></sl-icon></button>
    <button class="ghost-btn sm" data-move="${esc(g.file)}" data-dir="1" ${i === total - 1 ? 'disabled' : ''} title="Move down"><sl-icon name="arrow-down"></sl-icon></button>
    <button class="ghost-btn sm" data-edit="${esc(g.file)}"><sl-icon name="pencil"></sl-icon>Edit</button>
    <button class="ghost-btn sm" data-del="${esc(g.file)}" title="Remove gate"><sl-icon name="trash"></sl-icon></button></div>
    <div class="bd">${p.static_result ? `<p class="muted" style="margin:0">${esc((g.text.match(/^#\s*(.*)$/m) || [])[1] || 'Not automated: the gate returns its manual result until an analyst closes it.')}</p>` : `
      <div class="grid g2"><div>
        <div class="eyebrow">Fields extracted</div><table class="t compact">${(ex.fields || []).map(f => `<tr><td class="mono">${esc(f.name)}${f.recurring ? ' <span class="chip ghost" style="height:18px">recurring</span>' : ''}</td><td class="dim">${esc(f.description || '')}${f.ask ? `<div class="sub">If missing, ask for: ${esc(f.ask)}</div>` : ''}</td></tr>`).join('')}</table>
        ${ex.sources ? `<div class="eyebrow" style="margin-top:14px">Sources</div><div style="display:flex;gap:5px;flex-wrap:wrap">${(ex.sources.doc_types || []).map(d => `<span class="chip ghost">${esc(d)}</span>`).join('')}</div>` : ''}
      </div><div>
        <div class="eyebrow">Judge questions</div>${(p.questions || []).map(qq => `<div style="margin-bottom:8px"><span class="mono dim">${esc(qq.id)} · ${esc(qq.type)}${qq.options ? ` · ${esc(qq.options.join(' / '))}` : ''}</span><div>${esc(qq.q)}</div></div>`).join('')}
        <div class="eyebrow" style="margin-top:14px">Derive rules</div>${(p.derive || []).map((d, k) => `<div class="rule" style="padding:6px 0"><span class="i">${k + 1}</span><code>${esc(d.if ?? 'otherwise')}</code><sl-icon name="arrow-right" class="dim"></sl-icon><b style="font-weight:550">${esc(d.then)}</b></div>`).join('')}
        ${p.flags?.length ? `<div class="eyebrow" style="margin-top:14px">Flags</div>${p.flags.map(f => `<div class="rule" style="padding:6px 0"><sl-icon name="flag" class="dim"></sl-icon><code>${esc(f.if ?? 'always')}</code><sl-icon name="arrow-right" class="dim"></sl-icon><b style="font-weight:550">${esc(f.flag)}</b></div>`).join('')}` : ''}
        ${p.checks?.length ? `<div class="eyebrow" style="margin-top:14px">Analyst checks</div>${p.checks.map(k => `<div class="rule" style="padding:6px 0"><sl-icon name="person-check" class="dim"></sl-icon><span>${esc(k.q)}</span><span class="dim" style="font-size:12px">a no fails the gate</span></div>`).join('')}` : ''}
        <div class="dim" style="font-size:12px;margin-top:8px">Review below confidence ${esc(p.review_if?.min_confidence ?? 0.75)}${p.review_if?.decisive ? ` on ${esc(p.review_if.decisive.join(', '))}` : ''}</div>
      </div></div>`}</div></div>`;
}

function confirmDelete(g, done) {
  const d = document.createElement('sl-dialog');
  d.label = 'Remove gate';
  d.innerHTML = `<p style="margin-top:0">Remove <b>${esc(gateName(g.parsed.id))}</b> from the screen? New runs will not evaluate it. Past runs keep their results.</p>
    <p class="dim" style="font-size:12.5px">A copy is kept in the change history and can be restored.</p>
    <div slot="footer" style="display:flex;gap:8px;justify-content:flex-end"><button class="ghost-btn" data-x>Cancel</button><button class="ghost-btn" data-go style="border-color:var(--crit);color:#f3a3a3"><sl-icon name="trash"></sl-icon>Remove gate</button></div>`;
  document.body.append(d);
  d.addEventListener('sl-after-hide', e => { if (e.target === d) d.remove(); });
  d.querySelector('[data-x]').onclick = () => d.hide();
  d.querySelector('[data-go]').onclick = async () => {
    try { await api('gates/' + encodeURIComponent(g.file), { method: 'DELETE' }); d.hide(); toast(`Removed <b>${esc(g.parsed.id)}</b>. Restore it from the change history.`, 'good'); done(); }
    catch (e) { toast(esc(e.message), 'crit'); }
  };
  customElements.whenDefined('sl-dialog').then(() => requestAnimationFrame(() => d.show()));
}

// ---------- policy ----------
const DISPOSITIONS = ['Under review (analyst to confirm one or more gates)', 'Under review (gates that cannot be closed are named)',
  'Reviewed and not covered (draft, name the failed gate)', 'Coverable, subject to conditions'];

async function policyEditor(policy, done) {
  const Y = await YAML();
  let rules = clone(policy.parsed.rules || []), mode = 'form', yamlText = policy.text, valid = { errors: [], warnings: [] };
  const hadComments = /(^|\s)#/.test(policy.text);
  const d = $('#drawer');
  d.classList.add('wide');
  d.label = `Edit disposition policy · v${policy.id}`;
  d.innerHTML = `<div id="pe-status"></div>
    <div class="bar"><div class="seg" id="pe-mode"><button class="on" data-m="form">Form</button><button data-m="yaml">YAML</button></div><span class="sp"></span>
      <span class="dim" style="font-size:12px" id="pe-ver"></span>
      <button class="ghost-btn" id="pe-cancel">Cancel</button><button class="glow-btn" id="pe-save"><sl-icon name="check-lg"></sl-icon>Save policy</button></div>
    <div id="pe-body"></div>`;
  d.show();
  const body = $('#pe-body', d);
  const textNow = () => (mode === 'yaml' ? yamlText : Y.dump({ rules }, { lineWidth: 110 }));
  const rowBtns = (i, n) => `<span class="ed-rb"><button class="icon-btn" data-mv="${i}" data-d="-1" ${i === 0 ? 'disabled' : ''} title="Up"><sl-icon name="arrow-up"></sl-icon></button><button class="icon-btn" data-mv="${i}" data-d="1" ${i === n - 1 ? 'disabled' : ''} title="Down"><sl-icon name="arrow-down"></sl-icon></button><button class="icon-btn" data-rm="${i}" title="Remove"><sl-icon name="x-lg"></sl-icon></button></span>`;

  function drawForm() {
    body.innerHTML = `<div class="ed-sec"><div class="ed-h">Rules<small>checked top to bottom; the first condition that holds sets the disposition</small><span class="sp"></span><button class="ghost-btn sm" data-add><sl-icon name="plus-lg"></sl-icon>Rule</button></div>
      ${rules.map((r, i) => `<div class="ed-row"><span class="i rule-i">${i + 1}</span><span class="dim" style="font-size:12px">when</span>
        <select class="fi" data-k="when" data-i="${i}" style="max-width:300px">${Object.entries(WHEN).map(([k, label]) => `<option value="${k}" ${r.when === k ? 'selected' : ''}>${esc(label)}</option>`).join('')}${r.when in WHEN ? '' : `<option selected value="${esc(r.when ?? '')}">${esc(r.when ?? '(choose)')}</option>`}</select>
        <span class="dim" style="font-size:12px">then</span><input class="fi" list="pe-disp" data-k="disposition" data-i="${i}" value="${esc(r.disposition ?? '')}">${rowBtns(i, rules.length)}</div>`).join('')}
      <datalist id="pe-disp">${DISPOSITIONS.map(x => `<option value="${esc(x)}">`).join('')}</datalist></div>`;
  }
  function drawYaml() {
    body.innerHTML = `<textarea class="fi" data-mono id="pe-yaml" spellcheck="false" style="min-height:50vh;font-size:12.5px;line-height:1.6">${esc(yamlText)}</textarea>
      <p class="dim" style="font-size:12px">Saving from this tab writes the text exactly as shown, comments included.</p>`;
  }
  const draw = () => (mode === 'form' ? drawForm() : drawYaml());

  body.addEventListener('input', e => {
    const t = e.target;
    if (t.id === 'pe-yaml') yamlText = t.value;
    else if (t.dataset.k) rules[+t.dataset.i][t.dataset.k] = t.value;
    schedule();
  });
  body.addEventListener('click', e => {
    const add = e.target.closest('[data-add]'), mv = e.target.closest('[data-mv]'), rm = e.target.closest('[data-rm]');
    if (add) { const last = rules.at(-1); rules = last?.when === 'otherwise' ? [...rules.slice(0, -1), { when: 'any_fail', disposition: '' }, last] : [...rules, { when: 'otherwise', disposition: '' }]; }
    if (mv) { const i = +mv.dataset.mv, j = i + +mv.dataset.d; [rules[i], rules[j]] = [rules[j], rules[i]]; }
    if (rm) rules.splice(+rm.dataset.rm, 1);
    if (add || mv || rm) { drawForm(); schedule(); }
  });
  $$('#pe-mode button', d).forEach(b => b.addEventListener('click', () => {
    if (b.dataset.m === mode) return;
    if (b.dataset.m === 'yaml') { if (JSON.stringify(rules) !== JSON.stringify(policy.parsed.rules)) yamlText = Y.dump({ rules }, { lineWidth: 110 }); }
    else {
      try { const parsed = Y.load(yamlText) || {}; rules = Array.isArray(parsed.rules) ? parsed.rules : []; }
      catch (err) { toast('Fix the YAML before switching: ' + esc(err.message), 'crit'); return; }
    }
    mode = b.dataset.m;
    $$('#pe-mode button', d).forEach(x => x.classList.toggle('on', x === b));
    draw();
  }));
  $('#pe-cancel', d).addEventListener('click', () => d.hide());

  let timer;
  function schedule() { clearTimeout(timer); timer = setTimeout(check, 300); }
  async function check() {
    try { valid = await api('policy/validate', { method: 'POST', body: JSON.stringify({ text: textNow() }) }); } catch (e) { valid = { errors: [e.message], warnings: [] }; }
    const changed = mode === 'yaml' ? yamlText !== policy.text : JSON.stringify(rules) !== JSON.stringify(policy.parsed.rules);
    $('#pe-ver', d).textContent = changed ? 'saves as a new version' : `v${policy.id} · no changes`;
    $('#pe-status', d).innerHTML = valid.errors.length ? `<sl-alert variant="danger" open style="margin-bottom:12px"><sl-icon slot="icon" name="exclamation-octagon"></sl-icon><b>Fix before saving</b><ul style="margin:6px 0 0;padding-left:18px">${valid.errors.map(x => `<li>${esc(x)}</li>`).join('')}</ul></sl-alert>`
      : valid.warnings.length ? `<sl-alert variant="warning" open style="margin-bottom:12px"><sl-icon slot="icon" name="exclamation-triangle"></sl-icon>${valid.warnings.map(esc).join('<br>')}</sl-alert>`
      : `<div class="dim" style="font-size:12px;margin-bottom:10px;display:flex;gap:6px;align-items:center"><sl-icon name="check2-circle" style="color:var(--good)"></sl-icon>Valid${mode === 'form' && hadComments && changed ? ' · saving from the form rewrites the YAML without its comments; use the YAML tab to keep them' : ''}</div>`;
    $('#pe-save', d).disabled = !!valid.errors.length || !changed;
  }
  $('#pe-save', d).addEventListener('click', async () => {
    try {
      const r = await api('policy', { method: 'PUT', body: JSON.stringify({ text: textNow() }) });
      d.hide();
      toast(`Saved the disposition policy as <b>v${esc(r.id)}</b>. New runs use it; past runs keep the version they ran under.`, 'good');
      done();
    } catch (e) { toast(esc(e.message), 'crit'); }
  });
  draw();
  check();
}

async function policyHistory(done) {
  const hist = await api('policy/history');
  const d = $('#drawer');
  d.classList.remove('wide');
  d.label = 'Disposition policy · history';
  const list = () => `<table class="t compact"><tr><th>Version</th><th>Saved</th><th></th></tr>${hist.map(h => `<tr><td class="mono">v${esc(h.id)} ${h.current ? '<span class="chip good">In force</span>' : ''}</td><td class="tnum dim">${fmtDT(stampDate(h.stamp))}</td>
    <td class="n"><button class="ghost-btn sm" data-pv="${esc(h.id)}"><sl-icon name="eye"></sl-icon>View</button>${h.current ? '' : ` <button class="ghost-btn sm" data-pr="${esc(h.id)}"><sl-icon name="arrow-counterclockwise"></sl-icon>Restore</button>`}</td></tr>`).join('')}</table>`;
  d.innerHTML = list();
  d.onclick = async e => {
    const view = e.target.closest('[data-pv]'), back = e.target.closest('[data-back]'), restore = e.target.closest('[data-pr]');
    if (view) { const h = hist.find(x => String(x.id) === view.dataset.pv); d.innerHTML = `<div class="bar" style="margin-bottom:10px"><button class="ghost-btn sm" data-back><sl-icon name="arrow-left"></sl-icon>All versions</button><span class="sp"></span><span class="mono dim">v${esc(h.id)}</span></div><pre class="code">${esc(h.text)}</pre>`; }
    if (back) d.innerHTML = list();
    if (restore) {
      try { const r = await api('policy/restore', { method: 'POST', body: JSON.stringify({ id: +restore.dataset.pr }) }); d.hide(); toast(`Restored v${esc(restore.dataset.pr)} as <b>v${esc(r.id)}</b>`, 'good'); done(); }
      catch (err) { toast(esc(err.message), 'crit'); }
    }
  };
  d.addEventListener('sl-after-hide', () => { d.onclick = null; }, { once: true });
  d.show();
}

// ---------- editor ----------
async function editor(file, parsed, text, done) {
  const Y = await YAML();
  let g = clone(parsed), mode = 'form', yamlText = text || Y.dump(g, { lineWidth: 110, flowLevel: 3 }), dirtyYaml = false, valid = { errors: [], warnings: [] };
  const hadComments = /(^|\s)#/.test(text || '');
  const d = $('#drawer');
  d.classList.add('wide');
  d.label = file ? `Edit gate · ${file}` : 'New gate';
  d.innerHTML = `<div id="ed-status"></div>
    <div class="bar"><div class="seg" id="ed-mode"><button class="on" data-m="form">Form</button><button data-m="yaml">YAML</button></div><span class="sp"></span>
      <span class="dim" style="font-size:12px" id="ed-ver"></span>
      <button class="ghost-btn" id="ed-cancel">Cancel</button><button class="glow-btn" id="ed-save"><sl-icon name="check-lg"></sl-icon>${file ? 'Save gate' : 'Create gate'}</button></div>
    <div id="ed-body"></div>`;
  d.show();
  const body = $('#ed-body', d);

  const set = (obj, path, v) => { const ks = path.split('.'); let o = obj; ks.slice(0, -1).forEach((k, i) => { o = o[k] ??= /^\d+$/.test(ks[i + 1]) ? [] : {}; }); o[ks.at(-1)] = v; };
  const get = (obj, path) => path.split('.').reduce((o, k) => o?.[k], obj);
  const val = (path, t) => { const v = get(g, path); return t === 'list' ? (v || []).join(', ') : t === 'lines' ? (v || []).join('\n') : v ?? ''; };
  const inp = (path, t = '', ph = '', extra = '') => `<input class="fi ${t === 'num' ? 'num' : ''}" data-k="${path}" data-t="${t}" placeholder="${esc(ph)}" value="${esc(val(path, t))}" ${extra}>`;
  const area = (path, t = '', ph = '', rows = 2) => `<textarea class="fi" rows="${rows}" data-k="${path}" data-t="${t}" placeholder="${esc(ph)}">${esc(val(path, t))}</textarea>`;
  const rowBtns = (list, i, n) => `<span class="ed-rb"><button class="icon-btn" data-mv="${list}" data-i="${i}" data-d="-1" ${i === 0 ? 'disabled' : ''} title="Up"><sl-icon name="arrow-up"></sl-icon></button><button class="icon-btn" data-mv="${list}" data-i="${i}" data-d="1" ${i === n - 1 ? 'disabled' : ''} title="Down"><sl-icon name="arrow-down"></sl-icon></button><button class="icon-btn" data-rm="${list}" data-i="${i}" title="Remove"><sl-icon name="x-lg"></sl-icon></button></span>`;

  function drawForm() {
    const manual = !!g.static_result;
    const qs = g.questions || [], fields = g.extractor?.fields || [], rules = g.derive || [], flags = g.flags || [], checks = g.checks || [];
    const names = [...qs.map(q => q.id), ...qs.filter(q => q.type === 'choice').map(q => q.id + '_p'), ...CHECK_NAMES].filter(Boolean);
    body.innerHTML = `
      <div class="ed-sec"><div class="ed-h">Gate</div><div class="ed-grid">
        <label>Id<small>lowercase_with_underscores; shown as “${esc(gateName(g.id || ''))}”</small>${inp('id', '', 'e.g. key_person')}</label>
        <label>Manual gate<small>no extraction or judge; returns a fixed result</small><span><input type="checkbox" class="fi-cb" data-k="__manual" ${manual ? 'checked' : ''}> Not automated</span></label>
        ${manual ? `<label style="grid-column:span 2">Manual result${inp('static_result', '', 'Not yet run')}</label>` : ''}</div></div>
      ${manual ? '' : `
      <div class="ed-sec"><div class="ed-h">Retrieval<small>which pages the extractor reads</small></div><div class="ed-grid">
        <label>Document types<small>priority order, comma separated · known: ${DOC_TYPES.join(', ')}</small>${inp('extractor.sources.doc_types', 'list', 'terms, offering document')}</label>
        <label>Keywords<small>fallback when no catalog section matches</small>${inp('extractor.keywords', 'list', 'key person, key man')}</label>
        <label>Section title patterns<small>one regular expression per line</small>${area('extractor.sources.sections', 'lines', 'key (person|man)', 3)}</label>
        <label>Instructions to the extractor${area('extractor.rules', '', 'Quote the clause that…', 3)}</label></div></div>
      <div class="ed-sec"><div class="ed-h">Fields to extract<small>each becomes a cited fact with a verbatim quote</small><span class="sp"></span><button class="ghost-btn sm" data-add="fields"><sl-icon name="plus-lg"></sl-icon>Field</button></div>
        ${fields.map((f, i) => `<div class="ed-row">${inp(`extractor.fields.${i}.name`, '', 'field_name', 'style="max-width:220px" data-mono')}${inp(`extractor.fields.${i}.description`, '', 'What to find')}${inp(`extractor.fields.${i}.ask`, '', 'If missing, ask the manager for…', 'title="Goes on the screen note\'s request list when this field keeps the gate open"')}
          <label class="ed-inline" title="Summed into total_pct by the code check"><input type="checkbox" class="fi-cb" data-k="extractor.fields.${i}.recurring" data-t="bool" ${f.recurring ? 'checked' : ''}>recurring %</label>${rowBtns('extractor.fields', i, fields.length)}</div>`).join('')}</div>
      <div class="ed-sec"><div class="ed-h">Judge questions<small>bool gives P(true); choice gives the top option and its probability as id_p</small><span class="sp"></span><button class="ghost-btn sm" data-add="questions"><sl-icon name="plus-lg"></sl-icon>Question</button></div>
        ${qs.map((q, i) => `<div class="ed-row" style="align-items:flex-start">${inp(`questions.${i}.id`, '', 'question_id', 'style="max-width:170px" data-mono')}
          <select class="fi" data-k="questions.${i}.type" style="max-width:100px"><option ${q.type === 'bool' ? 'selected' : ''}>bool</option><option ${q.type === 'choice' ? 'selected' : ''}>choice</option></select>
          <div style="flex:1;display:flex;flex-direction:column;gap:6px">${area(`questions.${i}.q`, '', 'Do `facts` state…?', 2)}${q.type === 'choice' ? inp(`questions.${i}.options`, 'list', 'options, comma separated: net, gross, not_stated') : ''}</div>${rowBtns('questions', i, qs.length)}</div>`).join('')}</div>
      <div class="ed-sec"><div class="ed-h">Derive rules<small>checked top to bottom, first true condition sets the result · names: ${names.map(x => `<code>${esc(x)}</code>`).join(' ')}</small><span class="sp"></span><button class="ghost-btn sm" data-add="derive"><sl-icon name="plus-lg"></sl-icon>Rule</button></div>
        ${rules.map((r, i) => `<div class="ed-row"><span class="i rule-i">${i + 1}</span><span class="dim" style="font-size:12px">if</span>${inp(`derive.${i}.if`, 'expr', 'otherwise (leave empty)', 'data-mono')}<span class="dim" style="font-size:12px">then</span>
          <input class="fi" list="results" data-k="derive.${i}.then" value="${esc(r.then || '')}" style="max-width:220px">${rowBtns('derive', i, rules.length)}</div>`).join('')}
        <datalist id="results">${RESULTS.map(x => `<option value="${x}">`).join('')}</datalist></div>
      <div class="ed-sec"><div class="ed-h">Flags<small>every flag whose condition holds is shown with the result, e.g. QP-only · same names as the rules · empty condition means always</small><span class="sp"></span><button class="ghost-btn sm" data-add="flags"><sl-icon name="plus-lg"></sl-icon>Flag</button></div>
        ${flags.map((f, i) => `<div class="ed-row"><sl-icon name="flag" class="dim"></sl-icon><span class="dim" style="font-size:12px">if</span>${inp(`flags.${i}.if`, 'expr', 'always (leave empty)', 'data-mono')}<span class="dim" style="font-size:12px">flag</span>
          ${inp(`flags.${i}.flag`, '', 'e.g. QP-only', 'style="max-width:260px"')}${rowBtns('flags', i, flags.length)}</div>`).join('')}</div>
      <div class="ed-sec"><div class="ed-h">Analyst checks<small>yes/no questions only the analyst answers on each screen · a no fails the gate</small><span class="sp"></span><button class="ghost-btn sm" data-add="checks"><sl-icon name="plus-lg"></sl-icon>Check</button></div>
        ${checks.map((k, i) => `<div class="ed-row">${inp(`checks.${i}.id`, '', 'check_id', 'style="max-width:170px" data-mono')}${inp(`checks.${i}.q`, '', 'Can the position be custodied?')}${rowBtns('checks', i, checks.length)}</div>`).join('')}</div>
      <div class="ed-sec"><div class="ed-h">Analyst review</div><div class="ed-grid">
        <label>Review below confidence<small>a decisive answer under this goes to an analyst</small>${inp('review_if.min_confidence', 'num', '0.75', 'type="number" step="0.05" min="0" max="1"')}</label>
        <label>Decisive questions<small>none ticked means all questions</small><span style="display:flex;gap:12px;flex-wrap:wrap">${qs.filter(q => q.id).map(q => `<label class="ed-inline"><input type="checkbox" class="fi-cb" data-dec="${esc(q.id)}" ${(g.review_if?.decisive || []).includes(q.id) ? 'checked' : ''}>${esc(q.id)}</label>`).join('') || '<span class="dim">add questions first</span>'}</span></label></div></div>`}`;
  }
  function drawYaml() {
    body.innerHTML = `${hadComments && !dirtyYaml ? '' : ''}<textarea class="fi" data-mono id="ed-yaml" spellcheck="false" style="min-height:62vh;font-size:12.5px;line-height:1.6">${esc(yamlText)}</textarea>
      <p class="dim" style="font-size:12px">Saving from this tab writes the text exactly as shown, comments included.</p>`;
  }
  const draw = () => (mode === 'form' ? drawForm() : drawYaml());

  // form -> object
  body.addEventListener('input', e => {
    const t = e.target;
    if (t.id === 'ed-yaml') { yamlText = t.value; dirtyYaml = true; schedule(); return; }
    if (t.dataset.dec !== undefined) {
      const dec = $$('[data-dec]', body).filter(x => x.checked).map(x => x.dataset.dec);
      g.review_if ||= {}; if (dec.length) g.review_if.decisive = dec; else delete g.review_if.decisive;
    } else if (t.dataset.k === '__manual') {
      if (t.checked) g.static_result = g.static_result || 'Not yet run'; else delete g.static_result;
      if (!t.checked && !g.extractor) Object.assign(g, { ...TEMPLATE(), id: g.id, version: g.version });
      drawForm();
    } else if (t.dataset.k) {
      const k = t.dataset.k, ty = t.dataset.t;
      let v = ty === 'bool' ? t.checked : t.value;
      if (ty === 'list') v = t.value.split(',').map(x => x.trim()).filter(Boolean);
      if (ty === 'lines') v = t.value.split('\n').map(x => x.trim()).filter(Boolean);
      if (ty === 'num') v = t.value === '' ? undefined : +t.value;
      if (ty === 'expr' && !t.value.trim()) v = undefined;
      set(g, k, v);
      if (/^questions\.\d+\.type$/.test(k)) { const q = get(g, k.replace(/\.type$/, '')); if (v === 'choice') q.options ||= []; else delete q.options; drawForm(); }
    }
    dirtyYaml = false;
    schedule();
  });
  body.addEventListener('click', e => {
    const add = e.target.closest('[data-add]')?.dataset.add, mv = e.target.closest('[data-mv]'), rm = e.target.closest('[data-rm]');
    if (add === 'fields') (g.extractor ||= {}).fields = [...(g.extractor.fields || []), { name: '', description: '' }];
    if (add === 'checks') g.checks = [...(g.checks || []), { id: '', q: '' }];
    if (add === 'flags') g.flags = [...(g.flags || []), { if: '', flag: '' }];
    if (add === 'questions') g.questions = [...(g.questions || []), { id: '', type: 'bool', q: '' }];
    if (add === 'derive') { const r = g.derive || []; const last = r.at(-1); g.derive = last && last.if == null ? [...r.slice(0, -1), { if: '', then: 'Incomplete' }, last] : [...r, { if: '', then: 'Pass' }]; }
    if (mv) { const arr = get(g, mv.dataset.mv), i = +mv.dataset.i, j = i + +mv.dataset.d; [arr[i], arr[j]] = [arr[j], arr[i]]; }
    if (rm) get(g, rm.dataset.rm).splice(+rm.dataset.i, 1);
    if (add || mv || rm) { dirtyYaml = false; drawForm(); schedule(); }
  });
  $$('#ed-mode button', d).forEach(b => b.addEventListener('click', () => {
    if (b.dataset.m === mode) return;
    if (b.dataset.m === 'yaml') { if (!dirtyYaml) yamlText = sameAsOriginal() ? text : Y.dump(clean(g), { lineWidth: 110, flowLevel: 3 }); }
    else { try { g = Y.load(yamlText) || {}; } catch (err) { toast('Fix the YAML before switching: ' + esc(err.message), 'crit'); return; } }
    mode = b.dataset.m;
    $$('#ed-mode button', d).forEach(x => x.classList.toggle('on', x === b));
    draw();
  }));
  const sameAsOriginal = () => text && JSON.stringify(clean(g)) === JSON.stringify(clean(parsed));
  $('#ed-cancel', d).addEventListener('click', () => d.hide());

  let timer;
  function schedule() { clearTimeout(timer); timer = setTimeout(check, 350); }
  async function check() {
    const payload = mode === 'yaml' ? { text: yamlText } : { gate: clean(g) };
    try { valid = await api('gates/validate', { method: 'POST', body: JSON.stringify({ ...payload, file }) }); } catch (e) { valid = { errors: [e.message], warnings: [] }; }
    const changed = mode === 'yaml' ? yamlText !== text : !sameAsOriginal();
    $('#ed-ver', d).textContent = file ? (changed ? `saves as v${(+parsed.version || 0) + 1}` : `v${parsed.version} · no changes`) : 'starts at v1';
    $('#ed-status', d).innerHTML = valid.errors.length ? `<sl-alert variant="danger" open style="margin-bottom:12px"><sl-icon slot="icon" name="exclamation-octagon"></sl-icon><b>Fix before saving</b><ul style="margin:6px 0 0;padding-left:18px">${valid.errors.map(x => `<li>${esc(x)}</li>`).join('')}</ul></sl-alert>`
      : valid.warnings.length ? `<sl-alert variant="warning" open style="margin-bottom:12px"><sl-icon slot="icon" name="exclamation-triangle"></sl-icon>${valid.warnings.map(esc).join('<br>')}</sl-alert>`
      : `<div class="dim" style="font-size:12px;margin-bottom:10px;display:flex;gap:6px;align-items:center"><sl-icon name="check2-circle" style="color:var(--good)"></sl-icon>Valid${mode === 'form' && hadComments && changed ? ' · saving from the form rewrites the YAML without its comments; use the YAML tab to keep them' : ''}</div>`;
    $('#ed-save', d).disabled = !!valid.errors.length || (file && !changed);
  }
  $('#ed-save', d).addEventListener('click', async () => {
    const payload = mode === 'yaml' ? { text: yamlText } : { gate: clean(g) };
    try {
      const r = await api(file ? 'gates/' + encodeURIComponent(file) : 'gates', { method: file ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      d.hide();
      toast(file ? `Saved <b>${esc(r.file)}</b>${r.version ? ` as v${r.version}` : ''}` : `Created <b>${esc(r.file)}</b>`, 'good');
      done();
    } catch (e) { toast(esc(e.message), 'crit'); }
  });
  draw();
  check();
}

// Drop empty optional values so the saved YAML stays tidy.
function clean(g) {
  const o = clone(g);
  const ex = o.extractor;
  if (ex) {
    if (ex.sources) { for (const k of Object.keys(ex.sources)) if (Array.isArray(ex.sources[k]) && !ex.sources[k].length) delete ex.sources[k]; if (!Object.keys(ex.sources).length) delete ex.sources; }
    if (Array.isArray(ex.keywords) && !ex.keywords.length) delete ex.keywords;
    if (ex.rules === '') delete ex.rules;
    (ex.fields || []).forEach(f => { if (!f.recurring) delete f.recurring; if (f.description === '') delete f.description; if (!f.ask) delete f.ask; });
  }
  (o.derive || []).forEach(r => { if (r.if === '' || r.if == null) delete r.if; });
  (o.flags || []).forEach(f => { if (f.if === '' || f.if == null) delete f.if; });
  if (Array.isArray(o.flags) && !o.flags.length) delete o.flags;
  if (Array.isArray(o.checks) && !o.checks.length) delete o.checks;
  if (o.review_if) { if (o.review_if.min_confidence == null) delete o.review_if.min_confidence; if (!Object.keys(o.review_if).length) delete o.review_if; }
  if (o.static_result) { delete o.extractor; delete o.questions; delete o.derive; delete o.review_if; delete o.flags; delete o.checks; }
  return o;
}
