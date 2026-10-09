import { test, expect } from '@playwright/test';

async function openSlack(page: import('@playwright/test').Page, scenario = '') {
  await page.goto('/?demo=1' + (scenario ? `&scenario=${scenario}` : ''));
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '# Slack' }).click();
  await expect(page.getByText('Slackへの接続を確認しました')).toBeVisible();
}

test('Slack messages show the sender name and a decoded profile image', async ({ page }) => {
  await openSlack(page);
  await expect(page.locator('.sender-name')).toHaveText('Slackの花子（架空）');
  const image = page.locator('.sender-profile img');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('.chat-header > .avatar')).toHaveText('#');
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await expect(page.locator('.sender-profile')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '山田 はな（架空）' })).toBeVisible();
});

test('Slack DM profile images appear in the list and header', async ({ page }) => {
  await openSlack(page, 'slack-dm-profile');
  await expect(page.locator('.conversation .avatar img')).toHaveCount(1);
  await expect(page.locator('.chat-header > .avatar img')).toBeVisible();
});

test('Missing profile permission is explained while messages remain readable', async ({ page }) => {
  await openSlack(page, 'slack-profiles-permission');
  await expect(page.locator('.profile-notice')).toContainText('プロフィール閲覧の許可が必要');
  await expect(page.locator('.bubble')).toContainText('Slackの架空メッセージ');
  await expect(page.locator('.sender-name')).toHaveText('Slackメンバー');
  await expect(page.locator('.sender-profile img')).toHaveCount(0);
  await page.locator('.profile-notice').getByRole('button', { name: '接続設定' }).click();
  await expect(page.getByRole('tab', { name: 'Slack接続' })).toBeVisible();
});
