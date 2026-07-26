import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { ApiKeyCreateRequest } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function useApiKeys() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.auth.apiKeys,
    queryFn: () => api.listApiKeys(),
  });
}

export function useCreateApiKey() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApiKeyCreateRequest) => api.createApiKey(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.auth.apiKeys }),
  });
}

export function useRevokeApiKey() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (apiKeyId: string) => api.revokeApiKey(apiKeyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.auth.apiKeys }),
  });
}
