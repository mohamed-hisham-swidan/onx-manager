import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import type { OperationSummary } from "../types";

export function useActiveOperations(targetType = "server", targetId?: string | null) {
  const api = createAuthenticatedApi();

  const { data: operations = [], isLoading, isError, error, refetch } = useQuery<OperationSummary[]>({
    queryKey: ["operations", "list", targetType, targetId],
    queryFn: async () => {
      const ops = await api.listOperations({
        target_type: targetType,
        target_id: targetId || undefined,
        limit: 20,
      });
      return ops;
    },
    enabled: Boolean(targetId),
    refetchInterval: (query) => {
      const list = query.state.data;
      if (list && list.some((op) => ["QUEUED", "PREPARING", "RUNNING"].includes(op.status))) {
        return 5000;
      }
      return false;
    },
  });

  const activeOperations = operations.filter((op) =>
    ["QUEUED", "PREPARING", "RUNNING"].includes(op.status)
  );

  return {
    operations,
    activeOperations,
    hasActiveOperation: activeOperations.length > 0,
    isLoading,
    isError,
    error,
    refetch,
  };
}
