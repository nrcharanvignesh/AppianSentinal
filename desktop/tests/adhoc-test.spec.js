const { test, expect } = require('@playwright/test');

async function openPanel(page) {
  await page.goto('/dev/adhoc-test', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Ad Hoc Test' })).toBeVisible();
}

async function runRule(page) {
  await page.getByRole('button', { name: 'TEST RULE' }).click();
  await expect(page.getByText('Static analysis is running.')).toBeVisible();
  await expect(page.getByText(/Static analysis completed:/)).toBeVisible();
}

test('renders the three official ad hoc test sections', async ({ page }) => {
  await openPanel(page);
  await expect(page.getByRole('heading', { name: 'Test Inputs' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Local Variable Values' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Test Output' })).toBeVisible();
  await expect(page.getByText(/Static analysis only/)).toBeVisible();
});

test('switches a rule input between static value and expression', async ({ page }) => {
  await openPanel(page);
  const modes = page.getByRole('radiogroup', { name: 'amount input mode' });
  const staticValue = modes.getByRole('radio', { name: 'Static value' });
  const expression = modes.getByRole('radio', { name: 'Expression' });
  await expect(staticValue).toBeChecked();
  await expression.check();
  await expect(expression).toBeChecked();
  await expect(page.getByLabel('Expression', { exact: true }).first()).toBeVisible();
});

test('TEST RULE shows pending state and a static analysis result', async ({ page }) => {
  await openPanel(page);
  const run = page.getByRole('button', { name: 'TEST RULE' });
  await run.click();
  await expect(page.getByRole('button', { name: 'TESTING...' })).toBeDisabled();
  await expect(page.getByText('Static analysis is running.')).toBeVisible();
  await expect(page.getByText(/no structural errors/)).toBeVisible();
  await expect(page.getByLabel('Formatted map output')).toContainText('fixture-success');
});

test('renders formatted map raw list and expression output views', async ({ page }) => {
  await openPanel(page);
  await runRule(page);
  await expect(page.getByLabel('Formatted map output')).toContainText('"analysis"');

  await page.getByRole('tab', { name: 'Raw list' }).click();
  await expect(page.getByLabel('Raw list output')).toContainText('["analysis"');

  await page.getByRole('tab', { name: 'Expression' }).click();
  await expect(page.getByLabel('Expression output')).toContainText('a!map(');
});

test('renders the failure fixture without claiming an Appian execution', async ({ page }) => {
  await openPanel(page);
  await page.locator('#adhoc-input-0').fill('-1');
  await page.getByRole('button', { name: 'TEST RULE' }).click();
  await expect(page.getByText(/invalid negative fixture value/)).toBeVisible();
  await expect(page.getByLabel('Formatted map output')).toContainText('fixture-failure');
  await expect(page.getByText(/Static analysis completed:/)).toBeVisible();
});

test('shows the real error reason', async ({ page }) => {
  await openPanel(page);
  await page.locator('#adhoc-input-0').fill('error');
  await page.getByRole('button', { name: 'TEST RULE' }).click();
  await expect(page.getByText(
    'Static analysis error: Referenced rule APP_MissingRule was not found in the export.',
  )).toBeVisible();
});

test('renders every official saved test status unchanged', async ({ page }) => {
  await openPanel(page);
  const statuses = [
    'Test passed',
    'Test failed: test output did not match asserted output',
    'Test failed: assertion expression returned false',
    'Test failed to run',
    'Test returned an error',
  ];
  for (const status of statuses) {
    await expect(page.getByText(status, { exact: true })).toBeVisible();
  }
});

test('supports keyboard input mode selection and test execution', async ({ page }) => {
  await openPanel(page);
  const staticValue = page.getByRole('radio', { name: 'Static value' }).first();
  await staticValue.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('radio', { name: 'Expression' }).first()).toBeChecked();
  await page.getByRole('button', { name: 'TEST RULE' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText(/Static analysis completed:/)).toBeVisible();
});

test('renders in light theme', async ({ page }) => {
  await openPanel(page);
  await page.getByRole('button', { name: 'Use light theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.locator('.adhoc-panel')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Test Inputs' })).toBeVisible();
});
