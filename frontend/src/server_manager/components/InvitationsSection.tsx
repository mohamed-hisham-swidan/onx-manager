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
import type { InvitationItem, CreateInviteRequest } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

interface CurrentUserWithPerms {
  user_id?: string;
  roles?: string[];
  permissions?: string[];
}

export function InvitationsSection() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [createdInvite, setCreatedInvite] = useState<{ token: string; link: string } | null>(null);
  const [copiedField, setCopiedField] = useState<"link" | "token" | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; prefix: string } | null>(null);

  // Form State
  const [email, setEmail] = useState("");
  const [globalRole, setGlobalRole] = useState("member");
  const [serverId, setServerId] = useState("");
  const [serverRole, setServerRole] = useState("viewer");
  const [expiresInHours, setExpiresInHours] = useState(48);
  const [formError, setFormError] = useState<string | null>(null);

  const hasGetMe = typeof api.getMe === "function";
  const { data: currentUser } = useQuery<CurrentUserWithPerms | null>({
    queryKey: ["currentUser"],
    queryFn: () => api.getMe(),
    enabled: hasGetMe,
    retry: false,
  });

  const canManageInvites = useMemo(() => {
    if (!currentUser) return true;
    const roles = currentUser.roles ?? [];
    const perms = currentUser.permissions ?? [];
    return (
      roles.includes("owner") ||
      roles.includes("admin") ||
      perms.includes("user:write") ||
      perms.includes("admin:full")
    );
  }, [currentUser]);

  const { data: invites = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ["invites"],
    queryFn: () => api.listInvites(),
    enabled: canManageInvites,
  });

  const hasListServers = typeof api.listServers === "function";
  const { data: servers = [], isLoading: isLoadingServers, isError: serversError } = useQuery({
    queryKey: ["servers"],
    queryFn: () => api.listServers(),
    enabled: hasListServers && canManageInvites,
  });

  const serverNameMap = useMemo(
    () => new Map(servers.map((s: ServerResponse) => [s.server_id, s.name])),
    [servers],
  );

  const grantableGlobalRoles = useMemo(() => {
    const roles = currentUser?.roles || [];
    if (roles.includes("owner")) {
      return [
        { value: "owner", label: "Owner" },
        { value: "admin", label: "Administrator" },
        { value: "member", label: "Member (Standard)" },
        { value: "viewer", label: "Viewer (Limited)" },
      ];
    }
    if (roles.includes("admin")) {
      return [
        { value: "admin", label: "Administrator" },
        { value: "member", label: "Member (Standard)" },
        { value: "viewer", label: "Viewer (Limited)" },
      ];
    }
    return [
      { value: "member", label: "Member (Standard)" },
      { value: "viewer", label: "Viewer (Limited)" },
    ];
  }, [currentUser]);

  const safeDefaultRole = useMemo(() => {
    if (grantableGlobalRoles.some((r) => r.value === "member")) return "member";
    if (grantableGlobalRoles.some((r) => r.value === "viewer")) return "viewer";
    return grantableGlobalRoles[0]?.value ?? "member";
  }, [grantableGlobalRoles]);

  const createMutation = useMutation({
    mutationFn: (req: CreateInviteRequest) => api.createInvite(req),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["invites"] });
      const inviteUrl = `${window.location.origin}/invite/${res.token}`;
      setCreatedInvite({ token: res.token, link: inviteUrl });
      setIsModalOpen(false);
      setEmail("");
      setGlobalRole(safeDefaultRole);
      setServerId("");
      setServerRole("viewer");
      setExpiresInHours(48);
      setFormError(null);
      toast("success", "Invitation created", "Shareable invite link is ready.");
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to create invitation";
      setFormError(msg);
      toast("error", "Creation failed", msg);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.revokeInvite(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invites"] });
      toast("success", "Invitation revoked", "The invite token is no longer valid.");
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to revoke invitation";
      toast("error", "Revocation failed", msg);
    },
  });

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const payload: CreateInviteRequest = {
      email: email.trim() || undefined,
      global_role: globalRole || safeDefaultRole,
      expires_in_hours: expiresInHours ? Number(expiresInHours) : undefined,
    };

    if (serverId) {
      payload.server_id = serverId;
      payload.server_role = serverRole || "viewer";
    }

    createMutation.mutate(payload);
  };

  const copyToClipboard = (text: string, field: "link" | "token") => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    toast(
      "info",
      "Copied",
      field === "token" ? "Token copied to clipboard." : "Link copied to clipboard.",
    );
    setTimeout(() => setCopiedField((cur) => (cur === field ? null : cur)), 2000);
  };

  const openModal = () => {
    setCreatedInvite(null);
    setFormError(null);
    setGlobalRole(safeDefaultRole);
    setServerId("");
    setServerRole("viewer");
    setIsModalOpen(true);
  };

  const formatServerScope = (invite: InvitationItem) => {
    if (!invite.server_id) return "—";
    const resolvedName = serverNameMap.get(invite.server_id);
    const label = resolvedName || `${invite.server_id.slice(0, 8)}…`;
    return `${label} (${invite.server_role || "member"})`;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Invitations</h2>
          <p className="text-sm text-text-muted mt-0.5">
            Invite teammates with scoped panel or server roles.
          </p>
        </div>
        {canManageInvites && (
          <Button type="button" variant="primary" size="sm" icon="plus" onClick={openModal}>
            New Invite
          </Button>
        )}
      </div>

      {!canManageInvites ? (
        <div className="rounded-xl border border-border-subtle bg-surface-card p-8 text-center space-y-2.5 shadow-2xs">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-status-warning-bg text-status-warning">
            <Icon name="lock" size={20} />
          </div>
          <h3 className="text-sm font-semibold text-text-primary">Permission Required</h3>
          <p className="text-xs text-text-muted max-w-sm mx-auto">
            Administrator or Owner access is required to view or create invitations.
          </p>
        </div>
      ) : (
        <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-5">
          {createdInvite && (
            <div className="p-4 rounded-xl border border-status-success-border bg-status-success-bg text-text-primary space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-status-success">
                  <Icon name="check" size={16} />
                  <span className="font-semibold text-sm">Invitation Link Ready</span>
                </div>
                <button
                  type="button"
                  onClick={() => setCreatedInvite(null)}
                  aria-label="Dismiss invite secret"
                  className="rounded p-1 text-text-muted hover:text-text-primary cursor-pointer"
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
              <p className="text-xs text-text-secondary">
                This token is shown <strong>only once</strong>. Copy the link or token below.
              </p>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    readOnly
                    aria-label="Invitation Link"
                    value={createdInvite.link}
                    className="w-full px-3 py-1.5 rounded-lg border border-border-subtle bg-surface-page text-xs font-mono text-text-primary"
                  />
                  <Button
                    type="button"
                    size="xs"
                    variant="primary"
                    icon="copy"
                    onClick={() => copyToClipboard(createdInvite.link, "link")}
                  >
                    {copiedField === "link" ? "Copied!" : "Copy Link"}
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    readOnly
                    aria-label="Invitation Token"
                    value={createdInvite.token}
                    className="w-full px-3 py-1.5 rounded-lg border border-border-subtle bg-surface-page text-xs font-mono text-text-primary"
                  />
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    icon="copy"
                    onClick={() => copyToClipboard(createdInvite.token, "token")}
                  >
                    {copiedField === "token" ? "Copied!" : "Copy Token"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ) : isError ? (
            <ErrorState
              title="Failed to load invitations"
              message={error instanceof Error ? error.message : "Could not load invitations."}
              onRetry={() => refetch()}
            />
          ) : invites.length === 0 ? (
            <div className="rounded-lg bg-surface-page/70 px-4 py-5 text-center text-xs text-text-muted">
              No invitations yet. Create an invite to onboard teammates.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border-subtle">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-border-subtle bg-surface-page/70 text-text-muted">
                  <tr>
                    <th className="px-3.5 py-2.5 font-medium">Token</th>
                    <th className="px-3.5 py-2.5 font-medium">Email</th>
                    <th className="px-3.5 py-2.5 font-medium">Global Role</th>
                    <th className="px-3.5 py-2.5 font-medium">Server / Role</th>
                    <th className="px-3.5 py-2.5 font-medium">Status</th>
                    <th className="px-3.5 py-2.5 font-medium">Expires</th>
                    <th className="px-3.5 py-2.5 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {invites.map((invite: InvitationItem) => (
                    <tr key={invite.invite_id} className="hover:bg-surface-hover/50 transition-colors">
                      <td className="px-3.5 py-2.5 font-mono font-medium text-text-primary">
                        {invite.token_prefix}...
                      </td>
                      <td className="px-3.5 py-2.5 text-text-secondary">
                        {invite.email || <span className="text-text-muted">Any email</span>}
                      </td>
                      <td className="px-3.5 py-2.5 capitalize font-medium text-text-primary">
                        {invite.global_role}
                      </td>
                      <td className="px-3.5 py-2.5 text-text-secondary">
                        {formatServerScope(invite)}
                      </td>
                      <td className="px-3.5 py-2.5">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase border ${
                            invite.status === "ACTIVE"
                              ? "bg-status-success-bg text-status-success border-status-success-border"
                              : invite.status === "USED"
                              ? "bg-status-info-bg text-status-info border-status-info-border"
                              : "bg-surface-muted text-text-muted border-border-subtle"
                          }`}
                        >
                          {invite.status}
                        </span>
                      </td>
                      <td className="px-3.5 py-2.5 text-text-muted whitespace-nowrap">
                        {invite.expires_at
                          ? parseServerDate(invite.expires_at)?.toLocaleString() ?? "Never"
                          : "Never"}
                      </td>
                      <td className="px-3.5 py-2.5 text-right">
                        {invite.status === "ACTIVE" && (
                          <button
                            type="button"
                            onClick={() =>
                              setRevokeTarget({ id: invite.invite_id, prefix: invite.token_prefix })
                            }
                            disabled={revokeMutation.isPending}
                            className="text-status-danger hover:underline font-medium disabled:opacity-50 cursor-pointer"
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* Modal for creating invitation */}
      <Modal
        open={isModalOpen}
        onClose={() => {
          if (createMutation.isPending) return;
          setIsModalOpen(false);
        }}
        title="Generate Invitation"
        size="md"
        closeOnBackdrop={false}
        closeOnEscape={!createMutation.isPending}
        closeButtonAriaLabel="Close dialog"
      >
        <div className="space-y-4 max-h-[80vh] overflow-y-auto">
          {formError && <Banner variant="danger" title="Invitation failed" description={formError} />}

          <form onSubmit={handleCreateSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">
                Bound Email (Optional)
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Restrict to specific email address"
                className="w-full px-3 py-2 rounded-lg border border-border-subtle bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="globalRole" className="block text-xs font-medium text-text-secondary">
                Global Access Role
              </label>
              <select
                id="globalRole"
                value={globalRole}
                onChange={(e) => setGlobalRole(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-border-subtle bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden"
              >
                {grantableGlobalRoles.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
              {(globalRole === "owner" || globalRole === "admin") && (
                <div className="inline-flex items-center gap-1.5 rounded-full border border-status-warning-border bg-status-warning-bg px-2.5 py-1 text-[11px] font-medium text-status-warning">
                  <Icon name="alert" size={12} />
                  <span>Grants full administrative privileges across the panel.</span>
                </div>
              )}
            </div>

            <div className="border-t border-border-subtle pt-3 space-y-3">
              <label className="block text-xs font-medium text-text-secondary">
                Server Access (Optional)
              </label>
              <div>
                <select
                  id="serverId"
                  aria-label="Server Access"
                  value={serverId}
                  onChange={(e) => setServerId(e.target.value)}
                  disabled={isLoadingServers}
                  className="w-full px-3 py-2 rounded-lg border border-border-subtle bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden disabled:opacity-50"
                >
                  <option value="">[ No server access ]</option>
                  {servers.map((s: ServerResponse) => (
                    <option key={s.server_id} value={s.server_id}>
                      {s.name} ({s.server_id})
                    </option>
                  ))}
                </select>
                {serversError && (
                  <p className="text-[11px] text-status-warning mt-1">
                    Server list temporarily unavailable. You can still issue global invitations.
                  </p>
                )}
              </div>

              {serverId && (
                <div>
                  <label htmlFor="serverRole" className="block text-xs font-medium text-text-muted mb-1">
                    Server Role
                  </label>
                  <select
                    id="serverRole"
                    aria-label="Server Role"
                    value={serverRole}
                    onChange={(e) => setServerRole(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-border-subtle bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden"
                  >
                    <option value="viewer">Server Viewer</option>
                    <option value="dev">Developer</option>
                    <option value="admin">Server Administrator</option>
                  </select>
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1">
                Expiration (Hours)
              </label>
              <input
                type="number"
                min={1}
                max={720}
                value={expiresInHours}
                onChange={(e) => setExpiresInHours(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-lg border border-border-subtle bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={createMutation.isPending}
                onClick={() => setIsModalOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                loading={createMutation.isPending}
              >
                {createMutation.isPending ? "Generating..." : "Generate Invitation"}
              </Button>
            </div>
          </form>
        </div>
      </Modal>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke invitation?"
        description={
          revokeTarget
            ? `Token "${revokeTarget.prefix}..." will stop working immediately.`
            : undefined
        }
        confirmLabel="Revoke"
        onConfirm={() => {
          if (revokeTarget) {
            revokeMutation.mutate(revokeTarget.id);
            setRevokeTarget(null);
          }
        }}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
