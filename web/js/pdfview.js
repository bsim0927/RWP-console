// PDF viewer on PDF.js (vendored). Lazy page rendering, page jump, zoom, and a highlight drawn over the
// cited quote on the cited page.
import { esc } from './lib.js';

const BASE = '/vendor/pdfjs/';
let lib;
async function pdfjs() {
  if (!lib) {
    lib = await import(BASE + 'pdf.min.mjs');
    lib.GlobalWorkerOptions.workerSrc = BASE + 'pdf.worker.min.mjs';
  }
  return lib;
}

// Matching ignores whitespace entirely: PDF text runs split and join words unpredictably.
const squash = s => s.toLowerCase().replace(/[\u2018\u2019]/g, "'").replace(/[\u201c\u201d]/g, '"').replace(/[\u2013\u2014]/g, '-').replace(/\s+/g, '');

// Range of the quote in the page's text, or of the longest leading run of its words that matches.
function locate(items, quote) {
  let text = '';
  const spans = items.map(it => { const s = text.length; text += squash(it.str); return [s, text.length]; });
  const words = quote.trim().split(/\s+/).filter(Boolean);
  for (let n = words.length; n >= Math.min(4, words.length); n--) {
    const needle = squash(words.slice(0, n).join(''));
    const i = needle ? text.indexOf(needle) : -1;
    if (i >= 0) return { spans, from: i, to: i + needle.length };
  }
  return null;
}

/** @param {HTMLElement} box @param {string} url @param {{ page?: number, quote?: string }} [opts] */
export async function pdfViewer(box, url, { page = 1, quote } = {}) {
  box.innerHTML = `<div class="pdfv"><div class="pdf-bar">
      <button class="ghost-btn sm" data-a="prev" title="Previous page"><sl-icon name="chevron-up"></sl-icon></button>
      <button class="ghost-btn sm" data-a="next" title="Next page"><sl-icon name="chevron-down"></sl-icon></button>
      <span class="pdf-pg"><input type="number" min="1" value="${page}" aria-label="Page"> <span class="dim">of <b data-n>…</b></span></span>
      <span class="sp"></span>
      <button class="ghost-btn sm" data-a="out" title="Zoom out"><sl-icon name="dash-lg"></sl-icon></button>
      <span class="dim tnum" data-z style="min-width:44px;text-align:center;font-size:12px">fit</span>
      <button class="ghost-btn sm" data-a="in" title="Zoom in"><sl-icon name="plus-lg"></sl-icon></button>
      <button class="ghost-btn sm" data-a="fit" title="Fit width"><sl-icon name="arrows-angle-expand"></sl-icon>Fit</button>
      ${quote ? `<button class="ghost-btn sm" data-a="cite" title="Back to the cited quote"><sl-icon name="bookmark-star"></sl-icon>Cited p.${page}</button>` : ''}
    </div><div class="pdf-pages"><div class="shimmer sk" style="height:600px"></div></div></div>`;
  const pagesEl = box.querySelector('.pdf-pages');
  let doc;
  try {
    const L = await pdfjs();
    doc = await L.getDocument({ url, cMapUrl: BASE + 'cmaps/', cMapPacked: true, standardFontDataUrl: BASE + 'standard_fonts/', wasmUrl: BASE + 'wasm/', iccUrl: BASE + 'iccs/', verbosity: 0 }).promise;
  } catch (e) {
    pagesEl.innerHTML = `<div class="empty"><sl-icon name="file-earmark-x"></sl-icon><b>Could not render this PDF</b><span class="mono">${esc(e.message)}</span></div>`;
    return;
  }
  box.querySelector('[data-n]').textContent = doc.numPages;
  const first = await doc.getPage(1);
  const base = first.getViewport({ scale: 1 });
  let zoom = null; // null = fit width
  const scaleNow = () => zoom ?? Math.max(0.3, (pagesEl.clientWidth - 24) / base.width);
  let observer, rendered = new Map();

  function layout(target) {
    observer?.disconnect();
    rendered.forEach(t => t.cancel?.());
    rendered = new Map();
    const s = scaleNow();
    box.querySelector('[data-z]').textContent = zoom ? Math.round(zoom * 100) + '%' : 'fit';
    pagesEl.innerHTML = Array.from({ length: doc.numPages }, (_, i) => `<div class="pdf-page" data-p="${i + 1}" style="width:${base.width * s}px;height:${base.height * s}px"><span class="pdf-num">${i + 1}</span></div>`).join('');
    observer = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) draw(+/** @type {HTMLElement} */ (e.target).dataset.p); }), { root: null, rootMargin: '600px 0px' });
    pagesEl.querySelectorAll('.pdf-page').forEach(d => observer.observe(d));
    if (target) requestAnimationFrame(() => goTo(target, false));
  }

  async function draw(n) {
    if (rendered.has(n)) return;
    rendered.set(n, {});
    const holder = pagesEl.querySelector(`[data-p="${n}"]`);
    const p = await doc.getPage(n);
    const vp = p.getViewport({ scale: scaleNow() });
    const ratio = window.devicePixelRatio || 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(vp.width * ratio); canvas.height = Math.floor(vp.height * ratio);
    canvas.style.width = vp.width + 'px'; canvas.style.height = vp.height + 'px';
    holder.style.width = vp.width + 'px'; holder.style.height = vp.height + 'px';
    const task = p.render({ canvas, canvasContext: canvas.getContext('2d'), viewport: vp, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null });
    rendered.set(n, task);
    try { await task.promise; } catch { return; } // cancelled by a zoom change
    holder.prepend(canvas);
    if (quote && n === page) highlight(p, vp, holder);
  }

  async function highlight(p, vp, holder) {
    const { items } = await p.getTextContent();
    const hit = locate(items, quote);
    if (!hit) { holder.insertAdjacentHTML('beforeend', '<div class="pdf-note">Quote not located in the text layer; see Extracted text.</div>'); return; }
    const L = await pdfjs();
    let first = null;
    items.forEach((it, i) => {
      const [a, b] = hit.spans[i];
      if (a === b || b <= hit.from || a >= hit.to) return;
      const tx = L.Util.transform(vp.transform, it.transform);
      const h = Math.hypot(tx[2], tx[3]);
      const w = it.width * vp.scale;
      const mark = document.createElement('div');
      mark.className = 'pdf-hl';
      Object.assign(mark.style, { left: tx[4] + 'px', top: (tx[5] - h * 0.95) + 'px', width: w + 'px', height: h * 1.2 + 'px' });
      holder.append(mark);
      first ??= mark;
    });
    first?.scrollIntoView({ block: 'center' });
  }

  function current() {
    const top = pagesEl.getBoundingClientRect().top;
    let best = 1;
    pagesEl.querySelectorAll('.pdf-page').forEach(d => { if (d.getBoundingClientRect().top - top < 120) best = +d.dataset.p; });
    return best;
  }
  function goTo(n, smooth = true) {
    n = Math.min(doc.numPages, Math.max(1, n));
    pagesEl.querySelector(`[data-p="${n}"]`)?.scrollIntoView({ block: 'start', behavior: smooth ? 'smooth' : 'auto' });
    box.querySelector('.pdf-pg input').value = n;
  }

  box.querySelector('.pdf-bar').addEventListener('click', e => {
    const a = e.target.closest('[data-a]')?.dataset.a;
    if (!a) return;
    const cur = current();
    if (a === 'prev') goTo(cur - 1);
    if (a === 'next') goTo(cur + 1);
    if (a === 'cite') goTo(page);
    if (a === 'in' || a === 'out') { zoom = Math.min(4, Math.max(0.3, scaleNow() * (a === 'in' ? 1.2 : 1 / 1.2))); layout(cur); }
    if (a === 'fit') { zoom = null; layout(cur); }
  });
  box.querySelector('.pdf-pg input').addEventListener('change', e => goTo(+e.target.value));
  layout(page);
}
