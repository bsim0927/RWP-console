// Analyst review of one gate (decisions G1, G2, C3, C4): agree, or override with the document and page relied
// on, always with a one-line reason; and the gate's manual checks, where a "no" fails the gate. Every save is a
// new record, so the history below the form is complete.
import { $, $$, api, cached, bust, esc, toast, resultChip, fmtDT } from './lib.js';

const KEY = 'sg.reviewer';
const getMe = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const setMe = v => { try { localStorage.setItem(KEY, v); } catch { /* storage blocked */ } };
const RESULTS = ['Pass', 'Fail', 'Incomplete'];

/** Plain-English state of a reviewed gate, for cards and the drawer header. */
export function reviewNote(eff) {
  if (!eff) return '';
  const pending = eff.pending_checks?.length ? `${eff.pending_checks.length} check${eff.pending_checks.length > 1 ? 's' : ''} to answer` : '';
  if (eff.source === 'override') return `Overridden by ${eff.review.reviewer} · pipeline said ${eff.pipeline_result}`;
  if (eff.source === 'check') return `Failed the ${eff.failed_checks.join(' and ')} check`;
  if (eff.reviewed) return `Agreed by ${eff.review.reviewer}${pending ? ' · ' + pending : ''}`;
  return pending;
}

export async function reviewPanel(box, { fundId, run, rec, eff, onSaved }) {
  const people = (await cached('reviewers', 60000)).filter(p => p.active);
  const saved = getMe();
  let me = people.some(p => p.id === saved) ? saved : people[0]?.id;
  let verdict = 'agree';
  const docs = [...new Set([...(rec.brief?.facts || []).map(f => f.file), ...(rec.pages_offered || []).map(p => p[0])])];
  const checks = rec.checks || [];
  const post = async (path, body) => {
    try {
      const out = await api(path, { method: 'POST', body: JSON.stringify({ fund: fundId, run, gate: rec.gate, reviewer: me, ...body }) });
      bust('funds');
      toast('Review saved', 'good');
      onSaved(out);
    } catch (e) { toast(esc(e.message), 'crit'); }
  };

  const draw = () => {
    const hist = eff?.history || [];
    box.innerHTML = `<div class="card" id="review"><div class="hd"><h2 class="sec">Analyst review</h2><span class="sec-sub">${esc(reviewNote(eff) || 'Not reviewed yet')}</span></div><div class="bd">
      ${people.length ? `<label class="rv-row"><span class="dim">Reviewing as</span><select class="fi" id="rv-me" style="max-width:220px">${people.map(p => `<option value="${esc(p.id)}" ${p.id === me ? 'selected' : ''}>${esc(p.name)}${p.role === 'cio' && p.name !== 'CIO' ? ' (CIO)' : ''}</option>`).join('')}</select></label>`
        : '<p class="dim">Add a reviewer under Gates and policy before reviewing.</p>'}
      ${checks.map(k => {
        const a = eff?.checks?.[k.id];
        return `<div class="rv-check" data-check="${esc(k.id)}"><div style="flex:1">${esc(k.q)}${a ? `<div class="dim" style="font-size:12px">${a.ok ? 'Yes' : 'No'} · ${esc(a.reviewer)}${a.note ? ' · ' + esc(a.note) : ''}</div>` : '<div class="dim" style="font-size:12px">Not answered</div>'}</div>
          <input class="fi" data-note aria-label="Note" placeholder="Note (optional)" style="max-width:200px"><div class="seg"><button data-ok="1" class="${a?.ok === true ? 'on' : ''}">Yes</button><button data-ok="0" class="${a?.ok === false ? 'on' : ''}">No</button></div></div>`;
      }).join('')}
      <div class="rv-row"><div class="seg" id="rv-verdict"><button data-v="agree" class="${verdict === 'agree' ? 'on' : ''}">Agree</button><button data-v="override" class="${verdict === 'override' ? 'on' : ''}">Override</button></div>
        ${verdict === 'override' ? `<select class="fi" id="rv-result" aria-label="Result" style="max-width:130px">${RESULTS.map(x => `<option>${x}</option>`).join('')}</select>
          <input class="fi" id="rv-doc" aria-label="Document relied on" list="rv-docs" placeholder="Document relied on" style="flex:1;min-width:160px"><datalist id="rv-docs">${docs.map(f => `<option value="${esc(f)}">`).join('')}</datalist>
          <input class="fi num" id="rv-page" aria-label="Page" type="number" min="1" placeholder="Page" style="max-width:80px">` : ''}</div>
      <div class="rv-row"><input class="fi" id="rv-reason" aria-label="Reason" placeholder="One-line reason" style="flex:1"><button class="glow-btn sm" id="rv-save" ${people.length ? '' : 'disabled'}><sl-icon name="check-lg"></sl-icon>Save review</button></div>
      ${hist.length ? `<div class="eyebrow" style="margin-top:12px">History</div>${hist.map(h => `<div class="rv-hist">${h.verdict === 'override' ? resultChip(h.result) : '<span class="chip good"><sl-icon name="check2"></sl-icon>Agreed</span>'}
        <div style="flex:1"><div>${esc(h.reason)}</div><div class="dim" style="font-size:12px">${esc(h.reviewer)} · ${fmtDT(h.at)}${h.document ? ` · ${esc(h.document.split('/').pop())} p.${h.page}` : ''}</div></div></div>`).join('')}` : ''}
    </div></div>`;
    $('#rv-me', box)?.addEventListener('change', e => { me = e.target.value; setMe(me); });
    $$('#rv-verdict button', box).forEach(b => b.addEventListener('click', () => { verdict = b.dataset.v; draw(); }));
    $$('.rv-check', box).forEach(row => $$('[data-ok]', row).forEach(b => b.addEventListener('click', () =>
      post('check', { check: row.dataset.check, ok: b.dataset.ok === '1', note: $('[data-note]', row).value }))));
    $('#rv-save', box).addEventListener('click', () => post('review', {
      verdict, reason: $('#rv-reason', box).value, result: $('#rv-result', box)?.value, document: $('#rv-doc', box)?.value, page: $('#rv-page', box)?.value,
    }));
  };
  draw();
}
