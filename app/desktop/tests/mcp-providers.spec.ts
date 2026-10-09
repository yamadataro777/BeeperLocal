import { test, expect } from '@playwright/test';

for (const [provider, button, title, port] of [
  ['instagram', '◎ Instagram', 'Instagramの友人（架空）', 28644],
  ['x', '𝕏 𝕏', 'Xの友人（架空）', 28645],
  ['messenger', '↯ Messenger', 'Messengerの友人（架空）', 28646],
] as const) {
  test(`${provider} MCP grants, URL and tokens remain provider-scoped`, async ({ page }) => {
    await page.goto('/?demo=1');
    await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
    await page.getByRole('button', { name: button, exact: true }).click();
    await expect(page.getByRole('heading', { name: title })).toBeVisible();
    await page.getByRole('button', { name: '接続設定', exact: true }).click();
    await page.getByRole('tab', { name: 'MCP接続' }).click();
    await expect(page.getByRole('textbox', { name: '接続先URL' })).toHaveValue(`http://127.0.0.1:${port}/mcp`);
    await expect(page.getByRole('checkbox', { name: '選んだ会話への送信を許可' })).not.toBeChecked();
    await expect(page.getByRole('checkbox', { name: '保存済みメッセージの閲覧・検索を許可', exact: true })).toBeChecked();
    await expect(page.getByRole('checkbox', { name: title })).not.toBeChecked();
    await expect(page.getByRole('checkbox', { name: '山田 はな（架空）' })).toHaveCount(0);
    await page.getByRole('button', { name: 'MCPを有効にする' }).click();
    await expect(page.getByText('MCP 接続受付中', { exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: 'クライアント名' }).fill('サービス専用AI');
    await page.getByRole('checkbox', { name: title }).check();
    await page.getByRole('button', { name: 'この権限で登録' }).click();
    await expect(page.getByRole('textbox', { name: 'トークン', exact: true })).toHaveValue(`blc_FIXTURE_${provider}_ONCE`);
    await page.getByRole('button', { name: 'トークンを隠す' }).click();
    await page.screenshot({ path: `../docs/mcp-0.9.1-${provider}-fixture.png` });
    await page.getByRole('button', { name: '設定を閉じる' }).click();
    await page.getByRole('button', { name: 'LINE LINE', exact: true }).click();
    await page.getByRole('button', { name: '接続設定', exact: true }).click();
    await page.getByRole('tab', { name: 'MCP接続' }).click();
    await expect(page.getByText('MCP 停止中', { exact: true })).toBeVisible();
    await expect(page.getByText('サービス専用AI', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '設定を閉じる' }).click();
    await page.getByRole('button', { name: button, exact: true }).click();
    await page.getByRole('button', { name: '接続設定', exact: true }).click();
    await page.getByRole('tab', { name: 'MCP接続' }).click();
    await expect(page.getByRole('region', { name: '新しい接続トークン' })).toHaveCount(0);
    await page.getByRole('button', { name: 'サービス専用AIの権限を取り消す' }).click();
    await expect(page.getByText('まだ登録されていません。')).toBeVisible();
  });
}
