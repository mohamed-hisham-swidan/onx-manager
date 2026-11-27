import { CAPABILITY_OPTIONS } from "@/hooks/useAuthPermissions";
import type { CanonicalRole } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

interface RoleOption {
  value: CanonicalRole;
  label: string;
  description: string;
}

const ROLE_OPTIONS: RoleOption[] = [
  {
    value: "viewer",
    label: "Viewer",
    description:
      "Read-only access to assigned servers (logs, metrics, read-only panels). Never mutates state.",
  },
  {
    value: "server_admin",
    label: "Server Admin",
    description:
      "Manage assigned servers and enabled capabilities. Cannot create/delete servers, users, or global settings.",
  },
  {
    value: "admin",
    label: "Administrator",
    description:
      "Full access to all servers, server creation/deletion, global settings, and non-Owner user management.",
  },
  {
    value: "owner",
    label: "Owner",
    description:
      "Unrestricted instance control including panel exposure tunnels, Playit host agent, and Owner accounts.",
  },
];

export interface RoleScopeSelectorProps {
  role: CanonicalRole;
  onRoleChange: (role: CanonicalRole) => void;
  allowOwner: boolean;
  allServersAccess: boolean;
  onAllServersAccessChange: (value: boolean) => void;
  serverIds: string[];
  onServerIdsChange: (ids: string[]) => void;
  deniedPermissions: string[];
  onDeniedPermissionsChange: (denied: string[]) => void;
  servers: ServerResponse[];
  isLoadingServers?: boolean;
  serversError?: boolean;
  disabled?: boolean;
}

export function RoleScopeSelector({
  role,
  onRoleChange,
  allowOwner,
  allServersAccess,
  onAllServersAccessChange,
  serverIds,
  onServerIdsChange,
  deniedPermissions,
  onDeniedPermissionsChange,
  servers,
  isLoadingServers = false,
  serversError = false,
  disabled = false,
}: RoleScopeSelectorProps) {
  const visibleRoles = allowOwner
    ? ROLE_OPTIONS
    : ROLE_OPTIONS.filter((opt) => opt.value !== "owner");

  const isGlobalRole = role === "owner" || role === "admin";
  const deniedSet = new Set(deniedPermissions);

  const toggleServer = (id: string) => {
    if (serverIds.includes(id)) {
      onServerIdsChange(serverIds.filter((s) => s !== id));
    } else {
      onServerIdsChange([...serverIds, id]);
    }
  };

  const toggleCapability = (key: string) => {
    if (deniedSet.has(key)) {
      onDeniedPermissionsChange(deniedPermissions.filter((k) => k !== key));
    } else {
      onDeniedPermissionsChange([...deniedPermissions, key]);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <span className="mb-1.5 block text-xs font-medium text-text-secondary">
          Account Role
        </span>
        <div
          role="radiogroup"
          aria-label="Account Role"
          className="grid grid-cols-1 sm:grid-cols-2 gap-2"
        >
          {visibleRoles.map((opt) => {
            const selected = role === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => onRoleChange(opt.value)}
                className={`text-left rounded-lg border p-2.5 sm:p-3 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed ${
                  selected
                    ? "border-accent-primary bg-accent-primary/10"
                    : "border-border-subtle bg-surface-muted hover:border-border-hover"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-text-primary">
                    {opt.label}
                  </span>
                  {selected && (
                    <span className="inline-flex h-2 w-2 rounded-full bg-accent-primary shrink-0" />
                  )}
                </div>
                <p className="mt-1 text-xs leading-snug text-text-secondary">
                  {opt.description}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      {isGlobalRole ? (
        <div className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2.5 text-xs text-text-secondary">
          {role === "owner"
            ? "Owner automatically receives unrestricted access across all current and future servers, global panel settings, remote exposure, and host controls."
            : "Administrator automatically receives full access across all current and future servers, server lifecycle management, global settings, and non-Owner users."}
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-border-subtle bg-surface-muted p-2.5 sm:p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                Server Access
              </span>
              {!allServersAccess && servers.length > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onServerIdsChange(servers.map((s) => s.server_id))}
                    className="font-medium text-text-accent hover:underline cursor-pointer disabled:opacity-50"
                  >
                    Select All
                  </button>
                  <span className="text-border-subtle">·</span>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onServerIdsChange([])}
                    className="font-medium text-text-secondary hover:text-text-primary hover:underline cursor-pointer disabled:opacity-50"
                  >
                    Clear
                  </button>
                </div>
              )}
            </div>

            <label className="flex items-center gap-2 text-sm text-text-primary cursor-pointer">
              <input
                type="checkbox"
                checked={allServersAccess}
                disabled={disabled}
                onChange={(e) => onAllServersAccessChange(e.target.checked)}
                className="h-4 w-4 rounded border-border-default accent-accent-primary shrink-0"
              />
              <span>Grant access to all servers (current &amp; future)</span>
            </label>

            {!allServersAccess && (
              <div className="max-h-40 overflow-y-auto overscroll-contain space-y-1.5 pt-1">
                {isLoadingServers ? (
                  <p className="text-xs text-text-muted">Loading servers...</p>
                ) : serversError ? (
                  <p className="text-xs text-status-warning">
                    Server list temporarily unavailable. Save without specific server selection or retry later.
                  </p>
                ) : servers.length === 0 ? (
                  <p className="text-xs text-text-muted">
                    No servers exist yet. Enable &quot;all servers&quot; or create a server first.
                  </p>
                ) : (
                  servers.map((srv) => {
                    const checked = serverIds.includes(srv.server_id);
                    return (
                      <label
                        key={srv.server_id}
                        className="flex items-center justify-between gap-2 rounded-md border border-border-subtle bg-surface-card px-2.5 py-1.5 text-xs cursor-pointer hover:bg-surface-hover"
                      >
                        <span className="flex items-center gap-2 min-w-0">
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={disabled}
                            onChange={() => toggleServer(srv.server_id)}
                            className="h-3.5 w-3.5 rounded border-border-default accent-accent-primary shrink-0"
                          />
                          <span className="truncate font-medium text-text-primary">
                            {srv.name}
                          </span>
                        </span>
                        <span className="shrink-0 font-mono text-[11px] text-text-muted">
                          {srv.minecraft_version || srv.server_type || srv.server_id.slice(0, 8)}
                        </span>
                      </label>
                    );
                  })
                )}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-border-subtle bg-surface-muted p-2.5 sm:p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                {role === "viewer" ? "Read-Only Capabilities" : "Server Capabilities"}
              </span>
              <span className="text-[11px] text-text-muted">
                {role === "viewer"
                  ? "Mutations are locked off for Viewers"
                  : "Uncheck any capability to restrict"}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {CAPABILITY_OPTIONS.map((cap) => {
                const lockedOff = role === "viewer" && !cap.viewerSupported;
                const enabled = !lockedOff && !deniedSet.has(cap.key);
                const title = role === "viewer" ? cap.viewerLabel : cap.label;
                const description =
                  role === "viewer" ? cap.viewerDescription : cap.description;

                return (
                  <label
                    key={cap.key}
                    className={`flex items-start gap-2 rounded-md border border-border-subtle p-2 sm:px-2.5 sm:py-2 text-xs ${
                      lockedOff
                        ? "bg-surface-page/40 opacity-60 cursor-not-allowed"
                        : "bg-surface-card hover:bg-surface-hover cursor-pointer"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={enabled}
                      disabled={disabled || lockedOff}
                      onChange={() => !lockedOff && toggleCapability(cap.key)}
                      className="mt-0.5 h-3.5 w-3.5 rounded border-border-default accent-accent-primary shrink-0"
                    />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-medium text-text-primary">{title}</span>
                        {lockedOff && (
                          <span className="rounded bg-surface-muted px-1 py-0.5 text-[10px] text-text-muted">
                            Read-only
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-text-muted leading-tight mt-0.5">
                        {description}
                      </p>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
