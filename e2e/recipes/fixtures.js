// The bug-catching harness every recipe runs under.
//
// `test` from this file fails a test when the page does anything a user would experience as broken,
// even if the test's own assertions pass:
//   - an uncaught exception (pageerror)
//   - console.error output
//   - a network request that failed outright (requestfailed)
//   - an /api response with status >= 400
// A recipe that expects one of these (e.g. testing a 404 page) declares it with `allow`:
//   test('...', async ({ page, allow }) => { allow.api(/\/api\/raw/); ... })
import { test as base, expect } from '@playwright/test';

export const ROUTES = [
  { hash: '#/', heading: 'Overview' },
  { hash: '#/screening', heading: 'Screening' },
  { hash: '#/catalogs', heading: 'Catalogs' },
  { hash: '#/files', heading: 'Files' },
  { hash: '#/search', heading: 'Document search' },
  { hash: '#/analytics', heading: 'Analytics' },
  { hash: '#/logs', heading: 'Agent monitor' },
  { hash: '#/policy', heading: 'Gates and policy' },
];

// Fixture funds (e2e/fixtures/build.py). Ids are folder names with non-word runs replaced by "_".
export const FUNDS = {
  northwind: { id: 'Northwind_Capital_-_Private_Credit_Fund_I', manager: 'Northwind Capital' },
  acme: { id: 'Acme_Partners_-_Real_Estate_Opportunity_Fund_II', manager: 'Acme Partners' },
  bluefield: { id: 'Bluefield_Advisors_-_Infrastructure_Income_Fund', manager: 'Bluefield Advisors' },
  delta: { id: 'Delta_Ridge_Partners_-_Evergreen_Credit_Fund', manager: 'Delta Ridge Partners' },
};

export const test = base.extend({
  allow: [async ({}, use) => {
    const rules = { console: [], api: [], request: [] };
    await use({
      console: re => rules.console.push(re),
      api: re => rules.api.push(re),
      request: re => rules.request.push(re),
      rules,
    });
  }, { scope: 'test' }],

  page: async ({ page, allow }, use, testInfo) => {
    const problems = [];
    const allowed = (kind, s) => allow.rules[kind].some(re => re.test(s));
    page.on('pageerror', e => problems.push(`uncaught exception: ${e.message}`));
    page.on('console', m => {
      if (m.type() === 'error' && !allowed('console', m.text())) problems.push(`console.error: ${m.text()}`);
    });
    page.on('requestfailed', r => {
      const err = r.failure()?.errorText || '';
      // Navigating away aborts in-flight requests; that is not a bug.
      if (!/ERR_ABORTED|NS_BINDING_ABORTED/.test(err) && !allowed('request', r.url())) problems.push(`request failed: ${r.url()} (${err})`);
    });
    page.on('response', r => {
      if (r.url().includes('/api/') && r.status() >= 400 && !allowed('api', r.url())) problems.push(`HTTP ${r.status()}: ${r.url()}`);
    });
    // A deployed console behind SITE_PASSWORD: sign in first. The session cookie lands in the page's context.
    if (process.env.E2E_SITE_PASSWORD) await page.request.post('/login', { form: { password: process.env.E2E_SITE_PASSWORD }, maxRedirects: 0 });
    await use(page);
    if (problems.length) {
      await testInfo.attach('page-problems', { body: problems.join('\n'), contentType: 'text/plain' });
      expect(problems, 'the page reported errors while this test ran').toEqual([]);
    }
  },
});

export { expect };

/** Open a route and wait for the view's heading, i.e. for render() to finish. */
export async function open(page, hash, heading) {
  await page.goto('/' + hash);
  if (heading) await expect(page.locator('#view h1').first()).toHaveText(heading);
}
