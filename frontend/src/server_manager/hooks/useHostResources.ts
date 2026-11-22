import { useContext } from "react";
import { QueryClient, QueryClientContext, useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import type { HostResourceBudget } from "@/types";

const fallbackQueryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

export function useHostResources() {
  const existingClient = useContext(QueryClientContext);
  const api = createAuthenticatedApi();
  const canFetch = Boolean(existingClient) && typeof api?.getHostResources === "function";

  return useQuery<HostResourceBudget | undefined>(
    {
      queryKey: ["hostResources"],
      queryFn: () => api.getHostResources(),
      enabled: canFetch,
      refetchInterval: 10000,
    },
    existingClient ?? fallbackQueryClient,
  );
}
