// Guards web/js/components.js: every Shoelace tag the app renders must be defined up front, or views
// race the autoloader on a cold load (see the comment in components.js).
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, it } from 'vitest';

const WEB = join(import.meta.dirname, '../../web');
const sources = [join(WEB, 'index.html'), ...readdirSync(join(WEB, 'js'), { recursive: true })
  .filter(f => f.endsWith('.js') && f !== 'components.js').map(f => join(WEB, 'js', f))];

it('components.js defines every sl-* element the app uses', () => {
  const used = new Set(sources.flatMap(f => [...readFileSync(f, 'utf8').matchAll(/<(sl-[a-z-]+)|createElement\('(sl-[a-z-]+)'\)/g)].map(m => m[1] || m[2])));
  const preloaded = new Set([...readFileSync(join(WEB, 'js/components.js'), 'utf8').matchAll(/components\/([a-z-]+)\//g)].map(m => 'sl-' + m[1]));
  expect([...used].filter(t => !preloaded.has(t)).sort()).toEqual([]);
});

it('index.html loads components.js before app.js', () => {
  const html = readFileSync(join(WEB, 'index.html'), 'utf8');
  expect(html.indexOf('/js/components.js')).toBeGreaterThan(-1);
  expect(html.indexOf('/js/components.js')).toBeLessThan(html.indexOf('/js/app.js'));
});
