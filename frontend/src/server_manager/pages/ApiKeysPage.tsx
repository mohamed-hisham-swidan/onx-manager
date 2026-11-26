import { useState } from "react";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/server_manager/hooks/useApiKeys";
import { TableSkeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useClipboard } from "@/hooks/useClipboard";
import { toast } from "@/stores/toastStore";
import { parseServerDate } from "@/server_manager/utils/format";
import { useSettingsPermissions } from "@/server_manager/components/settings/settingsModel";

export function ApiKeysPage() {
  const { data: apiKeys, isLoading, error } = useApiKeys();
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();
  const { copy } = useClipboard();
  const { canManageApiKeys } = useSettingsPermissions();

  const [showCreate, setShowCreate] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; name: string } | null>(null);
  const hasKeys = Boolean(apiKeys && apiKeys.length > 0);
  const showHeaderAction = !isLoading && !error && (hasKeys || showCreate);

  const handleCreate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!canManageApiKeys) return;
    setFormError(null);
    setNewKeyValue(null);
    const trimmed = keyName.trim();
    if (!trimmed) {
      setFormError("Key name is required.");
      return;
    }
    try {
      const result = await createApiKey.mutateAsync({ name: trimmed });
      if (result.key) setNewKeyValue(result.key);
      setKeyName("");
      setShowCreate(false);
      toast("success", "API key created", "Copy this key now — it won't be shown again.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create API key";
      setFormError(msg);
      toast("error", "Failed to create key", msg);
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    const target = revokeTarget;
    setRevokeTarget(null);
    try {
      await revokeApiKey.mutateAsync(target.id);
      toast("success", "API key revoked", `"${target.name}" has been deactivated.`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to revoke API key";
      toast("error", "Failed to revoke key", msg);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">API Keys</h2>
          <p className="text-sm text-text-muted mt-0.5">
            Tokens for Discord bots, scripts, and CI/CD.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!canManageApiKeys && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle bg-surface-muted px-3 py-1 text-xs font-medium text-text-muted">
              <Icon name="lock" size={12} />
              Read-only access
            </span>
          )}
          {showHeaderAction && (
            <Button
              type="button"
              variant={showCreate ? "outline" : "primary"}
              size="sm"
              icon={showCreate ? "x" : "plus"}
              disabled={!canManageApiKeys}
              onClick={() => {
                setShowCreate((prev) => !prev);
                setFormError(null);
              }}
            >
              {showCreate ? "Cancel" : "Create Key"}
            </Button>
          )}
        </div>
      </div>

      {isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : (
        <div className="space-y-4">
          {error && (
            <ErrorState message={error instanceof Error ? error.message : "Failed to load API keys"} />
          )}

          {showCreate && (
            <form
              onSubmit={handleCreate}
              className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs space-y-3"
            >
              <div className="flex flex-col sm:flex-row sm:items-center gap-2.5">
                <input
                  name="name"
                  aria-label="Key Name"
                  value={keyName}
                  onChange={(e) => {
                    setFormError(null);
                    setKeyName(e.target.value);
                  }}
                  placeholder="Key name (e.g. Discord Bot or GitHub Actions)"
                  required
                  className="flex-1 px-3 py-2 rounded-lg border border-border-subtle bg-surface-page text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
                />
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  loading={createApiKey.isPending}
                >
                  {createApiKey.isPending ? "Creating..." : "Create"}
                </Button>
              </div>
              {formError && <p className="text-xs text-status-danger">{formError}</p>}
            </form>
          )}

          {newKeyValue && (
            <div className="rounded-xl border border-status-warning-border bg-status-warning-bg p-4 space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-status-warning">
                  Copy this key now — it won&apos;t be shown again.
                </p>
                <button
                  type="button"
                  onClick={() => setNewKeyValue(null)}
                  aria-label="Dismiss new key"
                  className="rounded p-1 text-text-muted hover:text-text-primary cursor-pointer"
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 px-3 py-2 bg-surface-page border border-border-subtle rounded-lg text-xs font-mono break-all text-text-primary">
                  {newKeyValue}
                </code>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  icon="copy"
                  onClick={() => copy(newKeyValue, "API key copied to clipboard")}
                >
                  Copy
                </Button>
              </div>
            </div>
          )}

          {!error && apiKeys && apiKeys.length > 0 ? (
            <div className="overflow-x-auto rounded-xl border border-border-subtle bg-surface-card shadow-2xs">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-subtle bg-surface-page/70 text-text-muted">
                    <th className="text-left px-4 py-2.5 font-medium">Name</th>
                    <th className="text-left px-4 py-2.5 font-medium">Prefix</th>
                    <th className="hidden px-4 py-2.5 font-medium sm:table-cell">Created</th>
                    <th className="text-left px-4 py-2.5 font-medium">Status</th>
                    <th className="text-right px-4 py-2.5 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {apiKeys.map((k) => (
                    <tr key={k.api_key_id} className="hover:bg-surface-hover/50 transition-colors">
                      <td className="px-4 py-3 font-medium text-text-primary">{k.name}</td>
                      <td className="px-4 py-3 font-mono text-text-muted">{k.prefix}...</td>
                      <td className="hidden px-4 py-3 text-text-muted sm:table-cell">
                        {parseServerDate(k.created_at)?.toLocaleDateString() ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border ${
                            k.is_revoked
                              ? "bg-status-danger-bg text-status-danger border-status-danger-border"
                              : "bg-status-success-bg text-status-success border-status-success-border"
                          }`}
                        >
                          {k.is_revoked ? "Revoked" : "Active"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {!k.is_revoked && (
                          <button
                            type="button"
                            onClick={() => setRevokeTarget({ id: k.api_key_id, name: k.name })}
                            disabled={!canManageApiKeys || revokeApiKey.isPending}
                            aria-label={`Revoke ${k.name}`}
                            title="Revoke"
                            className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer"
                          >
                            <Icon name="x" size={15} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            !error && (
              <div className="rounded-xl border border-border-subtle bg-surface-card p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs">
                <div>
                  <p className="text-sm font-medium text-text-primary">No API keys</p>
                  <p className="text-xs text-text-muted mt-0.5">
                    Create a token for automated scripts or bots.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  icon="plus"
                  disabled={!canManageApiKeys}
                  onClick={() => setShowCreate(true)}
                >
                  Create Key
                </Button>
              </div>
            )
          )}
        </div>
      )}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke API key?"
        description={
          revokeTarget
            ? `This immediately revokes "${revokeTarget.name}" and cannot be undone.`
            : undefined
        }
        confirmLabel="Revoke"
        onConfirm={handleRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
