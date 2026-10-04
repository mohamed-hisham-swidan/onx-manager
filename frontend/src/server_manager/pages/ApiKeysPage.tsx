import { useState } from "react";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/server_manager/hooks/useApiKeys";
import { TableSkeleton } from "@/components/Skeleton";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
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
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
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
        <form onSubmit={handleCreate} className="mb-6 space-y-3 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Create API Key</h3>
          <input
            name="name"
            placeholder="Key name (e.g. CI/CD)"
            required
            className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
          <button
            type="submit"
            disabled={createApiKey.isPending}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            {createApiKey.isPending ? "Creating..." : "Create"}
          </button>
        </form>
      )}

      {newKeyValue && (
        <div className="mb-6 rounded-xl border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-700 dark:bg-yellow-900/20">
          <p className="mb-2 text-sm font-semibold text-yellow-800 dark:text-yellow-300">
            This is the only time the key value will be shown. Copy it now.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-white dark:bg-gray-800 border border-yellow-300 dark:border-yellow-700 rounded text-sm font-mono break-all">
              {newKeyValue}
            </code>
            <button
              onClick={() => copy(newKeyValue, "API key copied to clipboard")}
              className="px-3 py-2 rounded bg-yellow-100 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200 text-sm font-medium hover:bg-yellow-200 dark:hover:bg-yellow-700 transition-colors"
            >
              Copy
            </button>
          </div>
        </div>
      )}

      {!error && apiKeys && apiKeys.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Prefix</th>
                <th className="hidden px-4 py-3 font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Created</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((k) => (
                <tr key={k.api_key_id} className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30">
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{k.name}</td>
                  <td className="px-4 py-3 font-mono text-gray-600 dark:text-gray-400">{k.prefix}...</td>
                  <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 sm:table-cell">{parseServerDate(k.created_at)?.toLocaleDateString() ?? "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      k.is_revoked
                        ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                        : "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
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
                        className="rounded-lg p-1.5 text-red-600 transition-colors hover:bg-red-100 hover:text-red-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-900/30 dark:hover:text-red-300"
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
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
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
