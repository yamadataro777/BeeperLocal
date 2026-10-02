import { test, expect } from '@playwright/test';

test('new user sees QR onboarding and cancellation clears the challenge', async ({ page }) => {
  await page.goto('/?demo=1&scenario=onboarding');
  const dialog = page.getByRole('dialog', { name: 'LINEを連携' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('note')).toContainText('この画面のQRコードではLINEに連携できません');
  await expect(page.getByRole('img', { name: 'LINE連携用QRコード' })).toHaveCount(0);
  await page.getByRole('button', { name: 'QRコードを表示して連携', exact: true }).click();
  await expect(page.getByRole('img', { name: 'LINE連携用QRコード' })).toBeVisible();
  await page.getByRole('button', { name: '連携を中止', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('img', { name: 'LINE連携用QRコード' })).toHaveCount(0);
});

test('phone PIN replaces QR and completion opens conversations', async ({ page }) => {
  await page.goto('/?demo=1&scenario=onboarding-success');
  await page.getByRole('button', { name: 'QRコードを表示して連携', exact: true }).click();
  await expect(page.getByLabel('スマートフォンに入力する確認コード')).toHaveText('123456');
  await expect(page.getByRole('img', { name: 'LINE連携用QRコード' })).toHaveCount(0);
  await expect(page.getByText('LINEの連携が完了しました', { exact: true })).toBeVisible();
  await expect(page.getByLabel('スマートフォンに入力する確認コード')).toHaveCount(0);
  await page.getByRole('button', { name: '会話一覧を開く', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'LINEを連携' })).toHaveCount(0);
  await expect(page.getByText('LINE 接続確認済み', { exact: true })).toBeVisible();
});

test('failed login removes the QR and allows retry', async ({ page }) => {
  await page.goto('/?demo=1&scenario=onboarding-failed');
  await page.getByRole('button', { name: 'QRコードを表示して連携', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('連携を完了できませんでした');
  await expect(page.getByRole('img', { name: 'LINE連携用QRコード' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'QRコードを表示して連携', exact: true })).toBeEnabled();
});

test('existing user explicitly chooses replacement and profile images render', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByRole('img', { name: '山田 はな（架空）のプロフィール画像' }).first()).toBeVisible();
  await page.getByRole('button', { name: '接続設定', exact: true }).click();
  await page.getByRole('button', { name: 'QRコードでLINEを連携・再ログイン', exact: true }).click();
  await expect(page.getByRole('button', { name: 'QRコードを表示して連携', exact: true })).toBeDisabled();
  await page.getByLabel('このMacに保存済みのLINEログインを更新する').check();
  await expect(page.getByRole('button', { name: 'QRコードを表示して連携', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '連携画面を閉じる', exact: true }).click();
});
