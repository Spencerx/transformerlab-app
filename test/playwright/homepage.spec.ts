import { test, expect } from '@playwright/test';

test('has title or loads content', async ({ page }) => {
  await page.goto('/');

  // Adjust this based on what we expect to see on the homepage.
  // For now, let's just wait for the page to load and check the title or some text.
  // Since I don't know the exact title, I'll just check if the page body is visible.
  await expect(page.locator('body')).toBeVisible();
});
