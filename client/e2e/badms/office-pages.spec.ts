import { expect, signedInAs, test } from "../support/test";

// The BADMS office pages, opened directly by someone the sidebar never
// offered them to. The four a plain user may use (backups, archival,
// restoration, storage) are not in this list (routes.tsx).
const OFFICE_PAGES = [
  "schedules", "archival-review", "classification", "encryption",
  "special-archival", "storage-approvals", "audit", "security", "reports",
];

test.describe("badms: office pages", () => {
  test.use(signedInAs("student"));

  for (const path of OFFICE_PAGES) {
    test(`a student who opens /badms/${path} is told it is not for them`,
      async ({ page }) => {
        await page.goto(`/badms/${path}`);
        await expect(page.getByText("Not available to your role")).toBeVisible();
        await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
      });
  }
});
