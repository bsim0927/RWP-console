import { $, api, cached, esc, q, openPreview, empty } from '../lib.js';
import { setCrumbs } from '../app.js';

export async function render(el, r) {
  setCrumbs([['Document search']]);
  el.innerHTML = `<div class="page"><div class="ph"><div><h1>Document search</h1><p>Full text across every indexed page in every data room. All words must appear on the page.</p></div></div><div id="sp"></div></div>`;
  await searchPanel($('#sp', el), { q: r.query.q || '', fund: r.query.fund || '', page: true });
}

export async function searchPanel(box, { q: initial = '', fund = '', page = false }) {
  const funds = await cached('funds');
  box.innerHTML = `<div class="bar">
    <sl-input id="sq" placeholder="management fee, key person, side letter…" clearable value="${esc(initial)}" style="flex:1;min-width:260px"><sl-icon name="search" slot="prefix"></sl-icon></sl-input>
    ${page ? `<sl-select id="sf" placeholder="All data rooms" clearable value="${esc(fund)}" style="width:300px">${funds.map(f => `<sl-option value="${esc(f.id)}">${esc(f.name)}</sl-option>`).join('')}</sl-select>` : ''}
    <button class="glow-btn" id="sgo"><sl-icon name="search"></sl-icon>Search</button></div><div id="sres"></div>`;
  const run = async () => {
    const term = $('#sq', box).value.trim();
    const scope = page ? $('#sf', box).value : fund;
    if (page) history.replaceState(null, '', '#/search?' + q(Object.fromEntries(Object.entries({ q: term, fund: scope }).filter(([, v]) => v))));
    const res = $('#sres', box);
    if (!term) { res.innerHTML = `<div class="card">${empty('search', 'Search the data rooms', 'Results link straight to the page, with the words highlighted.')}</div>`; return; }
    res.innerHTML = `<div class="card"><div class="bd"><div class="shimmer sk"></div><div class="shimmer sk" style="width:70%"></div></div></div>`;
    let hits;
    try { hits = await api('search?' + q({ q: term, ...(scope ? { fund: scope } : {}) })); } catch (e) { res.innerHTML = `<div class="card">${empty('exclamation-octagon', 'Search failed', esc(e.message))}</div>`; return; }
    const words = term.split(/\s+/).filter(w => w.length > 1).map(w => w.replace(/[^\w]/g, '')).filter(Boolean);
    const hl = s => words.length ? esc(s).replace(new RegExp(`(${words.join('|')})`, 'gi'), '<mark>$1</mark>') : esc(s);
    const rooms = new Set(hits.map(h => h.room));
    const named = hits.filter(h => h.by_name).length;
    res.innerHTML = hits.length ? `<div class="card"><div class="hd"><h2 class="sec">${named ? `${named} file${named > 1 ? 's' : ''} by name · ` : ''}${hits.length - named}${hits.length === 80 ? '+' : ''} pages</h2><span class="sec-sub">in ${rooms.size} data room${rooms.size > 1 ? 's' : ''}, ranked by term count</span></div><div class="bd flush">
      ${hits.map((h, i) => `<div class="hit-card" data-i="${i}"><div class="f"><sl-icon name="file-earmark-pdf" style="color:#e66767"></sl-icon><b style="font-weight:550">${esc(h.file.split('/').pop())}</b>${h.by_name ? `<span class="chip ghost">file name</span><span class="dim mono" style="font-size:11px">${hl(h.file)}</span>` : `<span class="chip ghost">p.${h.page}</span>`}<span class="sp"></span>${!fund ? `<span class="dim" style="font-size:12px">${esc(h.room)}</span>` : ''}</div>
        <div class="s">…${hl(h.snippet)}…</div></div>`).join('')}</div></div>` : `<div class="card">${empty('search', 'No pages match', 'Try fewer words.')}</div>`;
    res.querySelectorAll('.hit-card').forEach(c => c.addEventListener('click', () => { const h = hits[+c.dataset.i]; openPreview(h.path, h.by_name ? { page: h.page } : { page: h.page, quote: term }); }));
  };
  $('#sgo', box).addEventListener('click', run);
  $('#sq', box).addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
  $('#sf', box)?.addEventListener('sl-change', run);
  await run();
}
