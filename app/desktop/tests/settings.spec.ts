import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '接続設定' }).click();
});

test('MCP defaults to no conversations and no send, shows token once, revokes client', async ({ page }) => {
  await page.getByRole('tab', { name: 'MCP接続' }).click();
  await expect(page.getByText('MCP 停止中', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '選んだ会話への送信を許可' })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: '山田 はな（架空）' })).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'この権限で登録' })).toBeDisabled();
  await page.getByRole('button', { name: 'MCPを有効にする' }).click();
  await expect(page.getByText('MCP 接続受付中', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'クライアント名' }).fill('検証用AI');
  await page.getByRole('checkbox', { name: '山田 はな（架空）' }).check();
  await page.getByRole('button', { name: 'この権限で登録' }).click();
  await expect(page.getByRole('textbox', { name: 'トークン', exact: true })).toHaveValue('blc_FIXTURE_TOKEN_SHOWN_ONCE');
  await page.screenshot({ path: '../docs/desktop-0.6.0-mcp-fixture.png' });
  await page.getByRole('button', { name: '設定を閉じる' }).click();
  await page.getByRole('button', { name: '接続設定' }).click();
  await page.getByRole('tab', { name: 'MCP接続' }).click();
  await expect(page.getByRole('region', { name: '新しい接続トークン' })).toHaveCount(0);
  await expect(page.getByText('検証用AI', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '検証用AIの権限を取り消す' }).click();
  await expect(page.getByText('まだ登録されていません。')).toBeVisible();
});

test('storage deletion requires preview and confirmation and clears displayed content', async ({ page }) => {
  await page.getByRole('tab', { name: '保存管理' }).click();
  await page.getByRole('button', { name: '削除対象を確認' }).click();
  await expect(page.getByText('保存停止中', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '確認したデータを削除' })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'このMacの対象データを削除することを確認しました' }).check();
  await page.getByRole('button', { name: '確認したデータを削除' }).click();
  await expect(page.getByText('対象データを削除しました。保存は停止中です。')).toBeVisible();
  await page.getByRole('button', { name: '設定を閉じる' }).click();
  await expect(page.locator('.bubble')).toHaveCount(0);
  await expect(page.getByText('0件の会話')).toBeVisible();
});

test('pausing storage disables sending while saved history remains', async ({ page }) => {
  await page.getByRole('tab', { name: '保存管理' }).click();
  await page.getByRole('button', { name: '保存を停止', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存を再開' })).toBeVisible();
  await page.getByRole('button', { name: '設定を閉じる' }).click();
  await expect(page.locator('.bubble').first()).toBeVisible();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('保存停止中');
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
});
