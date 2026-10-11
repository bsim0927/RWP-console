// Recipe: a screened fund end to end. Gate cards -> gate drawer -> cited quote -> PDF preview.
import { test, expect, open, FUNDS } from './fixtures.js';

const fundUrl = (f, tab = '') => `#/fund/${f.id}${tab ? '/' + tab : ''}`;

test('screen tab shows a card per gate with its result', async ({ page }) => {
  await open(page, fundUrl(FUNDS.acme), FUNDS.acme.manager);
  const cards = page.locator('#p-screen .gcard');
  await expect(cards).toHaveCount(5);
  // A QP-only fund passes eligibility and carries the flag (decision A2); cost has no threshold (B1).
  const eligibility = page.locator('#p-screen .gcard[data-g="investor_eligibility"]');
  await expect(eligibility).toContainText('Pass');
  await expect(eligibility).toContainText('QP-only');
  await expect(page.locator('#p-screen .gcard[data-g="total_annual_cost"]')).toContainText('Pass');
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

test('intake shows who referred the fund and the screen clock', async ({ page }) => {
  await open(page, fundUrl(FUNDS.northwind), FUNDS.northwind.manager);
  const intake = page.locator('#intake');
  await expect(intake).toContainText('Adviser network');
  await expect(intake).toContainText('Class I');
  await expect(intake).toContainText('Sep 1, 2026');
  await expect(intake).toContainText('Sep 8, 2026'); // five business days after filing
  await expect(page.locator('.fund-hd')).toContainText('Screened late');
});

test('the analyst edits intake and the fund picks it up', async ({ page }) => {
  await open(page, fundUrl(FUNDS.bluefield), FUNDS.bluefield.manager);
  await page.locator('#intake-edit').click();
  const dialog = page.locator('sl-dialog[label="Intake"]');
  await dialog.locator('sl-input[data-k="referred_by"] input').fill('Consultant B');
  await dialog.locator('sl-input[data-k="owner"] input').fill('Analyst C');
  await dialog.locator('[data-go]').click();
  await expect(page.locator('#intake')).toContainText('Consultant B');
  await expect(page.locator('.fund-hd')).toContainText('Analyst C');
});
