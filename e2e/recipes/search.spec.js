// Recipe: finding things. Document search, the omni box, and its keyboard shortcut.
import { test, expect, open, FUNDS } from './fixtures.js';

test('document search finds a phrase and opens the page', async ({ page }) => {
  await open(page, '#/search?q=valuation%20policy', 'Document search');
  const hits = page.locator('#sres .hit-card');
  await expect(hits).toHaveCount(1);
  await expect(hits.first()).toContainText('PPM.pdf');
  await expect(hits.first().locator('mark').first()).toBeVisible();
  await hits.first().click();
  await expect(page.locator('#drawer .chip', { hasText: 'Page 3' })).toBeVisible();
});

test('a search with no hits says so', async ({ page }) => {
  await open(page, '#/search?q=zzqxv', 'Document search');
  await expect(page.locator('#sres')).toContainText('No pages match');
});

test('"/" focuses the omni box, which jumps to a fund', async ({ page }) => {
  await open(page, '#/', 'Overview');
  await page.keyboard.press('/');
  await page.keyboard.type('northwind');
  await expect(page.locator('#omni-list')).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(new RegExp(`#/fund/${FUNDS.northwind.id}`));
});

test('XSS: a search term is shown as text, never as markup', async ({ page }) => {
  let dialog = false;
  page.on('dialog', d => { dialog = true; d.dismiss(); });
  await open(page, `#/search?q=${encodeURIComponent('<img src=x onerror=alert(1)>')}`, 'Document search');
  await expect(page.locator('#sres')).toContainText('No pages match');
  expect(dialog).toBe(false);
});
