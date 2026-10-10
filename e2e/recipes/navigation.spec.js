// Recipe: routing. Sidebar links, active state, deep links, unknown routes, browser history.
import { test, expect, open, ROUTES } from './fixtures.js';

test('sidebar reaches every view and marks it active', async ({ page }) => {
  await open(page, '#/', 'Overview');
  for (const r of ROUTES.slice(1)) {
    const link = page.locator(`#nav a[href="${r.hash}"]`);
    await link.click();
    await expect(page.locator('#view h1').first()).toHaveText(r.heading);
    await expect(link).toHaveClass(/\bon\b/);
  }
});

test('unknown route shows a not-found state, not a blank page', async ({ page }) => {
  await page.goto('/#/no-such-view');
  await expect(page.locator('#view')).toContainText('Page not found');
  await page.getByRole('link', { name: 'Back to overview' }).click();
  await expect(page.locator('#view h1').first()).toHaveText('Overview');
});

test('back and forward restore the previous view', async ({ page }) => {
  await open(page, '#/screening', 'Screening');
  await page.locator('#nav a[href="#/analytics"]').click();
  await expect(page.locator('#view h1').first()).toHaveText('Analytics');
  await page.goBack();
  await expect(page.locator('#view h1').first()).toHaveText('Screening');
  await page.goForward();
  await expect(page.locator('#view h1').first()).toHaveText('Analytics');
});

test('reload keeps the current deep link', async ({ page }) => {
  await open(page, '#/policy', 'Gates and policy');
  await page.reload();
  await expect(page.locator('#view h1').first()).toHaveText('Gates and policy');
});
