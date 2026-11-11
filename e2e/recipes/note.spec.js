// Recipe: the screen note (decisions F1, F4). The tool drafts it from the run; the analyst edits it, and
// every version is kept.
import { test, expect, open, FUNDS } from './fixtures.js';

test('the tool drafts the note and the request list, and an edit becomes a new version', async ({ page }) => {
  await open(page, `#/fund/${FUNDS.acme.id}/note`, FUNDS.acme.manager);
  const box = page.locator('#p-note');
  await box.locator('#nt-draft').click();
  const body = box.locator('#note');
  await expect(body).toContainText('Acme Partners - Real Estate Opportunity Fund II: screen note');
  await expect(body).toContainText('What the manager must provide');
  await expect(body).toContainText('Reconcile the management fee');
  await expect(body).toContainText('Marketing against filed: Target fund size');

  await box.locator('#nt-edit').click();
  await box.locator('#nt-body').fill('# Acme screen note\n\nFee schedule requested from the sponsor.');
  await box.locator('#nt-save').click();
  await expect(box.locator('#note')).toContainText('Fee schedule requested from the sponsor.');
  await expect(box).toContainText('Edited by CIO');
  await expect(box).toContainText('Earlier versions');
});
