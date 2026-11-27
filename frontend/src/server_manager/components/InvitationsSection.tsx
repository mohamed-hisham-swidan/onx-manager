import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Banner } from "@/components/ui/Banner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { toast } from "@/stores/toastStore";
import { parseServerDate } from "@/server_manager/utils/format";
import { ROLE_LABELS, useAuthPermissions } from "@/hooks/useAuthPermissions";
import { RoleScopeSelector } from "@/server_manager/components/RoleScopeSelector";
import type { CanonicalRole, InvitationItem, CreateInviteRequest } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

function formatInviteRoleLabel(inv: InvitationItem): string {
  const raw = String(inv.role || inv.global_role || "viewer").toLowerCase();
  if (raw === "owner") return ROLE_LABELS.owner;
  if (raw === "admin") return ROLE_LABELS.admin;
  if (raw === "server_admin" || (raw === "member" && (inv.server_role === "admin" || inv.server_role === "dev" || inv.server_role === "server_admin"))) {
    return ROLE_LABELS.server_admin;
  }
  return ROLE_LABELS.viewer;
}

export function InvitationsSection() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const auth = useAuthPermissions();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [createdInvite, setCreatedInvite] = useState<{ token: string; link: string } | null>(null);
  const [copiedField, setCopiedField] = useState<"link" | "token" | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; prefix: string } | null>(null);

  // Form State — safely defaults to lowest-privilege 'viewer'
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<CanonicalRole>("viewer");
  const [allServersAccess, setAllServersAccess] = useState(false);
  const [serverIds, setServerIds] = useState<string[]>([]);
  const [deniedPermissions, setDeniedPermissions] = useState<string[]>([]);
  const [expiresInHours, setExpiresInHours] = useState(48);
  const [formError, setFormError] = useState<string | null>(null);

  const canManageInvites = auth.canManageUsers;

  const { data: invites = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ["invites"],
    queryFn: () => api.listInvites(),
    enabled: canManageInvites,
  });

  const hasListServers = typeof api.listServers === "function";
  const {
    data: servers = [],
    isLoading: isLoadingServers,
    isError: serversError,
  } = useQuery({
    queryKey: ["servers"],
    queryFn: () => api.listServers(),
    enabled: hasListServers && canManageInvites,
  });

  const serverNameMap = useMemo(
    () => new Map(servers.map((s: ServerResponse) => [s.server_id, s.name])),
    [servers],
  );

  const createMutation = useMutation({
    mutationFn: (req: CreateInviteRequest) => api.createInvite(req),
    onSuccess: (res) => {
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      setCreatedInvite({
        token: res.token,
        link: `${origin}/invite/${res.token}`,
      });
      setIsModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["invites"] });
      toast("success", "Invitation generated", "Copy the invite link to share access safely.");
    },
    onError: (err) => {
      setFormError(err instanceof Error ? err.message : "Failed to generate invitation");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.revokeInvite(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invites"] });
      toast("success", "Invitation revoked", "The invitation link is no longer valid.");
    },
    onError: (err) => {
      toast("error", "Revoke failed", err instanceof Error ? err.message : "Unknown error");
    },
  });

  const openModal = () => {
    setEmail("");
    setRole("viewer");
    setAllServersAccess(false);
    setServerIds([]);
    setDeniedPermissions([]);
    setExpiresInHours(48);
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const req: CreateInviteRequest = {
      email: email.trim() || undefined,
      role,
      all_servers_access: role === "owner" || role === "admin" ? true : allServersAccess,
      server_ids: role === "owner" || role === "admin" || allServersAccess ? [] : serverIds,
      denied_permissions: role === "owner" || role === "admin" ? [] : deniedPermissions,
      expires_in_hours: expiresInHours || 48,
    };
    createMutation.mutate(req);
  };

  const handleCopy = (value: string, field: "link" | "token") => {
    if (!navigator.clipboard) return;
    void navigator.clipboard.writeText(value);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  if (auth.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    );
  }

  if (!canManageInvites) {
    return (
      <div className="rounded-xl border border-status-warning-border bg-status-warning-bg p-6">
        <div className="flex items-start gap-3">
          <Icon name="lock" size={20} className="text-status-warning shrink-0 mt-0.5" />
          <div className="text-sm text-status-warning">
            <p className="font-semibold text-base">Permission Required</p>
            <p className="mt-1 opacity-90">
              Only Owners and Administrators can generate or revoke team invitations.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    );
  }

  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load invitations"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-text-primary">Invitations</h3>
          <p className="text-sm text-text-secondary mt-0.5">
            Generate single-use or expiring invitation links with scoped roles, multi-server access, and capability limits.
          </p>
        </div>
        <Button onClick={openModal} icon="plus" size="md">
          New Invite
        </Button>
      </div>

      {createdInvite && (
        <Banner
          variant="success"
          title="Invitation generated — copy link now"
          onDismiss={() => setCreatedInvite(null)}
          action={
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={copiedField === "link" ? "check" : "copy"}
                onClick={() => handleCopy(createdInvite.link, "link")}
              >
                {copiedField === "link" ? "Copied Link" : "Copy Link"}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={copiedField === "token" ? "check" : "copy"}
                onClick={() => handleCopy(createdInvite.token, "token")}
              >
                {copiedField === "token" ? "Copied Token" : "Copy Token"}
              </Button>
            </div>
          }
        >
          <p className="text-xs opacity-90 mb-2">
            The invitation secret is shown only once and will not be visible again after closing this alert.
          </p>
          <code className="block rounded-lg bg-surface-page/70 border border-border-subtle px-3 py-2 text-xs font-mono break-all text-text-primary select-all">
            {createdInvite.link}
          </code>
        </Banner>
      )}

      {invites.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-subtle bg-surface-card p-10 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
            <Icon name="users" size={24} />
          </div>
          <p className="text-sm font-medium text-text-primary">No invitations found</p>
          <p className="text-xs text-text-muted mt-1 max-w-sm mx-auto">
            Create an invitation link to onboard new team members with a clearly scoped role and server list.
          </p>
          <Button variant="secondary" size="sm" onClick={openModal} className="mt-4">
            Create Invitation
          </Button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface-card shadow-2xs">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs uppercase text-text-muted">
                <th className="py-3 px-4 font-semibold">Recipient / Prefix</th>
                <th className="py-3 px-4 font-semibold">Role</th>
                <th className="py-3 px-4 font-semibold">Server Scope</th>
                <th className="py-3 px-4 font-semibold">Restrictions</th>
                <th className="py-3 px-4 font-semibold">Status</th>
                <th className="py-3 px-4 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {invites.map((inv: InvitationItem) => {
                const rawRole = String(inv.role || inv.global_role || "viewer").toLowerCase();
                const isGlobal = rawRole === "owner" || rawRole === "admin";
                const invServerIds =
                  inv.server_ids && inv.server_ids.length > 0
                    ? inv.server_ids
                    : inv.server_id
                      ? [inv.server_id]
                      : [];
                const denied = inv.denied_permissions ?? [];

                return (
                  <tr key={inv.invite_id} className="hover:bg-surface-hover/40 transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-medium text-text-primary">
                        {inv.email || (
                          <span className="italic text-text-muted">Anyone with link</span>
                        )}
                      </div>
                      <div className="text-xs text-text-muted font-mono">{inv.token_prefix}...</div>
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex items-center rounded-md border border-border-subtle bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-primary">
                        {formatInviteRoleLabel(inv)}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-xs text-text-secondary">
                      {isGlobal || inv.all_servers_access ? (
                        <span className="font-medium text-text-primary">All Servers</span>
                      ) : invServerIds.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {invServerIds.map((sid) => (
                            <span
                              key={sid}
                              className="inline-flex items-center rounded bg-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-text-primary"
                            >
                              {serverNameMap.get(sid) || `${sid.slice(0, 8)}...`}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-text-muted">No servers assigned</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-xs text-text-muted">
                      {isGlobal ? (
                        "None"
                      ) : denied.length > 0 ? (
                        <span>No {denied.join(", ")}</span>
                      ) : (
                        <span>Default role capabilities</span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium border ${
                          inv.status === "ACTIVE"
                            ? "bg-status-success-bg text-status-success border-status-success-border"
                            : inv.status === "USED"
                              ? "bg-surface-muted text-text-secondary border-border-subtle"
                              : "bg-status-danger-bg text-status-danger border-status-danger-border"
                        }`}
                      >
                        {inv.status}
                      </span>
                      {inv.expires_at && inv.status === "ACTIVE" && (
                        <div className="mt-1 text-[11px] text-text-muted">
                          Expires {parseServerDate(inv.expires_at)?.toLocaleString() ?? inv.expires_at}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right">
                      {inv.status === "ACTIVE" && (
                        <Button
                          variant="danger"
                          size="xs"
                          onClick={() =>
                            setRevokeTarget({ id: inv.invite_id, prefix: inv.token_prefix })
                          }
                          disabled={revokeMutation.isPending}
                        >
                          Revoke
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={isModalOpen}
        onClose={() => {
          if (!createMutation.isPending) setIsModalOpen(false);
        }}
        title="Generate Invitation"
        description="Configure an invitation link with a canonical role, server assignments, and optional capability limits."
        size="xl"
        closeOnBackdrop={false}
        closeOnEscape={!createMutation.isPending}
        footer={
          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="secondary"
              size="md"
              onClick={() => setIsModalOpen(false)}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="create-invite-form"
              variant="primary"
              size="md"
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? "Generating..." : "Generate Invitation"}
            </Button>
          </div>
        }
      >
        <form id="create-invite-form" onSubmit={handleSubmit} className="space-y-3">
          {formError && (
            <div
              role="alert"
              className="rounded-lg bg-status-danger-bg border border-status-danger-border px-3 py-2 text-xs text-status-danger"
            >
              {formError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 sm:gap-3">
            <div>
              <label
                htmlFor="invite-email"
                className="mb-1 block text-xs font-medium text-text-secondary"
              >
                Email Address (optional)
              </label>
              <input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={createMutation.isPending}
                placeholder="teammate@example.com (leave empty for anyone)"
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-60"
              />
            </div>

            <div>
              <label
                htmlFor="invite-expiry"
                className="mb-1 block text-xs font-medium text-text-secondary"
              >
                Expires In
              </label>
              <select
                id="invite-expiry"
                value={expiresInHours}
                onChange={(e) => setExpiresInHours(Number(e.target.value))}
                disabled={createMutation.isPending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-60"
              >
                <option value={1}>1 Hour</option>
                <option value={24}>24 Hours</option>
                <option value={48}>48 Hours (Default)</option>
                <option value={168}>7 Days</option>
              </select>
            </div>
          </div>

          <RoleScopeSelector
            role={role}
            onRoleChange={setRole}
            allowOwner={auth.isOwner}
            allServersAccess={allServersAccess}
            onAllServersAccessChange={setAllServersAccess}
            serverIds={serverIds}
            onServerIdsChange={setServerIds}
            deniedPermissions={deniedPermissions}
            onDeniedPermissionsChange={setDeniedPermissions}
            servers={servers}
            isLoadingServers={isLoadingServers}
            serversError={serversError}
            disabled={createMutation.isPending}
          />
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Revoke Invitation?"
        description={
          revokeTarget
            ? `Revoke invite token ${revokeTarget.prefix}...? Anyone who still has this link will not be able to register.`
            : ""
        }
        confirmLabel="Revoke Invitation"
        variant="danger"
        isPending={revokeMutation.isPending}
        onConfirm={() => {
          if (revokeTarget) {
            revokeMutation.mutate(revokeTarget.id, {
              onSettled: () => setRevokeTarget(null),
            });
          }
        }}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
