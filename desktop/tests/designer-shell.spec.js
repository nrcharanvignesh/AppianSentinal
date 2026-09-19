const { test, expect } = require('@playwright/test');

const LABELS = ['Plan', 'Explore', 'Build', 'Packages', 'Deploy', 'Monitor'];

async function openShell(page) {
  await page.goto('/dev/designer-shell', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.designer-shell')).toHaveAttribute('data-hydrated', 'true');
  await expect(page.getByRole('navigation', { name: 'Application' })).toBeVisible();
}

test('navigation uses the official application order and labels', async ({ page }) => {
  await openShell(page);
  const navigation = page.getByRole('navigation', { name: 'Application' });
  await expect(navigation.getByRole('listitem')).toHaveCount(LABELS.length);
  await expect(navigation.locator('button')).toHaveText(LABELS);
});

test('active and unavailable navigation entries expose their states', async ({ page }) => {
  await openShell(page);
  await expect(page.getByRole('button', { name: 'Build' }))
    .toHaveAttribute('aria-current', 'page');

  const plan = page.getByRole('button', { name: 'Plan' });
  await expect(plan).toBeDisabled();
  await expect(plan.locator('..')).toHaveAttribute(
    'title',
    'This view is not available in Appian Sentinel yet.',
  );
});

test('keyboard navigation moves focus and activates a view', async ({ page }) => {
  await openShell(page);
  const build = page.getByRole('button', { name: 'Build' });
  const explore = page.getByRole('button', { name: 'Explore' });
  await build.focus();
  await page.keyboard.press('ArrowUp');
  await expect(explore).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(explore).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('heading', { name: 'Explore' })).toBeVisible();
});

test('quick search reports the submitted term', async ({ page }) => {
  await openShell(page);
  const search = page.getByRole('searchbox', { name: 'Quick search' });
  await search.fill('APP_Request');
  await search.press('Enter');
  await expect(page.getByText('Search term: APP_Request')).toBeVisible();
});

test('header renders application context and supplied menus', async ({ page }) => {
  await openShell(page);
  await expect(page.getByText('Sentinel Demo')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Back' })).toBeVisible();
  await expect(page.getByTitle('Settings menu')).toBeVisible();
  await expect(page.getByTitle('Navigation menu')).toBeVisible();
  await expect(page.getByTitle('User menu')).toBeVisible();
});

test('designer shell remains visible in light theme', async ({ page }) => {
  await openShell(page);
  await page.getByRole('button', { name: 'Use light theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.getByRole('banner')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Application' })).toBeVisible();
  for (const label of LABELS) {
    await expect(page.getByRole('button', { name: label })).toBeVisible();
  }
});
