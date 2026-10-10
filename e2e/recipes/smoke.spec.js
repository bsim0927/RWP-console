// Recipe: every top-level view renders without errors (the harness fails on any console error,
// uncaught exception, failed request or API error).
import { test, expect, open, ROUTES } from './fixtures.js';

for (const r of ROUTES) {
  test(`${r.heading} renders cleanly @smoke`, async ({ page }) => {
    await open(page, r.hash, r.heading);
    await expect(page.locator('#view')).not.toContainText('Could not load this view');
    await expect(page.locator('.empty', { hasText: 'Page not found' })).toHaveCount(0);
  });
}
