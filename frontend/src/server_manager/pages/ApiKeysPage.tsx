import { useState } from "react";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/server_manager/hooks/useApiKeys";
import { TableSkeleton } from "@/components/Skeleton";
import { EmptyState } from "@/components/EmptyState";

export function ApiKeysPage() {
  const { data: apiKeys, isLoading, error } = useApiKeys();
  const createApiKey = useCreateApiKey();
  const revokeApiKey = useRevokeApiKey();
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

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

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch { /* clipboard not available */ }
  };

  if (isLoading) return <TableSkeleton rows={4} cols={4} />;

  if (error) {
    return (
      <p className="text-red-600 dark:text-red-400">
        {error instanceof Error ? error.message : "Failed to load API keys"}
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">API Keys</h2>
        <button
          onClick={() => { setShowCreate(!showCreate); setNewKeyValue(null); }}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
        >
          {showCreate ? "Cancel" : "+ Create API Key"}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 mb-6 space-y-3">
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
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-700 rounded-xl p-4 mb-6">
          <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-300 mb-2">
            This is the only time the key value will be shown. Copy it now.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-white dark:bg-gray-800 border border-yellow-300 dark:border-yellow-700 rounded text-sm font-mono break-all">
              {newKeyValue}
            </code>
            <button
              onClick={() => copyToClipboard(newKeyValue)}
              className="px-3 py-2 rounded bg-yellow-100 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200 text-sm font-medium hover:bg-yellow-200 dark:hover:bg-yellow-700 transition-colors"
            >
              Copy
            </button>
          </div>
        </div>
      )}

      {apiKeys && apiKeys.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Prefix</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Created</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((k) => (
                <tr key={k.api_key_id} className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="px-4 py-3 text-gray-900 dark:text-gray-100 font-medium">{k.name}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400 font-mono">{k.prefix}...</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{new Date(k.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      k.is_revoked
                        ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                        : "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                    }`}>
                      {k.is_revoked ? "Revoked" : "Active"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!k.is_revoked && (
                      <button
                        onClick={() => {
                          if (confirm(`Revoke API key "${k.name}"? This cannot be undone.`))
                            revokeApiKey.mutate(k.api_key_id);
                        }}
                        disabled={revokeApiKey.isPending}
                        className="px-2 py-1 text-xs rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50"
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
      ) : (
        <EmptyState
          icon="⚙"
          title="No API keys"
          description="Create an API key for programmatic access."
          action={
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
            >
              + Create API Key
            </button>
          }
        />
      )}
    </div>
  );
}
