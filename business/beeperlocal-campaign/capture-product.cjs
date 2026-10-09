const { chromium } = require('/Users/haruotsuchiya/Documents/ChatGPT/BeeperLocal　検証/BeeperLocal_PoC_v0.4_Phase1/desktop/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const out = path.resolve(__dirname, '../stripe-site-draft/public/assets');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1200, height: 760 }, deviceScaleFactor: 1.5 });
  await page.goto('http://127.0.0.1:5197/?demo=1');
  await page.getByText('デザイン確認用・架空データ').waitFor();
  await page.getByText('LINEへの接続を確認しました').waitFor();
  await page.screenshot({ path: path.join(out, 'product-line.png') });
  await page.getByRole('button', { name: '◎ Instagram' }).click();
  await page.getByText('Instagramの架空メッセージです。').last().waitFor();
  await page.screenshot({ path: path.join(out, 'product-instagram.png') });
  await page.getByRole('button', { name: '# Slack' }).click();
  await page.getByText('Slackの架空メッセージです。').last().waitFor();
  await page.screenshot({ path: path.join(out, 'product-slack.png') });
  console.log('Captured three product screens using development-only fictional conversations.');
  await browser.close();
})();
