import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "@/services/queryClient";
import { AuthGuard } from "@/components/guards/AuthGuard";
import { SystemStatusGuard } from "@/components/guards/SystemStatusGuard";
import { AppShell } from "@/layouts/AppShell";
import { ServerShell } from "@/layouts/ServerShell";
import { SplashScreen } from "@/components/brand/SplashScreen";
import { WebSocketManager } from "@/components/WebSocketManager";

// Route-level code-splitting: load page chunks on demand
const LoginPage = lazy(() => import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import("@/pages/RegisterPage").then((m) => ({ default: m.RegisterPage })));
const SetupPage = lazy(() => import("@/pages/SetupPage").then((m) => ({ default: m.SetupPage })));
const InvitePage = lazy(() => import("@/pages/InvitePage").then((m) => ({ default: m.InvitePage })));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));

const DashboardPage = lazy(() => import("@/server_manager/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const ServersPage = lazy(() => import("@/server_manager/pages/ServersPage").then((m) => ({ default: m.ServersPage })));
const CreateServerPage = lazy(() => import("@/server_manager/pages/CreateServerPage").then((m) => ({ default: m.CreateServerPage })));
const ImportServerPage = lazy(() => import("@/server_manager/pages/ImportServerPage").then((m) => ({ default: m.ImportServerPage })));
const ServerDetailPage = lazy(() => import("@/server_manager/pages/ServerDetailPage").then((m) => ({ default: m.ServerDetailPage })));
const ServerFilesPage = lazy(() => import("@/server_manager/pages/ServerFilesPage").then((m) => ({ default: m.ServerFilesPage })));
const ServerExposurePage = lazy(() => import("@/server_manager/pages/ServerExposurePage").then((m) => ({ default: m.ServerExposurePage })));
const ServerModsPage = lazy(() => import("@/server_manager/pages/ServerModsPage").then((m) => ({ default: m.ServerModsPage })));
const ServerVersioningPage = lazy(() => import("@/server_manager/pages/ServerVersioningPage").then((m) => ({ default: m.ServerVersioningPage })));
const ServerActivityPage = lazy(() => import("@/server_manager/pages/ServerActivityPage").then((m) => ({ default: m.ServerActivityPage })));
const ServerSettingsPage = lazy(() => import("@/server_manager/pages/ServerSettingsPage").then((m) => ({ default: m.ServerSettingsPage })));
const BackupListPage = lazy(() => import("@/server_manager/pages/BackupListPage").then((m) => ({ default: m.BackupListPage })));
const PluginListPage = lazy(() => import("@/server_manager/pages/PluginListPage").then((m) => ({ default: m.PluginListPage })));
const PluginMarketplacePage = lazy(() => import("@/server_manager/pages/PluginMarketplacePage").then((m) => ({ default: m.PluginMarketplacePage })));
const PluginDetailPage = lazy(() => import("@/server_manager/pages/PluginDetailPage").then((m) => ({ default: m.PluginDetailPage })));
const SettingsPage = lazy(() => import("@/server_manager/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const ApiKeysPage = lazy(() => import("@/server_manager/pages/ApiKeysPage").then((m) => ({ default: m.ApiKeysPage })));

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ReactQueryDevtools initialIsOpen={false} />
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
                  <Route path="servers/create" element={<CreateServerPage />} />
                  <Route path="servers/import" element={<ImportServerPage />} />
                  <Route path="backups" element={<BackupListPage />} />
                  <Route path="plugins" element={<PluginListPage />} />
                  <Route path="plugins/marketplace" element={<PluginMarketplacePage />} />
                  <Route path="plugins/marketplace/:projectId" element={<PluginDetailPage />} />
                  <Route path="marketplace" element={<PluginMarketplacePage />} />
                  <Route path="marketplace/:projectId" element={<PluginDetailPage />} />
                  <Route path="settings" element={<SettingsPage />} />
                  <Route path="settings/api-keys" element={<ApiKeysPage />} />
                </Route>
                <Route path="servers/:serverId" element={<ServerShell />}>
                  <Route index element={<ServerDetailPage />} />
                  <Route path="console" element={<ServerDetailPage />} />
                  <Route path="files" element={<ServerFilesPage />} />
                  <Route path="network" element={<ServerExposurePage />} />
                  <Route path="mods" element={<ServerModsPage />} />
                  <Route path="plugins" element={<PluginListPage />} />
                  <Route path="versioning" element={<ServerVersioningPage />} />
                  <Route path="activity" element={<ServerActivityPage />} />
                  <Route path="settings" element={<ServerSettingsPage />} />
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
