import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { toast } from "@/stores/toastStore";
import { parseServerDate } from "@/server_manager/utils/format";
import type { InvitationItem, CreateInviteRequest } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

export function InvitationsSection() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [createdInvite, setCreatedInvite] = useState<{ token: string; link: string } | null>(null);
  const [copiedField, setCopiedField] = useState<"link" | "token" | null>(null);

  // Form State
  const [email, setEmail] = useState("");
  const [globalRole, setGlobalRole] = useState("member");
  const [serverId, setServerId] = useState("");
  const [serverRole, setServerRole] = useState("viewer");
  const [expiresInHours, setExpiresInHours] = useState(48);
  const [formError, setFormError] = useState<string | null>(null);

  // 1. Fetch Invites
  const { data: invites = [], isLoading, isError, error } = useQuery({
    queryKey: ["invites"],
    queryFn: () => api.listInvites(),
  });

  // 2. Fetch Current User Identity
  const { data: currentUser } = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => api.getMe(),
  });

  // 3. Fetch Server List
  const { data: servers = [], isLoading: isLoadingServers, isError: serversError } = useQuery({
    queryKey: ["servers"],
    queryFn: () => api.listServers(),
  });

  // Calculate grantable global roles based on user's current roles
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

  const createMutation = useMutation({
    mutationFn: (req: CreateInviteRequest) => api.createInvite(req),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["invites"] });
      const inviteUrl = `${window.location.origin}/invite/${res.token}`;
      setCreatedInvite({ token: res.token, link: inviteUrl });
      setIsModalOpen(false);
      // Reset form
      setEmail("");
      setGlobalRole(grantableGlobalRoles[0]?.value || "member");
      setServerId("");
      setServerRole("viewer");
      setExpiresInHours(48);
      setFormError(null);
      toast("success", "Invitation Created", "Shareable invitation link has been generated.");
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to create invitation";
      setFormError(msg);
      toast("error", "Creation Failed", msg);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.revokeInvite(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invites"] });
      toast("success", "Invitation Revoked", "The invitation token is now invalidated.");
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to revoke invitation";
      toast("error", "Revocation Failed", msg);
    },
  });

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const payload: CreateInviteRequest = {
      email: email.trim() || undefined,
      global_role: globalRole || grantableGlobalRoles[0]?.value || "member",
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
      field === "token" ? "Token copied to clipboard!" : "Link copied to clipboard!",
    );
    setTimeout(() => setCopiedField((cur) => (cur === field ? null : cur)), 2000);
  };

  const openModal = () => {
    setCreatedInvite(null);
    setFormError(null);
    setGlobalRole(grantableGlobalRoles[0]?.value || "member");
    setServerId("");
    setServerRole("viewer");
    setIsModalOpen(true);
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border-default bg-surface-card p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h3 className="text-base font-semibold text-text-primary">
              Invitations Management
            </h3>
            <p className="text-xs text-text-muted mt-0.5">
              Create and manage invitation links to invite new users to this instance.
            </p>
          </div>
          <button
            type="button"
            onClick={openModal}
            className="inline-flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover shrink-0 cursor-pointer"
          >
            <Icon name="plus" size={16} />
            Create Invitation
          </button>
        </div>

        {/* Display created invitation secret once */}
        {createdInvite && (
          <div className="mb-6 p-4 rounded-xl border border-status-success-border bg-status-success-bg text-status-success space-y-3">
            <div className="flex items-center gap-2">
              <Icon name="check" size={18} className="text-status-success" />
              <span className="font-semibold text-sm">Invitation Link Generated!</span>
            </div>
            <p className="text-xs text-status-success opacity-90">
              This secret raw token is displayed <strong>only once</strong>. Copy the link or token below to share it.
            </p>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  aria-label="Invitation Link"
                  value={createdInvite.link}
                  className="w-full px-3 py-1.5 rounded-lg border border-status-success-border bg-surface-page text-xs font-mono text-text-primary"
                />
                <button
                  type="button"
                  onClick={() => copyToClipboard(createdInvite.link, "link")}
                  className="px-3 py-1.5 rounded-lg bg-status-success text-accent-contrast-text text-xs font-medium shrink-0 flex items-center gap-1 cursor-pointer"
                >
                  <Icon name="copy" size={14} />
                  {copiedField === "link" ? "Copied!" : "Copy Link"}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  aria-label="Invitation Token"
                  value={createdInvite.token}
                  className="w-full px-3 py-1.5 rounded-lg border border-status-success-border bg-surface-page text-xs font-mono text-text-primary"
                />
                <button
                  type="button"
                  onClick={() => copyToClipboard(createdInvite.token, "token")}
                  className="px-3 py-1.5 rounded-lg border border-status-success-border bg-surface-page hover:bg-surface-hover text-status-success text-xs font-medium shrink-0 flex items-center gap-1 cursor-pointer"
                >
                  <Icon name="copy" size={14} />
                  {copiedField === "token" ? "Copied!" : "Copy Token"}
                </button>
              </div>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="py-8 text-center text-sm text-text-muted">Loading invitations...</div>
        ) : isError ? (
          <div className="p-4 rounded-lg bg-status-danger-bg text-xs text-status-danger border border-status-danger-border">
            {error instanceof Error ? error.message : "Failed to load invitations"}
          </div>
        ) : invites.length === 0 ? (
          <div className="py-8 text-center text-sm text-text-muted border border-dashed border-border-default rounded-lg">
            No invitations created yet. Click "Create Invitation" to generate one.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border-default bg-surface-page text-text-muted uppercase">
                <tr>
                  <th className="px-4 py-3 font-semibold">Token Prefix</th>
                  <th className="px-4 py-3 font-semibold">Bound Email</th>
                  <th className="px-4 py-3 font-semibold">Global Role</th>
                  <th className="px-4 py-3 font-semibold">Server / Role</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Expires</th>
                  <th className="px-4 py-3 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {invites.map((invite: InvitationItem) => (
                  <tr key={invite.invite_id} className="hover:bg-surface-hover transition-colors">
                    <td className="px-4 py-3 font-mono font-medium text-text-primary">
                      {invite.token_prefix}...
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {invite.email || <span className="text-text-muted italic">Any email</span>}
                    </td>
                    <td className="px-4 py-3 capitalize font-medium text-text-primary">
                      {invite.global_role}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {invite.server_id ? `${invite.server_id} (${invite.server_role || "member"})` : "-"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase border ${
                          invite.status === "ACTIVE"
                            ? "bg-status-success-bg text-status-success border-status-success-border"
                            : invite.status === "USED"
                            ? "bg-status-info-bg text-status-info border-status-info-border"
                            : "bg-surface-elevated text-text-muted border-border-default"
                        }`}
                      >
                        {invite.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-text-muted">
                      {invite.expires_at ? (parseServerDate(invite.expires_at)?.toLocaleString() ?? "Never") : "Never"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {invite.status === "ACTIVE" && (
                        <button
                          type="button"
                          onClick={() => revokeMutation.mutate(invite.invite_id)}
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
      </div>

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
          {formError && (
            <div role="alert" className="p-3 text-xs text-status-danger bg-status-danger-bg border border-status-danger-border rounded-lg">
              {formError}
            </div>
          )}

          <form onSubmit={handleCreateSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">
                Bound Email (Optional)
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Restrict to specific email address"
                className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-accent-primary focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="globalRole" className="block text-sm font-medium text-text-secondary mb-1">
                Global Access Role
              </label>
              <select
                id="globalRole"
                value={globalRole}
                onChange={(e) => setGlobalRole(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-accent-primary focus:outline-none"
              >
                {grantableGlobalRoles.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Server Access (Optional) */}
            <div className="border-t border-border-default pt-4 space-y-3">
              <label className="block text-sm font-medium text-text-secondary">
                Server Access (Optional)
              </label>
              <div>
                <select
                  id="serverId"
                  aria-label="Server Access"
                  value={serverId}
                  onChange={(e) => setServerId(e.target.value)}
                  disabled={isLoadingServers}
                  className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-accent-primary focus:outline-none disabled:opacity-50"
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
                    className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-accent-primary focus:outline-none"
                  >
                    <option value="viewer">Server Viewer</option>
                    <option value="dev">Developer</option>
                    <option value="admin">Server Administrator</option>
                  </select>
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">
                Expiration (Hours)
              </label>
              <input
                type="number"
                min={1}
                max={720}
                value={expiresInHours}
                onChange={(e) => setExpiresInHours(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-accent-primary focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                disabled={createMutation.isPending}
                className="px-4 py-2 rounded-lg border border-border-default text-sm font-medium text-text-secondary hover:bg-surface-hover disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createMutation.isPending}
                className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-sm font-medium text-accent-contrast-text disabled:opacity-50 cursor-pointer"
              >
                {createMutation.isPending ? "Generating..." : "Generate Invitation"}
              </button>
            </div>
          </form>
        </div>
      </Modal>
    </div>
  );
}
