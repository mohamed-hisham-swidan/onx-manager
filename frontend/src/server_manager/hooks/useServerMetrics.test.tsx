import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useServerMetrics } from "./useServerMetrics";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState } from "@/websocket/types";

const getMetricsMock = vi.fn().mockResolvedValue([]);

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: () => ({ getMetrics: getMetricsMock }),
  };
});

describe("useServerMetrics", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("disables refetchInterval when WS is connected", async () => {
    useWSStore.getState().setConnectionState(ConnectionState.CONNECTED);
    expect(useWSStore.getState().connected).toBe(true);

    const { result } = renderHook(() => useServerMetrics("srv-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // When WS is connected, refetchInterval is false
    const query = queryClient.getQueryCache().findAll()[0];
    expect(query).toBeDefined();
    // Verify query options
    expect(query.options.refetchInterval).toBe(false);
  });

  it("enables HTTP polling (refetchInterval=2000) when WS is disconnected", async () => {
    useWSStore.getState().setConnectionState(ConnectionState.DISCONNECTED);
    expect(useWSStore.getState().connected).toBe(false);

    const { result } = renderHook(() => useServerMetrics("srv-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const query = queryClient.getQueryCache().findAll()[0];
    expect(query).toBeDefined();
    expect(query.options.refetchInterval).toBe(2000);
  });
});
