import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:1432', browserName: 'chromium', channel: 'chrome', viewport: { width: 1180, height: 780 } },
  webServer: { command: 'npm run dev -- --port 1432 --strictPort', url: 'http://127.0.0.1:1432', reuseExistingServer: false },
});
