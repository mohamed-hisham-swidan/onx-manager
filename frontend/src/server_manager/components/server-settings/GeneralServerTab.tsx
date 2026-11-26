import React, { useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { ServerIcon } from "@/server_manager/components/ServerIcon";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import type { ServerDetailResponse } from "@/server_manager/types";
import { NumberStepper, SettingsCard, SettingsRow } from "./ServerSettingsControls";
import {
  PORT_MAX,
  PORT_MIN,
  type NumericDraftKey,
  type ServerSettingsFormState,
  type ServerValidationErrors,
} from "./serverSettingsModel";

const MAX_ICON_BYTES = 1024 * 1024; // 1 MiB

export interface GeneralServerTabProps {
  serverId: string;
  server: ServerDetailResponse;
  form: ServerSettingsFormState;
  rawDrafts: Partial<Record<NumericDraftKey, string>>;
  errors: ServerValidationErrors;
  disabled: boolean;
  gitBacked: boolean;
  isMainBranch: boolean;
  isWorkingBranch: boolean;
  activeBranch?: string;
  onUpdateForm: (patch: Partial<ServerSettingsFormState>) => void;
  onNumericChange: (key: NumericDraftKey, raw: string) => void;
  onNumericBlur: (key: NumericDraftKey) => void;
  onNumericStep: (key: NumericDraftKey, delta: number) => void;
}

export function GeneralServerTab({
  serverId,
  server,
  form,
  rawDrafts,
  errors,
  disabled,
  gitBacked,
  isMainBranch,
  isWorkingBranch,
  activeBranch,
  onUpdateForm,
  onNumericChange,
  onNumericBlur,
  onNumericStep,
}: GeneralServerTabProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isUploadingIcon, setIsUploadingIcon] = useState(false);

  const iconUploadBlockedOnMain = gitBacked && isMainBranch;
  const canUploadIcon = !disabled && !iconUploadBlockedOnMain;

  const handleIconSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    const isPng =
      file.type === "image/png" || file.name.toLowerCase().endsWith(".png");
    if (!isPng) {
      toast("error", "Invalid icon format", "Please choose a PNG file.");
      return;
    }
    if (file.size > MAX_ICON_BYTES) {
      toast("error", "Icon too large", "Server icon must be 1 MiB or smaller.");
      return;
    }
    if (typeof api.uploadServerFile !== "function") {
      toast("error", "Upload unavailable", "File upload API is not available.");
      return;
    }

    setIsUploadingIcon(true);
    try {
      const iconFile = new File([file], "server-icon.png", { type: "image/png" });
      await api.uploadServerFile(
        serverId,
        "",
        iconFile,
        isWorkingBranch ? activeBranch : undefined,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.servers.detail(serverId, activeBranch),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.servers.all }),
        queryClient.invalidateQueries({
          queryKey: ["servers", serverId, "server-icon"],
        }),
      ]);
      toast("success", "Server icon updated", "Saved server-icon.png.");
    } catch (err) {
      toast(
        "error",
        "Icon upload failed",
        err instanceof Error ? err.message : "Failed to upload server icon",
      );
    } finally {
      setIsUploadingIcon(false);
    }
  };

  const previewMotd = stripMinecraftFormatting(form.motd || "A Minecraft Server");

  return (
    <div className="space-y-6" data-testid="server-settings-tab-general">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-text-primary">
          General
        </h2>
        <p className="text-xs text-text-muted">
          Server identity, description, icon, and game port.
        </p>
      </header>

      <SettingsCard title="Identity">
        <SettingsRow
          id="srv-setting-icon"
          label="Server Icon"
          description="64×64 PNG shown in multiplayer server lists."
        >
          <div className="flex flex-col items-start sm:items-end gap-1.5 w-full">
            <div className="flex items-center gap-3">
              <ServerIcon
                serverId={serverId}
                serverName={form.name || server.name}
                serverType={server.server_type}
                iconDataUrl={server.icon_data_url}
                size={48}
              />
              <input
                ref={fileInputRef}
                id="srv-setting-icon"
                type="file"
                accept="image/png,.png"
                disabled={!canUploadIcon || isUploadingIcon}
                onChange={handleIconSelected}
                className="sr-only"
                aria-label="Upload PNG server icon"
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                icon="upload"
                loading={isUploadingIcon}
                disabled={!canUploadIcon}
                onClick={() => fileInputRef.current?.click()}
              >
                Upload PNG
              </Button>
            </div>
            {iconUploadBlockedOnMain && (
              <span className="text-[11px] text-text-muted">
                Switch to a working branch to update icon
              </span>
            )}
          </div>
        </SettingsRow>

        <SettingsRow
          id="srv-setting-name"
          label="Server Name"
          description={
            gitBacked
              ? "Server-wide label (updates immediately)."
              : "Display label shown in the fleet dashboard."
          }
        >
          <div className="w-full space-y-1">
            <input
              id="srv-setting-name"
              type="text"
              maxLength={128}
              required
              disabled={disabled}
              value={form.name}
              onChange={(e) => onUpdateForm({ name: e.target.value })}
              className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
            />
            {errors.name && (
              <p className="text-xs font-medium text-status-danger">{errors.name}</p>
            )}
          </div>
        </SettingsRow>

        <SettingsRow
          id="srv-setting-motd"
          label="MOTD"
          description="Tagline shown in the Minecraft multiplayer list."
          alignTop
        >
          <div className="w-full space-y-2">
            <input
              id="srv-setting-motd"
              type="text"
              disabled={disabled}
              value={form.motd}
              onChange={(e) => onUpdateForm({ motd: e.target.value })}
              placeholder="A Minecraft Server"
              className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
            />
            <div
              data-testid="motd-live-preview"
              className="flex items-center gap-2.5 rounded-lg border border-border-subtle bg-surface-muted px-2.5 py-2"
            >
              <ServerIcon
                serverId={serverId}
                serverName={form.name || server.name}
                serverType={server.server_type}
                iconDataUrl={server.icon_data_url}
                size={28}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-semibold text-text-primary">
                  {form.name.trim() || server.name}
                </p>
                <p className="truncate text-[11px] text-text-muted">
                  {previewMotd || "A Minecraft Server"}
                </p>
              </div>
            </div>
          </div>
        </SettingsRow>
      </SettingsCard>

      <SettingsCard title="Network Port">
        <SettingsRow
          id="srv-setting-port"
          label="Game Port"
          description={
            isWorkingBranch
              ? "Host game port is server-wide. Working branches auto-assign isolated test ports."
              : "Host TCP/UDP port players connect to. Requires restart."
          }
        >
          <div className="flex flex-col items-start sm:items-end gap-1 w-full">
            <NumberStepper
              id="srv-setting-port"
              name="server-port"
              label="Game Port"
              value={form.port}
              draftValue={rawDrafts.port}
              onChange={(val) => onNumericChange("port", val)}
              onBlur={() => onNumericBlur("port")}
              onStep={(delta) => onNumericStep("port", delta)}
              min={PORT_MIN}
              max={PORT_MAX}
              step={1}
              disabled={disabled || isWorkingBranch}
            />
            {errors.port && (
              <p className="text-xs font-medium text-status-danger">{errors.port}</p>
            )}
          </div>
        </SettingsRow>
      </SettingsCard>
    </div>
  );
}
