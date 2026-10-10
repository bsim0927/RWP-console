import { $, $$, api, cached, esc, q, bytes, ago, fileIcon, extOf, openPreview, empty } from '../lib.js';
import { setCrumbs } from '../app.js';

// Paths here are paths in the merged RWP tree: the server lays the Drive download parts over each other.
export async function render(el, r) {
  setCrumbs([['Files']]);
  el.innerHTML = `<div class="page"><div class="ph"><div><h1>Files</h1><p>The RWP drive as one folder tree, with original file names and folders. Indexed data rooms are tagged.</p></div></div>
    <div class="fb"><div class="fb-tree"><sl-tree id="tree" selection="single"></sl-tree></div><div class="fb-main" id="fbm"></div></div></div>`;
  const tree = $('#tree', el);
  const item = e => `<sl-tree-item data-path="${esc(e.path)}" ${e.dir ? 'lazy' : ''}><sl-icon name="${e.room ? 'database' : 'folder'}"></sl-icon>${esc(e.name)}</sl-tree-item>`;
  const root = await api('fs?' + q({ path: '' }));
  tree.innerHTML = root.entries.filter(e => e.dir).map(item).join('');
  tree.addEventListener('sl-lazy-load', async ev => {
    const it = ev.target;
    const res = await api('fs?' + q({ path: it.dataset.path }));
    it.insertAdjacentHTML('beforeend', res.entries.filter(e => e.dir).map(item).join(''));
    it.lazy = false;
  });
  tree.addEventListener('sl-selection-change', ev => {
    const p = ev.detail.selection[0]?.dataset.path;
    if (p != null) location.hash = '#/files?' + q({ path: p });
  });
  await browser($('#fbm', el), { root: '', path: r.query.path || '', navigate: p => { location.hash = '#/files?' + q({ path: p }); } });
}

// A folder listing with breadcrumbs, filter, and preview. Used on the Files page and inside a fund.
export async function browser(box, { root, path, navigate, embedded }) {
  const go = p => navigate ? navigate(p) : load(p);
  let text = '';
  async function load(p) {
    box.innerHTML = `<div class="fb-bar"><div class="shimmer sk" style="width:40%"></div></div>`;
    let res;
    try { res = await api('fs?' + q({ path: p })); } catch (e) { box.innerHTML = empty('folder-x', 'Folder not found', esc(p)); return; }
    const funds = await cached('funds');
    const cur = res.path, base = root || '';
    const rel = base && cur.startsWith(base) ? cur.slice(base.length).replace(/^\//, '') : cur;
    const segs = rel ? rel.split('/') : [];
    const crumbs = [`<a data-go="${esc(base)}">${esc(base ? base.split('/').pop() : res.root)}</a>`,
      ...segs.map((s, i) => i === segs.length - 1 ? `<b>${esc(s)}</b>` : `<a data-go="${esc([base, ...segs.slice(0, i + 1)].filter(Boolean).join('/'))}">${esc(s)}</a>`)];
    const draw = () => {
      const t = text.toLowerCase();
      const ents = res.entries.filter(e => !t || e.name.toLowerCase().includes(t));
      $('#fbl', box).innerHTML = ents.length ? `<table class="t"><tr><th>Name</th><th>Modified</th><th class="n">Size</th><th>Kind</th></tr>${ents.map(e => {
        const f = e.room && funds.find(x => x.vpath === e.path);
        return `<tr class="click" data-p="${esc(e.path)}" data-real="${esc(e.real)}" data-dir="${e.dir ? 1 : ''}"><td>${fileIcon(e.name, e.dir)}<span class="nm" style="font-weight:${e.dir ? 550 : 450}">${esc(e.name)}</span>${f ? `<a class="room-tag" href="#/fund/${encodeURIComponent(f.id)}">Data room</a>` : ''}</td>
          <td class="dim tnum">${ago(new Date(e.mtime * 1000))}</td><td class="n dim tnum">${e.dir ? '–' : bytes(e.size)}</td><td class="dim">${e.dir ? 'Folder' : esc(extOf(e.name).toUpperCase())}</td></tr>`;
      }).join('')}</table>` : empty('folder', text ? 'No matches' : 'Empty folder');
      $$('tr[data-p]', box).forEach(tr => tr.addEventListener('click', ev => {
        if (ev.target.closest('a')) return;
        tr.dataset.dir ? go(tr.dataset.p) : openPreview(tr.dataset.real);
      }));
    };
    const nd = res.entries.filter(e => e.dir).length;
    box.innerHTML = `<div class="fb-bar"><div class="path">${crumbs.join('<sl-icon name="chevron-right" style="font-size:10px"></sl-icon>')}</div><span class="sp"></span>
      <span class="dim" style="font-size:12px">${nd} folders · ${res.entries.length - nd} files</span>
      <sl-input id="ff" size="small" placeholder="Filter this folder" clearable style="width:200px"><sl-icon name="filter" slot="prefix"></sl-icon></sl-input></div>
      <div class="fb-list" id="fbl"></div>`;
    if (embedded) box.querySelector('.fb-list').style.maxHeight = '64vh';
    $$('[data-go]', box).forEach(a => a.addEventListener('click', () => go(a.dataset.go)));
    $('#ff', box).addEventListener('sl-input', e => { text = e.target.value; draw(); });
    draw();
  }
  if (embedded) { box.classList.add('card'); box.style.overflow = 'hidden'; }
  await load(path);
}
