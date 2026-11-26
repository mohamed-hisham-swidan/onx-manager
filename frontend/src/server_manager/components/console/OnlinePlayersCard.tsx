import { useCallback, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { toast } from "@/stores/toastStore";
import { parseOnlinePlayersList, type ParsedPlayersList } from "./consoleLogParser";

export interface OnlinePlayersCardProps {
  serverId: string;
  branch?: string;
  isRunning: boolean;
  livePlayersCount: number | null;
  maxPlayers: number;
  canConsole: boolean;
}

type PendingPlayerAction = {
  type: "op" | "kick";
  player: string;
};

export function OnlinePlayersCard({
  serverId,
  branch,
  isRunning,
  livePlayersCount,
  maxPlayers,
  canConsole,
}: OnlinePlayersCardProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [roster, setRoster] = useState<ParsedPlayersList | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingPlayerAction | null>(null);

  const listMutation = useMutation({
    mutationFn: async () => {
      if (typeof api.sendServerCommand !== "function") return null;
      const res = await api.sendServerCommand(serverId, { command: "list" }, branch);
      const output = typeof res?.output === "string" ? res.output : "";
      return parseOnlinePlayersList(output);
    },
    onSuccess: (parsed) => {
      if (parsed) {
        setRoster(parsed);
      }
    },
  });

  const actionMutation = useMutation({
    mutationFn: async (action: PendingPlayerAction) => {
      const cmd =
        action.type === "op"
          ? `op ${action.player}`
          : `kick ${action.player} Kicked by server administrator`;
      return api.sendServerCommand(serverId, { command: cmd }, branch);
    },
    onSuccess: (_data, action) => {
      toast(
        "success",
        action.type === "op" ? "Operator granted" : "Player kicked",
        action.type === "op"
          ? `Granted operator privileges to ${action.player}.`
          : `Kicked ${action.player} from the server.`,
      );
      if (action.type === "kick") {
        setRoster((prev) =>
          prev
            ? {
                ...prev,
                online: Math.max(0, prev.online - 1),
                names: prev.names.filter((n) => n !== action.player),
              }
            : prev,
        );
      }
    },
    onError: (err, action) => {
      toast(
        "error",
        action.type === "op" ? "Op failed" : "Kick failed",
        err instanceof Error ? err.message : "Command failed.",
      );
    },
  });

  const refreshRoster = useCallback(() => {
    if (!isRunning || !canConsole || listMutation.isPending) return;
    listMutation.mutate();
  }, [isRunning, canConsole, listMutation]);

  const activeRoster = isRunning ? roster : null;
  const effectiveCount = isRunning ? (activeRoster?.online ?? livePlayersCount ?? 0) : 0;
  const effectiveMax = activeRoster?.max ?? maxPlayers;

  return (
    <div
      data-testid="online-players-card"
      className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs space-y-2.5"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
          <Icon name="users" size={14} className="text-accent-primary" />
          <span>Players</span>
        </h3>
        <div className="flex items-center gap-2">
          <span
            data-testid="online-players-count"
            className="font-mono text-xs font-bold tabular-nums text-text-primary"
          >
            {isRunning ? `${effectiveCount} / ${effectiveMax}` : "—"}
          </span>
          {isRunning && canConsole && (
            <button
              type="button"
              data-testid="refresh-players-btn"
              disabled={listMutation.isPending}
              onClick={refreshRoster}
              className="p-1 rounded-md text-text-muted hover:bg-surface-hover hover:text-text-primary transition-colors disabled:opacity-40 cursor-pointer"
              title="Fetch online player list via RCON"
              aria-label="Refresh online players"
            >
              <Icon name="restart" size={12} />
            </button>
          )}
        </div>
      </div>

      {!isRunning ? (
        <p className="text-xs text-text-muted">Server offline</p>
      ) : activeRoster && activeRoster.names.length > 0 ? (
        <ul className="space-y-1.5 max-h-36 overflow-y-auto pr-0.5">
          {activeRoster.names.map((player) => (
            <li
              key={player}
              className="flex items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-muted px-2.5 py-1.5 text-xs"
            >
              <span className="font-mono font-medium text-text-primary truncate">{player}</span>
              {canConsole && (
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    data-testid={`player-op-${player}`}
                    disabled={actionMutation.isPending}
                    onClick={() => setPendingAction({ type: "op", player })}
                    className="px-1.5 py-0.5 rounded border border-border-default bg-surface-card text-[10px] font-semibold text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
                    title={`Grant OP to ${player}`}
                  >
                    Op
                  </button>
                  <button
                    type="button"
                    data-testid={`player-kick-${player}`}
                    disabled={actionMutation.isPending}
                    onClick={() => setPendingAction({ type: "kick", player })}
                    className="px-1.5 py-0.5 rounded border border-status-danger-border bg-status-danger-bg text-[10px] font-semibold text-status-danger hover:opacity-90 transition-opacity cursor-pointer"
                    title={`Kick ${player}`}
                  >
                    Kick
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : effectiveCount > 0 ? (
        <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
          <span>
            {effectiveCount} {effectiveCount === 1 ? "player" : "players"} connected
          </span>
          {canConsole && (
            <button
              type="button"
              data-testid="load-players-list-btn"
              disabled={listMutation.isPending}
              onClick={refreshRoster}
              className="text-accent-primary hover:underline font-medium cursor-pointer disabled:opacity-50"
            >
              {listMutation.isPending ? "Loading..." : "Show roster"}
            </button>
          )}
        </div>
      ) : (
        <p className="text-xs text-text-muted">No players online</p>
      )}

      <ConfirmDialog
        open={Boolean(pendingAction)}
        title={
          pendingAction?.type === "op"
            ? `Grant operator to ${pendingAction.player}?`
            : `Kick ${pendingAction?.player ?? "player"}?`
        }
        description={
          pendingAction?.type === "op"
            ? `This will run "op ${pendingAction.player}" and grant full in-game operator permissions.`
            : `This will disconnect "${pendingAction?.player ?? ""}" from the server immediately.`
        }
        confirmLabel={pendingAction?.type === "op" ? "Grant Op" : "Kick Player"}
        variant={pendingAction?.type === "kick" ? "danger" : "info"}
        onConfirm={() => {
          if (pendingAction) {
            actionMutation.mutate(pendingAction);
          }
          setPendingAction(null);
        }}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}
