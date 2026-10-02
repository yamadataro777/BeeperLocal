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
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('line', { receiving: 'waiting', retryAttempt: 0, errorCode: null });
  });
  await expect(page.locator('.activity')).not.toContainText('1分間隔で自動的に再確認します');
  await expect(page.locator('.chat-person')).toContainText('この会話を受信待機中');
  await expect(composer).toHaveValue('回復待ちの下書き');
});
