import { test, expect } from '@playwright/test';

test('unread aggregates background services and is not marked read behind settings', async ({ page }) => {
  await page.goto('/?demo=1&scenario=extensions');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.evaluate(async () => { const f = await import('/src/fixture.ts'); f.addUnread('instagram'); f.addUnread('slack'); });
  await expect(page.getByLabel('全サービスの未読')).toContainText('6');
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'mark_read' && c.provider !== 'line'))).toEqual([]);
  await page.getByRole('button', { name: /◎ Instagram/ }).click();
  await page.getByRole('button', { name: '接続設定', exact: true }).click();
  await page.evaluate(async () => (await import('/src/fixture.ts')).addUnread('instagram'));
  await expect(page.getByLabel('Instagramの未読')).toContainText('3');
  await page.getByRole('button', { name: '設定を閉じる' }).click();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).focus();
  await expect(page.getByLabel('全サービスの未読')).toContainText('3');
  await expect(page.getByLabel('Slackの未読')).toContainText('3');
});

test('older saved pages and resumable history keep groups and attachments visible', async ({ page }) => {
  await page.goto('/?demo=1&scenario=extensions');
  await page.getByRole('button', { name: '◎ Instagram', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Instagramの友人（架空）' })).toBeVisible();
  await expect(page.locator('.conversation')).toContainText('グループ');
  await page.getByRole('button', { name: '保存済みの過去履歴を表示', exact: true }).click();
  await expect(page.locator('.bubble').filter({ hasText: '過去ページの架空メッセージ' })).toHaveCount(1);
  await expect(page.locator('.bubble').filter({ hasText: 'Instagramの架空メッセージ' })).toHaveCount(1);
  await page.getByRole('button', { name: '画像を表示', exact: true }).click();
  await expect(page.locator('.attachment img')).toHaveAttribute('src', /^data:image\/png;base64,/);
  await page.getByRole('button', { name: 'この会話の過去履歴を取得', exact: true }).click();
  await expect(page.getByRole('button', { name: 'この会話の過去取得を停止', exact: true })).toBeVisible();
  await expect(page.locator('.bubble').filter({ hasText: '過去ページの架空メッセージ' })).toHaveCount(1);
  await expect(page.locator('.attachment img')).toHaveAttribute('src', /^data:image\/png;base64,/);
  await page.screenshot({ path: '../docs/inbox-0.9.0-fixture.png' });
  await page.getByRole('button', { name: '# Slack', exact: true }).click();
  await expect(page.locator('.attachment img')).toHaveCount(0);
});

for (const [provider, name] of [['instagram', '◎ Instagram'], ['x', '𝕏 𝕏'], ['messenger', '↯ Messenger'], ['slack', '# Slack']]) {
  test(`${provider} local deletion is confirmed and leaves LINE data available`, async ({ page }) => {
    await page.goto('/?demo=1');
    await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
    await page.getByRole('button', { name, exact: true }).click();
    await expect(page.locator('.bubble').first()).toBeVisible();
    await page.getByRole('button', { name: '接続設定', exact: true }).click();
    await page.getByRole('tab', { name: '保存管理', exact: true }).click();
    await page.getByRole('button', { name: '削除対象を確認', exact: true }).click();
    await expect(page.getByRole('button', { name: '確認したデータを削除', exact: true })).toBeDisabled();
    await page.getByRole('checkbox', { name: 'このMacの対象データを削除することを確認しました', exact: true }).check();
    await page.getByRole('button', { name: '確認したデータを削除', exact: true }).click();
    await expect(page.getByRole('region', { name: '保存管理' })).toContainText('対象データを削除しました');
    await page.getByRole('button', { name: '設定を閉じる' }).click();
    await expect(page.locator('.bubble')).toHaveCount(0);
    await page.getByRole('button', { name: 'LINE LINE', exact: true }).click();
    await expect(page.locator('.bubble').first()).toContainText('週末');
  });
}

test('notification preference is explicit and update checking preserves drafts', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await expect(page.getByRole('button', { name: '通知 オフ', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: '通知 オフ', exact: true }).click();
  await expect(page.getByRole('button', { name: '通知 オン', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const input = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await input.fill('保存しない架空の下書き');
  await page.getByRole('button', { name: '更新を確認', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('新しい更新はありません');
  await expect(input).toHaveValue('保存しない架空の下書き');
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('架空の下書き');
});
