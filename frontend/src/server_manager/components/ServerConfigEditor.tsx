import { useState } from "react";
import { useUpdateServer } from "@/server_manager/hooks/useServers";
import type { ServerDetailResponse } from "@/server_manager/types";

interface ServerConfigEditorProps {
  serverId: string;
  server: ServerDetailResponse;
}

export function ServerConfigEditor({ serverId, server }: ServerConfigEditorProps) {
  const updateServer = useUpdateServer();
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setMessage(null);
    const form = new FormData(e.currentTarget);

    const properties: Record<string, unknown> = {};
    const motd = form.get("motd") as string;
    const maxPlayers = form.get("max_players") as string;
    const difficulty = form.get("difficulty") as string;
    const gamemode = form.get("gamemode") as string;
    const pvp = form.get("pvp") as string;
    const whitelist = form.get("whitelist") as string;

    if (motd) properties.motd = motd;
    if (maxPlayers) properties.max_players = Number(maxPlayers);
    if (difficulty) properties.difficulty = difficulty;
    if (gamemode) properties.gamemode = gamemode;
    if (pvp) properties.pvp = pvp === "true";
    if (whitelist) properties.whitelist = whitelist === "true";

    try {
      await updateServer.mutateAsync({
        serverId,
        body: {
          properties,
          min_memory_mb: Number(form.get("min_memory_mb")) || null,
          max_memory_mb: Number(form.get("max_memory_mb")) || null,
        },
      });
      setMessage({ type: "success", text: "Configuration saved successfully." });
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Failed to save configuration." });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Min Memory (MB)</label>
          <input
            name="min_memory_mb"
            type="number"
            defaultValue={server.min_memory_mb}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Max Memory (MB)</label>
          <input
            name="max_memory_mb"
            type="number"
            defaultValue={server.max_memory_mb}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">MOTD</label>
          <input
            name="motd"
            defaultValue={server.motd}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Max Players</label>
          <input
            name="max_players"
            type="number"
            defaultValue={server.max_players}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Gamemode</label>
          <select
            name="gamemode"
            defaultValue={server.gamemode}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          >
            <option value="survival">Survival</option>
            <option value="creative">Creative</option>
            <option value="adventure">Adventure</option>
            <option value="spectator">Spectator</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Difficulty</label>
          <select
            name="difficulty"
            defaultValue={server.difficulty}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          >
            <option value="peaceful">Peaceful</option>
            <option value="easy">Easy</option>
            <option value="normal">Normal</option>
            <option value="hard">Hard</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">PVP</label>
          <select
            name="pvp"
            defaultValue={server.pvp ? "true" : "false"}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          >
            <option value="true">Enabled</option>
            <option value="false">Disabled</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Whitelist</label>
          <select
            name="whitelist"
            defaultValue={server.whitelist ? "true" : "false"}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm focus:outline-none focus:ring-2 focus:ring-border-focus text-text-primary"
          >
            <option value="true">Enabled</option>
            <option value="false">Disabled</option>
          </select>
        </div>
      </div>

      {message && (
        <p className={`text-sm ${message.type === "success" ? "text-status-success" : "text-status-danger"}`}>
          {message.text}
        </p>
      )}

      <button
        type="submit"
        disabled={updateServer.isPending}
        className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50"
      >
        {updateServer.isPending ? "Saving..." : "Save Configuration"}
      </button>
    </form>
  );
}
