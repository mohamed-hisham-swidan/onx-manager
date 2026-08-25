import { useState, useMemo, useRef } from "react";
import { usePanelExposure } from "@/server_manager/hooks/usePanelExposure";
import { PlayitClaimCard } from "@/server_manager/components/PlayitClaimCard";
import { useClipboard } from "@/hooks/useClipboard";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Skeleton } from "@/components/Skeleton";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import type { PanelExposureMethodType, PanelExposureResponse } from "@/types";

const FQDN_REGEX = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;

function isValidFQDN(val: string): boolean {
  const clean = val.trim().toLowerCase();
  return clean.length >= 4 && clean.length <= 253 && FQDN_REGEX.test(clean);
}

export function PanelExposureSection() {
  // Form State
  const [draftMethod, setDraftMethod] = useState<PanelExposureMethodType>("none");
  const [cloudflareToken, setCloudflareToken] = useState("");
  const [hostname, setHostname] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [externalPort, setExternalPort] = useState<number | null>(null);
  const [isConfirmDisableOpen, setIsConfirmDisableOpen] = useState(false);
  const [isRotatingToken, setIsRotatingToken] = useState(false);
  const [isGeneratingClaim, setIsGeneratingClaim] = useState(false);
  const [isResettingAgent, setIsResettingAgent] = useState(false);
  const [claimData, setClaimData] = useState<import("@/types").ClaimResponse | null>(null);

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

  // Refs for focus management (F-74-08)
  const firstInputRef = useRef<HTMLInputElement>(null);
  const disableButtonRef = useRef<HTMLButtonElement>(null);
  const modalCancelButtonRef = useRef<HTMLButtonElement>(null);
  const activeAddressRef = useRef<HTMLAnchorElement>(null);

  // Sync draft state during rendering when panel query data arrives (React 19 pattern)
  const [syncedPanel, setSyncedPanel] = useState<PanelExposureResponse | null | undefined>(null);
  if (panel && syncedPanel !== panel) {
    setSyncedPanel(panel);
    setDraftMethod(panel.method);
    if (panel.public_address && !hostname) {
      const cleanHost = panel.public_address.replace(/^https?:\/\//, "").split(":")[0];
      setHostname(cleanHost);
    }
    if (panel.external_port && !externalPort) {
      setExternalPort(panel.external_port);
    }
  }
  if (agent?.claimed && claimData) {
    setClaimData(null);
  }

  // Focus management when switching method cards
  const handleSelectMethod = (method: PanelExposureMethodType) => {
    setDraftMethod(method);
    // Asynchronous focus shift to allow DOM to render form inputs
    setTimeout(() => {
      firstInputRef.current?.focus();
    }, 50);
  };

  const handleGenerateClaim = async () => {
    try {
      setIsGeneratingClaim(true);
      const res = await api.generateClaim();
      setClaimData(res);
      await refetch();
      toast("success", "Claim Link Generated", "Authorize with playit.gg to complete setup.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to generate claim link";
      toast("error", "Claim Generation Failed", msg);
    } finally {
      setIsGeneratingClaim(false);
    }
  };

  const handleResetAgent = async () => {
    try {
      setIsResettingAgent(true);
      await api.resetAgent();
      await refetch();
      toast("success", "Agent Reset", "Playit agent credentials cleared.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to reset agent";
      toast("error", "Reset Failed", msg);
    } finally {
      setIsResettingAgent(false);
    }
  };

  const handleSaveConfiguration = () => {
    if (draftMethod === "none") {
      updateExposure({
        method: "none",
        desired_state: "DISABLED",
      });
      return;
    }

    if (draftMethod === "cloudflare_tunnel") {
      if (!isValidFQDN(hostname)) return;
      updateExposure(
        {
          method: "cloudflare_tunnel",
          desired_state: "ENABLED",
          cloudflare_token: cloudflareToken.trim(),
          hostname: hostname.trim().toLowerCase(),
        },
        {
          onSuccess: () => {
            setCloudflareToken("");
            setIsRotatingToken(false);
            setTimeout(() => activeAddressRef.current?.focus(), 100);
          },
        },
      );
      return;
    }

    if (draftMethod === "playit_http") {
      updateExposure(
        {
          method: "playit_http",
          desired_state: "ENABLED",
        },
        {
          onSuccess: () => {
            setTimeout(() => activeAddressRef.current?.focus(), 100);
          },
        },
      );
      return;
    }

    if (draftMethod === "port_forward") {
      updateExposure(
        {
          method: "port_forward",
          desired_state: "ENABLED",
          external_port: externalPort || undefined,
        },
        {
          onSuccess: () => {
            setTimeout(() => activeAddressRef.current?.focus(), 100);
          },
        },
      );
      return;
    }
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

  if (isLoading) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  const isEnabled = panel?.desired_state === "ENABLED";
  const isCurrentlyActive = isEnabled && (panel?.status === "ACTIVE" || panel?.status === "DEGRADED");
  const isReclaimRequired = panel?.status === "RECLAIM_REQUIRED";
  const isBindMismatch = panel?.error_code === "BIND_MISMATCH";

  const publicUrl = panel?.public_address
    ? panel.public_address.startsWith("http")
      ? panel.public_address
      : `${panel.protocol || "https"}://${panel.public_address}`
    : null;

  return (
    <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 p-6 space-y-6">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-700 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Panel Network Exposure
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Configure external network access to this MCS Manager web interface.
          </p>
        </div>
        <div>
          <StatusBadge status={panel?.status || "DISABLED"} />
        </div>
      </div>

      {/* Security Advisory Banner (LOCAL Mode Unencrypted Port Forwarding) */}
      {panel?.security_advisory && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 flex items-start gap-3"
        >
          <Icon name="alert" size={20} className="text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
          <div className="space-y-1">
            <h4 className="text-xs font-semibold text-amber-800 dark:text-amber-300 uppercase tracking-wider">
              Security Advisory
            </h4>
            <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
              {panel.security_advisory}
            </p>
          </div>
        </div>
      )}

      {/* BIND_MISMATCH Auto-Fixed Banner */}
      {isBindMismatch && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 space-y-2"
        >
          <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold text-sm">
            <Icon name="alert" size={18} />
            <span>Action Required: Restart Panel to Complete Port Forwarding</span>
          </div>
          <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
            {panel.fix_hint ||
              "Panel bind address updated to 0.0.0.0 in config/settings.yaml. Restart the panel service for changes to take effect."}
          </p>
        </div>
      )}

      {/* Generic Error Banner */}
      {panel?.status === "ERROR" && !isBindMismatch && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 space-y-2"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-red-700 dark:text-red-300 font-semibold text-xs">
              <Icon name="alert" size={16} />
              <span>{panel.error_message || "Exposure operation encountered an error"}</span>
            </div>
            {panel.error_code && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300">
                {panel.error_code}
              </span>
            )}
          </div>
          {panel.fix_hint && (
            <p className="text-xs text-red-600 dark:text-red-300 pl-6">
              {panel.fix_hint}
            </p>
          )}
        </div>
      )}

      {/* Active Public Address Card */}
      {isCurrentlyActive && publicUrl && (
        <div className="p-4 rounded-xl bg-green-50/50 dark:bg-green-900/10 border border-green-200 dark:border-green-800 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-green-800 dark:text-green-300 uppercase tracking-wider">
              Live Public Panel Address
            </span>
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
              panel.tls
                ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
                : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300"
            }`}>
              {panel.tls ? "HTTPS (Encrypted)" : "HTTP (Unencrypted)"}
            </span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-white dark:bg-gray-800 border border-green-200 dark:border-green-700/60 shadow-sm">
            <a
              ref={activeAddressRef}
              href={publicUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-sm font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1.5 break-all"
            >
              <span>{publicUrl}</span>
              <Icon name="external" size={14} />
            </a>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => copy(publicUrl, "Public address copied to clipboard")}
                aria-label="Copy public address"
                className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-1.5 transition-colors"
              >
                <Icon name="copy" size={14} />
                <span>Copy Link</span>
              </button>
              <button
                ref={disableButtonRef}
                type="button"
                onClick={() => setIsConfirmDisableOpen(true)}
                className="px-3 py-1.5 rounded-lg border border-red-300 dark:border-red-800 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              >
                Disable Exposure
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Method Selector Cards (Grid) */}
      <div className="space-y-3">
        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          Select Exposure Method
        </span>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* 1. None */}
          <button
            type="button"
            onClick={() => handleSelectMethod("none")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "none"
                ? "border-blue-500 bg-blue-50/40 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            }`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Local Only</h4>
              {draftMethod === "none" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Disabled. Panel is accessible only via local LAN or VPN.
            </p>
          </button>

          {/* 2. Cloudflare */}
          <button
            type="button"
            onClick={() => handleSelectMethod("cloudflare_tunnel")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "cloudflare_tunnel"
                ? "border-blue-500 bg-blue-50/40 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            }`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Cloudflare</h4>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300">
                  Recommended
                </span>
              </div>
              {draftMethod === "cloudflare_tunnel" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Named tunnel via custom domain. Automatic HTTPS and DDoS protection.
            </p>
          </button>

          {/* 3. playit.gg */}
          <button
            type="button"
            onClick={() => handleSelectMethod("playit_http")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "playit_http"
                ? "border-blue-500 bg-blue-50/40 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            }`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">playit.gg</h4>
              {draftMethod === "playit_http" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              HTTP edge tunnel via shared playit agent. Works behind CGNAT.
            </p>
          </button>

          {/* 4. Port Forward */}
          <button
            type="button"
            onClick={() => handleSelectMethod("port_forward")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "port_forward"
                ? "border-blue-500 bg-blue-50/40 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            }`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Port Forward</h4>
              {draftMethod === "port_forward" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              UPnP IGD local router mapping. Direct unencrypted HTTP access.
            </p>
          </button>
        </div>
      </div>

      {/* Configuration Panel for Selected Method */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-800/60 p-5 space-y-4">
        {/* None Form */}
        {draftMethod === "none" && (
          <div className="space-y-4">
            <p className="text-xs text-gray-600 dark:text-gray-300">
              External panel exposure is disabled. The panel is only reachable from this machine or devices on the same local network.
            </p>
            {isEnabled && (
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSaveConfiguration}
                  disabled={isUpdating}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors disabled:opacity-50"
                >
                  {isUpdating ? "Disabling..." : "Save & Disable Exposure"}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Cloudflare Form */}
        {draftMethod === "cloudflare_tunnel" && (
          <div className="space-y-4">
            {isReclaimRequired && (
              <div role="alert" className="p-3 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-300 dark:border-red-800 text-xs text-red-700 dark:text-red-300">
                Cloudflare API Token was invalidated or revoked. Please enter a fresh token to restore the tunnel.
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Hostname Input */}
              <div className="space-y-1.5">
                <label htmlFor="cloudflare-hostname" className="block text-xs font-semibold text-gray-700 dark:text-gray-300">
                  Custom Domain / Hostname <span className="text-red-500">*</span>
                </label>
                <input
                  ref={firstInputRef}
                  id="cloudflare-hostname"
                  type="text"
                  value={hostname}
                  onChange={(e) => setHostname(e.target.value)}
                  placeholder="panel.example.com"
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                />
                {hostname && !isValidFQDN(hostname) ? (
                  <p className="text-[11px] text-red-600 dark:text-red-400">
                    Please enter a valid fully-qualified domain name (e.g. panel.example.com).
                  </p>
                ) : (
                  <p className="text-[11px] text-gray-500 dark:text-gray-400">
                    Must be a domain managed in your Cloudflare account.
                  </p>
                )}
              </div>

              {/* API Token Input */}
              <div className="space-y-1.5">
                <label htmlFor="cloudflare-token" className="block text-xs font-semibold text-gray-700 dark:text-gray-300">
                  Cloudflare API Token {panel?.cloudflare_tunnel_id && !isRotatingToken && !isReclaimRequired ? "(Stored)" : <span className="text-red-500">*</span>}
                </label>
                <div className="relative">
                  <input
                    id="cloudflare-token"
                    type={showToken ? "text" : "password"}
                    value={cloudflareToken}
                    onChange={(e) => setCloudflareToken(e.target.value)}
                    placeholder={
                      panel?.cloudflare_tunnel_id && !isRotatingToken && !isReclaimRequired
                        ? "••••••••••••••••••••••••••••••••"
                        : "Enter Cloudflare API token..."
                    }
                    className={`w-full px-3 py-2 pr-10 rounded-lg border bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all ${
                      isReclaimRequired && !cloudflareToken
                        ? "border-red-500 dark:border-red-500"
                        : "border-gray-300 dark:border-gray-600"
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken(!showToken)}
                    aria-label={showToken ? "Hide API token" : "Show API token"}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1"
                  >
                    <Icon name={showToken ? "moon" : "sun"} size={14} />
                  </button>
                </div>
                <p className="text-[11px] text-gray-500 dark:text-gray-400">
                  Requires <code>Zone.DNS:Edit</code> and <code>Account.Cloudflare Tunnel:Edit</code> scopes.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                onClick={handleSaveConfiguration}
                disabled={
                  isUpdating ||
                  !isValidFQDN(hostname) ||
                  (!cloudflareToken && (!panel?.cloudflare_tunnel_id || isRotatingToken || isReclaimRequired))
                }
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
              >
                {isUpdating
                  ? "Configuring Tunnel..."
                  : isReclaimRequired
                  ? "Update Token & Reconnect"
                  : "Enable Cloudflare Tunnel"}
              </button>

              {panel?.cloudflare_tunnel_id && !isRotatingToken && !isReclaimRequired && (
                <button
                  type="button"
                  onClick={() => {
                    setIsRotatingToken(true);
                    setCloudflareToken("");
                  }}
                  className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                >
                  Rotate API Token
                </button>
              )}
            </div>
          </div>
        )}

        {/* playit.gg Form */}
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

            {agent?.claimed && (
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSaveConfiguration}
                  disabled={isUpdating}
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
                >
                  {isUpdating ? "Connecting Tunnel..." : "Enable playit.gg Tunnel"}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Port Forwarding Form */}
        {draftMethod === "port_forward" && (
          <div className="space-y-4">
            <div className="max-w-xs space-y-1.5">
              <label htmlFor="external-port" className="block text-xs font-semibold text-gray-700 dark:text-gray-300">
                Requested External Port (Optional)
              </label>
              <input
                ref={firstInputRef}
                id="external-port"
                type="number"
                min={1}
                max={65535}
                value={externalPort ?? ""}
                onChange={(e) => {
                  const val = e.target.value;
                  setExternalPort(val ? parseInt(val, 10) : null);
                }}
                placeholder="Auto (8000)"
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
              />
              <p className="text-[11px] text-gray-500 dark:text-gray-400">
                Leave blank to request the standard panel port (8000).
              </p>
            </div>

            {panel?.upnp_last_result && (
              <div className="text-xs text-gray-600 dark:text-gray-300">
                <span className="font-medium">UPnP Status:</span>{" "}
                <code className="font-mono px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-[11px]">
                  {panel.upnp_last_result}
                </code>
              </div>
            )}

            <div className="pt-2">
              <button
                type="button"
                onClick={handleSaveConfiguration}
                disabled={isUpdating}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
              >
                {isUpdating ? "Configuring UPnP..." : "Enable Port Forwarding"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Disable Confirmation Modal */}
      {isConfirmDisableOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="disable-modal-title"
        >
          <div className="w-full max-w-md bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
            <div className="border-b border-gray-200 dark:border-gray-700 pb-3">
              <h3 id="disable-modal-title" className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                Disable Panel Exposure?
              </h3>
            </div>

            <p className="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
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
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDisable}
                disabled={isUpdating}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
              >
                {isUpdating ? "Disabling..." : "Confirm Disable"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
