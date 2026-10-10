// Recipe: automated accessibility scan (axe) on every view. Fails on critical violations; serious ones
// are attached to the report so they can be burned down without blocking merges.
import AxeBuilder from '@axe-core/playwright';
import { test, expect, open, ROUTES } from './fixtures.js';

for (const r of ROUTES) {
  test(`${r.heading} has no critical accessibility violations @a11y`, async ({ page }, testInfo) => {
    await open(page, r.hash, r.heading);
    // Scan the settled UI: mid-upgrade, a Shoelace child can expose its ARIA role before its parent
    // renders the matching container role, which axe reports as a transient aria-required-parent.
    await page.waitForFunction(() => !document.querySelector(':not(:defined)'));
    await page.evaluate(() => document.fonts.ready);
    const { violations } = await new AxeBuilder({ page }).exclude('#tip').analyze();
    const summary = violations.map(v => `${v.impact}: ${v.id} (${v.nodes.length}) ${v.help}`);
    if (summary.length) await testInfo.attach('axe', { body: summary.join('\n'), contentType: 'text/plain' });
    expect(violations.filter(v => v.impact === 'critical').map(v => v.id)).toEqual([]);
  });
}
