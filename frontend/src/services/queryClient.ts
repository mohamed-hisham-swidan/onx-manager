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
    marketplace: {
      search: (serverId: string, query: string, projectType?: string, offset = 0, loader?: string) =>
        ["plugins", "marketplace", "search", serverId, query, projectType ?? "plugin", offset, loader ?? "all"] as const,
      // Global (no server_id) marketplace search — distinct from the server-scoped `search` key to avoid cache collisions.
      global: (query: string, projectType?: string, offset = 0, loader?: string) =>
        ["plugins", "marketplace", "global", query, projectType ?? "plugin", offset, loader ?? "all"] as const,
      project: (projectId: string) => ["plugins", "marketplace", "project", projectId] as const,
      projectVersions: (projectId: string, offset = 0) => ["plugins", "marketplace", "project-versions", projectId, offset] as const,
      versions: (serverId: string, projectId: string, offset = 0) => ["plugins", "marketplace", "versions", serverId, projectId, offset] as const,
    },
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
    crashReports: (serverId: string) => ["console", "crash-reports", serverId] as const,
  },
  settings: {
    all: ["settings"] as const,
  },
  files: {
    all: ["files"] as const,
    list: (serverId: string, path: string, branch?: string) => ["files", "list", serverId, path, branch ?? null] as const,
    content: (serverId: string, path: string, branch?: string) => ["files", "content", serverId, path, branch ?? null] as const,
  },
  versioning: {
    branches: (serverId: string) => ["versioning", "branches", serverId] as const,
    commits: (serverId: string) => ["versioning", "commits", serverId] as const,
  },
  exposure: {
    all: ["exposure"] as const,
    panel: () => ["exposure", "panel"] as const,
    agent: () => ["exposure", "agent"] as const,
    server: (serverId: string) => ["exposure", "server", serverId] as const,
    targets: (serverId: string) => ["exposure", "targets", serverId] as const,
    ports: (serverId: string) => ["exposure", "ports", serverId] as const,
  },
};
