/** SchedulesPage: the office page's states, and the controls split between
 *  the local schedule manager and the global schedule owner. */
import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Schedule } from "../api/types";
import SchedulesPage from "./SchedulesPage";

const hooks = vi.hoisted(() => ({
  useSchedules: vi.fn(),
  useRepositories: vi.fn(),
  useCreateSchedule: vi.fn(),
  useModifySchedule: vi.fn(),
  useGlobalSchedule: vi.fn(),
  useSetGlobalSchedule: vi.fn(),
  useScheduleChanges: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

const auth = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../../../auth/AuthProvider", () => auth);

const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };

const schedule = {
  id: 1, scope: "local", dataset: "student-db", frequency: "daily",
  run_at: "02:00:00", weekday: null, is_active: true,
  created_at: "2026-11-22T09:00:00Z",
} as unknown as Schedule;

function renderPage() {
  return render(<MantineProvider><SchedulesPage /></MantineProvider>);
}

describe("SchedulesPage", () => {
  beforeEach(() => {
    auth.useAuth.mockReturnValue({ can: (p: string) =>
      p === "badms.schedule.manage" || p === "badms.schedule.manage_global" });
    hooks.useRepositories.mockReturnValue({ data: [], isPending: false });
    hooks.useCreateSchedule.mockReturnValue(idle);
    hooks.useModifySchedule.mockReturnValue(idle);
    hooks.useSetGlobalSchedule.mockReturnValue(idle);
    hooks.useGlobalSchedule.mockReturnValue({ data: null, isPending: false });
    hooks.useScheduleChanges.mockReturnValue({ data: [], isPending: false });
  });

  it("shows the loading state", () => {
    hooks.useSchedules.mockReturnValue({ data: undefined, isPending: true });
    renderPage();
    expect(document.querySelector(".mantine-Loader-root")).toBeInTheDocument();
  });

  it("shows an explicit empty state", () => {
    hooks.useSchedules.mockReturnValue({ data: [], isPending: false });
    renderPage();
    expect(screen.getByText(/no schedules/i)).toBeInTheDocument();
  });

  it("renders its rows and gives the manager the new-schedule control", () => {
    hooks.useSchedules.mockReturnValue({ data: [schedule], isPending: false });
    renderPage();
    expect(screen.getByText("student-db")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new schedule/i }))
      .toBeInTheDocument();
  });

  it("shows the global-schedule section only to its owner", () => {
    auth.useAuth.mockReturnValue({ can: (p: string) =>
      p === "badms.schedule.manage" });
    hooks.useSchedules.mockReturnValue({ data: [], isPending: false });
    renderPage();
    expect(screen.queryByRole("button", { name: /global/i }))
      .not.toBeInTheDocument();
  });

  it("gives the super admin the global control", () => {
    auth.useAuth.mockReturnValue({ can: () => true });
    hooks.useSchedules.mockReturnValue({ data: [], isPending: false });
    renderPage();
    expect(screen.getByRole("button", { name: /global/i }))
      .toBeInTheDocument();
  });
});
