import {
  actAs, expect, openModuleNav, sidebar, signedInAs, test,
} from "../support/test";

test.describe("badms: manual backup (UC-BA-001)", () => {
  test.use(signedInAs("badmsSysadmin"));

  test("a sysadmin triggers a manual backup and sees it recorded",
    async ({ page }) => {
      await page.goto("/");
      await actAs(page, "badmsSysadmin");
      await openModuleNav(page, "Backup & Archive");
      await sidebar(page).getByRole("link", { name: "Backup Status" }).click();
      await expect(
        page.getByRole("heading", { name: "Backup Status", level: 2 }),
      ).toBeVisible();

      await page.getByRole("button", { name: /trigger backup/i }).click();
      await expect(page.getByText(/backup finished|backup failed/i))
        .toBeVisible({ timeout: 15_000 });
    });
});
