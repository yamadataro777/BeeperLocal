import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
});

test('opens a conversation, keeps Enter as newline and sends once with the button', async ({ page }) => {
  await page.screenshot({ path: '../docs/desktop-ui-fixture.png' });
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('テストの下書き');
  await composer.press('Enter');
  await composer.press('a');
  await expect(composer).toHaveValue('テストの下書き\na');
  await expect(page.locator('.bubble').filter({ hasText: 'テストの下書き' })).toHaveCount(0);
  await page.getByRole('button', { name: '送信', exact: true }).dblclick();
  await expect(page.locator('.bubble').filter({ hasText: 'テストの下書き' })).toHaveCount(1);
  await expect(composer).toHaveValue('');
});

test('drafts belong to their conversation and do not move to another recipient', async ({ page }) => {
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('はなさんへの下書き');
  await page.getByRole('button', { name: /佐藤 りく/ }).click();
  await expect(page.getByRole('heading', { name: '佐藤 りく（架空）' })).toBeVisible();
  await expect(composer).toHaveValue('');
  await expect(page.locator('.activity')).not.toContainText('会話を開いています');
  await composer.fill('りくさんへの下書き');
  await page.getByRole('button', { name: /山田 はな/ }).click();
  await expect(composer).toHaveValue('はなさんへの下書き');
});

test('searches saved messages and opens the correct conversation', async ({ page }) => {
  await page.getByRole('button', { name: '検索 ⌘ K' }).click();
  await page.getByRole('textbox', { name: '保存済みメッセージを検索' }).fill('資料');
  await expect(page.getByText('1件の検索結果')).toBeVisible();
  await page.getByRole('button', { name: /佐藤 りく.*資料を確認/ }).click();
  await expect(page.getByRole('heading', { name: '佐藤 りく（架空）' })).toBeVisible();
  await expect(page.locator('.highlighted .bubble')).toContainText('資料を確認しました');
});

test('ambiguous sends retain the draft and never silently retry', async ({ page }) => {
  const composer = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await composer.fill('結果不明のテスト');
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.getByText(/送信結果が不明です/)).toBeVisible();
  await expect(composer).toHaveValue('結果不明のテスト');
  await expect(page.locator('.bubble').filter({ hasText: '結果不明のテスト' })).toHaveCount(0);
});

test('offline viewing stays available and sending is disabled', async ({ page }) => {
  await page.getByRole('button', { name: '接続設定' }).click();
  await page.getByRole('button', { name: '受信を停止' }).click();
  await expect(page.getByText('保存済みの会話を表示')).toBeVisible();
  await expect(page.locator('.bubble').first()).toBeVisible();
  await page.getByRole('textbox', { name: 'メッセージ', exact: true }).fill('オフライン下書き');
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
});

test('narrow windows show one conversation pane at a time', async ({ page }) => {
  await page.setViewportSize({ width: 660, height: 720 });
  await page.getByRole('button', { name: /山田 はな/ }).click();
  await expect(page.getByRole('heading', { name: '山田 はな（架空）' })).toBeVisible();
  await page.getByRole('button', { name: '会話一覧へ戻る' }).click();
  await expect(page.getByRole('heading', { name: 'メッセージ', exact: true })).toBeVisible();
});
