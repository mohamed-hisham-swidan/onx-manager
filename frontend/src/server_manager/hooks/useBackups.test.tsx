import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useBackupsList } from "./useBackups";

const mockListBackups = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listBackups: (...args: unknown[]) => mockListBackups(...args),
  }),
}));

describe("useBackupsList adaptive polling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("polls every 3000ms while any backup is in_progress and stops once terminal", async () => {
    vi.useFakeTimers();
    try {
      mockListBackups
        .mockResolvedValueOnce([{ backup_id: "b1", status: "in_progress" }])
        .mockResolvedValueOnce([{ backup_id: "b1", status: "completed" }]);

      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      );

      renderHook(() => useBackupsList(), { wrapper });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(50);
      });
      expect(mockListBackups).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100);
      });
      expect(mockListBackups).toHaveBeenCalledTimes(2);

      // Now status is completed -> polling stops
      await act(async () => {
        await vi.advanceTimersByTimeAsync(6500);
      });
      expect(mockListBackups).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
