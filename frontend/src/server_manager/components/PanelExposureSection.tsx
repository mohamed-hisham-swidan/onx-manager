import { useState, useMemo, useRef, type KeyboardEvent } from "react";
import { usePanelExposure } from "@/server_manager/hooks/usePanelExposure";
import { PlayitClaimCard } from "@/server_manager/components/PlayitClaimCard";
import { useClipboard } from "@/hooks/useClipboard";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ConfigureCredentialsModal } from "@/components/auth/ConfigureCredentialsModal";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Skeleton } from "@/components/Skeleton";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import type { CloudflareModeType, PanelExposureMethodType, PanelExposureResponse } from "@/types";

const RESERVED_PANEL_PORTS = new Set([25575, 3306, 5432, 6379, 27017, 9090, 9100]);
const BLOCKED_PORT_KEYS = new Set(["e", "E", "+", "-", "."]);

function isPasswordRequiredError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  return (err as { code?: unknown }).code === "PASSWORD_REQUIRED_FOR_EXPOSURE";
}

function validatePortInput(raw: string): string | null {
  if (!raw.trim()) return null;
  if (!/^\d+$/.test(raw.trim())) {
    return "External port must contain digits only (1–65535).";
  }
  const num = Number(raw.trim());
  if (!Number.isInteger(num) || num < 1 || num > 65535) {
    return "External port must be between 1 and 65535.";
  }
  if (RESERVED_PANEL_PORTS.has(num)) {
    return `Port ${num} is reserved for internal services and cannot be exposed.`;
  }
  return null;
}

function validateTunnelTokenInput(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (/\s/.test(trimmed)) {
    return "Tunnel token cannot contain spaces or line breaks.";
  }
  if (trimmed.length < 12) {
    return "Tunnel token appears too short. Paste the full token from Cloudflare Zero Trust.";
  }
  return null;
}

function EyeIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
        <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
        <line x1="1" y1="1" x2="23" y2="23" />
      </svg>
    );
  }
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function PanelExposureSection() {
  const { isLocalZeroLogin } = useDeploymentProfile();
  const [draftMethod, setDraftMethod] = useState<PanelExposureMethodType>("none");
  const [cloudflareMode, setCloudflareMode] = useState<CloudflareModeType>("token");
  const [cloudflareToken, setCloudflareToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [portInput, setPortInput] = useState<string>("");
  const [isConfirmDisableOpen, setIsConfirmDisableOpen] = useState(false);
  const [isRotatingToken, setIsRotatingToken] = useState(false);
  const [isGeneratingClaim, setIsGeneratingClaim] = useState(false);
  const [isResettingAgent, setIsResettingAgent] = useState(false);
  const [claimData, setClaimData] = useState<import("@/types").ClaimResponse | null>(null);
  const [isCredentialsModalOpen, setIsCredentialsModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => Promise<void> | void) | null>(null);

  const {
    panel,
    isLoading,
    agent,
    updateExposure,
    isUpdating,
    refetch,
  } = usePanelExposure(draftMethod);

  const { copy } = useClipboard();
  const api = useMemo(() => createAuthenticatedApi(), []);

  // Refs for focus management
  const firstInputRef = useRef<HTMLInputElement>(null);
  const disableButtonRef = useRef<HTMLButtonElement>(null);
  const modalCancelButtonRef = useRef<HTMLButtonElement>(null);
  const activeAddressRef = useRef<HTMLAnchorElement>(null);

  // Sync draft state during rendering when panel query data arrives
  const [syncedPanel, setSyncedPanel] = useState<PanelExposureResponse | null | undefined>(null);
  if (panel && syncedPanel !== panel) {
    setSyncedPanel(panel);
    setDraftMethod(panel.method);
    if (panel.method === "cloudflare_tunnel") {
      if (panel.cloudflare_mode === "quick" || panel.ephemeral || panel.cloudflare_tunnel_id === "quick") {
        setCloudflareMode("quick");
      } else {
        setCloudflareMode("token");
      }
    }
    if (panel.external_port && !portInput) {
      setPortInput(String(panel.external_port));
    }
  }
  if (agent?.claimed && claimData) {
    setClaimData(null);
  }

  const portError = validatePortInput(portInput);
  const tokenInputError = validateTunnelTokenInput(cloudflareToken);
  const hasSavedToken = Boolean(
    panel?.token_configured ||
      (panel?.cloudflare_tunnel_id && panel.cloudflare_tunnel_id !== "quick"),
  );

  const handleSelectMethod = (method: PanelExposureMethodType) => {
    setDraftMethod(method);
    setTimeout(() => {
      firstInputRef.current?.focus();
    }, 50);
  };

  const executeGenerateClaim = async () => {
    try {
      setIsGeneratingClaim(true);
      const res = await api.generateClaim();
      setClaimData(res);
      await refetch();
      toast("success", "Claim Link Generated", "Authorize with playit.gg to complete setup.");
    } catch (err: unknown) {
      if (isPasswordRequiredError(err)) {
        setPendingAction(() => () => executeGenerateClaim());
        setIsCredentialsModalOpen(true);
        return;
      }
      const msg = err instanceof Error && err.message.trim() ? err.message : "Failed to generate claim link";
      toast("error", "Claim Generation Failed", msg);
    } finally {
      setIsGeneratingClaim(false);
    }
  };

  const handleGenerateClaim = async () => {
    if (isLocalZeroLogin) {
      setPendingAction(() => () => executeGenerateClaim());
      setIsCredentialsModalOpen(true);
      return;
    }
    await executeGenerateClaim();
  };

  const handleResetAgent = async () => {
    try {
      setIsResettingAgent(true);
      await api.resetAgent();
      await refetch();
      toast("success", "Agent Reset", "Playit agent credentials cleared.");
    } catch (err: unknown) {
      const msg = err instanceof Error && err.message.trim() ? err.message : "Failed to reset agent";
      toast("error", "Reset Failed", msg);
    } finally {
      setIsResettingAgent(false);
    }
  };

  const executeSaveForMethod = (targetMethod: PanelExposureMethodType, modeOverride?: CloudflareModeType) => {
    if (targetMethod === "none") {
      updateExposure({
        method: "none",
        desired_state: "DISABLED",
      });
      return;
    }

    const handleGateError = (err: unknown) => {
      if (isPasswordRequiredError(err)) {
        setPendingAction(() => () => executeSaveForMethod(targetMethod, modeOverride));
        setIsCredentialsModalOpen(true);
      }
    };

    if (targetMethod === "cloudflare_tunnel") {
      const effectiveMode = modeOverride ?? cloudflareMode;
      if (effectiveMode === "quick") {
        updateExposure(
          {
            method: "cloudflare_tunnel",
            desired_state: "ENABLED",
            cloudflare_mode: "quick",
          },
          {
            onSuccess: () => {
              setTimeout(() => activeAddressRef.current?.focus(), 100);
            },
            onError: handleGateError,
          },
        );
        return;
      }

      if (tokenInputError) return;
      if (!cloudflareToken.trim() && (!hasSavedToken || isRotatingToken || panel?.status === "RECLAIM_REQUIRED")) {
        return;
      }
      updateExposure(
        {
          method: "cloudflare_tunnel",
          desired_state: "ENABLED",
          cloudflare_mode: "token",
          ...(cloudflareToken.trim() ? { cloudflare_token: cloudflareToken.trim() } : {}),
        },
        {
          onSuccess: () => {
            setCloudflareToken("");
            setIsRotatingToken(false);
            setTimeout(() => activeAddressRef.current?.focus(), 100);
          },
          onError: handleGateError,
        },
      );
      return;
    }

    if (targetMethod === "playit_http") {
      updateExposure(
        {
          method: "playit_http",
          desired_state: "ENABLED",
        },
        {
          onSuccess: () => {
            setTimeout(() => activeAddressRef.current?.focus(), 100);
          },
          onError: handleGateError,
        },
      );
      return;
    }

    if (targetMethod === "port_forward") {
      if (portError) return;
      const parsedPort = portInput.trim() ? Number(portInput.trim()) : undefined;
      updateExposure(
        {
          method: "port_forward",
          desired_state: "ENABLED",
          external_port: parsedPort,
        },
        {
          onSuccess: () => {
            setTimeout(() => activeAddressRef.current?.focus(), 100);
          },
          onError: handleGateError,
        },
      );
    }
  };

  const handleSaveConfiguration = (modeOverride?: CloudflareModeType) => {
    if (draftMethod === "port_forward" && portError) return;
    if (
      draftMethod === "cloudflare_tunnel" &&
      (modeOverride ?? cloudflareMode) === "token" &&
      tokenInputError
    ) {
      return;
    }
    if (draftMethod !== "none" && isLocalZeroLogin) {
      setPendingAction(() => () => executeSaveForMethod(draftMethod, modeOverride));
      setIsCredentialsModalOpen(true);
      return;
    }
    executeSaveForMethod(draftMethod, modeOverride);
  };

  const handleSwitchToLocalOnly = () => {
    updateExposure(
      {
        method: "none",
        desired_state: "DISABLED",
      },
      {
        onSuccess: () => {
          setIsConfirmDisableOpen(false);
          setDraftMethod("none");
          disableButtonRef.current?.focus();
        },
      },
    );
  };

  const handleConfirmDisable = () => {
    updateExposure(
      {
        method: panel?.method || "none",
        desired_state: "DISABLED",
      },
      {
        onSuccess: () => {
          setIsConfirmDisableOpen(false);
          setDraftMethod("none");
          disableButtonRef.current?.focus();
        },
      },
    );
  };

  const handlePortKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (BLOCKED_PORT_KEYS.has(e.key)) {
      e.preventDefault();
    }
  };

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-card p-6 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  const isEnabled = panel?.desired_state === "ENABLED";
  const isCurrentlyActive = isEnabled && (panel?.status === "ACTIVE" || panel?.status === "DEGRADED");
  const isReclaimRequired = panel?.status === "RECLAIM_REQUIRED";
  const isBindMismatch = panel?.error_code === "BIND_MISMATCH";
  const isCgnatDetected =
    panel?.error_code === "CGNAT_DETECTED" || panel?.error_code === "DOUBLE_NAT_DETECTED";
  const isQuickActive =
    panel?.method === "cloudflare_tunnel" &&
    (panel?.cloudflare_mode === "quick" || panel?.ephemeral || panel?.cloudflare_tunnel_id === "quick");
  const isQuickStarting =
    isEnabled &&
    isQuickActive &&
    !panel?.public_address &&
    panel?.status !== "ERROR";
  const isTokenModeActive =
    panel?.method === "cloudflare_tunnel" && isEnabled && !isQuickActive;

  const headerBadgeStatus = isBindMismatch
    ? "BIND_MISMATCH"
    : isCgnatDetected
    ? "CGNAT_DETECTED"
    : panel?.status || "DISABLED";

  const showSecurityAdvisory = Boolean(
    panel?.security_advisory &&
      isEnabled &&
      (panel.method === "port_forward" || (panel.method === "playit_http" && !panel.tls)),
  );

  const publicUrl = panel?.public_address
    ? panel.public_address.startsWith("http")
      ? panel.public_address
      : `${panel.protocol || "https"}://${panel.public_address}`
    : null;

  const panelPort = 8000;

  return (
    <div className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-5">
      {/* Header */}
      <div className="border-b border-border-subtle pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            Panel Remote Access
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Publish this web panel over a tunnel or port forward.
          </p>
        </div>
        <div>
          <StatusBadge status={headerBadgeStatus} />
        </div>
      </div>

      {/* Passwordless Local Mode Gate Banner */}
      {isLocalZeroLogin && (
        <div
          data-testid="passwordless-panel-exposure-banner"
          role="alert"
          className="p-4 rounded-xl bg-status-warning-bg border border-status-warning-border flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <div className="space-y-1">
            <h4 className="text-xs font-semibold text-status-warning uppercase tracking-wider">
              Password Required for Panel Exposure
            </h4>
            <p className="text-xs text-text-secondary">
              Set an administrator username and password before publishing the panel to the internet.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setPendingAction(null);
              setIsCredentialsModalOpen(true);
            }}
            className="shrink-0 px-3.5 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors cursor-pointer"
          >
            Set Username &amp; Password
          </button>
        </div>
      )}

      {/* Security Advisory Banner (relevant only to unencrypted HTTP exposure) */}
      {showSecurityAdvisory && panel?.security_advisory && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-status-warning-bg border border-status-warning-border flex items-start gap-3"
        >
          <Icon name="alert" size={20} className="text-status-warning mt-0.5 shrink-0" />
          <div className="space-y-1">
            <h4 className="text-xs font-semibold text-status-warning uppercase tracking-wider">
              Security Advisory
            </h4>
            <p className="text-xs text-status-warning leading-relaxed">
              {panel.security_advisory}
            </p>
          </div>
        </div>
      )}

      {/* BIND_MISMATCH Diagnostic Banner */}
      {isBindMismatch && panel && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-status-warning-bg border border-status-warning-border space-y-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2 text-status-warning font-semibold text-sm">
              <Icon name="alert" size={18} />
              <span>Action Required: Restart Panel to Complete Port Forwarding</span>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-status-warning/20 text-status-warning shrink-0">
              BIND_MISMATCH
            </span>
          </div>
          <p className="text-xs text-status-warning leading-relaxed">
            {panel.fix_hint ||
              panel.error_message ||
              "Panel bind address updated to 0.0.0.0 in config/settings.yaml. Restart the panel service for changes to take effect."}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => executeSaveForMethod(panel.method)}
              disabled={isUpdating}
              className="px-3 py-1.5 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50"
            >
              {isUpdating ? "Checking..." : "Retry Check"}
            </button>
            <button
              type="button"
              onClick={handleSwitchToLocalOnly}
              disabled={isUpdating}
              className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-card hover:bg-surface-hover text-text-secondary text-xs font-medium transition-colors disabled:opacity-50"
            >
              Switch to Local Only
            </button>
          </div>
        </div>
      )}

      {/* CGNAT / Generic Error Diagnostic Banner */}
      {panel?.status === "ERROR" && !isBindMismatch && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-status-danger-bg border border-status-danger-border space-y-3"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-status-danger font-semibold text-xs">
              <Icon name="alert" size={16} className="shrink-0" />
              <span>
                {isCgnatDetected
                  ? "ISP CGNAT / Double-NAT Detected"
                  : panel.error_message || "Exposure operation encountered an error"}
              </span>
            </div>
            {panel.error_code && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-status-danger/20 text-status-danger shrink-0">
                {panel.error_code}
              </span>
            )}
          </div>
          {isCgnatDetected && panel.error_message && (
            <p className="text-xs text-status-danger leading-relaxed pl-6">
              {panel.error_message}
            </p>
          )}
          {panel.fix_hint && (
            <p className="text-xs text-status-danger/90 pl-6">
              {panel.fix_hint}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2 pl-6 pt-1">
            <button
              type="button"
              onClick={() => executeSaveForMethod(panel.method)}
              disabled={isUpdating}
              className="px-3 py-1.5 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50"
            >
              {isUpdating ? "Retrying..." : "Retry"}
            </button>
            {isCgnatDetected && (
              <button
                type="button"
                onClick={() => handleSelectMethod("cloudflare_tunnel")}
                disabled={isUpdating}
                className="px-3 py-1.5 rounded-lg border border-accent-primary/40 bg-accent-primary/10 hover:bg-accent-primary/20 text-accent-primary text-xs font-medium transition-colors disabled:opacity-50"
              >
                Use Cloudflare Tunnel
              </button>
            )}
            <button
              type="button"
              onClick={handleSwitchToLocalOnly}
              disabled={isUpdating}
              className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-card hover:bg-surface-hover text-text-secondary text-xs font-medium transition-colors disabled:opacity-50"
            >
              Switch to Local Only
            </button>
          </div>
        </div>
      )}

      {/* Active Public Address Card */}
      {isCurrentlyActive && publicUrl && (
        <div className="p-4 rounded-xl bg-status-success-bg border border-status-success-border space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-status-success uppercase tracking-wider">
              Live Public Panel Address
            </span>
            <div className="flex items-center gap-2">
              {panel?.ephemeral && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-status-warning/20 text-status-warning">
                  Temporary Quick URL
                </span>
              )}
              <span
                className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                  panel.tls
                    ? "bg-status-success/20 text-status-success"
                    : "bg-status-warning/20 text-status-warning"
                }`}
              >
                {panel.tls ? "HTTPS (Encrypted)" : "HTTP (Unencrypted)"}
              </span>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-surface-elevated border border-border-default shadow-xs">
            <a
              ref={activeAddressRef}
              href={publicUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-sm font-semibold text-accent-primary hover:underline flex items-center gap-1.5 break-all"
            >
              <span>{publicUrl}</span>
              <Icon name="external" size={14} />
            </a>

            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => copy(publicUrl, "Public address copied to clipboard")}
                aria-label="Copy public address"
                className="px-3 py-1.5 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover flex items-center gap-1.5 transition-colors"
              >
                <Icon name="copy" size={14} />
                <span>Copy Link</span>
              </button>
              <button
                ref={disableButtonRef}
                type="button"
                onClick={() => setIsConfirmDisableOpen(true)}
                className="px-3 py-1.5 rounded-lg border border-status-danger-border text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors"
              >
                Disable Exposure
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Active Permanent Token Status Card (when Zero Trust manages hostname remotely) */}
      {isTokenModeActive && !publicUrl && panel?.status !== "ERROR" && panel?.status !== "RECLAIM_REQUIRED" && (
        <div className="p-4 rounded-xl bg-status-success-bg/70 border border-status-success-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-status-success uppercase tracking-wider">
                Cloudflare Tunnel {panel?.status === "ACTIVE" ? "Connected" : "Connecting"}
              </span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-status-success/20 text-status-success">
                HTTPS (Zero Trust)
              </span>
            </div>
            <p className="text-xs text-text-secondary">
              Traffic routes via your configured Public Hostname in Cloudflare Zero Trust.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <a
              href="https://one.dash.cloudflare.com/"
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-card text-xs font-medium text-text-secondary hover:bg-surface-hover inline-flex items-center gap-1.5 transition-colors"
            >
              <span>Zero Trust</span>
              <Icon name="external" size={12} />
            </a>
            <button
              ref={disableButtonRef}
              type="button"
              onClick={() => setIsConfirmDisableOpen(true)}
              className="px-3 py-1.5 rounded-lg border border-status-danger-border text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors"
            >
              Disable Exposure
            </button>
          </div>
        </div>
      )}

      {/* Method Selector Cards */}
      <div className="space-y-3">
        <span className="text-xs font-medium text-text-muted uppercase tracking-wider">
          Select Exposure Method
        </span>
        <div className="grid grid-cols-1 sm:grid-cols-2 2xl:grid-cols-4 gap-3">
          {/* 1. None */}
          <button
            type="button"
            aria-pressed={draftMethod === "none"}
            onClick={() => handleSelectMethod("none")}
            className={`min-w-0 overflow-hidden p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
              draftMethod === "none"
                ? "border-accent-primary bg-accent-primary/10 shadow-xs"
                : "border-border-subtle hover:border-border-hover bg-surface-page"
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-1 min-w-0">
              <h4 className="text-sm font-semibold text-text-primary min-w-0">Local Only</h4>
              {draftMethod === "none" && (
                <Icon name="check" size={15} className="text-text-accent shrink-0 mt-0.5" />
              )}
            </div>
            <p className="text-xs text-text-muted">
              Reachable on localhost and LAN only.
            </p>
          </button>

          {/* 2. Cloudflare */}
          <button
            type="button"
            aria-pressed={draftMethod === "cloudflare_tunnel"}
            onClick={() => handleSelectMethod("cloudflare_tunnel")}
            className={`min-w-0 overflow-hidden p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
              draftMethod === "cloudflare_tunnel"
                ? "border-accent-primary bg-accent-primary/10 shadow-xs"
                : "border-border-subtle hover:border-border-hover bg-surface-page"
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5 min-w-0">
                <h4 className="text-sm font-semibold text-text-primary">Cloudflare</h4>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-accent-primary/12 text-text-accent shrink-0">
                  Recommended
                </span>
              </div>
              {draftMethod === "cloudflare_tunnel" && (
                <Icon name="check" size={15} className="text-text-accent shrink-0 mt-0.5" />
              )}
            </div>
            <p className="text-xs text-text-muted">
              Encrypted HTTPS tunnel behind CGNAT.
            </p>
          </button>

          {/* 3. playit.gg */}
          <button
            type="button"
            aria-pressed={draftMethod === "playit_http"}
            onClick={() => handleSelectMethod("playit_http")}
            className={`min-w-0 overflow-hidden p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
              draftMethod === "playit_http"
                ? "border-accent-primary bg-accent-primary/10 shadow-xs"
                : "border-border-subtle hover:border-border-hover bg-surface-page"
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-1 min-w-0">
              <h4 className="text-sm font-semibold text-text-primary min-w-0">playit.gg</h4>
              {draftMethod === "playit_http" && (
                <Icon name="check" size={15} className="text-text-accent shrink-0 mt-0.5" />
              )}
            </div>
            <p className="text-xs text-text-muted">
              Edge tunnel via shared playit agent.
            </p>
          </button>

          {/* 4. Port Forward */}
          <button
            type="button"
            aria-pressed={draftMethod === "port_forward"}
            onClick={() => handleSelectMethod("port_forward")}
            className={`min-w-0 overflow-hidden p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
              draftMethod === "port_forward"
                ? "border-accent-primary bg-accent-primary/10 shadow-xs"
                : "border-border-subtle hover:border-border-hover bg-surface-page"
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-1 min-w-0">
              <h4 className="text-sm font-semibold text-text-primary min-w-0">Port Forward</h4>
              {draftMethod === "port_forward" && (
                <Icon name="check" size={15} className="text-text-accent shrink-0 mt-0.5" />
              )}
            </div>
            <p className="text-xs text-text-muted">
              UPnP router mapping on public IP.
            </p>
          </button>
        </div>
      </div>

      {/* Configuration Panel for Selected Method */}
      <div className="rounded-xl border border-border-subtle bg-surface-page/70 p-5 space-y-4">
        {/* 1. Local Only Form */}
        {draftMethod === "none" && (
          <div className="space-y-4">
            <p className="text-xs text-text-secondary leading-relaxed">
              External panel exposure is disabled. The panel listens safely on{" "}
              <code className="font-mono px-1.5 py-0.5 rounded bg-surface-elevated">127.0.0.1</code>{" "}
              and is only reachable locally or via VPN.
            </p>
            <div className="flex flex-wrap items-center gap-3 pt-1">
              {isEnabled ? (
                <button
                  type="button"
                  onClick={() => handleSaveConfiguration()}
                  disabled={isUpdating}
                  className="px-4 py-2 rounded-lg bg-status-danger hover:opacity-90 text-white text-xs font-medium transition-colors disabled:opacity-50"
                >
                  {isUpdating ? "Disabling..." : "Switch to Local Only"}
                </button>
              ) : (
                <button
                  type="button"
                  disabled
                  className="px-4 py-2 rounded-lg border border-border-default bg-surface-card text-text-muted text-xs font-medium cursor-default opacity-80 inline-flex items-center gap-1.5"
                >
                  <Icon name="check" size={14} className="text-status-success" />
                  <span>Local Only Active</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* 2. Cloudflare Modern Form (Permanent Token Mode + Quick Preview Mode) */}
        {draftMethod === "cloudflare_tunnel" && (
          <div className="space-y-4">
            {/* Segmented Mode Toggle */}
            <div
              role="tablist"
              aria-label="Cloudflare tunnel mode"
              className="inline-flex p-1 rounded-lg bg-surface-elevated border border-border-default gap-1"
            >
              <button
                type="button"
                role="tab"
                aria-selected={cloudflareMode === "token"}
                onClick={() => setCloudflareMode("token")}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  cloudflareMode === "token"
                    ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                Permanent (Tunnel Token)
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={cloudflareMode === "quick"}
                onClick={() => setCloudflareMode("quick")}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  cloudflareMode === "quick"
                    ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                Quick Preview (Temporary)
              </button>
            </div>

            {cloudflareMode === "token" ? (
              <div className="space-y-4">
                {isReclaimRequired && (
                  <div
                    role="alert"
                    className="p-3 rounded-lg bg-status-danger-bg border border-status-danger-border text-xs text-status-danger"
                  >
                    Cloudflare Tunnel Token was invalidated or rejected. Please paste a fresh Tunnel Token to reconnect.
                  </div>
                )}

                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <label htmlFor="cloudflare-token" className="block text-xs font-semibold text-text-secondary">
                    Tunnel Token{" "}
                    {hasSavedToken && !isRotatingToken && !isReclaimRequired ? (
                      <span className="text-status-success font-normal">(Saved)</span>
                    ) : (
                      <span className="text-status-danger">*</span>
                    )}
                  </label>
                  <a
                    href="https://one.dash.cloudflare.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-accent-primary hover:underline"
                  >
                    <span>Open Cloudflare Tunnels</span>
                    <Icon name="external" size={13} />
                  </a>
                </div>

                <div className="relative">
                  <input
                    ref={firstInputRef}
                    id="cloudflare-token"
                    type={showToken ? "text" : "password"}
                    value={cloudflareToken}
                    onChange={(e) => setCloudflareToken(e.target.value)}
                    placeholder={
                      hasSavedToken && !isRotatingToken && !isReclaimRequired
                        ? "•••••••••••••••• (Saved — enter new token to replace)"
                        : "eyJhIjoi..."
                    }
                    className={`w-full px-3 py-2 pr-10 rounded-lg border bg-surface-card text-text-primary text-xs font-mono focus:ring-2 focus:ring-accent-primary focus:border-transparent outline-none transition-all ${
                      (isReclaimRequired && !cloudflareToken) || tokenInputError
                        ? "border-status-danger"
                        : "border-border-default"
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken(!showToken)}
                    aria-label={showToken ? "Hide token" : "Show token"}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary p-1"
                  >
                    <EyeIcon open={showToken} />
                  </button>
                </div>

                {tokenInputError && (
                  <p role="alert" className="text-[11px] text-status-danger">
                    {tokenInputError}
                  </p>
                )}

                {/* Concise 3-step inline guide */}
                <ol className="rounded-lg bg-surface-card border border-border-default p-3.5 space-y-1.5 text-xs text-text-secondary list-decimal list-inside">
                  <li>
                    Open Cloudflare Zero Trust (<span className="font-medium text-text-primary">Networks → Tunnels</span>) and create a Cloudflared tunnel.
                  </li>
                  <li>Copy the Tunnel Token (<code className="font-mono text-[11px]">eyJ...</code>) and paste it above.</li>
                  <li>
                    Point a Public Hostname to{" "}
                    <code className="font-mono text-[11px] px-1 py-0.5 rounded bg-surface-elevated">
                      http://127.0.0.1:{panelPort}
                    </code>{" "}
                    (HTTP).
                  </li>
                </ol>

                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <button
                    type="button"
                    onClick={() => handleSaveConfiguration("token")}
                    disabled={
                      isUpdating ||
                      Boolean(tokenInputError) ||
                      (!cloudflareToken.trim() && (!hasSavedToken || isRotatingToken || isReclaimRequired))
                    }
                    className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
                  >
                    {isUpdating
                      ? "Configuring Tunnel..."
                      : isReclaimRequired
                      ? "Update Token & Reconnect"
                      : isTokenModeActive
                      ? "Restart / Update Tunnel"
                      : "Enable Cloudflare Tunnel"}
                  </button>

                  {hasSavedToken && !isRotatingToken && !isReclaimRequired && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsRotatingToken(true);
                        setCloudflareToken("");
                      }}
                      className="px-3 py-2 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors"
                    >
                      Replace Token
                    </button>
                  )}

                  {panel?.method === "cloudflare_tunnel" && isEnabled && (
                    <button
                      type="button"
                      onClick={() => setIsConfirmDisableOpen(true)}
                      disabled={isUpdating}
                      className="px-3 py-2 rounded-lg border border-status-danger-border text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors disabled:opacity-50"
                    >
                      Disable
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div
                  role="note"
                  className="p-3.5 rounded-lg bg-status-warning-bg border border-status-warning-border flex items-start gap-2.5 text-xs text-status-warning"
                >
                  <Icon name="info" size={16} className="shrink-0 mt-0.5" />
                  <span>
                    Temporary <code className="font-mono">trycloudflare.com</code> URL for quick testing — changes on every restart. No domain required.
                  </span>
                </div>

                {((isUpdating && cloudflareMode === "quick") || isQuickStarting) && (
                  <div
                    data-testid="quick-tunnel-starting-row"
                    className="flex items-center gap-2.5 p-3 rounded-lg bg-surface-card border border-border-default text-xs text-text-secondary"
                  >
                    <span
                      aria-hidden="true"
                      className="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent-primary border-t-transparent"
                    />
                    <span>Starting Quick Tunnel &amp; waiting for trycloudflare.com URL...</span>
                  </div>
                )}

                {isQuickActive && isEnabled && panel?.status === "ACTIVE" && publicUrl && (
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg bg-surface-card border border-status-success-border">
                    <span className="font-mono text-xs text-accent-primary break-all">{publicUrl}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => copy(publicUrl, "Quick URL copied to clipboard")}
                        className="px-2.5 py-1 rounded border border-border-default text-xs text-text-secondary hover:bg-surface-hover inline-flex items-center gap-1"
                      >
                        <Icon name="copy" size={12} />
                        <span>Copy</span>
                      </button>
                      <a
                        href={publicUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2.5 py-1 rounded border border-border-default text-xs text-accent-primary hover:bg-surface-hover inline-flex items-center gap-1"
                      >
                        <span>Open</span>
                        <Icon name="external" size={12} />
                      </a>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <button
                    type="button"
                    onClick={() => handleSaveConfiguration("quick")}
                    disabled={isUpdating || isQuickStarting}
                    className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
                  >
                    {isUpdating || isQuickStarting
                      ? "Starting Quick Tunnel..."
                      : isQuickActive && isEnabled
                      ? "Restart Quick Tunnel"
                      : "Start Quick Tunnel"}
                  </button>

                  {panel?.method === "cloudflare_tunnel" && isEnabled && (
                    <button
                      type="button"
                      onClick={() => setIsConfirmDisableOpen(true)}
                      disabled={isUpdating}
                      className="px-3 py-2 rounded-lg border border-status-danger-border text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors disabled:opacity-50"
                    >
                      Disable
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 3. playit.gg Form */}
        {draftMethod === "playit_http" && (
          <div className="space-y-4">
            <PlayitClaimCard
              claimed={Boolean(agent?.claimed)}
              claimActive={Boolean(!agent?.claimed && (agent?.claim_active || claimData?.claim_code))}
              claimCode={!agent?.claimed ? claimData?.claim_code : undefined}
              claimUrl={!agent?.claimed ? claimData?.claim_url : undefined}
              claimExpiresAt={!agent?.claimed ? (claimData?.expires_at || agent?.claim_expires_at || undefined) : undefined}
              onGenerateClaim={handleGenerateClaim}
              isGenerating={isGeneratingClaim}
              onResetAgent={handleResetAgent}
              isResetting={isResettingAgent}
              title="playit.gg Panel Tunnel"
              description="A playit claim authorizes this host to publish the web panel through an encrypted edge tunnel."
            />

            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => handleSaveConfiguration()}
                disabled={isUpdating}
                className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
              >
                {isUpdating
                  ? "Connecting Tunnel..."
                  : panel?.method === "playit_http" && isEnabled
                  ? "Restart playit.gg Tunnel"
                  : "Enable playit.gg Tunnel"}
              </button>

              {panel?.method === "playit_http" && isEnabled && (
                <button
                  type="button"
                  onClick={() => setIsConfirmDisableOpen(true)}
                  disabled={isUpdating}
                  className="px-3 py-2 rounded-lg border border-status-danger-border text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors disabled:opacity-50"
                >
                  Disable
                </button>
              )}
            </div>
          </div>
        )}

        {/* 4. Port Forwarding Form */}
        {draftMethod === "port_forward" && (
          <div className="space-y-4">
            <div className="max-w-xs space-y-1.5">
              <label htmlFor="external-port" className="block text-xs font-semibold text-text-secondary">
                Requested External Port (Optional)
              </label>
              <input
                ref={firstInputRef}
                id="external-port"
                type="text"
                inputMode="numeric"
                value={portInput}
                onKeyDown={handlePortKeyDown}
                onChange={(e) => {
                  const digitsOnly = e.target.value.replace(/\D/g, "");
                  setPortInput(digitsOnly);
                }}
                placeholder="Auto (8000)"
                className={`w-full px-3 py-2 rounded-lg border bg-surface-card text-text-primary text-xs font-mono focus:ring-2 focus:ring-accent-primary focus:border-transparent outline-none transition-all ${
                  portError ? "border-status-danger" : "border-border-default"
                }`}
              />
              {portError ? (
                <p role="alert" className="text-[11px] text-status-danger">
                  {portError}
                </p>
              ) : (
                <p className="text-[11px] text-text-muted">
                  Enter a port from 1 to 65535, or leave blank for default (8000).
                </p>
              )}
            </div>

            {panel?.upnp_last_result && (
              <div className="text-xs text-text-secondary">
                <span className="font-medium">UPnP Status:</span>{" "}
                <code className="font-mono px-1.5 py-0.5 rounded bg-surface-elevated text-[11px]">
                  {panel.upnp_last_result}
                </code>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => handleSaveConfiguration()}
                disabled={isUpdating || Boolean(portError)}
                className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
              >
                {isUpdating
                  ? "Configuring UPnP..."
                  : panel?.method === "port_forward" && panel?.status === "ERROR"
                  ? "Retry Port Forwarding"
                  : "Enable Port Forwarding"}
              </button>

              {panel?.method === "port_forward" && isEnabled && (
                <button
                  type="button"
                  onClick={() => setIsConfirmDisableOpen(true)}
                  disabled={isUpdating}
                  className="px-3 py-2 rounded-lg border border-status-danger-border text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors disabled:opacity-50"
                >
                  Disable
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Disable Confirmation Modal */}
      <Modal
        open={isConfirmDisableOpen}
        onClose={() => {
          if (isUpdating) return;
          setIsConfirmDisableOpen(false);
          disableButtonRef.current?.focus();
        }}
        title="Disable Panel Exposure?"
        size="md"
        closeOnBackdrop={false}
        closeOnEscape={!isUpdating}
        closeButtonAriaLabel="Close dialog"
      >
        <div className="space-y-4">
          <p className="text-xs text-text-secondary leading-relaxed">
            Disabling panel exposure will tear down the active tunnel and close public network access to this panel. You will still be able to connect locally.
          </p>

          <div className="flex justify-end gap-3 pt-2">
            <button
              ref={modalCancelButtonRef}
              type="button"
              onClick={() => {
                setIsConfirmDisableOpen(false);
                disableButtonRef.current?.focus();
              }}
              disabled={isUpdating}
              className="px-4 py-2 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmDisable}
              disabled={isUpdating}
              className="px-4 py-2 rounded-lg bg-status-danger hover:opacity-90 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
            >
              {isUpdating ? "Disabling..." : "Confirm Disable"}
            </button>
          </div>
        </div>
      </Modal>

      <ConfigureCredentialsModal
        open={isCredentialsModalOpen}
        onClose={() => {
          setIsCredentialsModalOpen(false);
          setPendingAction(null);
        }}
        onSuccess={async () => {
          const action = pendingAction;
          setPendingAction(null);
          if (action) {
            await action();
          }
        }}
      />
    </div>
  );
}
