// Recipe: a screened fund end to end. Gate cards -> gate drawer -> cited quote -> PDF preview.
import { test, expect, open, FUNDS } from './fixtures.js';

const fundUrl = (f, tab = '') => `#/fund/${f.id}${tab ? '/' + tab : ''}`;

test('screen tab shows a card per gate with its result', async ({ page }) => {
  await open(page, fundUrl(FUNDS.acme), FUNDS.acme.manager);
  const cards = page.locator('#p-screen .gcard');
  await expect(cards).toHaveCount(5);
  await expect(page.locator('#p-screen .gcard[data-g="investor_eligibility"]')).toContainText('Fail');
  await expect(page.locator('#p-screen .gcard[data-g="total_annual_cost"]')).toContainText('Route with disclosure');
});

test('gate drawer shows verified facts and the rejected, fabricated quote', async ({ page }) => {
  await open(page, fundUrl(FUNDS.northwind), FUNDS.northwind.manager);
  await page.locator('#p-screen .gcard[data-g="operability"]').click();
  const drawer = page.locator('#drawer');
  await expect(drawer).toContainText('Facts extracted');
  await expect(drawer).toContainText('Harbor Fund Services');
  await expect(drawer).toContainText('This sentence does not appear anywhere in the data room.');
});

test('a citation opens the source PDF at the cited page', async ({ page }) => {
  await open(page, fundUrl(FUNDS.northwind), FUNDS.northwind.manager);
  await page.locator('#p-screen .gcard[data-g="operability"]').click();
  await page.locator('#drawer .cite').first().click();
  const drawer = page.locator('#drawer');
  await expect(drawer.locator('.chip', { hasText: 'Page 3' })).toBeVisible();
  await expect(drawer.locator('.pdf-page canvas').first()).toBeVisible({ timeout: 15_000 });
  await drawer.locator('[data-back]').click();
  await expect(drawer).toContainText('Facts extracted');
});

test('every tab renders for a screened fund', async ({ page }) => {
  await open(page, fundUrl(FUNDS.northwind), FUNDS.northwind.manager);
  for (const tab of ['catalog', 'files', 'search', 'history', 'report']) {
    await page.locator(`#tabs sl-tab[panel="${tab}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/${tab}(/|$)`));
    await expect(page.locator(`#p-${tab}`)).not.toBeEmpty();
  }
  await expect(page.locator('#p-report')).toContainText('Screen run');
});

test('an unscreened fund offers to run the screen instead of a broken tab', async ({ page }) => {
  await open(page, fundUrl(FUNDS.bluefield), FUNDS.bluefield.manager);
  await expect(page.locator('#p-screen')).toContainText('Not screened yet');
  await page.locator('#p-screen [data-go]').click();
  await expect(page.locator('sl-dialog[label="Run screen"]')).toHaveAttribute('open', '');
});
