import { test, expect } from '@playwright/test';

test('explains an OS Keychain failure and retry does not move the connect button', async ({ page }) => {
  await page.goto('/?demo=1&scenario=keychain-session');
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Macのキーチェーン自体で認証エラー');
  await expect(alert).toContainText('作業を保存してMacを再起動');
  const button = page.getByRole('button', { name: 'LINEに接続する', exact: true });
  const before = await button.boundingBox();
  await button.click();
  await expect(alert).toContainText('Macのキーチェーン自体で認証エラー');
  await expect(button).toBeEnabled();
  const after = await button.boundingBox();
  expect(Math.abs(after!.x - before!.x)).toBeLessThan(1);
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(1);
  expect(after!.width).toBe(before!.width);
  await page.screenshot({ path: '../docs/desktop-keychain-fixture.png' });
});

test('can connect after the Mac authentication state recovers', async ({ page }) => {
  await page.goto('/?demo=1&scenario=keychain-once');
  await expect(page.getByRole('alert')).toContainText('Macのキーチェーン自体で認証エラー');
  await page.getByRole('button', { name: 'LINEに接続する', exact: true }).click();
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await expect(page.getByRole('heading', { name: '山田 はな（架空）' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
