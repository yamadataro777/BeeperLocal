import { test, expect } from '@playwright/test';

test('X drafts, verified history, search and send stay in the selected provider', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('LINEの下書き');
  await page.getByRole('button', { name: '𝕏 𝕏', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Xの友人（架空）' })).toBeVisible();
  await expect(composer).toHaveValue('');
  await expect(page.locator('.history-scope')).toContainText('2件');
  await composer.fill('Xだけの架空メッセージ');
  await page.getByRole('button', { name: '送信', exact: true }).dblclick();
  await expect(page.locator('.bubble').filter({ hasText: 'Xだけの架空メッセージ' })).toHaveCount(1);
  await page.getByRole('button', { name: '検索 ⌘ K' }).click();
  await page.getByRole('textbox', { name: '保存済みメッセージを検索' }).fill('Xだけの');
  await expect(page.getByText('1件の検索結果')).toBeVisible();
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await expect(composer).toHaveValue('LINEの下書き');
  await expect(page.locator('.bubble').filter({ hasText: 'Xだけの架空メッセージ' })).toHaveCount(0);
});

test('X byte limit, ambiguous send and settings preserve safety state', async ({ page }) => {
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: '𝕏 𝕏', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Xの友人（架空）' })).toBeVisible();
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('あ'.repeat(3334));
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  await composer.fill('結果不明のテスト');
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.locator('.activity')).toContainText('送信結果が不明です');
  await expect(composer).toHaveValue('結果不明のテスト');
  await page.getByRole('button', { name: '接続設定' }).click();
  await expect(page.getByRole('button', { name: 'MCPを有効にする' })).toHaveCount(0);
  await page.getByRole('button', { name: '受信を停止' }).click();
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => ({ ...localStorage }))).toMatchObject({ 'beeperlocal.provider': 'x', 'beeperlocal.connected.x': '1' });
  expect(await page.evaluate(() => Object.keys(localStorage).every(k => /^beeperlocal\.(provider|connected\.(line|instagram|slack|x|messenger))$/.test(k)))).toBe(true);
});

test('X login uses a native window and never offers browser credential inputs', async ({ page }) => {
  await page.goto('/?demo=1&scenario=x-login');
  await page.getByRole('button', { name: '𝕏 𝕏', exact: true }).click();
  await expect(page.getByRole('heading', { name: '𝕏を連携' })).toBeVisible();
  await expect(page.locator('dialog input')).toHaveCount(0);
  await page.getByRole('button', { name: 'Xのログイン画面を開く' }).click();
  await expect(page.getByText('別ウィンドウでXにログインしてください。')).toBeVisible();
  await page.getByRole('button', { name: '連携を中止', exact: true }).click();
  await expect(page.getByRole('heading', { name: '𝕏を連携' })).toHaveCount(0);
});

test('X legacy text is visible and unsupported empty history does not imply a new conversation', async ({ page }) => {
  await page.goto('/?demo=1&scenario=x-legacy');
  await page.getByRole('button', { name: '𝕏 𝕏', exact: true }).click();
  await expect(page.locator('.bubble')).toContainText('Xの架空メッセージです。');
  await expect(page.locator('.history-scope')).toContainText('旧形式の本文1件（署名なし）');
  await page.goto('/?demo=1&scenario=x-empty');
  await expect(page.locator('.empty-history')).toContainText('未対応の形式のため表示できない履歴があります。');
  await expect(page.getByText('この会話を始めましょう')).toHaveCount(0);
});
