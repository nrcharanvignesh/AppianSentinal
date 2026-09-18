const { defineConfig, devices } = require('@playwright/test');

const port = process.env.SENTINEL_PW_PORT || '8911';
const channel = process.env.SENTINEL_PW_CHANNEL || 'msedge';

module.exports = defineConfig({
  testDir: './tests',
  outputDir: './test-results/playwright',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1024, height: 640 },
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    ...(channel ? { channel } : {}),
  },
  webServer: {
    command: `npx next dev -p ${port} --hostname 127.0.0.1`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 180000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1024, height: 640 },
        ...(channel ? { channel } : {}),
      },
    },
  ],
});
