import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
});

test('switches provider, keeps drafts scoped, and sends once to the IG conversation', async ({ page }) => {
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('LINEの下書き');
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Instagramの友人（架空）' })).toBeVisible();
  await expect(composer).toHaveValue('');
  await expect(page.locator('.history-scope')).toContainText('直近20件');
  await composer.fill('Instagramだけに送る架空文');
  await page.getByRole('button', { name: '送信', exact: true }).dblclick();
  await expect(page.locator('.bubble').filter({ hasText: 'Instagramだけに送る架空文' })).toHaveCount(1);
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await expect(page.getByRole('heading', { name: '山田 はな（架空）' })).toBeVisible();
  await expect(composer).toHaveValue('LINEの下書き');
  await expect(page.locator('.bubble').filter({ hasText: 'Instagramだけに送る架空文' })).toHaveCount(0);
});

test('IG search and settings stay separate from LINE and its MCP', async ({ page }) => {
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '検索 ⌘ K' }).click();
  await page.getByRole('textbox', { name: '保存済みメッセージを検索' }).fill('Instagramの架空');
  await expect(page.getByText('1件の検索結果')).toBeVisible();
  await page.getByRole('button', { name: '接続設定' }).click();
  await expect(page.getByRole('heading', { name: 'Instagram接続' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'MCPを有効にする' })).toHaveCount(0);
  await page.getByRole('button', { name: '受信を停止' }).click();
  await expect(page.getByText('保存済みの会話を表示')).toBeVisible();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('保存する下書き');
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
});

test('IG byte limit and ambiguous response keep the draft', async ({ page }) => {
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('あ'.repeat(1334));
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  await composer.fill('結果不明のテスト');
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.getByText(/送信結果が不明です/)).toBeVisible();
  await expect(composer).toHaveValue('結果不明のテスト');
  await expect(page.getByText('結果が未確定の送信が1件あります。再送する前に履歴を確認してください。')).toBeVisible();
});

test('reopening remembers only the selected service and never stores the draft', async ({ page }) => {
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('保存してはいけない下書き');
  const stored = await page.evaluate(() => JSON.stringify(localStorage));
  expect(stored).toBe('{"beeperlocal.provider":"instagram"}');
  await page.reload();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'メッセージ', exact: true })).toHaveValue('');
});

test('a recovered receiver clears its connection error without leaking it to LINE', async ({ page }) => {
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('instagram', { receiving: 'reconnecting', retryAttempt: 1, errorCode: 'IG_REQUEST_FAILED' });
  });
  await expect(page.locator('.activity')).toContainText('Instagramとの接続が停止しました');
  await expect(page.locator('.chat-person')).toContainText('再接続中（1回目）');
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('instagram', { receiving: 'waiting', retryAttempt: 0, errorCode: null });
  });
  await expect(page.locator('.activity')).not.toContainText('Instagramとの接続が停止しました');
  await expect(page.locator('.chat-person')).toContainText('この会話を受信待機中');
  await page.getByRole('button', { name: 'LINE LINE' }).click();
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('instagram', { receiving: 'error', errorCode: 'IG_LOGIN_REQUIRED' });
  });
  await expect(page.locator('.activity')).not.toContainText('Instagram接続.command');
});

test('receiver recovery never hides an unknown send or its draft', async ({ page }) => {
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await expect(page.getByText('Instagramへの接続を確認しました')).toBeVisible();
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('結果不明のテスト');
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.locator('.activity')).toContainText('送信結果が不明です');
  await page.evaluate(async () => {
    const fixture = await import('/src/fixture.ts');
    fixture.emitStatus('instagram', { receiving: 'waiting', errorCode: null });
  });
  await expect(page.locator('.activity')).toContainText('送信結果が不明です');
  await expect(composer).toHaveValue('結果不明のテスト');
  await expect(page.getByText('結果が未確定の送信が1件あります。再送する前に履歴を確認してください。')).toBeVisible();
});
