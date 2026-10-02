import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '# Slack' }).click();
  await expect(page.getByText('Slackへの接続を確認しました')).toBeVisible();
});

test('Slack user conversations, polling scope, send and draft isolation', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Slackテスト（架空）' })).toBeVisible();
  await expect(page.locator('.chat-person')).toContainText('定期取得待機中');
  await expect(page.locator('.history-scope')).toContainText('スレッドはMCPから個別取得');
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('Slackだけの架空送信');
  await page.getByRole('button', { name: '送信', exact: true }).dblclick();
  await expect(page.locator('.bubble').filter({ hasText: 'Slackだけの架空送信' })).toHaveCount(1);
  await composer.fill('Slack下書き');
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await expect(page.getByRole('heading', { name: '山田 はな（架空）' })).toBeVisible();
  await expect(composer).toHaveValue('');
  await expect(page.locator('.bubble').filter({ hasText: 'Slackだけの架空送信' })).toHaveCount(0);
  await page.getByRole('button', { name: '# Slack' }).click();
  await expect(composer).toHaveValue('Slack下書き');
});

test('Slack MCP settings and grants are independent of LINE', async ({ page }) => {
  await page.getByRole('button', { name: '接続設定' }).click();
  await expect(page.getByRole('tab', { name: 'Slack接続' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'QRコードでLINEを連携・再ログイン' })).toHaveCount(0);
  await page.getByRole('tab', { name: 'MCP接続' }).click();
  await expect(page.getByRole('spinbutton', { name: 'ポート番号' })).toHaveValue('28642');
  await page.getByRole('textbox', { name: 'クライアント名', exact: true }).fill('Slack専用');
  await page.getByLabel('Slackテスト（架空）', { exact: true }).check();
  await page.getByRole('button', { name: 'この権限で登録' }).click();
  await expect(page.getByRole('region', { name: '新しい接続トークン' })).toContainText('28642');
  await page.getByRole('button', { name: '設定を閉じる' }).click();
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await expect(page.getByRole('heading', { name: '山田 はな（架空）' })).toBeVisible();
  await page.getByRole('button', { name: '接続設定' }).click();
  await page.getByRole('tab', { name: 'MCP接続' }).click();
  await expect(page.getByRole('spinbutton', { name: 'ポート番号' })).toHaveValue('28641');
  await expect(page.getByText('Slack専用', { exact: true })).toHaveCount(0);
});

test('Slack unknown send retains draft and input has a 4000 character limit', async ({ page }) => {
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('あ'.repeat(4001));
  await expect(composer).toHaveValue('あ'.repeat(4000));
  await composer.fill('結果不明のテスト');
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.locator('.activity')).toContainText('Slackの送信結果が不明です');
  await expect(composer).toHaveValue('結果不明のテスト');
  await expect(page.getByText('結果が未確定の送信が1件あります。再送する前に履歴を確認してください。')).toBeVisible();
});
