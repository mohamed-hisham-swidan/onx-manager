import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "@/services/queryClient";
import { AuthGuard } from "@/components/guards/AuthGuard";
import { AppShell } from "@/layouts/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { DashboardPage } from "@/server_manager/pages/DashboardPage";
import { ServersPage } from "@/server_manager/pages/ServersPage";
import { CreateServerPage } from "@/server_manager/pages/CreateServerPage";
import { ImportServerPage } from "@/server_manager/pages/ImportServerPage";
import { ServerDetailPage } from "@/server_manager/pages/ServerDetailPage";
import { BackupListPage } from "@/server_manager/pages/BackupListPage";
import { PluginListPage } from "@/server_manager/pages/PluginListPage";
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
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<AuthGuard />}>
            <Route element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route path="servers" element={<ServersPage />} />
              <Route path="servers/create" element={<CreateServerPage />} />
              <Route path="servers/import" element={<ImportServerPage />} />
              <Route path="servers/:serverId" element={<ServerDetailPage />} />
              <Route path="backups" element={<BackupListPage />} />
              <Route path="plugins" element={<PluginListPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="settings/api-keys" element={<ApiKeysPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
