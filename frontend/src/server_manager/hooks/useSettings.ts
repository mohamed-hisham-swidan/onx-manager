import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";

import type { SettingsUpdateRequest } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function useSettings() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.settings.all,
    queryFn: () => api.getSettings(),
  });
}

export function useUpdateSettings() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsUpdateRequest) => api.updateSettings(body),
    onSuccess: (data) => {
      if (data?.settings) {
        qc.setQueryData(queryKeys.settings.all, (prev: Record<string, unknown> | undefined) =>
          prev ? { ...prev, ...data.settings } : data.settings,
        );
      }
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
    },
  });
}

