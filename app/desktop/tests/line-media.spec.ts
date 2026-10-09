import { test, expect } from '@playwright/test';

test('LINE images and stickers render, enlarge and never follow the next conversation', async ({ page }) => {
  await page.goto('/?demo=1&scenario=line-media');
  await expect(page.getByRole('img', { name: 'LINEの画像', exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: 'LINEのスタンプ', exact: true })).toBeVisible();
  for (const image of await page.locator('.media-open img').all()) {
    expect(await image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBeTruthy();
  }
  await page.getByRole('button', { name: '画像を拡大', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '画像の拡大表示' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: '画像の拡大表示' })).not.toBeVisible();
  await page.screenshot({ path: '../docs/line-media-fixture.png' });
  await page.getByRole('button', { name: /佐藤 りく/ }).click();
  await expect(page.getByRole('img', { name: 'LINEの画像', exact: true })).toHaveCount(0);
  await expect(page.locator('.bubble')).toContainText('資料を確認しました');
});

test('unavailable media stays in the timeline and can be retried', async ({ page }) => {
  await page.goto('/?demo=1&scenario=line-media-failure');
  await expect(page.getByText('画像を取得できませんでした')).toBeVisible();
  await expect(page.getByText('スタンプを取得できませんでした')).toBeVisible();
  await page.locator('.photo').getByRole('button', { name: '再読み込み' }).click();
  await expect(page.getByText('画像を取得できませんでした')).toBeVisible();
  await page.locator('.photo').getByRole('button', { name: '再読み込み' }).click();
  await expect(page.getByRole('img', { name: 'LINEの画像', exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'メッセージ', exact: true })).toBeEnabled();
});

test('switching service while media loads does not leak LINE media into Slack', async ({ page }) => {
  await page.goto('/?demo=1&scenario=line-media-slow');
  await expect(page.getByText('読み込み中…').first()).toBeVisible();
  await page.getByRole('button', { name: '# Slack' }).click();
  await expect(page.getByRole('heading', { name: 'Slackテスト（架空）' })).toBeVisible();
  await expect(page.locator('.line-media')).toHaveCount(0);
});
