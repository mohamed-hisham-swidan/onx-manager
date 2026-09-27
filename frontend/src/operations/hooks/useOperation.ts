import { useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { useOperationStore } from "../stores/operationStore";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import type { OperationDetail } from "../types";

export function useOperation(operationId: string | null | undefined) {
  const queryClient = useQueryClient();
  const api = createAuthenticatedApi();

  const storeOp = useOperationStore((state) =>
    operationId ? state.operations[operationId] : undefined
  );
  const logs = useOperationStore((state) =>
    operationId ? state.logs[operationId] || [] : []
  );
  const setOperation = useOperationStore((state) => state.setOperation);
  const clearGap = useOperationStore((state) => state.clearGap);

  // Subscribe to WebSocket channel
  useEffect(() => {
    if (!operationId) return;
    const channel = `operation:${operationId}`;
    subscribeChannels([channel]);

    return () => {
      unsubscribeChannels([channel]);
    };
  }, [operationId]);

  // Query operation from REST API
  const { data, isLoading, isError, error, refetch } = useQuery<OperationDetail>({
    queryKey: ["operations", "detail", operationId],
    queryFn: async () => {
      if (!operationId) throw new Error("No operationId provided");
      const op = await api.getOperation(operationId);
      setOperation(op);
      clearGap(operationId);
      return op;
    },
    enabled: Boolean(operationId),
    refetchInterval: (query) => {
      // Poll as fallback if operation is still active
      const op = query.state.data;
      if (op && (op.status === "QUEUED" || op.status === "PREPARING" || op.status === "RUNNING")) {
        return 3000;
      }
      return false;
    },
  });

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: async () => {
      if (!operationId) return;
      const op = await api.cancelOperation(operationId);
      setOperation(op);
      queryClient.setQueryData(["operations", "detail", operationId], op);
      return op;
    },
  });

  // Retry mutation
  const retryMutation = useMutation({
    mutationFn: async () => {
      if (!operationId) return;
      const op = await api.retryOperation(operationId);
      setOperation(op);
      queryClient.setQueryData(["operations", "detail", op.id], op);
      return op;
    },
  });

  const cancel = useCallback(async () => {
    return cancelMutation.mutateAsync();
  }, [cancelMutation]);

  const retry = useCallback(async () => {
    return retryMutation.mutateAsync();
  }, [retryMutation]);

  return {
    operation: storeOp || data,
    logs,
    isLoading,
    isError,
    error,
    refetch,
    cancel,
    retry,
    isCancelling: cancelMutation.isPending,
    isRetrying: retryMutation.isPending,
  };
}
