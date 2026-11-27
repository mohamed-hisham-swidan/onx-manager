import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useAuthPermissions } from "./useAuthPermissions";
import type { CurrentUserResponse } from "@/types";

const mockGetMe = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getMe: mockGetMe,
  }),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: { accessToken: string | null }) => unknown) =>
    selector({ accessToken: "fake.token.sig" }),
}));

function renderPermissions(user: CurrentUserResponse) {
  mockGetMe.mockResolvedValue(user);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  qc.setQueryData(["currentUser"], user);

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(() => useAuthPermissions(), { wrapper });
}

describe("useAuthPermissions (RBAC v2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("grants full instance privileges exclusively to Owner and server/settings/user admin to Admin", async () => {
    const { result: ownerHook } = renderPermissions({
      user_id: "u-owner",
      email: "owner@example.com",
      display_name: "Owner",
      is_active: true,
      roles: ["owner"],
      global_role: "owner",
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    });
    await waitFor(() => expect(ownerHook.current.isOwner).toBe(true));
    expect(ownerHook.current.canAccessHostExposure).toBe(true);
    expect(ownerHook.current.canAccessModeAndCreds).toBe(true);
    expect(ownerHook.current.canManageUsers).toBe(true);
    expect(ownerHook.current.canPower("srv-any")).toBe(true);

    const { result: adminHook } = renderPermissions({
      user_id: "u-admin",
      email: "admin@example.com",
      display_name: "Admin",
      is_active: true,
      roles: ["admin"],
      global_role: "admin",
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    });
    await waitFor(() => expect(adminHook.current.isAdmin).toBe(true));
    expect(adminHook.current.isOwner).toBe(false);
    expect(adminHook.current.canAccessHostExposure).toBe(false);
    expect(adminHook.current.canAccessModeAndCreds).toBe(false);
    expect(adminHook.current.canManageUsers).toBe(true);
    expect(adminHook.current.canCreateServer).toBe(true);
    expect(adminHook.current.canPower("srv-any")).toBe(true);
  });

  it("scopes Server Admin to assigned servers and honors denied_permissions toggles", () => {
    const { result } = renderPermissions({
      user_id: "u-sa",
      email: "sa@example.com",
      display_name: "Server Admin",
      is_active: true,
      roles: ["server_admin"],
      global_role: "server_admin",
      all_servers_access: false,
      assigned_server_ids: ["srv-1"],
      denied_permissions: ["power", "backups"],
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    });

    const p = result.current;
    expect(p.isServerAdmin).toBe(true);
    expect(p.canCreateServer).toBe(false);
    expect(p.canManageUsers).toBe(false);
    expect(p.canAccessGlobalSettings).toBe(false);
    expect(p.canViewServer("srv-1")).toBe(true);
    expect(p.canViewServer("srv-2")).toBe(false);

    // Allowed capabilities on assigned srv-1
    expect(p.canConsole("srv-1")).toBe(true);
    expect(p.canFiles("srv-1")).toBe(true);
    expect(p.canSettings("srv-1")).toBe(true);
    // Denied capabilities on srv-1
    expect(p.canPower("srv-1")).toBe(false);
    expect(p.canBackups("srv-1")).toBe(false);
    expect(p.canViewBackups("srv-1")).toBe(false);
    // All capabilities denied on unassigned srv-2
    expect(p.canConsole("srv-2")).toBe(false);
    expect(p.canFiles("srv-2")).toBe(false);
  });

  it("enforces strictly read-only capabilities for Viewer and blocks all writes", () => {
    const { result } = renderPermissions({
      user_id: "u-view",
      email: "viewer@example.com",
      display_name: "Viewer",
      is_active: true,
      roles: ["viewer"],
      global_role: "viewer",
      all_servers_access: true,
      denied_permissions: ["files"],
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    });

    const p = result.current;
    expect(p.isViewer).toBe(true);
    expect(p.canViewServer("srv-1")).toBe(true);
    expect(p.canViewServer("srv-2")).toBe(true);

    // All mutations strictly false
    expect(p.canCreateServer).toBe(false);
    expect(p.canDeleteServer).toBe(false);
    expect(p.canManageUsers).toBe(false);
    expect(p.canPower("srv-1")).toBe(false);
    expect(p.canConsole("srv-1")).toBe(false);
    expect(p.canFiles("srv-1")).toBe(false);
    expect(p.canManagePlugins("srv-1")).toBe(false);
    expect(p.canBackups("srv-1")).toBe(false);
    expect(p.canSettings("srv-1")).toBe(false);
    expect(p.canManageExposure("srv-1")).toBe(false);
    expect(p.canVersioning("srv-1")).toBe(false);

    // Non-denied read-only views enabled; denied "files" (logs) disabled
    expect(p.canConsoleView("srv-1")).toBe(true);
    expect(p.canViewBackups("srv-1")).toBe(true);
    expect(p.canViewPlugins("srv-1")).toBe(true);
    expect(p.canViewExposure("srv-1")).toBe(true);
    expect(p.canViewVersioning("srv-1")).toBe(true);
    expect(p.canViewLogs("srv-1")).toBe(false);
  });
});
