import {
  actAs, expect, openModuleNav, sidebar, signedInAs, test, uniqueName,
} from "../support/test";

test.describe("badms: secure archival (UC-BA-002..004)", () => {
  test.use(signedInAs("student"));

  test("a student submits an archival request and sees it routed for review",
    async ({ page }) => {
      const fileName = `${uniqueName("E2E Records")}.pdf`;

      await page.goto("/");
      await actAs(page, "student");
      await openModuleNav(page, "Backup & Archive");
      await sidebar(page).getByRole("link", { name: "Secure Archival" })
        .click();
      await expect(
        page.getByRole("heading", { name: "Secure Archival", level: 2 }),
      ).toBeVisible();

      await page.getByRole("button", { name: "New request" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("textbox", { name: "File name" }).fill(fileName);
      await dialog.getByRole("textbox", { name: "Owners" }).fill("E2E Owner");
      await dialog.getByRole("textbox", { name: "File type" }).fill("pdf");
      await dialog.getByRole("textbox", { name: "Reason" })
        .fill("e2e archival journey");
      await dialog.getByRole("textbox", { name: "Attachment reference" })
        .fill("att://e2e");

      const submitted = page.waitForResponse((r) =>
        r.url().includes("/api/v1/badms/archival")
        && r.request().method() === "POST");
      await dialog.getByRole("button", { name: /submit/i }).click();
      expect((await submitted).status()).toBe(201);

      await expect(dialog).toBeHidden();
      const row = page.getByRole("row").filter({ hasText: fileName });
      await expect(row).toBeVisible();
      await expect(row).toContainText(/submitted/i);
    });
});
