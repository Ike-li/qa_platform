import { expect, test } from "@playwright/test";
import { createProject, loginViaApi, uniqueSuffix } from "./helpers";

test("login against the real backend, open a seeded project, then logout", async ({
  page,
  request,
}) => {
  const suffix = uniqueSuffix();
  const { token } = await loginViaApi(request);
  const project = await createProject(request, token, {
    name: `E2E Login ${suffix}`,
    slug: `e2e-login-${suffix}`,
  });

  const adminPassword = process.env.E2E_ADMIN_PASSWORD || "admin123";
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(adminPassword);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { name: "Projects", exact: true })).toBeVisible();

  await page.getByRole("textbox", { name: "Search projects..." }).fill(project.name);
  const projectLink = page.locator(`a[href="/projects/${project.id}"]`);
  await expect(projectLink).toBeVisible();
  await expect(projectLink.getByRole("heading", { name: project.name })).toBeVisible();
  await projectLink.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}$`));
  await expect(page.getByRole("heading", { name: project.name })).toBeVisible();

  await page.getByRole("button", { name: /Log out/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to QA Platform" })).toBeVisible();
});
