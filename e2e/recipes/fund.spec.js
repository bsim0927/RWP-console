// Recipe: a screened fund end to end. Gate cards -> gate drawer -> cited quote -> PDF preview.
import { test, expect, open, FUNDS } from './fixtures.js';

const fundUrl = (f, tab = '') => `#/fund/${f.id}${tab ? '/' + tab : ''}`;

test('screen tab shows a card per gate with its result', async ({ page }) => {
  await open(page, fundUrl(FUNDS.acme), FUNDS.acme.manager);
  const cards = page.locator('#p-screen .gcard');
  await expect(cards).toHaveCount(5);
  // A QP-only fund passes eligibility and carries the flag (decision A2).
  const eligibility = page.locator('#p-screen .gcard[data-g="investor_eligibility"]');
  await expect(eligibility).toContainText('Pass');
  await expect(eligibility).toContainText('QP-only');
  // The deck and term sheet quote different fees, so cost stays open (B6) and the disagreement shows (F3).
  const cost = page.locator('#p-screen .gcard[data-g="total_annual_cost"]');
  await expect(cost).toContainText('Incomplete');
  await expect(cost).toContainText('Fee rates disagree across documents');
  await expect(cost).toContainText('1 disagree');
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
  for (const tab of ['catalog', 'files', 'search', 'history', 'note', 'report']) {
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
  // Nothing is confirmed yet, so the screen is still open and past due.
  await expect(page.locator('.fund-hd')).toContainText('Late · due Sep 8, 2026');
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

test('documents that disagree are findings, with both sources cited', async ({ page }) => {
  await open(page, fundUrl(FUNDS.acme), FUNDS.acme.manager);
  const marketing = page.locator('#p-screen #marketing');
  await expect(marketing).toContainText('Target fund size');
  await expect(marketing).toContainText('Targeting a $400 million fund.');
  await expect(marketing).toContainText('Target fund size: $250 million.');

  await page.locator('#p-screen .gcard[data-g="total_annual_cost"]').click();
  const disagree = page.locator('#drawer #disagree');
  await expect(disagree).toContainText('management_fee');
  await expect(disagree).toContainText('Documents give 1.75%, 2%');
  await expect(disagree).toContainText('Marketing vs filed');
  await disagree.locator('.cite').last().click();
  await expect(page.locator('#drawer .chip', { hasText: 'Page 1' })).toBeVisible();
});

test('the CIO moves a fund\'s status, and the move is kept', async ({ page }) => {
  await open(page, fundUrl(FUNDS.bluefield), FUNDS.bluefield.manager);
  const standing = page.locator('#standing');
  await expect(standing).toContainText('Covered');
  await expect(standing).toContainText('imported from the old pipeline file');
  await standing.locator('#status-edit').click();
  const dialog = page.locator('sl-dialog[label="Pipeline status"]');
  await dialog.locator('#ps-status').selectOption('Watch');
  await dialog.locator('#ps-note').fill('Annual review flagged a key person change');
  await dialog.locator('[data-go]').click();
  await expect(page.locator('#standing')).toContainText('Watch');
  await expect(page.locator('#standing')).toContainText('set by CIO');
});
