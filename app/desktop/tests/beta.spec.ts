import { test, expect } from '@playwright/test';

test('search failure clears older hits and allows another search', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '検索 ⌘ K' }).click();
  const query = page.getByRole('textbox', { name: '保存済みメッセージを検索' });
  await query.fill('資料');
  await expect(page.locator('.search-result')).toHaveCount(1);
  await page.evaluate(async () => { (await import('/src/fixture.ts')).nextFailure['line:search'] = 'LOCAL_DB_UNAVAILABLE'; });
  await query.fill('別の架空語');
  await expect(page.getByRole('alert')).toContainText('検索を完了できませんでした');
  await expect(page.locator('.search-result')).toHaveCount(0);
  await query.fill('資料');
  await expect(page.locator('.search-result')).toHaveCount(1);
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('a saved search hit outside the latest remote catalog can be opened', async ({ page }) => {
  await page.goto('/?demo=1&scenario=beta-hidden');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await expect(page.locator('.conversation')).toHaveCount(1);
  await page.getByRole('button', { name: '検索 ⌘ K' }).click();
  await page.getByRole('textbox', { name: '保存済みメッセージを検索' }).fill('資料');
  await page.getByRole('button', { name: /一覧外の友人.*資料/ }).click();
  await expect(page.getByRole('heading', { name: '一覧外の友人（架空）' })).toBeVisible();
  await expect(page.locator('.highlighted .bubble')).toContainText('資料を確認しました');
});

test('unknown sends require confirmation before a second attempt, including keyboard send', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const input = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await input.fill('結果不明のテスト');
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  await input.press('Meta+Enter');
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send').length)).toBe(1);
  await page.getByRole('checkbox', { name: /この下書きは送信済み/ }).check();
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /この下書きは送信済み/ })).not.toBeChecked();
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send').length)).toBe(2);
  await input.fill('別の下書き');
  await expect(page.getByRole('checkbox', { name: /この下書きは送信済み/ })).toHaveCount(0);
});

test('Core exit immediately disables send without discarding drafts or saved history', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const input = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await input.fill('失ってはいけない架空の下書き');
  await page.evaluate(async () => { (await import('/src/fixture.ts')).emitFatal(); });
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  await expect(input).toHaveValue('失ってはいけない架空の下書き');
  await expect(page.locator('.bubble').first()).toBeVisible();
  await expect(page.locator('.activity')).toContainText('接続プロセスが停止しました');
});

test('paused first launch explains how to resume and does not connect automatically', async ({ page }) => {
  await page.goto('/?demo=1&scenario=beta-paused');
  await expect(page.locator('.welcome-feedback')).toContainText('保存を停止中です');
  await expect(page.getByRole('button', { name: 'LINEに接続する', exact: true })).toBeDisabled();
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.some(c => c.op === 'connect'))).toBe(false);
  await page.locator('.welcome-feedback').getByRole('button', { name: '接続設定を開く' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
});

test('onboarding errors remain visible at the minimum window width', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 500 });
  await page.goto('/?demo=1&scenario=keychain-session');
  await expect(page.locator('.mobile-feedback')).toContainText('Macのキーチェーン自体で認証エラー');
  await page.locator('.mobile-feedback').getByRole('button', { name: '接続設定を開く' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
});

test('help states service limitations and diagnostics omit content and identities', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('PRIVATE_DRAFT_CANARY');
  await page.getByRole('button', { name: '使い方・ベータ版の対応範囲' }).click();
  await expect(page.getByRole('dialog')).toContainText('過去の暗号化バックアップの復元は未対応');
  const diagnostics = await page.getByRole('textbox', { name: '共有用の診断情報' }).inputValue();
  expect(JSON.parse(diagnostics)).toMatchObject({ version: '0.9.5', provider: 'line', conversations: 2 });
  for (const forbidden of ['PRIVATE_DRAFT_CANARY', '山田', 'カフェ', 'a'.repeat(64), 'token']) expect(diagnostics).not.toContain(forbidden);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

for (const [button, label, provider] of [['◎ Instagram', 'Instagram', 'instagram']]) {
  test(`${label} login uses the bundled setup and stops only its receiver`, async ({ page }) => {
    await page.goto('/?demo=1');
    await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
    await page.getByRole('button', { name: button, exact: true }).click();
    await expect(page.getByText(`${label}への接続を確認しました`)).toBeVisible();
    await page.getByRole('button', { name: '接続設定', exact: true }).click();
    await page.getByRole('button', { name: `${label}にログイン`, exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Instagram公式サイトの専用ログイン画面');
    await expect(page.getByText('Instagram公式サイトの専用画面でログインと本人確認を進めます。通知が来ない場合は、公式画面に表示される別の確認方法を選んでください。')).toBeVisible();
    const result = await page.evaluate(async () => { const f = await import('/src/fixture.ts'); return { launches: f.setupLaunches, stops: f.calls.filter(c => c.op === 'stop') }; });
    expect(result).toEqual({ launches: [provider], stops: [{ provider, op: 'stop' }] });
  });
}

test('a one-time MCP token survives a subsequent management refresh failure', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '接続設定', exact: true }).click();
  await page.getByRole('tab', { name: 'MCP接続' }).click();
  await page.getByLabel('クライアント名').fill('Fixture client');
  await page.getByRole('checkbox', { name: '山田 はな（架空）' }).check();
  await page.evaluate(async () => { (await import('/src/fixture.ts')).nextFailure['line:management'] = 'LOCAL_DB_UNAVAILABLE'; });
  await page.getByRole('button', { name: 'この権限で登録' }).click();
  await expect(page.getByRole('region', { name: '新しい接続トークン' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('保存データを開けません');
});


test('Slack login opens the browser approval flow without token inputs', async ({ page }) => {
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: '# Slack', exact: true }).click();
  await expect(page.getByText('Slackへの接続を確認しました')).toBeVisible();
  await page.getByRole('button', { name: '接続設定', exact: true }).click();
  await page.getByRole('button', { name: 'Slackにログイン', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('ブラウザでSlackの承認を待っています');
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'ログインを中止' }).click();
  const calls = await page.evaluate(async () => (await import('/src/fixture.ts')).calls);
  expect(calls.filter(c => c.op.startsWith('slack_login')).map(c => c.op)).toContain('slack_login_cancel');
});
