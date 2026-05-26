import { expect, test } from "@playwright/test";

test("login against the real backend, open a project if present, then logout", async ({ page }) => {
  const adminPassword = process.env.E2E_ADMIN_PASSWORD || "admin123";
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(adminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  const firstProject = page.locator('a[href^="/projects/"]').first();
  if (await firstProject.isVisible().catch(() => false)) {
    const projectName = (await firstProject.locator("h3").textContent())?.trim();
    await firstProject.click();
    await expect(page).toHaveURL(/\/projects\/[^/]+$/);
    if (projectName) {
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    }
  }

  await page.getByRole("button", { name: /Log out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to QA Platform" })).toBeVisible();
});
