import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "@/services/queryClient";
import { AuthGuard } from "@/components/guards/AuthGuard";
import { AppLayout } from "@/layouts/AppLayout";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { DashboardPage } from "@/server_manager/pages/DashboardPage";
import { ServersPage } from "@/server_manager/pages/ServersPage";
import { CreateServerPage } from "@/server_manager/pages/CreateServerPage";
import { ImportServerPage } from "@/server_manager/pages/ImportServerPage";
import { ServerDetailPage } from "@/server_manager/pages/ServerDetailPage";
import { BackupListPage } from "@/server_manager/pages/BackupListPage";
import { PluginListPage } from "@/server_manager/pages/PluginListPage";
import { SettingsPage } from "@/server_manager/pages/SettingsPage";
import { ApiKeysPage } from "@/server_manager/pages/ApiKeysPage";
import { ErrorBoundary } from "@/components/ErrorBoundary";
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
            <Route element={<AppLayout />}>
              <Route index element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
              <Route path="servers" element={<ErrorBoundary><ServersPage /></ErrorBoundary>} />
              <Route path="servers/create" element={<ErrorBoundary><CreateServerPage /></ErrorBoundary>} />
              <Route path="servers/import" element={<ErrorBoundary><ImportServerPage /></ErrorBoundary>} />
              <Route path="servers/:serverId" element={<ErrorBoundary><ServerDetailPage /></ErrorBoundary>} />
              <Route path="backups" element={<ErrorBoundary><BackupListPage /></ErrorBoundary>} />
              <Route path="plugins" element={<ErrorBoundary><PluginListPage /></ErrorBoundary>} />
              <Route path="settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
              <Route path="settings/api-keys" element={<ErrorBoundary><ApiKeysPage /></ErrorBoundary>} />
            </Route>
          </Route>
        </Routes>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
