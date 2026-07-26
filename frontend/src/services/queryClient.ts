import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export const queryKeys = {
  servers: {
    all: ["servers"] as const,
    list: () => ["servers", "list"] as const,
    detail: (id: string) => ["servers", "detail", id] as const,
  },
  backups: {
    all: ["backups"] as const,
    list: (serverId?: string) => ["backups", "list", serverId] as const,
    detail: (id: string) => ["backups", "detail", id] as const,
  },
  plugins: {
    all: ["plugins"] as const,
    list: (serverId: string) => ["plugins", "list", serverId] as const,
    detail: (serverId: string, pluginId: string) => ["plugins", "detail", serverId, pluginId] as const,
  },
  auth: {
    me: ["auth", "me"] as const,
    apiKeys: ["auth", "api-keys"] as const,
  },
  users: {
    all: ["users"] as const,
    list: () => ["users", "list"] as const,
    detail: (id: string) => ["users", "detail", id] as const,
  },
  monitoring: {
    metrics: (serverId?: string) => ["monitoring", "metrics", serverId] as const,
  },
  console: {
    history: (serverId: string) => ["console", "history", serverId] as const,
  },
  settings: {
    all: ["settings"] as const,
  },
};
