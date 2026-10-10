// Recipe: layout bugs. No view may scroll the whole page sideways, at desktop or phone width.
// Runs in both projects (tag @responsive), so the mobile project covers phone width.
import { test, expect, open, ROUTES } from './fixtures.js';

for (const r of ROUTES) {
  test(`${r.heading} has no horizontal page overflow @responsive`, async ({ page }) => {
    await open(page, r.hash, r.heading);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}
