import { test, expect } from "@playwright/test";
import { createSession, lassoAllPoints } from "./acceptance.spec";

test.describe("Phase 8 item 3: saved analyses", () => {
  test("save, reload with different state, then load restores it", async ({ page }) => {
    const userId = `e2e-user-${Date.now()}`;

    await createSession(page);
    await lassoAllPoints(page);
    await page.locator('[data-testid^="metric-row-"]').first().click();

    await page.getByTestId("band-select").click();
    await page.getByRole("option", { name: "24h" }).click();

    await page.getByTestId("user-id-input").fill(userId);
    await page.getByTestId("analysis-name-input").fill("my saved view");
    await page.getByTestId("save-analysis-btn").click();

    await expect(page.getByTestId("saved-analyses-list").getByText("my saved view")).toBeVisible({
      timeout: 10_000,
    });

    // change state away from what was saved
    await page.getByTestId("band-select").click();
    await page.getByRole("option", { name: "5m" }).click();
    await expect(page.getByTestId("band-select")).toContainText("5m");

    // load it back
    await page.getByTestId("saved-analyses-list").getByText("my saved view").click();
    await expect(page.getByTestId("band-select")).toContainText("24h", { timeout: 10_000 });
  });

  test("saved analyses are scoped per user", async ({ page }) => {
    const userA = `e2e-user-a-${Date.now()}`;
    const userB = `e2e-user-b-${Date.now()}`;

    await createSession(page);
    await page.getByTestId("user-id-input").fill(userA);
    await page.getByTestId("analysis-name-input").fill("user A's analysis");
    await page.getByTestId("save-analysis-btn").click();
    await expect(page.getByTestId("saved-analyses-list").getByText("user A's analysis")).toBeVisible({
      timeout: 10_000,
    });

    await page.getByTestId("user-id-input").fill(userB);
    await expect(page.getByTestId("saved-analyses-list").getByText("user A's analysis")).toHaveCount(0);
  });

  test("delete removes the saved analysis from the list", async ({ page }) => {
    const userId = `e2e-user-del-${Date.now()}`;

    await createSession(page);
    await page.getByTestId("user-id-input").fill(userId);
    await page.getByTestId("analysis-name-input").fill("to be deleted");
    await page.getByTestId("save-analysis-btn").click();
    const row = page.getByTestId("saved-analyses-list").getByText("to be deleted");
    await expect(row).toBeVisible({ timeout: 10_000 });

    await page.locator('[data-testid^="delete-"]').first().click();
    await expect(row).toHaveCount(0);
  });
});
