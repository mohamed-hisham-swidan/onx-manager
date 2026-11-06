import { useState } from "react";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/server_manager/hooks/useApiKeys";
import { TableSkeleton } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useClipboard } from "@/hooks/useClipboard";
import { parseServerDate } from "@/server_manager/utils/format";

export function ApiKeysPage() {
  const { data: apiKeys, isLoading, error } = useApiKeys();
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();
  const { copy } = useClipboard();
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; name: string } | null>(null);

  const handleCreate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFormError(null);
    setNewKeyValue(null);
    const form = new FormData(e.currentTarget);
    const name = form.get("name") as string;
    if (!name) { setFormError("Name is required."); return; }
    try {
      const result = await createApiKey.mutateAsync({ name });
      if (result.key) setNewKeyValue(result.key);
      setShowCreate(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create API key");
    }
  };

  const handleRevoke = () => {
    if (!revokeTarget) return;
    revokeApiKey.mutate(revokeTarget.id);
    setRevokeTarget(null);
  };

  return (
    <div>
      <PageHeader
        title="API Keys"
        description="Manage programmatic access to the API"
        icon="settings"
        actions={
          <button
            onClick={() => { setShowCreate(!showCreate); setNewKeyValue(null); }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover cursor-pointer"
          >
            <Icon name="plus" size={16} />
            {showCreate ? "Cancel" : "Create API Key"}
          </button>
        }
      />

      {isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : (
        <>
      {error && (
        <ErrorState className="mb-6" message={error instanceof Error ? error.message : "Failed to load API keys"} />
      )}

      {showCreate && (
        <form onSubmit={handleCreate} className="mb-6 space-y-3 rounded-xl border border-border-default bg-surface-card p-4">
          <h3 className="font-semibold text-text-primary">Create API Key</h3>
          <input
            name="name"
            placeholder="Key name (e.g. CI/CD)"
            required
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
          />
          {formError && <p className="text-sm text-status-danger">{formError}</p>}
          <button
            type="submit"
            disabled={createApiKey.isPending}
            className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50 cursor-pointer"
          >
            {createApiKey.isPending ? "Creating..." : "Create"}
          </button>
        </form>
      )}

      {newKeyValue && (
        <div className="mb-6 rounded-xl border border-status-warning-border bg-status-warning-bg p-4">
          <p className="mb-2 text-sm font-semibold text-status-warning">
            This is the only time the key value will be shown. Copy it now.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-surface-page border border-status-warning-border rounded text-sm font-mono break-all text-text-primary">
              {newKeyValue}
            </code>
            <button
              onClick={() => copy(newKeyValue, "API key copied to clipboard")}
              className="px-3 py-2 rounded bg-surface-elevated text-text-primary text-sm font-medium hover:bg-surface-hover transition-colors border border-border-default cursor-pointer"
            >
              Copy
            </button>
          </div>
        </div>
      )}

      {!error && apiKeys && apiKeys.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-border-default bg-surface-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-default bg-surface-page">
                <th className="text-left px-4 py-3 font-medium text-text-muted">Name</th>
                <th className="text-left px-4 py-3 font-medium text-text-muted">Prefix</th>
                <th className="hidden px-4 py-3 font-medium text-text-muted sm:table-cell">Created</th>
                <th className="text-left px-4 py-3 font-medium text-text-muted">Status</th>
                <th className="text-right px-4 py-3 font-medium text-text-muted">Actions</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((k) => (
                <tr key={k.api_key_id} className="border-b border-border-subtle hover:bg-surface-hover">
                  <td className="px-4 py-3 font-medium text-text-primary">{k.name}</td>
                  <td className="px-4 py-3 font-mono text-text-muted">{k.prefix}...</td>
                  <td className="hidden px-4 py-3 text-text-muted sm:table-cell">{parseServerDate(k.created_at)?.toLocaleDateString() ?? "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                      k.is_revoked
                        ? "bg-status-danger-bg text-status-danger border-status-danger-border"
                        : "bg-status-success-bg text-status-success border-status-success-border"
                    }`}>
                      <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
                      {k.is_revoked ? "Revoked" : "Active"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!k.is_revoked && (
                      <button
                        onClick={() => setRevokeTarget({ id: k.api_key_id, name: k.name })}
                        disabled={revokeApiKey.isPending}
                        aria-label={`Revoke ${k.name}`}
                        title="Revoke"
                        className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                      >
                        <Icon name="x" size={16} />
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
          <EmptyState
            icon="settings"
            title="No API keys"
            description="Create an API key for programmatic access."
            action={
              <button
                onClick={() => setShowCreate(true)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover cursor-pointer"
              >
                <Icon name="plus" size={16} />
                Create API Key
              </button>
            }
          />
        )
      )}
      </>
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
