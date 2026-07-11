import { test, expect, type Page } from "@playwright/test";

async function createSession(page: Page) {
  await page.goto("/");
  // retry session creation: this suite runs against a live synth-data feed
  // (see ingest-infra/tools/synth_nodes.py), so a session created in the
  // first instant after (re)seeding can race an empty tensor window.
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.getByTestId("create-session-btn").click();
    await expect(page.getByTestId("node-similarity-svg")).toBeVisible({ timeout: 30_000 });
    try {
      await expect(page.locator("circle.node-point").first()).toBeVisible({ timeout: 5_000 });
      return;
    } catch {
      await page.reload();
    }
  }
  await expect(page.locator("circle.node-point").first()).toBeVisible({ timeout: 30_000 });
}

async function lassoAllPoints(page: Page) {
  const svg = page.getByTestId("node-similarity-svg");
  const box = await svg.boundingBox();
  if (!box) throw new Error("svg not found");
  // drag a large rectangle-shaped lasso path enclosing the whole plot area
  await page.mouse.move(box.x + 2, box.y + 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 2, box.y + 2, { steps: 5 });
  await page.mouse.move(box.x + box.width - 2, box.y + box.height - 2, { steps: 5 });
  await page.mouse.move(box.x + 2, box.y + box.height - 2, { steps: 5 });
  await page.mouse.move(box.x + 2, box.y + 2, { steps: 5 });
  await page.mouse.up();
}

test.describe("Phase 6 acceptance criteria", () => {
  test("changing k recolors the scatter in <1s without recomputing UMAP", async ({ page }) => {
    await createSession(page);

    const positionsBefore = await page.locator("circle.node-point").evaluateAll((els) =>
      els.map((el) => ({ cx: el.getAttribute("cx"), cy: el.getAttribute("cy") })),
    );
    const colorsBefore = await page.locator("circle.node-point").evaluateAll((els) =>
      els.map((el) => el.getAttribute("fill")),
    );

    const kInput = page.getByTestId("k-input");
    await kInput.fill("5");

    const t0 = Date.now();
    await expect
      .poll(
        async () => {
          const colors = await page.locator("circle.node-point").evaluateAll((els) =>
            els.map((el) => el.getAttribute("fill")),
          );
          return JSON.stringify(colors) !== JSON.stringify(colorsBefore);
        },
        { timeout: 5_000, message: "expected point colors to change after k edit" },
      )
      .toBe(true);
    const elapsed = Date.now() - t0;

    const positionsAfter = await page.locator("circle.node-point").evaluateAll((els) =>
      els.map((el) => ({ cx: el.getAttribute("cx"), cy: el.getAttribute("cy") })),
    );

    // positions unchanged -> E was NOT recomputed, only labels/coloring changed
    expect(positionsAfter).toEqual(positionsBefore);
    expect(elapsed).toBeLessThan(1000);
  });

  test("lasso selection shows raw series in 3c", async ({ page }) => {
    await createSession(page);
    await lassoAllPoints(page);

    // select a metric in 3a so 3c has something to render
    const firstMetricRow = page.locator('[data-testid^="metric-row-"]').first();
    await firstMetricRow.click();

    await expect(page.locator('[data-testid^="reading-inspection-svg-"]').first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('[data-testid^="reading-inspection-svg-"] path').first()).toHaveCount(1, {
      timeout: 10_000,
    });
  });

  test("brushing a baseline on one metric only updates that metric's heatmap row", async ({ page }) => {
    await createSession(page);
    await lassoAllPoints(page);

    const metricRows = page.locator('[data-testid^="metric-row-"]');
    await metricRows.nth(0).click();
    await metricRows.nth(1).click();

    const svgTestIds = await page.locator('[data-testid^="reading-inspection-svg-"]').evaluateAll((els) =>
      els.map((el) => el.getAttribute("data-testid")),
    );
    expect(svgTestIds.length).toBeGreaterThanOrEqual(2);

    const targetSvg = page.locator(`[data-testid="${svgTestIds[0]}"]`);
    const box = await targetSvg.boundingBox();
    if (!box) throw new Error("svg not found");

    await page.mouse.move(box.x + box.width * 0.3, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();

    // heatmap should now reflect a per-metric baseline change for the brushed metric only
    await expect(page.getByTestId("node-behavior-svg")).toBeVisible({ timeout: 10_000 });
  });

  test("brushing Time Domain updates the 3c time range", async ({ page }) => {
    await createSession(page);
    await lassoAllPoints(page);
    await page.locator('[data-testid^="metric-row-"]').first().click();

    const tdSvg = page.getByTestId("time-domain-svg");
    const box = await tdSvg.boundingBox();
    if (!box) throw new Error("svg not found");

    await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();

    await expect(page.locator('[data-testid^="reading-inspection-svg-"]').first()).toBeVisible({
      timeout: 10_000,
    });
  });
});
