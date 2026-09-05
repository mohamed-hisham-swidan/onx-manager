import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "@/services/queryClient";
import { AuthGuard } from "@/components/guards/AuthGuard";
import { SystemStatusGuard } from "@/components/guards/SystemStatusGuard";
import { AppShell } from "@/layouts/AppShell";
import { ServerShell } from "@/layouts/ServerShell";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { SetupPage } from "@/pages/SetupPage";
import { InvitePage } from "@/pages/InvitePage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { DashboardPage } from "@/server_manager/pages/DashboardPage";
import { ServersPage } from "@/server_manager/pages/ServersPage";
import { CreateServerPage } from "@/server_manager/pages/CreateServerPage";
import { ImportServerPage } from "@/server_manager/pages/ImportServerPage";
import { ServerDetailPage } from "@/server_manager/pages/ServerDetailPage";
import { ServerFilesPage } from "@/server_manager/pages/ServerFilesPage";
import { ServerExposurePage } from "@/server_manager/pages/ServerExposurePage";
import { ServerModsPage } from "@/server_manager/pages/ServerModsPage";
import { ServerSettingsPage } from "@/server_manager/pages/ServerSettingsPage";
import { BackupListPage } from "@/server_manager/pages/BackupListPage";
import { PluginListPage } from "@/server_manager/pages/PluginListPage";
import { PluginMarketplacePage } from "@/server_manager/pages/PluginMarketplacePage";
import { PluginDetailPage } from "@/server_manager/pages/PluginDetailPage";
import { SettingsPage } from "@/server_manager/pages/SettingsPage";
import { ApiKeysPage } from "@/server_manager/pages/ApiKeysPage";
import { WebSocketManager } from "@/components/WebSocketManager";

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ReactQueryDevtools initialIsOpen={false} />
        <WebSocketManager />
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
                <Route path="settings" element={<ServerSettingsPage />} />
              </Route>
              <Route element={<AppShell />}>
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
