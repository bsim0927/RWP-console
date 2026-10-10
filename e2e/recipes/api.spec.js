// Recipe: API contracts and security regressions, without a browser.
import { test, expect } from '@playwright/test';

test('/api/funds returns the fixture rooms with the shape the UI reads', async ({ request }) => {
  const res = await request.get('/api/funds');
  expect(res.ok()).toBeTruthy();
  const funds = await res.json();
  expect(funds).toHaveLength(3);
  for (const f of funds) {
    expect(f).toEqual(expect.objectContaining({ id: expect.any(String), name: expect.any(String), runs: expect.any(Array) }));
  }
});

test('/api/config exposes all five gates in order', async ({ request }) => {
  const cfg = await (await request.get('/api/config')).json();
  expect(cfg.gates.map(g => g.parsed.id)).toEqual(
    ['investor_eligibility', 'total_annual_cost', 'operability', 'track_record', 'disclosure_history']);
});

for (const path of ['../../../../etc/passwd', '/etc/passwd', '..%2F..%2Fserver.py', '../server.py']) {
  test(`path traversal is refused: ${path}`, async ({ request }) => {
    const res = await request.get(`/api/raw?path=${path}`);
    expect(res.status()).toBe(404);
    expect(await res.text()).not.toContain('root:');
  });
}

test('static files cannot escape web/', async ({ request }) => {
  const res = await request.get('/..%2Fserver.py');
  expect(res.status()).toBe(404);
});

test('unknown API route is a JSON 404', async ({ request }) => {
  const res = await request.get('/api/nope');
  expect(res.status()).toBe(404);
  expect(await res.json()).toEqual({ error: expect.any(String) });
});
