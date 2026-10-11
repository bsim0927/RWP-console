// Recipe: the screening queue reflects the runs on disk (fixture: 2 screened funds needing analyst
// review, 1 unscreened).
import { test, expect, open, FUNDS } from './fixtures.js';

test('lists every indexed data room with its latest disposition', async ({ page }) => {
  await open(page, '#/screening', 'Screening');
  const rows = page.locator('#tbl tr[data-id]');
  await expect(rows).toHaveCount(3);
  await expect(page.locator(`#tbl tr[data-id="${FUNDS.bluefield.id}"]`)).toContainText('Not screened');
  await expect(page.locator(`#tbl tr[data-id="${FUNDS.northwind.id}"]`)).toContainText('Under review');
});

test('filters narrow the table and their counts agree with it', async ({ page }) => {
  await open(page, '#/screening', 'Screening');
  for (const [f, expected] of [['unscreened', 1], ['screened', 2], ['review', 2], ['late', 1], ['all', 3]]) {
    const btn = page.locator(`#seg button[data-f="${f}"]`);
    await btn.click();
    await expect(btn.locator('.c')).toHaveText(String(expected));
    await expect(page.locator('#tbl tr[data-id]')).toHaveCount(expected);
  }
});

test('nav badge counts screens waiting on analyst review', async ({ page }) => {
  await open(page, '#/screening', 'Screening');
  await expect(page.locator('#nav-review')).toBeVisible();
  await expect(page.locator('#nav-review')).toHaveText('2');
});

test('clicking a row opens the fund', async ({ page }) => {
  await open(page, '#/screening', 'Screening');
  await page.locator(`#tbl tr[data-id="${FUNDS.northwind.id}"]`).click();
  await expect(page).toHaveURL(new RegExp(`#/fund/${FUNDS.northwind.id}`));
  await expect(page.locator('#view h1').first()).toHaveText(FUNDS.northwind.manager);
});
