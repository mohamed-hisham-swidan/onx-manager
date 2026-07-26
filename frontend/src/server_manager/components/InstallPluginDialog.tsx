import { useState } from "react";
import { useInstallPlugin } from "@/server_manager/hooks/usePlugins";

interface InstallPluginDialogProps {
  serverId: string;
  onDone: () => void;
}

export function InstallPluginDialog({ serverId, onDone }: InstallPluginDialogProps) {
  const installPlugin = useInstallPlugin(serverId);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const form = new FormData(e.currentTarget);
    const name = form.get("name") as string;
    const version = form.get("version") as string;
    const description = form.get("description") as string;
    const author = form.get("author") as string;
    if (!name || !version) { setError("Name and version are required."); return; }
    try {
      await installPlugin.mutateAsync({ server_id: serverId, name, version, description: description || undefined, author: author || undefined });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to install plugin");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100">Install Plugin</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <input
          name="name"
          placeholder="Plugin name"
          required
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input
          name="version"
          placeholder="Version (e.g. 1.0.0)"
          required
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input
          name="description"
          placeholder="Description (optional)"
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input
          name="author"
          placeholder="Author (optional)"
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={installPlugin.isPending}
        className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
      >
        {installPlugin.isPending ? "Installing..." : "Install"}
      </button>
    </form>
  );
}
