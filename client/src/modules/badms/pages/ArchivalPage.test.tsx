/** ArchivalPage: the states a page owes its reader, plus the submit control
 *  the submitter role gets and a viewer does not. */
import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArchivalRequest, MyRequest } from "../api/types";
import ArchivalPage from "./ArchivalPage";

const hooks = vi.hoisted(() => ({
  useMyArchival: vi.fn(),
  useMyRequests: vi.fn(),
  useSubmitArchival: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

const auth = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../../../auth/AuthProvider", () => auth);

const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

const request = {
  id: 1, file_name: "records.pdf", file_type: "pdf", file_date: "2026-08-01",
  status: "submitted", classification: "routine", retention_rule: "",
  encryption_algorithm: "", created_at: "2026-11-22T09:00:00Z",
} as unknown as ArchivalRequest;

const tracked = {
  id: 1, kind: "archival", title: "records.pdf", status: "submitted",
} as unknown as MyRequest;

function renderPage() {
  return render(<MantineProvider><ArchivalPage /></MantineProvider>);
}

describe("ArchivalPage", () => {
  beforeEach(() => {
    auth.useAuth.mockReturnValue({ can: (p: string) =>
      p === "badms.archival.submit" });
    hooks.useMyRequests.mockReturnValue({ data: [tracked], isPending: false,
                                          error: null });
    hooks.useSubmitArchival.mockReturnValue(idle);
  });

  it("shows the loading state", () => {
    hooks.useMyArchival.mockReturnValue({ data: undefined, isPending: true,
                                          error: null });
    renderPage();
    expect(document.querySelector(".mantine-Loader-root")).toBeInTheDocument();
  });

  it("shows an explicit empty state", () => {
    hooks.useMyArchival.mockReturnValue({ data: [], isPending: false,
                                          error: null });
    renderPage();
    expect(screen.getByText(/no archival requests/i)).toBeInTheDocument();
  });

  it("renders its rows", () => {
    hooks.useMyArchival.mockReturnValue({ data: [request], isPending: false,
                                          error: null });
    renderPage();
    expect(screen.getAllByText("records.pdf").length).toBeGreaterThan(0);
  });

  it("gives a submitter the main action", async () => {
    hooks.useMyArchival.mockReturnValue({ data: [], isPending: false,
                                          error: null });
    renderPage();
    expect(screen.getByRole("button", { name: /new request/i }))
      .toBeInTheDocument();
    screen.getByRole("button", { name: /new request/i }).click();
    await waitFor(() =>
      expect(screen.getByText(/defaults to routine/i)).toBeInTheDocument());
  });

  it("hides the submit control from a viewer without the permission", () => {
    auth.useAuth.mockReturnValue({ can: () => false });
    hooks.useMyArchival.mockReturnValue({ data: [], isPending: false,
                                          error: null });
    renderPage();
    expect(screen.queryByRole("button", { name: /new request/i }))
      .not.toBeInTheDocument();
  });
});
