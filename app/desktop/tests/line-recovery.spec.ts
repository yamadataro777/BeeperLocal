import { test, expect } from '@playwright/test';

test('LINE slow retries explain automatic recovery, preserve drafts and clear on recovery', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('回復待ちの下書き');
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('line', { receiving: 'reconnecting', retryAttempt: 7,
      errorCode: 'LINE_RECONNECT_WAITING' });
  });
  await expect(page.locator('.activity')).toContainText('1分間隔で自動的に再確認します');
  await expect(composer).toHaveValue('回復待ちの下書き');
  await expect(page.locator('.connection-strip')).toContainText('再接続中');
  await expect(page.locator('.connection-strip .status-dot')).not.toHaveClass(/online/);
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('line', { receiving: 'waiting', retryAttempt: 0, errorCode: null });
  });
  await expect(page.locator('.activity')).not.toContainText('1分間隔で自動的に再確認します');
  await expect(page.locator('.chat-person')).toContainText('全会話の新着を確認中');
  await expect(composer).toHaveValue('回復待ちの下書き');
});

test('LINE revoked login removes connected status and preserves draft and history for manual relink', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('切断しても残す下書き');
  const history = await page.locator('.timeline').innerText();
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('line', { connection: 'error', receiving: 'error', retryAttempt: 0, errorCode: 'LINE_SESSION_REVOKED' });
  });
  await expect(page.locator('.connection-strip')).toContainText('再ログインが必要');
  await expect(page.locator('.connection-strip .status-dot')).not.toHaveClass(/online/);
  await expect(page.locator('.activity')).toContainText('本家Beeper');
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  await expect(composer).toHaveValue('切断しても残す下書き');
  expect(await page.locator('.timeline').innerText()).toBe(history);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.screenshot({ path: '../docs/line-session-0.9.3-fixture.png' });
  await page.getByRole('button', { name: 'QRコードで再連携', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('同じLINEアカウントで同時利用できません');
  await expect(page.getByRole('img', { name: 'LINE連携用QRコード' })).toHaveCount(0);
});
