import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useServerExposure } from "./useServerExposure";
import { ApiError } from "@/services/api";
import { toast } from "@/stores/toastStore";

const mockApi = {
  getServerExposure: vi.fn(),
  getAgentStatus: vi.fn().mockResolvedValue({ claimed: false, running: false }),
  listServerPorts: vi.fn().mockResolvedValue([]),
  setServerExposure: vi.fn(),
  setServerExposureState: vi.fn(),
  removeServerExposure: vi.fn(),
  createExposureTarget: vi.fn(),
  updateExposureTarget: vi.fn(),
  deleteExposureTarget: vi.fn(),
  registerServerPort: vi.fn(),
  deleteServerPort: vi.fn(),
};

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: () => mockApi,
  };
});

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useServerExposure honest error and STARTING state handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("surfaces 403 and 500 errors instead of masking them as DISABLED", async () => {
    mockApi.getServerExposure.mockRejectedValueOnce(
      new ApiError(403, "PERMISSION_DENIED", "Forbidden"),
    );

    const { result } = renderHook(
      () => useServerExposure("srv-1", "main", { includeAgentAndPorts: false }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.exposure).toBeUndefined();
    expect((result.current.error as ApiError).status).toBe(403);
  });

  it("treats genuine 404 as unconfigured DISABLED exposure", async () => {
    mockApi.getServerExposure.mockRejectedValueOnce(
      new ApiError(404, "NOT_FOUND", "Exposure not configured"),
    );

    const { result } = renderHook(
      () => useServerExposure("srv-1", "main", { includeAgentAndPorts: false }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.exposure?.aggregate_status).toBe("DISABLED"));
    expect(result.current.isError).toBe(false);
  });

  it("shows an info toast when setExposure returns STARTING instead of claiming success", async () => {
    mockApi.getServerExposure.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "main",
      method: "none",
      desired_state: "DISABLED",
      aggregate_status: "DISABLED",
      error_code: null,
      error_message: null,
      cloudflare_tunnel_id: null,
      has_cloudflare_credentials: false,
      targets: [],
    });
    mockApi.setServerExposure.mockResolvedValueOnce({
      server_id: "srv-1",
      branch_name: "main",
      method: "cloudflare_tcp",
      desired_state: "ENABLED",
      aggregate_status: "STARTING",
      error_code: null,
      error_message: null,
      cloudflare_tunnel_id: null,
      has_cloudflare_credentials: false,
      targets: [],
    });

    const { result } = renderHook(
      () => useServerExposure("srv-1", "main", { includeAgentAndPorts: false }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.exposure).toBeDefined());

    await act(async () => {
      await result.current.setExposureAsync({
        method: "cloudflare_tcp",
        desired_state: "ENABLED",
      });
    });

    expect(toast).toHaveBeenCalledWith(
      "info",
      "Exposure Starting",
      "Exposure starting — waiting for public address...",
    );
  });

  it("propagates registerServerPort failures instead of swallowing them", async () => {
    mockApi.getServerExposure.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "main",
      method: "port_forward",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      error_code: null,
      error_message: null,
      cloudflare_tunnel_id: null,
      has_cloudflare_credentials: false,
      targets: [],
    });
    mockApi.registerServerPort.mockRejectedValueOnce(
      new ApiError(500, "INTERNAL_ERROR", "Port registration failed"),
    );

    const { result } = renderHook(
      () => useServerExposure("srv-1", "main", { includeAgentAndPorts: false }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.exposure).toBeDefined());

    await expect(
      act(async () => {
        await result.current.createTargetAsync({
          service_type: "voice",
          protocol: "udp",
          local_port: 24454,
        });
      }),
    ).rejects.toThrow("Port registration failed");
    expect(mockApi.createExposureTarget).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("error", "Target Creation Failed", "Port registration failed"),
    );
  });
});
