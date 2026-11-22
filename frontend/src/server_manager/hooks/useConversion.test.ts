import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { queryKeys } from "@/services/queryClient";
import { useConvertToAdvanced, useConvertToSimple } from "./useConversion";
import type { ConvertToAdvancedResponse } from "@/types";

const mockConvertToAdvanced = vi.fn();
const mockConvertToSimple = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: vi.fn(() => ({
    convertToAdvanced: mockConvertToAdvanced,
    convertToSimple: mockConvertToSimple,
  })),
}));

function renderWithQc<T>(qc: QueryClient, hook: () => T) {
  return renderHook(hook, {
    wrapper: ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client: qc }, children),
  });
}

describe("useConversion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConvertToAdvanced.mockReset();
    mockConvertToSimple.mockReset();
  });

  it("useConvertToAdvanced calls api.convertToAdvanced with the server id", async () => {
    mockConvertToAdvanced.mockResolvedValue({
      server_id: "srv-1",
      mode: "advanced",
      main_commit_sha: "abc",
      backup_id: "bkp-1",
      cas_ingested: 3,
    } as ConvertToAdvancedResponse);
    const qc = new QueryClient();
    const { result } = renderWithQc(qc, () => useConvertToAdvanced());
    await expect(result.current.mutateAsync("srv-1")).resolves.toBeDefined();
    expect(mockConvertToAdvanced).toHaveBeenCalledWith("srv-1");
  });

  it("useConvertToAdvanced invalidates servers and backups", async () => {
    mockConvertToAdvanced.mockResolvedValue({
      server_id: "srv-1",
      mode: "advanced",
      main_commit_sha: "abc",
      backup_id: "bkp-1",
      cas_ingested: 3,
    } as ConvertToAdvancedResponse);
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderWithQc(qc, () => useConvertToAdvanced());
    await result.current.mutateAsync("srv-1");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.servers.detail("srv-1") });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.servers.all });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.backups.all });
  });

  it("useConvertToSimple calls api.convertToSimple with server id and body", async () => {
    mockConvertToSimple.mockResolvedValue({ new_server_id: "srv-2", name: "Copy (Simple)" });
    const qc = new QueryClient();
    const { result } = renderWithQc(qc, () => useConvertToSimple());
    await result.current.mutateAsync({ serverId: "srv-1", body: { name: "Copy (Simple)", port: 25565 } });
    expect(mockConvertToSimple).toHaveBeenCalledWith("srv-1", { name: "Copy (Simple)", port: 25565 });
  });

  it("useConvertToSimple invalidates servers", async () => {
    mockConvertToSimple.mockResolvedValue({ new_server_id: "srv-2", name: "Copy (Simple)" });
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderWithQc(qc, () => useConvertToSimple());
    await result.current.mutateAsync({ serverId: "srv-1", body: { name: "Copy (Simple)" } });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.servers.all });
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: queryKeys.servers.detail("srv-1") });
  });
});
