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

// Evidence cites a file by its name or by its path inside the room; either must find it from the omni box,
// even though neither appears in the file's text (no page says "PPM.pdf").
for (const name of ['Northwind Private Credit Fund I - PPM.pdf', '01 Offering/Northwind Private Credit Fund I - PPM.pdf']) {
  test(`the omni box finds a document by the name evidence cites: ${name}`, async ({ page }) => {
    await open(page, '#/', 'Overview');
    await page.keyboard.press('/');
    await page.keyboard.type(name);
    await page.keyboard.press('Enter');
    await expect(page.locator('h1', { hasText: 'Document search' })).toBeVisible();
    const hit = page.locator('#sres .hit-card').first();
    await expect(hit).toContainText('Northwind Private Credit Fund I - PPM.pdf');
    await expect(hit).toContainText('file name');
    await hit.click();
    await expect(page.locator('#drawer .chip', { hasText: 'Page 1' })).toBeVisible();
  });
}
