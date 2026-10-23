// Recipe: analyst review of a screen run (decisions G1, G2, C3, C4). Uses Acme's gates that are not waiting
// on review, so the Screening filter counts other recipes check stay the same.
import { test, expect, open, FUNDS } from './fixtures.js';

const acme = `#/fund/${FUNDS.acme.id}`;

test('a "no" on a manual check fails operability', async ({ page }) => {
  await open(page, acme, FUNDS.acme.manager);
  await page.locator('#p-screen .gcard[data-g="operability"]').click();
  const panel = page.locator('#drawer #review');
  await expect(panel).toContainText('Can the position be custodied?');
  const pricing = panel.locator('.rv-check[data-check="pricing"]');
  await pricing.locator('[data-note]').fill('Not in the reporting system');
  await pricing.locator('[data-ok="0"]').click();
  await expect(page.locator('#drawer #review')).toContainText('Not in the reporting system');
  const card = page.locator('#p-screen .gcard[data-g="operability"]');
  await expect(card).toContainText('Fail');
  await expect(card).toContainText('Failed the pricing check');
});

test('an override records the result, reason, document and page', async ({ page }) => {
  await open(page, acme, FUNDS.acme.manager);
  await page.locator('#p-screen .gcard[data-g="investor_eligibility"]').click();
  const panel = page.locator('#drawer #review');
  await panel.locator('#rv-verdict [data-v="override"]').click();
  await panel.locator('#rv-result').selectOption('Incomplete');
  await panel.locator('#rv-doc').fill('Acme REOF II - Term Sheet.pdf');
  await panel.locator('#rv-page').fill('1');
  await panel.locator('#rv-reason').fill('Subscription booklet not yet received');
  await panel.locator('#rv-save').click();
  await expect(page.locator('#drawer #review')).toContainText('Subscription booklet not yet received');
  await expect(page.locator('#drawer #review')).toContainText('Term Sheet.pdf p.1');
  const card = page.locator('#p-screen .gcard[data-g="investor_eligibility"]');
  await expect(card).toContainText('Incomplete');
  await expect(card).toContainText('Overridden by CIO');
});

test('reviewers are managed under Gates and policy', async ({ page }) => {
  await open(page, '#/policy', 'Gates and policy');
  const card = page.locator('#reviewers');
  await expect(card.locator('tr[data-rid="cio"]')).toBeVisible();
  await card.locator('#rv-new').fill('Analyst Two');
  await card.locator('#rv-add').click();
  await expect(page.locator('#reviewers tr[data-rid="analyst_two"]')).toBeVisible();
});
