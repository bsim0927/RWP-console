// Recipe: editing the disposition policy. Form edit -> new version in force; invalid YAML blocked;
// history -> restore an earlier version. Serial: the tests share the one policy.
import { test, expect, open } from './fixtures.js';

test.describe.configure({ mode: 'serial' });

const card = page => page.locator('#policy');
const inForce = async page => (await (await page.request.get('/api/config')).json()).policy;

test('editing a disposition in the form saves a new version that is in force', async ({ page }) => {
  const before = await inForce(page);
  await open(page, '#/policy', 'Gates and policy');
  await page.locator('#pol-edit').click();
  const last = page.locator('#pe-body input[data-k="disposition"]').last();
  await last.fill('Coverable, subject to conditions (e2e edit)');
  await expect(page.locator('#pe-ver')).toHaveText('saves as a new version');
  await page.locator('#pe-save').click();
  await expect(card(page)).toContainText('Coverable, subject to conditions (e2e edit)');
  const after = await inForce(page);
  expect(after.id).toBeGreaterThan(before.id);
  await expect(card(page).locator('.chip.mono')).toHaveText(`v${after.id}`);
});

test('invalid YAML is explained and cannot be saved', async ({ page }) => {
  await open(page, '#/policy', 'Gates and policy');
  await page.locator('#pol-edit').click();
  await page.locator('#pe-mode button[data-m="yaml"]').click();
  await page.locator('#pe-yaml').fill('rules:\n  - when: sometimes\n    disposition: Coverable\n');
  await expect(page.locator('#pe-status')).toContainText('when must be one of');
  await expect(page.locator('#pe-save')).toBeDisabled();
  await page.locator('#pe-yaml').fill('rules:\n  - when: any_fail\n    disposition: Under review\n');
  await expect(page.locator('#pe-status')).toContainText('no otherwise rule');
  await expect(page.locator('#pe-save')).toBeEnabled();
});

test('history restores an earlier version as a new one', async ({ page }) => {
  const seeded = (await (await page.request.get('/api/policy/history')).json()).at(-1);
  await open(page, '#/policy', 'Gates and policy');
  await page.locator('#pol-hist').click();
  await page.locator(`#drawer [data-pv="${seeded.id}"]`).click();
  await expect(page.locator('#drawer pre')).toContainText('when: otherwise');
  await page.locator('#drawer [data-back]').click();
  await page.locator(`#drawer [data-pr="${seeded.id}"]`).click();
  await expect(card(page)).not.toContainText('(e2e edit)');
  const now = await inForce(page);
  expect(now.id).toBeGreaterThan(seeded.id);
  expect(now.text).toBe(seeded.text); // comments and all
});
