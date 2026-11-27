import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { toast } from "@/stores/toastStore";
import {
  ROLE_LABELS,
  normalizeCanonicalRole,
  useAuthPermissions,
} from "@/hooks/useAuthPermissions";
import { RoleScopeSelector } from "@/server_manager/components/RoleScopeSelector";
import { InvitationsSection } from "@/server_manager/components/InvitationsSection";
import type { CanonicalRole, UserResponse } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

export interface UsersPermissionsSectionProps {
  initialSubTab?: "users" | "invitations";
}

export function UsersPermissionsSection({
  initialSubTab = "users",
}: UsersPermissionsSectionProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const auth = useAuthPermissions();

  const [subTab, setSubTab] = useState<"users" | "invitations">(initialSubTab);

  // Add User modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<CanonicalRole>("viewer");
  const [newAllServers, setNewAllServers] = useState(false);
  const [newServerIds, setNewServerIds] = useState<string[]>([]);
  const [newDenied, setNewDenied] = useState<string[]>([]);
  const [addError, setAddError] = useState<string | null>(null);

  // Edit User Access modal state
  const [editTarget, setEditTarget] = useState<UserResponse | null>(null);
  const [editRole, setEditRole] = useState<CanonicalRole>("viewer");
  const [editAllServers, setEditAllServers] = useState(false);
  const [editServerIds, setEditServerIds] = useState<string[]>([]);
  const [editDenied, setEditDenied] = useState<string[]>([]);
  const [editIsActive, setEditIsActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);

  // Delete User confirm state
  const [deleteTarget, setDeleteTarget] = useState<UserResponse | null>(null);

  const canManage = auth.canManageUsers;

  const {
    data: users = [],
    isLoading: isLoadingUsers,
    isError: usersError,
    error: usersErrObj,
    refetch: refetchUsers,
  } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.listUsers(),
    enabled: canManage && typeof api.listUsers === "function",
  });

  const {
    data: servers = [],
    isLoading: isLoadingServers,
    isError: serversError,
  } = useQuery({
    queryKey: ["servers"],
    queryFn: () => api.listServers(),
    enabled: canManage && typeof api.listServers === "function",
  });

  const serverNameMap = useMemo(
    () => new Map(servers.map((s: ServerResponse) => [s.server_id, s.name])),
    [servers],
  );

  const invalidateUserCaches = () => {
    queryClient.invalidateQueries({ queryKey: ["users"] });
    queryClient.invalidateQueries({ queryKey: ["currentUser"] });
    queryClient.invalidateQueries({ queryKey: queryKeys.auth.me });
  };

  const createUserMutation = useMutation({
    mutationFn: () =>
      api.adminCreateUser({
        username: newUsername.trim(),
        display_name: newDisplayName.trim() || undefined,
        email: newEmail.trim() || undefined,
        password: newPassword,
        role: newRole,
        all_servers_access: newRole === "owner" || newRole === "admin" ? true : newAllServers,
        server_ids: newRole === "owner" || newRole === "admin" || newAllServers ? [] : newServerIds,
        denied_permissions: newRole === "owner" || newRole === "admin" ? [] : newDenied,
        is_active: true,
      }),
    onSuccess: (created) => {
      setIsAddModalOpen(false);
      invalidateUserCaches();
      toast(
        "success",
        "User created",
        `"${created.display_name || created.username}" added as ${ROLE_LABELS[normalizeCanonicalRole(created)]}.`,
      );
    },
    onError: (err) => {
      setAddError(err instanceof Error ? err.message : "Failed to create user");
    },
  });

  const updateAccessMutation = useMutation({
    mutationFn: () => {
      if (!editTarget) throw new Error("No target user selected");
      return api.updateUserAccess(editTarget.user_id, {
        role: editRole,
        all_servers_access: editRole === "owner" || editRole === "admin" ? true : editAllServers,
        server_ids:
          editRole === "owner" || editRole === "admin" || editAllServers ? [] : editServerIds,
        denied_permissions:
          editRole === "owner" || editRole === "admin" ? [] : editDenied,
        is_active: editIsActive,
      });
    },
    onSuccess: (updated) => {
      setEditTarget(null);
      invalidateUserCaches();
      toast(
        "success",
        "Permissions updated",
        `Updated access for "${updated.display_name || updated.username}".`,
      );
    },
    onError: (err) => {
      setEditError(err instanceof Error ? err.message : "Failed to update permissions");
    },
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ userId, isActive }: { userId: string; isActive: boolean }) =>
      api.updateUser(userId, { is_active: isActive }),
    onSuccess: (_res, vars) => {
      invalidateUserCaches();
      toast(
        "success",
        vars.isActive ? "User activated" : "User deactivated",
        vars.isActive ? "User can sign in again." : "User access has been disabled.",
      );
    },
    onError: (err) => {
      toast("error", "Status update failed", err instanceof Error ? err.message : "Unknown error");
    },
  });

  const deleteUserMutation = useMutation({
    mutationFn: (userId: string) => api.deleteUser(userId),
    onSuccess: () => {
      invalidateUserCaches();
      toast("success", "User deleted", "User account has been removed.");
    },
    onError: (err) => {
      toast("error", "Delete failed", err instanceof Error ? err.message : "Unknown error");
    },
  });

  const openAddModal = () => {
    setNewUsername("");
    setNewDisplayName("");
    setNewEmail("");
    setNewPassword("");
    setNewRole("viewer");
    setNewAllServers(false);
    setNewServerIds([]);
    setNewDenied([]);
    setAddError(null);
    setIsAddModalOpen(true);
  };

  const openEditModal = (u: UserResponse) => {
    const resolved = normalizeCanonicalRole(u);
    setEditTarget(u);
    setEditRole(resolved);
    setEditAllServers(Boolean(u.all_servers_access));
    setEditServerIds(u.assigned_server_ids ?? []);
    setEditDenied((u.denied_permissions ?? []).map((p) => String(p)));
    setEditIsActive(u.is_active);
    setEditError(null);
  };

  if (auth.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    );
  }

  if (!canManage) {
    return (
      <div className="rounded-xl border border-status-warning-border bg-status-warning-bg p-6">
        <div className="flex items-start gap-3">
          <Icon name="lock" size={20} className="text-status-warning shrink-0 mt-0.5" />
          <div className="text-sm text-status-warning">
            <p className="font-semibold text-base">Permission Required</p>
            <p className="mt-1 opacity-90">
              Only Owners and Administrators can manage team members, roles, and invitations.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-4">
        <div className="flex items-center gap-2 rounded-lg bg-surface-muted p-1">
          <button
            type="button"
            onClick={() => setSubTab("users")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              subTab === "users"
                ? "bg-surface-card text-text-primary shadow-2xs"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            Team Members ({users.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab("invitations")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              subTab === "invitations"
                ? "bg-surface-card text-text-primary shadow-2xs"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            Invitations
          </button>
        </div>

        {subTab === "users" && (
          <Button onClick={openAddModal} icon="plus" size="md">
            Add User
          </Button>
        )}
      </div>

      {subTab === "invitations" ? (
        <InvitationsSection />
      ) : isLoadingUsers ? (
        <div className="space-y-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-36 w-full rounded-xl" />
        </div>
      ) : usersError ? (
        <ErrorState
          message={usersErrObj instanceof Error ? usersErrObj.message : "Failed to load users"}
          onRetry={() => refetchUsers()}
        />
      ) : (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold text-text-primary">Team Members</h3>
            <p className="text-sm text-text-secondary mt-0.5">
              Assign canonical roles, per-server scope, and capability toggles. Changes take effect immediately across HTTP and live console sessions.
            </p>
          </div>

          <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface-card shadow-2xs">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs uppercase text-text-muted">
                  <th className="py-3 px-4 font-semibold">User</th>
                  <th className="py-3 px-4 font-semibold">Role</th>
                  <th className="py-3 px-4 font-semibold">Server Scope</th>
                  <th className="py-3 px-4 font-semibold">Capabilities</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                  <th className="py-3 px-4 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {users.map((u: UserResponse) => {
                  const resolvedRole = normalizeCanonicalRole(u);
                  const isTargetOwner = resolvedRole === "owner";
                  const isSelf = auth.user?.user_id === u.user_id;
                  const canEditTarget = auth.isOwner || !isTargetOwner;
                  const isGlobalRole = resolvedRole === "owner" || resolvedRole === "admin";
                  const assignedIds = u.assigned_server_ids ?? [];
                  const denied = u.denied_permissions ?? [];

                  return (
                    <tr key={u.user_id} className="hover:bg-surface-hover/40 transition-colors">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-text-primary">
                            {u.display_name || u.username || u.user_id}
                          </span>
                          {isSelf && (
                            <span className="rounded bg-accent-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-text-accent">
                              You
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-text-muted">
                          {u.username ? `@${u.username}` : ""}
                          {u.username && u.email ? " · " : ""}
                          {u.email || ""}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center rounded-md border border-border-subtle bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-primary">
                          {ROLE_LABELS[resolvedRole]}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-xs text-text-secondary">
                        {isGlobalRole || u.all_servers_access ? (
                          <span className="font-medium text-text-primary">All Servers</span>
                        ) : assignedIds.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {assignedIds.map((sid) => (
                              <span
                                key={sid}
                                className="inline-flex items-center rounded bg-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-text-primary"
                              >
                                {serverNameMap.get(sid) || `${sid.slice(0, 8)}...`}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-text-muted">No servers</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-xs text-text-muted">
                        {isGlobalRole ? (
                          "Full capabilities"
                        ) : denied.length > 0 ? (
                          <span>Restricted: {denied.join(", ")}</span>
                        ) : resolvedRole === "viewer" ? (
                          <span>Read-only views</span>
                        ) : (
                          <span>All server capabilities</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border ${
                            u.is_active
                              ? "bg-status-success-bg text-status-success border-status-success-border"
                              : "bg-status-danger-bg text-status-danger border-status-danger-border"
                          }`}
                        >
                          {u.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <Button
                            variant="secondary"
                            size="xs"
                            disabled={!canEditTarget}
                            title={
                              canEditTarget
                                ? "Edit role and server access"
                                : "Only an Owner can edit an Owner account"
                            }
                            onClick={() => openEditModal(u)}
                          >
                            Edit Access
                          </Button>
                          {!isSelf && (
                            <>
                              <Button
                                variant="ghost"
                                size="xs"
                                disabled={!canEditTarget || toggleActiveMutation.isPending}
                                onClick={() =>
                                  toggleActiveMutation.mutate({
                                    userId: u.user_id,
                                    isActive: !u.is_active,
                                  })
                                }
                              >
                                {u.is_active ? "Disable" : "Enable"}
                              </Button>
                              <Button
                                variant="danger"
                                size="xs"
                                disabled={!canEditTarget || deleteUserMutation.isPending}
                                onClick={() => setDeleteTarget(u)}
                              >
                                Delete
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add User Modal */}
      <Modal
        open={isAddModalOpen}
        onClose={() => {
          if (!createUserMutation.isPending) setIsAddModalOpen(false);
        }}
        title="Add User Account"
        description="Directly create an account with a scoped role, server access, and capability limits."
        size="xl"
        closeOnBackdrop={false}
        closeOnEscape={!createUserMutation.isPending}
        footer={
          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="secondary"
              size="md"
              onClick={() => setIsAddModalOpen(false)}
              disabled={createUserMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="add-user-form"
              variant="primary"
              size="md"
              disabled={createUserMutation.isPending}
            >
              {createUserMutation.isPending ? "Creating..." : "Create User"}
            </Button>
          </div>
        }
      >
        <form
          id="add-user-form"
          onSubmit={(e) => {
            e.preventDefault();
            setAddError(null);
            createUserMutation.mutate();
          }}
          className="space-y-3"
        >
          {addError && (
            <div
              role="alert"
              className="rounded-lg bg-status-danger-bg border border-status-danger-border px-3 py-2 text-xs text-status-danger"
            >
              {addError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 sm:gap-3">
            <div>
              <label
                htmlFor="add-user-username"
                className="mb-1 block text-xs font-medium text-text-secondary"
              >
                Username *
              </label>
              <input
                id="add-user-username"
                type="text"
                required
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                disabled={createUserMutation.isPending}
                placeholder="alex"
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
            </div>

            <div>
              <label
                htmlFor="add-user-display"
                className="mb-1 block text-xs font-medium text-text-secondary"
              >
                Display Name
              </label>
              <input
                id="add-user-display"
                type="text"
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
                disabled={createUserMutation.isPending}
                placeholder="Alex"
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
            </div>

            <div>
              <label
                htmlFor="add-user-email"
                className="mb-1 block text-xs font-medium text-text-secondary"
              >
                Email (optional)
              </label>
              <input
                id="add-user-email"
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                disabled={createUserMutation.isPending}
                placeholder="alex@example.com"
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
            </div>

            <div>
              <label
                htmlFor="add-user-password"
                className="mb-1 block text-xs font-medium text-text-secondary"
              >
                Temporary Password (min 8 chars) *
              </label>
              <input
                id="add-user-password"
                type="password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={createUserMutation.isPending}
                placeholder="********"
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
            </div>
          </div>

          <RoleScopeSelector
            role={newRole}
            onRoleChange={setNewRole}
            allowOwner={auth.isOwner}
            allServersAccess={newAllServers}
            onAllServersAccessChange={setNewAllServers}
            serverIds={newServerIds}
            onServerIdsChange={setNewServerIds}
            deniedPermissions={newDenied}
            onDeniedPermissionsChange={setNewDenied}
            servers={servers}
            isLoadingServers={isLoadingServers}
            serversError={serversError}
            disabled={createUserMutation.isPending}
          />
        </form>
      </Modal>

      {/* Edit User Access Modal */}
      <Modal
        open={Boolean(editTarget)}
        onClose={() => {
          if (!updateAccessMutation.isPending) setEditTarget(null);
        }}
        title={
          editTarget
            ? `Edit Access: ${editTarget.display_name || editTarget.username}`
            : "Edit User Access"
        }
        description="Update global role, server assignments, and capability overrides."
        size="xl"
        closeOnBackdrop={false}
        closeOnEscape={!updateAccessMutation.isPending}
        footer={
          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="secondary"
              size="md"
              onClick={() => setEditTarget(null)}
              disabled={updateAccessMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="edit-user-access-form"
              variant="primary"
              size="md"
              disabled={updateAccessMutation.isPending}
            >
              {updateAccessMutation.isPending ? "Saving..." : "Save Permissions"}
            </Button>
          </div>
        }
      >
        <form
          id="edit-user-access-form"
          onSubmit={(e) => {
            e.preventDefault();
            setEditError(null);
            updateAccessMutation.mutate();
          }}
          className="space-y-3"
        >
          {editError && (
            <div
              role="alert"
              className="rounded-lg bg-status-danger-bg border border-status-danger-border px-3 py-2 text-xs text-status-danger"
            >
              {editError}
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-text-primary cursor-pointer">
            <input
              type="checkbox"
              checked={editIsActive}
              disabled={updateAccessMutation.isPending}
              onChange={(e) => setEditIsActive(e.target.checked)}
              className="h-4 w-4 rounded border-border-default accent-accent-primary"
            />
            <span>Account Active</span>
          </label>

          <RoleScopeSelector
            role={editRole}
            onRoleChange={setEditRole}
            allowOwner={auth.isOwner}
            allServersAccess={editAllServers}
            onAllServersAccessChange={setEditAllServers}
            serverIds={editServerIds}
            onServerIdsChange={setEditServerIds}
            deniedPermissions={editDenied}
            onDeniedPermissionsChange={setEditDenied}
            servers={servers}
            isLoadingServers={isLoadingServers}
            serversError={serversError}
            disabled={updateAccessMutation.isPending}
          />
        </form>
      </Modal>

      {/* Delete User Confirm */}
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete User Account?"
        description={
          deleteTarget
            ? `Permanently delete user "${deleteTarget.display_name || deleteTarget.username}"? Active sessions will be disconnected immediately.`
            : ""
        }
        confirmLabel="Delete User"
        variant="danger"
        isPending={deleteUserMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) {
            deleteUserMutation.mutate(deleteTarget.user_id, {
              onSettled: () => setDeleteTarget(null),
            });
          }
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
