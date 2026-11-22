/** StoragePage: the states a page owes its reader, and the extension request
 *  that only a full quota reveals (BR-BA-016). */
import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StorageExtension, StorageProfile } from "../api/types";
import StoragePage from "./StoragePage";

const hooks = vi.hoisted(() => ({
  useMyStorage: vi.fn(),
  useMyExtensions: vi.fn(),
  useSubmitExtension: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

const profile = {
  used_bytes: 10_000, quota_bytes: 10_000, full: true,
  checked_at: "2026-11-22T09:00:00Z",
} as unknown as StorageProfile;

const extension = {
  id: 1, requested_bytes: 4096, justification: "thesis data",
  status: "submitted", decided_at: null, created_at: "2026-11-22T09:00:00Z",
} as unknown as StorageExtension;

function renderPage() {
  return render(<MantineProvider><StoragePage /></MantineProvider>);
}

describe("StoragePage", () => {
  beforeEach(() => {
    hooks.useSubmitExtension.mockReturnValue(idle);
    hooks.useMyExtensions.mockReturnValue({ data: [extension],
                                            isPending: false, error: null });
  });

  it("shows the loading state", () => {
    hooks.useMyStorage.mockReturnValue({ data: undefined, isPending: true,
                                         error: null });
    hooks.useMyExtensions.mockReturnValue({ data: undefined, isPending: true,
                                            error: null });
    renderPage();
    expect(document.querySelector(".mantine-Loader-root")).toBeInTheDocument();
  });

  it("shows the error state", () => {
    hooks.useMyStorage.mockReturnValue({ data: undefined, isPending: false,
                                         error: { detail: "boom" } });
    renderPage();
    expect(screen.getByText(/could not load this/i)).toBeInTheDocument();
  });

  it("shows a full quota with its extension control", () => {
    hooks.useMyStorage.mockReturnValue({ data: profile, isPending: false,
                                         error: null });
    renderPage();
    expect(screen.getByText(/quota full/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /request extension/i }))
      .toBeInTheDocument();
  });

  it("hides the extension control while the quota has room (BR-BA-016)", () => {
    hooks.useMyStorage.mockReturnValue({
      data: { ...profile, used_bytes: 100, full: false },
      isPending: false, error: null });
    renderPage();
    expect(screen.queryByRole("button", { name: /request extension/i }))
      .not.toBeInTheDocument();
  });

  it("fires the main action from a full quota", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    hooks.useSubmitExtension.mockReturnValue({ ...idle, mutateAsync });
    hooks.useMyStorage.mockReturnValue({ data: profile, isPending: false,
                                         error: null });
    renderPage();
    screen.getByRole("button", { name: /request extension/i }).click();
    await waitFor(() =>
      expect(screen.getByText(/request a storage extension/i))
        .toBeInTheDocument());
  });
});
