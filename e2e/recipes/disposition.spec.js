// Recipe: a disposition is a draft until the analyst confirms it (decision F5). Delta Ridge has no gate
// waiting on review, only the operability checks, so confirming it leaves other recipes' counts alone.
import { test, expect, open, FUNDS } from './fixtures.js';

test('answering the checks unblocks confirmation, and the confirmation is recorded', async ({ page }) => {
  await open(page, `#/fund/${FUNDS.delta.id}`, FUNDS.delta.manager);
  const bar = page.locator('#p-screen #decision');
  await expect(bar).toContainText('Draft');
  await expect(bar).toContainText('answer the custody (operability), pricing (operability) checks');
  await expect(bar.locator('#dc-go')).toBeDisabled();

  await page.locator('#p-screen .gcard[data-g="operability"]').click();
  await page.locator('#drawer .rv-check[data-check="custody"] [data-ok="1"]').click();
  await expect(page.locator('#drawer .rv-check[data-check="custody"]')).toContainText('Yes');
  await page.locator('#drawer .rv-check[data-check="pricing"] [data-ok="1"]').click();
  await expect(page.locator('#drawer .rv-check[data-check="pricing"]')).toContainText('Yes');
  await page.locator('#drawer [part~="close-button"]').click();
  await expect(page.locator('#drawer')).not.toHaveAttribute('open', '');

  await expect(bar.locator('#dc-go')).toBeEnabled();
  await bar.locator('#dc-reason').fill('Fee and track record requests sent');
  await bar.locator('#dc-go').click();
  await expect(bar).toContainText('Confirmed by CIO: Fee and track record requests sent');

  await open(page, '#/screening', 'Screening');
  await expect(page.locator(`#tbl tr[data-id="${FUNDS.delta.id}"]`)).toContainText('Confirmed');
});
