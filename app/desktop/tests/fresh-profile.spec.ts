import { test, expect } from '@playwright/test';

for (const provider of ['line', 'instagram', 'slack', 'x', 'messenger']) {
  test(`${provider}: empty first launch offers setup and leaves MCP ungranted`, async ({ page }) => {
    const failures: string[] = [];
    page.on('pageerror', error => failures.push(error.name));
    await page.addInitScript(p => localStorage.setItem('beeperlocal.provider', p), provider);
    await page.goto('/?demo=1&scenario=fresh-profile');
    if (provider === 'line' || provider === 'x' || provider === 'messenger') {
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      const label = provider === 'line' ? 'QRコードを表示して連携' : provider === 'x' ? 'Xのログイン画面を開く' : 'Facebookのログイン画面を開く';
      await expect(dialog.getByRole('button', { name: label, exact: true })).toBeEnabled();
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
    } else if (provider === 'instagram') {
      await expect(page.locator('.welcome-feedback').getByRole('button', { name: 'Instagramにログイン', exact: true })).toBeEnabled();
    } else {
      await expect(page.locator('.welcome-feedback')).toContainText('Slackの新規ログインをまだ利用できません');
      await expect(page.locator('.welcome-feedback').getByRole('button', { name: 'Slackにログイン', exact: true })).toBeDisabled();
    }
    await expect(page.locator('.conversation')).toHaveCount(0);
    await expect(page.locator('.bubble')).toHaveCount(0);
    await page.getByRole('button', { name: '接続設定', exact: true }).click();
    const settings = page.getByRole('dialog');
    await expect(settings).toBeVisible();
    await settings.getByRole('tab', { name: 'MCP接続' }).click();
    await expect(settings).toContainText('MCP 停止中');
    await expect(settings.getByRole('button', { name: 'この権限で登録' })).toBeDisabled();
    await expect(settings.getByRole('region', { name: '新しい接続トークン' })).toHaveCount(0);
    await settings.getByRole('tab', { name: '保存管理' }).click();
    await expect(settings).toBeVisible();
    expect(failures).toEqual([]);
    const calls = await page.evaluate(async () => (await import('/src/fixture.ts')).calls);
    expect(calls.filter(c => c.op === 'send' || c.op === 'mcp_register' || c.op.endsWith('_login_start'))).toEqual([]);
  });
}

test('unconfigured Slack login does not interrupt an existing connection', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('beeperlocal.provider', 'slack'));
  await page.goto('/?demo=1&scenario=slack-unconfigured');
  await expect(page.getByText('Slackへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '接続設定', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('すでに接続済みのアカウントは再接続できます');
  await expect(page.getByRole('button', { name: 'Slackにログイン', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '再接続・一覧更新', exact: true })).toBeEnabled();
});
