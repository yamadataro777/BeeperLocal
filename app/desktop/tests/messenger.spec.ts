import { test, expect } from '@playwright/test';

test('Messenger displays and searches saved encrypted text and sends once through its own composer', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('LINEの下書き');
  await page.getByRole('button', { name: '↯ Messenger', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Messengerの友人（架空）' })).toBeVisible();
  await expect(page.locator('.bubble')).toContainText('Messengerの架空メッセージ');
  await expect(page.getByText('Messengerへの接続を確認しました')).toBeVisible();
  await page.screenshot({ path: '../docs/messenger-integration-fixture.png' });
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('架空の返信');
  await page.getByRole('button', { name: '送信', exact: true }).dblclick();
  await expect(page.locator('.bubble').filter({ hasText: '架空の返信' })).toHaveCount(1);
  await expect(page.locator('.history-scope').first()).toContainText('暗号化バックアップ復元');
  await page.getByRole('button', { name: '検索 ⌘ K' }).click();
  await page.getByRole('textbox', { name: '保存済みメッセージを検索' }).fill('Messenger');
  await expect(page.getByText('1件の検索結果')).toBeVisible();
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await expect(page.getByRole('textbox', { name: 'メッセージ', exact: true })).toHaveValue('LINEの下書き');
  await expect(page.locator('.bubble').filter({ hasText: 'Messengerの架空' })).toHaveCount(0);
});

test('Messenger native login can be cancelled and has no credential fields', async ({ page }) => {
  await page.goto('/?demo=1&scenario=messenger-login');
  await page.getByRole('button', { name: '↯ Messenger', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Messengerを連携' })).toBeVisible();
  await expect(page.locator('dialog input')).toHaveCount(0);
  await page.getByRole('button', { name: 'Facebookのログイン画面を開く' }).click();
  await expect(page.getByText('別ウィンドウでFacebookにログインしてください。')).toBeVisible();
  await page.getByRole('button', { name: '連携を中止', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Messengerを連携' })).toHaveCount(0);
});

test('Messenger settings pause reception without reusing MCP permissions', async ({ page }) => {
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: '↯ Messenger', exact: true }).click();
  await expect(page.getByText('Messengerへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '接続設定' }).click();
  await expect(page.getByRole('heading', { name: 'Messenger接続' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'MCPを有効にする' })).toHaveCount(0);
  await page.getByRole('tab', { name: '保存管理', exact: true }).click();
  await page.getByRole('button', { name: '保存を停止', exact: true }).click();
  await expect(page.getByRole('region', { name: '保存管理' }).getByText('保存停止中', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => ({ ...localStorage }))).toMatchObject({ 'beeperlocal.provider': 'messenger', 'beeperlocal.connected.messenger': '1' });
  expect(await page.evaluate(() => Object.keys(localStorage).every(k => /^beeperlocal\.(provider|connected\.(line|instagram|slack|x|messenger))$/.test(k)))).toBe(true);
});

test('Unknown registration does not offer an automatic retry or claim empty history', async ({ page }) => {
  await page.goto('/?demo=1&scenario=messenger-unknown');
  await page.getByRole('button', { name: '↯ Messenger', exact: true }).click();
  await expect(page.locator('.activity')).toContainText('自動再登録せず');
  await expect(page.getByRole('heading', { name: 'Messengerを連携' })).toHaveCount(0);
  await expect(page.locator('.bubble')).toContainText('Messengerの架空メッセージ');
});
