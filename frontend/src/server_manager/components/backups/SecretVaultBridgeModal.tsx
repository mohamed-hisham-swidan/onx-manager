import { Link } from "react-router-dom";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import type { ServerResponse } from "@/server_manager/types";

export interface SecretVaultBridgeModalProps {
  open: boolean;
  onClose: () => void;
  servers: ServerResponse[];
  scopedServerId?: string;
}

export function SecretVaultBridgeModal({
  open,
  onClose,
  servers,
  scopedServerId,
}: SecretVaultBridgeModalProps) {
  const advancedServers = servers.filter(
    (s) => s.mode === "advanced" && (!scopedServerId || s.server_id === scopedServerId),
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Secret Vault"
      description="Manage encrypted secrets and live data snapshots for Advanced servers."
      size="md"
    >
      {advancedServers.length > 0 ? (
        <div className="space-y-2.5">
          {advancedServers.map((s) => {
            const isOnline = s.status === "running";
            return (
              <div
                key={s.server_id}
                className="flex items-center justify-between gap-3 rounded-xl border border-border-subtle bg-surface-page px-3.5 py-2.5"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <span
                    className={`h-2 w-2 rounded-full shrink-0 ${
                      isOnline ? "bg-status-success" : "bg-text-muted/50"
                    }`}
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-text-primary truncate">
                      {s.name}
                    </div>
                    <div className="text-xs text-text-muted">
                      Minecraft {s.minecraft_version}
                    </div>
                  </div>
                </div>
                <Link
                  to={`/servers/${s.server_id}/versioning?openVault=true`}
                  onClick={onClose}
                  className="inline-flex items-center gap-1 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shrink-0"
                >
                  <span>Open Vault</span>
                  <Icon name="chevron-right" size={13} />
                </Link>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-border-subtle bg-surface-page p-4 text-sm text-text-secondary">
            No Advanced-mode servers found. Convert a server to Advanced mode to use the Secret Vault.
          </div>
          <div className="flex justify-end">
            <Link
              to="/servers"
              onClick={onClose}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover"
            >
              <span>Go to Servers</span>
              <Icon name="chevron-right" size={13} />
            </Link>
          </div>
        </div>
      )}
    </Modal>
  );
}
