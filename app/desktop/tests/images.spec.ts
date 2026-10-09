import { test, expect } from '@playwright/test';

const image = { name: 'fixture.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64') };
const providers = [['line', 'LINE LINE'], ['instagram', '◎ Instagram'], ['slack', '# Slack'], ['x', '𝕏 𝕏'], ['messenger', '↯ Messenger']];

for (const [provider, label] of providers) {
  test(`${provider} image preview requires explicit send and keeps text draft`, async ({ page }) => {
    await page.goto('/?demo=1');
    await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
    if (provider !== 'line') await page.getByRole('button', { name: label, exact: true }).click();
    await expect(page.locator('.bubble').first()).toBeVisible();
    await expect(page.getByRole('button', { name: '画像を選択', exact: true })).toBeEnabled();
    const draft = page.getByRole('textbox', { name: 'メッセージ', exact: true });
    await draft.fill('残す架空の下書き');
    await page.getByLabel('送信する画像', { exact: true }).setInputFiles(image);
    await expect(page.getByAltText('送信前の画像プレビュー')).toBeVisible();
    if (provider === 'line') await page.screenshot({ path: '../docs/image-send-0.9.3-fixture.png' });
    expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send_image').length)).toBe(0);
    await page.getByRole('button', { name: 'この画像を送信', exact: true }).click();
    await expect(page.getByAltText('送信した画像', { exact: true })).toBeVisible();
    await expect(page.getByAltText('送信前の画像プレビュー')).toHaveCount(0);
    await expect(draft).toHaveValue('残す架空の下書き');
    expect(await page.evaluate(async p => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send_image' && c.provider === p).length, provider)).toBe(1);
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(/残す架空|data:image/);
  });
}

test('unknown image result stops resend until explicit confirmation', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  await page.getByLabel('送信する画像', { exact: true }).setInputFiles(image);
  await page.evaluate(async () => { (await import('/src/fixture.ts')).nextFailure['line:send_image'] = 'LINE_SEND_UNKNOWN'; });
  const send = page.getByRole('button', { name: 'この画像を送信', exact: true });
  await send.click();
  await expect(page.getByRole('checkbox', { name: /この画像は送信済みの可能性/ })).toBeVisible();
  await expect(send).toBeDisabled();
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send_image').length)).toBe(1);
  await page.getByRole('checkbox', { name: /この画像は送信済みの可能性/ }).check();
  await send.click();
  await expect(page.getByAltText('送信した画像', { exact: true })).toBeVisible();
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send_image').length)).toBe(2);
});

test('paste and drop select one image at the minimum window size without sending', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 500 });
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: /山田 はな/ }).click();
  await expect(page.getByRole('button', { name: '画像を選択', exact: true })).toBeEnabled();
  for (const event of ['paste', 'drop']) {
    await page.evaluate(({ event, base64 }) => {
      const data = new DataTransfer();
      const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
      data.items.add(new File([bytes], 'fixture.png', { type: 'image/png' }));
      const target = document.querySelector('.composer')!;
      target.dispatchEvent(event === 'paste' ? new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }) : new DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true }));
    }, { event, base64: image.buffer.toString('base64') });
    const send = page.getByRole('button', { name: 'この画像を送信', exact: true });
    await expect(send).toBeVisible();
    const box = await send.boundingBox();
    expect(box!.y + box!.height).toBeLessThanOrEqual(500);
    const heading = await page.getByRole('heading', { name: '山田 はな（架空）', exact: true }).boundingBox();
    expect(heading!.y).toBeGreaterThanOrEqual(0);
    await page.screenshot({ path: '../docs/image-send-0.9.3-minimum-fixture.png' });
    await page.getByRole('button', { name: '画像を外す', exact: true }).click();
  }
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send_image').length)).toBe(0);
});

test('invalid or oversized files are rejected and switching conversation clears image', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const input = page.getByLabel('送信する画像', { exact: true });
  await input.setInputFiles({ name: 'file.gif', mimeType: 'image/gif', buffer: image.buffer });
  await expect(page.getByRole('alert')).toContainText('JPEGまたはPNG');
  await input.setInputFiles({ ...image, buffer: Buffer.alloc(4 * 1024 * 1024 + 1) });
  await expect(page.getByRole('alert')).toContainText('4MB以内');
  await input.setInputFiles(image);
  await expect(page.getByAltText('送信前の画像プレビュー')).toBeVisible();
  await page.getByRole('button', { name: /佐藤 りく/ }).click();
  await expect(page.getByAltText('送信前の画像プレビュー')).toHaveCount(0);
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.op === 'send_image').length)).toBe(0);
});

test('conversation avatars survive provider remount without refetching', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByText('LINEへの接続を確認しました')).toBeVisible();
  const photo = page.getByAltText('山田 はな（架空）のプロフィール画像').first();
  await expect(photo).toBeVisible();
  const before = await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.provider === 'line' && c.op === 'avatar').length);
  await page.getByRole('button', { name: '# Slack', exact: true }).click();
  await expect(page.locator('.bubble').first()).toBeVisible();
  await page.getByRole('button', { name: 'LINE LINE', exact: true }).click();
  await expect(photo).toBeVisible();
  expect(await page.evaluate(async () => (await import('/src/fixture.ts')).calls.filter(c => c.provider === 'line' && c.op === 'avatar').length)).toBe(before);
});
