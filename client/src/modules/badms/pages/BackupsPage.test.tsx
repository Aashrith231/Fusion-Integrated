/** BackupsPage: the states a page owes its reader (Step 6.7) and the
 *  control only the triggering role gets. */
import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Backup } from "../api/types";
import BackupsPage from "./BackupsPage";

const hooks = vi.hoisted(() => ({
  useBackups: vi.fn(),
  useRepositories: vi.fn(),
  useTriggerBackup: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

const auth = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../../../auth/AuthProvider", () => auth);

const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

const backup = {
  id: 1, kind: "manual", dataset: "platform", status: "success",
  started_at: "2026-11-22T02:00:00Z", finished_at: "2026-11-22T02:04:00Z",
  integrity_verified: true, consecutive_failures: 0, error: "",
  repository_name: "primary",
} as unknown as Backup;

function renderPage() {
  return render(<MantineProvider><BackupsPage /></MantineProvider>);
}

describe("BackupsPage", () => {
  beforeEach(() => {
    auth.useAuth.mockReturnValue({ can: (p: string) =>
      p === "badms.backup.view" });
    hooks.useRepositories.mockReturnValue({ data: [], isPending: false });
    hooks.useTriggerBackup.mockReturnValue(idle);
  });

  it("shows the loading state and no table rows", () => {
    hooks.useBackups.mockReturnValue({ data: undefined, isPending: true,
                                       error: null });
    renderPage();
    expect(document.querySelector(".mantine-Loader-root"))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /trigger backup/i }))
      .not.toBeInTheDocument();
  });

  it("shows an explicit empty state", () => {
    hooks.useBackups.mockReturnValue({ data: [], isPending: false,
                                       error: null });
    renderPage();
    expect(screen.getByText(/no backups yet/i)).toBeInTheDocument();
  });

  it("shows the error state", () => {
    hooks.useBackups.mockReturnValue({ data: undefined, isPending: false,
                                       error: { detail: "boom" } });
    renderPage();
    expect(screen.getByText(/could not load this/i)).toBeInTheDocument();
  });

  it("hides the trigger control from a plain viewer", () => {
    hooks.useBackups.mockReturnValue({ data: [backup], isPending: false,
                                       error: null });
    renderPage();
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /trigger backup/i }))
      .not.toBeInTheDocument();
  });

  it("gives the sysadmin the trigger control and fires the main action", () => {
    auth.useAuth.mockReturnValue({ can: (p: string) =>
      p === "badms.backup.view" || p === "badms.backup.trigger" });
    const mutate = vi.fn();
    hooks.useTriggerBackup.mockReturnValue({ ...idle, mutate });
    hooks.useBackups.mockReturnValue({ data: [backup], isPending: false,
                                       error: null });
    renderPage();
    expect(screen.getByRole("button", { name: /trigger backup/i }))
      .toBeInTheDocument();
    screen.getByRole("button", { name: /trigger backup/i }).click();
    expect(mutate).toHaveBeenCalled();
  });
});
