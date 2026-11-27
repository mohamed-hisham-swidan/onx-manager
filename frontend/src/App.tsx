import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/services/queryClient";
import { AuthGuard } from "@/components/guards/AuthGuard";
import { RequirePermission } from "@/components/guards/RequirePermission";
import { SystemStatusGuard } from "@/components/guards/SystemStatusGuard";
import { AppShell } from "@/layouts/AppShell";
import { ServerShell } from "@/layouts/ServerShell";
import { SplashScreen } from "@/components/brand/SplashScreen";
import { WebSocketManager } from "@/components/WebSocketManager";
import { lazyWithReload } from "@/utils/chunkReload";

// Route-level code-splitting: load page chunks on demand (auto-reload once if chunk hash rotated)
const LoginPage = lazyWithReload(() => import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const RegisterPage = lazyWithReload(() => import("@/pages/RegisterPage").then((m) => ({ default: m.RegisterPage })));
const SetupPage = lazyWithReload(() => import("@/pages/SetupPage").then((m) => ({ default: m.SetupPage })));
const InvitePage = lazyWithReload(() => import("@/pages/InvitePage").then((m) => ({ default: m.InvitePage })));
const NotFoundPage = lazyWithReload(() => import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));

const DashboardPage = lazyWithReload(() => import("@/server_manager/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const ServersPage = lazyWithReload(() => import("@/server_manager/pages/ServersPage").then((m) => ({ default: m.ServersPage })));
const CreateServerPage = lazyWithReload(() => import("@/server_manager/pages/CreateServerPage").then((m) => ({ default: m.CreateServerPage })));
const ImportServerPage = lazyWithReload(() => import("@/server_manager/pages/ImportServerPage").then((m) => ({ default: m.ImportServerPage })));
const ServerDetailPage = lazyWithReload(() => import("@/server_manager/pages/ServerDetailPage").then((m) => ({ default: m.ServerDetailPage })));
const ServerFilesPage = lazyWithReload(() => import("@/server_manager/pages/ServerFilesPage").then((m) => ({ default: m.ServerFilesPage })));
const ServerExposurePage = lazyWithReload(() => import("@/server_manager/pages/ServerExposurePage").then((m) => ({ default: m.ServerExposurePage })));
const ServerModsPage = lazyWithReload(() => import("@/server_manager/pages/ServerModsPage").then((m) => ({ default: m.ServerModsPage })));
const ServerVersioningPage = lazyWithReload(() => import("@/server_manager/pages/ServerVersioningPage").then((m) => ({ default: m.ServerVersioningPage })));
const ServerActivityPage = lazyWithReload(() => import("@/server_manager/pages/ServerActivityPage").then((m) => ({ default: m.ServerActivityPage })));
const ServerSettingsPage = lazyWithReload(() => import("@/server_manager/pages/ServerSettingsPage").then((m) => ({ default: m.ServerSettingsPage })));
const BackupListPage = lazyWithReload(() => import("@/server_manager/pages/BackupListPage").then((m) => ({ default: m.BackupListPage })));
const PluginListPage = lazyWithReload(() => import("@/server_manager/pages/PluginListPage").then((m) => ({ default: m.PluginListPage })));
const PluginMarketplacePage = lazyWithReload(() => import("@/server_manager/pages/PluginMarketplacePage").then((m) => ({ default: m.PluginMarketplacePage })));
const PluginDetailPage = lazyWithReload(() => import("@/server_manager/pages/PluginDetailPage").then((m) => ({ default: m.PluginDetailPage })));
const SettingsPage = lazyWithReload(() => import("@/server_manager/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const ApiKeysPage = lazyWithReload(() => import("@/server_manager/pages/ApiKeysPage").then((m) => ({ default: m.ApiKeysPage })));

declare global {
  interface ImportMetaEnv {
    readonly DEV: boolean;
    readonly VITE_QUERY_DEVTOOLS?: string;
  }
  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
}

const showDevtools =
  Boolean(import.meta.env.DEV) && import.meta.env.VITE_QUERY_DEVTOOLS === "true";

const ReactQueryDevtools = showDevtools
  ? lazy(() =>
      import("@tanstack/react-query-devtools").then((m) => ({
        default: m.ReactQueryDevtools,
      }))
    )
  : null;

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        {showDevtools && ReactQueryDevtools && (
          <Suspense fallback={null}>
            <ReactQueryDevtools initialIsOpen={false} />
          </Suspense>
        )}
        <WebSocketManager />
        <Suspense fallback={<SplashScreen />}>
          <Routes>
            <Route element={<SystemStatusGuard />}>
              <Route path="/setup" element={<SetupPage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/invite/:token" element={<InvitePage />} />
              <Route element={<AuthGuard />}>
                <Route element={<AppShell />}>
                  <Route index element={<DashboardPage />} />
                  <Route path="servers" element={<ServersPage />} />
                  <Route
                    path="servers/create"
                    element={
                      <RequirePermission check={(p) => p.canCreateServer} redirectTo="/servers">
                        <CreateServerPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="servers/import"
                    element={
                      <RequirePermission check={(p) => p.canImportServer} redirectTo="/servers">
                        <ImportServerPage />
                      </RequirePermission>
                    }
                  />
                  <Route path="backups" element={<BackupListPage />} />
                  <Route
                    path="plugins"
                    element={
                      <RequirePermission
                        check={(p) => p.isAdmin || (!p.isViewer && p.canViewPlugins())}
                        redirectTo="/"
                      >
                        <PluginListPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="plugins/marketplace"
                    element={
                      <RequirePermission
                        check={(p) => p.isAdmin || (!p.isViewer && p.canViewPlugins())}
                        redirectTo="/"
                      >
                        <PluginMarketplacePage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="plugins/marketplace/:projectId"
                    element={
                      <RequirePermission
                        check={(p) => p.isAdmin || (!p.isViewer && p.canViewPlugins())}
                        redirectTo="/"
                      >
                        <PluginDetailPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="marketplace"
                    element={
                      <RequirePermission
                        check={(p) => p.isAdmin || (!p.isViewer && p.canViewPlugins())}
                        redirectTo="/"
                      >
                        <PluginMarketplacePage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="marketplace/:projectId"
                    element={
                      <RequirePermission
                        check={(p) => p.isAdmin || (!p.isViewer && p.canViewPlugins())}
                        redirectTo="/"
                      >
                        <PluginDetailPage />
                      </RequirePermission>
                    }
                  />
                  <Route path="settings" element={<SettingsPage />} />
                  <Route path="settings/api-keys" element={<ApiKeysPage />} />
                </Route>
                <Route path="servers/:serverId" element={<ServerShell />}>
                  <Route index element={<ServerDetailPage />} />
                  <Route
                    path="console"
                    element={
                      <RequirePermission check={(p, sid) => p.canConsoleView(sid)}>
                        <ServerDetailPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="files"
                    element={
                      <RequirePermission check={(p, sid) => p.canFiles(sid) || p.canViewLogs(sid)}>
                        <ServerFilesPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="network"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewExposure(sid)}>
                        <ServerExposurePage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="backups"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewBackups(sid)}>
                        <BackupListPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="mods"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewPlugins(sid)}>
                        <ServerModsPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="mods/marketplace"
                    element={
                      <RequirePermission check={(p, sid) => p.canManagePlugins(sid)}>
                        <PluginMarketplacePage lockedProjectType="mod" />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="mods/marketplace/:projectId"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewPlugins(sid)}>
                        <PluginDetailPage lockedProjectType="mod" />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="plugins"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewPlugins(sid)}>
                        <PluginListPage />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="plugins/marketplace"
                    element={
                      <RequirePermission check={(p, sid) => p.canManagePlugins(sid)}>
                        <PluginMarketplacePage lockedProjectType="plugin" />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="plugins/marketplace/:projectId"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewPlugins(sid)}>
                        <PluginDetailPage lockedProjectType="plugin" />
                      </RequirePermission>
                    }
                  />
                  <Route
                    path="versioning"
                    element={
                      <RequirePermission check={(p, sid) => p.canViewVersioning(sid)}>
                        <ServerVersioningPage />
                      </RequirePermission>
                    }
                  />
                  <Route path="activity" element={<ServerActivityPage />} />
                  <Route
                    path="settings"
                    element={
                      <RequirePermission check={(p, sid) => p.canSettings(sid)}>
                        <ServerSettingsPage />
                      </RequirePermission>
                    }
                  />
                </Route>
                <Route element={<AppShell />}>
                  <Route path="*" element={<NotFoundPage />} />
                </Route>
              </Route>
            </Route>
          </Routes>
        </Suspense>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
