/** The backup-trigger path and the error the user reads when the repository
 *  refuses: one hook, two halves, the way the CSV export test pins it. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { http } from "../../../lib/http";
import { useTriggerBackup } from "./hooks";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useTriggerBackup", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts to the manual-backup endpoint and invalidates the module keys",
    async () => {
      const post = vi.spyOn(http, "post").mockResolvedValue({
        data: { id: 7, status: "success" },
      });

      const { result } = renderHook(() => useTriggerBackup(), { wrapper });
      result.current.mutate({ repository: 2, dataset: "students" });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(post).toHaveBeenCalledWith("/badms/backups/manual",
        { repository: 2, dataset: "students" });
    });

  it("carries the server's refusal message to onError", async () => {
    vi.spyOn(http, "post").mockRejectedValue({
      response: { data: { error: { message: "Repository is not reachable." } } },
    });

    const { result } = renderHook(() => useTriggerBackup(), { wrapper });
    result.current.mutate({});

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
