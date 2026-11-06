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
  const [copied, setCopied] = useState(false);

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

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    toast("info", "Copied", "Link copied to clipboard!");
    setTimeout(() => setCopied(false), 2000);
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
      <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              Invitations Management
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Create and manage invitation links to invite new users to this instance.
            </p>
          </div>
          <button
            type="button"
            onClick={openModal}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 shrink-0"
          >
            <Icon name="plus" size={16} />
            Create Invitation
          </button>
        </div>

        {/* Display created invitation secret once */}
        {createdInvite && (
          <div className="mb-6 p-4 rounded-xl border border-green-200 bg-green-50 dark:border-green-900/40 dark:bg-green-900/20 text-green-900 dark:text-green-100 space-y-3">
            <div className="flex items-center gap-2">
              <Icon name="check" size={18} className="text-green-600 dark:text-green-400" />
              <span className="font-semibold text-sm">Invitation Link Generated!</span>
            </div>
            <p className="text-xs text-green-800 dark:text-green-300">
              This secret raw token is displayed <strong>only once</strong>. Copy the link below to share it.
            </p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={createdInvite.link}
                className="w-full px-3 py-1.5 rounded-lg border border-green-300 dark:border-green-700 bg-white dark:bg-gray-800 text-xs font-mono text-gray-900 dark:text-gray-100"
              />
              <button
                type="button"
                onClick={() => copyToClipboard(createdInvite.link)}
                className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium shrink-0 flex items-center gap-1"
              >
                <Icon name="copy" size={14} />
                {copied ? "Copied!" : "Copy Link"}
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="py-8 text-center text-sm text-gray-500">Loading invitations...</div>
        ) : isError ? (
          <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 text-xs text-red-600 dark:text-red-400">
            {error instanceof Error ? error.message : "Failed to load invitations"}
          </div>
        ) : invites.length === 0 ? (
          <div className="py-8 text-center text-sm text-gray-500 dark:text-gray-400 border border-dashed border-gray-200 dark:border-gray-700 rounded-lg">
            No invitations created yet. Click "Create Invitation" to generate one.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 uppercase">
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
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {invites.map((invite: InvitationItem) => (
                  <tr key={invite.invite_id} className="hover:bg-gray-50/50 dark:hover:bg-gray-700/50">
                    <td className="px-4 py-3 font-mono font-medium text-gray-900 dark:text-gray-100">
                      {invite.token_prefix}...
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                      {invite.email || <span className="text-gray-400 italic">Any email</span>}
                    </td>
                    <td className="px-4 py-3 capitalize font-medium text-gray-800 dark:text-gray-200">
                      {invite.global_role}
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                      {invite.server_id ? `${invite.server_id} (${invite.server_role || "member"})` : "-"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                          invite.status === "ACTIVE"
                            ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                            : invite.status === "USED"
                            ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                            : "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300"
                        }`}
                      >
                        {invite.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                      {invite.expires_at ? (parseServerDate(invite.expires_at)?.toLocaleString() ?? "Never") : "Never"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {invite.status === "ACTIVE" && (
                        <button
                          type="button"
                          onClick={() => revokeMutation.mutate(invite.invite_id)}
                          disabled={revokeMutation.isPending}
                          className="text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 font-medium hover:underline disabled:opacity-50"
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
            <div role="alert" className="p-3 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg">
              {formError}
            </div>
          )}

          <form onSubmit={handleCreateSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Bound Email (Optional)
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Restrict to specific email address"
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="globalRole" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Global Access Role
              </label>
              <select
                id="globalRole"
                value={globalRole}
                onChange={(e) => setGlobalRole(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
              >
                {grantableGlobalRoles.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Server Access (Optional) */}
            <div className="border-t border-gray-200 dark:border-gray-700 pt-4 space-y-3">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Server Access (Optional)
              </label>
              <div>
                <select
                  id="serverId"
                  aria-label="Server Access"
                  value={serverId}
                  onChange={(e) => setServerId(e.target.value)}
                  disabled={isLoadingServers}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none disabled:opacity-50"
                >
                  <option value="">[ No server access ]</option>
                  {servers.map((s: ServerResponse) => (
                    <option key={s.server_id} value={s.server_id}>
                      {s.name} ({s.server_id})
                    </option>
                  ))}
                </select>
                {serversError && (
                  <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1">
                    Server list temporarily unavailable. You can still issue global invitations.
                  </p>
                )}
              </div>

              {serverId && (
                <div>
                  <label htmlFor="serverRole" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Server Role
                  </label>
                  <select
                    id="serverRole"
                    aria-label="Server Role"
                    value={serverRole}
                    onChange={(e) => setServerRole(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                  >
                    <option value="viewer">Server Viewer</option>
                    <option value="dev">Developer</option>
                    <option value="admin">Server Administrator</option>
                  </select>
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Expiration (Hours)
              </label>
              <input
                type="number"
                min={1}
                max={720}
                value={expiresInHours}
                onChange={(e) => setExpiresInHours(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                disabled={createMutation.isPending}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createMutation.isPending}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-sm font-medium text-white disabled:opacity-50"
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
