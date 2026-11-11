import { $, $$, api, cached, bust, esc, n, pct, splitName, TIERS, TIER_COL, legend, empty, skeleton, toast } from '../lib.js';
import { setCrumbs } from '../app.js';

export async function render(el) {
  setCrumbs([['Catalogs']]);
  el.innerHTML = `<div class="page">${skeleton(8)}</div>`;
  let funds = await cached('funds');
  let text = '';
  const draw = () => {
    const cat = funds.filter(f => f.catalog);
    const sum = k => cat.reduce((a, f) => a + k(f.catalog), 0);
    el.innerHTML = `<div class="page">
      <div class="ph"><div><h1>Catalogs</h1><p>Each data room sorted into document types and tiers, with duplicates and superseded versions set aside so the gates read only canonical pages.</p></div></div>
      <div class="kpis">
        <div class="kpi"><div class="l"><sl-icon name="journal-text"></sl-icon>Rooms catalogued</div><div class="v">${cat.length}<small>/ ${funds.length}</small></div><div class="f">${funds.length - cat.length} build on first open</div></div>
        <div class="kpi"><div class="l"><sl-icon name="files"></sl-icon>Pages read</div><div class="v">${n(sum(c => c.pages))}</div><div class="f">${n(sum(c => c.files))} files</div></div>
        <div class="kpi hl"><div class="l"><sl-icon name="bullseye"></sl-icon>Core pages</div><div class="v">${n(sum(c => c.core_pages))}</div><div class="f">${pct(sum(c => c.core_pages) / Math.max(1, sum(c => c.pages)))} of pages carry the gates</div></div>
        <div class="kpi"><div class="l"><sl-icon name="copy"></sl-icon>Set aside</div><div class="v">${n(sum(c => c.exact_duplicates.pages + c.superseded.pages))}</div><div class="f">duplicate or superseded pages</div></div>
      </div>
      <div class="bar"><sl-input id="cf" size="small" placeholder="Filter data rooms" clearable value="${esc(text)}"><sl-icon name="filter" slot="prefix"></sl-icon></sl-input><span class="sp"></span>${legend(TIERS.map(t => [t, TIER_COL[t]]))}</div>
      <div class="cat-grid" id="cg"></div></div>`;
    grid();
    $('#cf', el).addEventListener('sl-input', e => { text = e.target.value; grid(); });
  };
  const grid = () => {
    const t = text.toLowerCase();
    const list = funds.filter(f => !t || f.name.toLowerCase().includes(t)).sort((a, b) => (b.catalog?.pages ?? -1) - (a.catalog?.pages ?? -1) || a.name.localeCompare(b.name));
    $('#cg', el).innerHTML = list.map(f => {
        const s = splitName(f.name), c = f.catalog;
        return `<div class="cat-card" data-id="${esc(f.id)}"><div><div class="nm">${esc(s.manager)}</div><div class="mg">${esc(s.strategy || '')}</div></div>
          ${c ? `<div class="nums"><div><b>${n(c.pages)}</b>pages</div><div><b>${c.files}</b>files</div><div><b>${n(c.core_pages)}</b>core</div><div><b>${c.sections ?? 0}</b>sections</div></div>
            <div class="track" style="display:flex;gap:2px;height:8px;border-radius:3px;overflow:hidden">${TIERS.filter(t => c.by_tier[t]).map(t => `<span style="flex:${c.by_tier[t].pages};background:${TIER_COL[t]}" data-tip="<b>${t}</b> · ${c.by_tier[t].files} files · ${n(c.by_tier[t].pages)} pages"></span>`).join('')}${c.exact_duplicates.pages + c.superseded.pages ? `<span style="flex:${c.exact_duplicates.pages + c.superseded.pages};background:var(--s4)" data-tip="Set aside · ${c.exact_duplicates.pages + c.superseded.pages} pages"></span>` : ''}</div>`
            : `<div style="display:flex;align-items:center;gap:10px"><span class="dim" style="font-size:12.5px">Not catalogued yet</span><span class="sp"></span><button class="ghost-btn sm" data-build="${esc(f.id)}"><sl-icon name="hammer"></sl-icon>Build</button></div>`}</div>`;
      }).join('') || empty('journal', 'No data rooms match');
    $$('.cat-card', el).forEach(c => c.addEventListener('click', e => { if (!e.target.closest('[data-build]')) location.hash = `#/fund/${encodeURIComponent(c.dataset.id)}/catalog`; }));
    $$('[data-build]', el).forEach(b => b.addEventListener('click', async () => {
      b.disabled = true; b.innerHTML = '<sl-spinner></sl-spinner>Building';
      try { await api('catalog/' + encodeURIComponent(b.dataset.build)); bust('funds'); funds = await cached('funds'); toast('Catalog built', 'good'); draw(); }
      catch (e) { toast('Build failed: ' + esc(e.message), 'crit'); b.disabled = false; b.textContent = 'Retry'; }
    }));
  };
  draw();
}
