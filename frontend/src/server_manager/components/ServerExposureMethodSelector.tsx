import { useState, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { PlayitClaimCard } from "@/server_manager/components/PlayitClaimCard";
import type {
  ExposureMethodType,
  ServerExposureResponse,
  AgentStatusResponse,
  ClaimResponse,
} from "@/types";

const FQDN_REGEX = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;

function isValidFQDN(val: string): boolean {
  const clean = val.trim().toLowerCase();
  return clean.length >= 4 && clean.length <= 253 && FQDN_REGEX.test(clean);
}

export interface ServerExposureMethodSelectorProps {
  exposure: ServerExposureResponse | null | undefined;
  agent: AgentStatusResponse | null | undefined;
  draftMethod: ExposureMethodType;
  onSelectMethod: (method: ExposureMethodType) => void;
  onSaveExposure: (params: {
    method: ExposureMethodType;
    desired_state: "ENABLED" | "DISABLED";
    cloudflare_token?: string;
    hostname?: string;
    acknowledged_warning?: boolean;
  }) => Promise<void> | void;
  onGenerateClaim: () => Promise<ClaimResponse | void>;
  onResetAgent: () => Promise<void>;
  claimData: ClaimResponse | null;
  isUpdating?: boolean;
  isGeneratingClaim?: boolean;
  isResettingAgent?: boolean;
  isReadOnly?: boolean;
}

export function ServerExposureMethodSelector({
  exposure,
  agent,
  draftMethod,
  onSelectMethod,
  onSaveExposure,
  onGenerateClaim,
  onResetAgent,
  claimData,
  isUpdating = false,
  isGeneratingClaim = false,
  isResettingAgent = false,
  isReadOnly = false,
}: ServerExposureMethodSelectorProps) {
  // Local form inputs
  const [cloudflareToken, setCloudflareToken] = useState("");
  const [hostname, setHostname] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [acknowledgedWarning, setAcknowledgedWarning] = useState(false);
  const [isRotatingToken, setIsRotatingToken] = useState(false);

  // Method switch confirmation state (F-75-17)
  const [pendingMethod, setPendingMethod] = useState<ExposureMethodType | null>(null);
  const [switchConfirmInput, setSwitchConfirmInput] = useState("");

  const firstInputRef = useRef<HTMLInputElement>(null);
  const switchInputRef = useRef<HTMLInputElement>(null);

  // Sync draft state from server exposure during rendering (React 19 pattern)
  const [syncedExposure, setSyncedExposure] = useState<ServerExposureResponse | null | undefined>(null);
  if (exposure && syncedExposure !== exposure) {
    setSyncedExposure(exposure);
    if (exposure.targets && exposure.targets[0]?.public_address && !hostname) {
      const cleanHost = exposure.targets[0].public_address.replace(/^https?:\/\//, "").split(":")[0];
      setHostname(cleanHost);
    }
  }

  const isCurrentEnabled = exposure?.desired_state === "ENABLED";
  const hasActiveTargets = Boolean(
    exposure?.targets?.some((t) => t.status === "ACTIVE")
  );

  // Method card click with safety guard (F-75-17)
  const handleCardClick = (method: ExposureMethodType) => {
    if (isReadOnly || method === draftMethod) return;

    // Check if live active tunnels exist on current method
    if (isCurrentEnabled && hasActiveTargets && exposure?.method !== method && exposure?.method !== "none") {
      setPendingMethod(method);
      setSwitchConfirmInput("");
      return;
    }

    onSelectMethod(method);
    setTimeout(() => firstInputRef.current?.focus(), 50);
  };

  const handleConfirmSwitch = () => {
    if (!pendingMethod) return;
    onSelectMethod(pendingMethod);
    setPendingMethod(null);
    setSwitchConfirmInput("");
    setTimeout(() => firstInputRef.current?.focus(), 50);
  };



  const handleSave = () => {
    if (isReadOnly || isUpdating) return;

    if (draftMethod === "none") {
      onSaveExposure({
        method: "none",
        desired_state: "DISABLED",
      });
      return;
    }

    if (draftMethod === "playit") {
      onSaveExposure({
        method: "playit",
        desired_state: "ENABLED",
      });
      return;
    }

    if (draftMethod === "port_forward") {
      onSaveExposure({
        method: "port_forward",
        desired_state: "ENABLED",
      });
      return;
    }

    if (draftMethod === "cloudflare_tcp") {
      if (!isValidFQDN(hostname) || !acknowledgedWarning) return;
      onSaveExposure({
        method: "cloudflare_tcp",
        desired_state: "ENABLED",
        cloudflare_token: cloudflareToken.trim() || undefined,
        hostname: hostname.trim().toLowerCase(),
        acknowledged_warning: true,
      });
    }
  };

  const isReclaimRequired = exposure?.aggregate_status === "RECLAIM_REQUIRED";

  return (
    <div className="space-y-6">
      {/* 4 Method Cards Grid */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
            Network Exposure Method
          </span>
          {isReadOnly && (
            <span className="text-[11px] text-gray-400 dark:text-gray-500 italic">
              View-only mode
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* 1. None / Local Only */}
          <button
            type="button"
            disabled={isReadOnly}
            onClick={() => handleCardClick("none")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "none"
                ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            } ${isReadOnly ? "cursor-default opacity-90" : ""}`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Not Exposed</h4>
              {draftMethod === "none" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Disabled. Reachable only via local LAN or private VPN.
            </p>
          </button>

          {/* 2. playit.gg (Recommended) */}
          <button
            type="button"
            disabled={isReadOnly}
            onClick={() => handleCardClick("playit")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "playit"
                ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            } ${isReadOnly ? "cursor-default opacity-90" : ""}`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">playit.gg</h4>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300">
                  Recommended
                </span>
              </div>
              {draftMethod === "playit" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Public edge tunnel via shared agent. Supports Java (TCP) & Bedrock/Voice (UDP). Works behind CGNAT.
            </p>
          </button>

          {/* 3. Port Forwarding */}
          <button
            type="button"
            disabled={isReadOnly}
            onClick={() => handleCardClick("port_forward")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "port_forward"
                ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            } ${isReadOnly ? "cursor-default opacity-90" : ""}`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Port Forward</h4>
              {draftMethod === "port_forward" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Router port forwarding via UPnP IGD. Direct public IP access.
            </p>
          </button>

          {/* 4. Cloudflare Named Tunnel (TCP) */}
          <button
            type="button"
            disabled={isReadOnly}
            onClick={() => handleCardClick("cloudflare_tcp")}
            className={`p-4 rounded-xl border text-left transition-all ${
              draftMethod === "cloudflare_tcp"
                ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20 shadow-sm"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
            } ${isReadOnly ? "cursor-default opacity-90" : ""}`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Cloudflare TCP</h4>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300">
                  Advanced
                </span>
              </div>
              {draftMethod === "cloudflare_tcp" && (
                <span className="text-xs font-medium text-blue-600 dark:text-blue-400">Selected</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              Encrypted TCP tunnel via custom domain. Requires client-side Modflared.
            </p>
          </button>
        </div>
      </div>

      {/* Configuration Panel for Selected Draft Method */}
      {!isReadOnly && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-800/60 p-5 space-y-4">
          {/* None Form */}
          {draftMethod === "none" && (
            <div className="space-y-4">
              <p className="text-xs text-gray-600 dark:text-gray-300">
                Network exposure is disabled. This Minecraft server is accessible only on the local network or through a configured VPN.
              </p>
              {isCurrentEnabled && (
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={isUpdating}
                  className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
                >
                  {isUpdating ? "Disabling..." : "Save & Disable Exposure"}
                </button>
              )}
            </div>
          )}

          {/* playit.gg Form */}
          {draftMethod === "playit" && (
            <div className="space-y-4">
              {/* If host agent is unclaimed, mount decoupled PlayitClaimCard */}
              {!agent?.claimed && (
                <PlayitClaimCard
                  claimed={Boolean(agent?.claimed)}
                  claimActive={Boolean(agent?.claim_active || claimData?.claim_code)}
                  claimCode={claimData?.claim_code}
                  claimUrl={claimData?.claim_url}
                  claimExpiresAt={claimData?.expires_at || agent?.claim_expires_at}
                  onGenerateClaim={async () => {
                    await onGenerateClaim();
                  }}
                  isGenerating={isGeneratingClaim}
                  onResetAgent={onResetAgent}
                  isResetting={isResettingAgent}
                  title="playit.gg Game Server Tunnel"
                  description="A playit claim authorizes this host to publish Minecraft game servers through encrypted edge tunnels."
                />
              )}

              {agent?.claimed && (
                <div className="space-y-3">
                  <div className="rounded-lg border border-green-200 bg-green-50/50 dark:border-green-800/40 dark:bg-green-900/10 p-4">
                    <div className="flex items-center gap-2 text-green-800 dark:text-green-300 font-semibold text-xs">
                      <Icon name="check" size={16} />
                      <span>Host playit.gg agent is claimed and active.</span>
                    </div>
                    <p className="text-xs text-gray-600 dark:text-gray-300 mt-1">
                      Applying playit exposure will establish tunnels for your configured server targets.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={isUpdating}
                    className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
                  >
                    {isUpdating ? "Applying..." : "Save & Apply playit.gg Exposure"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Port Forward Form */}
          {draftMethod === "port_forward" && (
            <div className="space-y-4">
              <p className="text-xs text-gray-600 dark:text-gray-300">
                Port Forwarding requests automatic port mapping on your local router via UPnP IGD. Your router must have UPnP enabled and be assigned a public IP (no carrier-grade NAT).
              </p>
              <button
                type="button"
                onClick={handleSave}
                disabled={isUpdating}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
              >
                {isUpdating ? "Applying..." : "Save & Enable Port Forwarding"}
              </button>
            </div>
          )}

          {/* Cloudflare TCP Form with Mandatory Warning & Checkbox (F-75-03) */}
          {draftMethod === "cloudflare_tcp" && (
            <div className="space-y-4">
              {/* Amber Player Warning Banner */}
              <div
                role="alert"
                className="p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 space-y-2"
              >
                <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold text-xs uppercase tracking-wider">
                  <Icon name="alert" size={16} />
                  <span>Mandatory Player Software Requirement</span>
                </div>
                <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
                  Unlike websites, Minecraft game traffic cannot be proxied natively over standard DNS through Cloudflare. To connect to a Cloudflare TCP tunnel, all connecting players must install the <strong>Modflared</strong> client mod or run <code>cloudflared access tcp</code> on their computers.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Hostname */}
                <div className="space-y-1.5">
                  <label
                    htmlFor="cloudflare-tcp-hostname"
                    className="block text-xs font-semibold text-gray-700 dark:text-gray-300"
                  >
                    Custom Domain / FQDN <span className="text-red-500">*</span>
                  </label>
                  <input
                    ref={firstInputRef}
                    id="cloudflare-tcp-hostname"
                    type="text"
                    value={hostname}
                    onChange={(e) => setHostname(e.target.value)}
                    placeholder="play.example.com"
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                  />
                  {hostname && !isValidFQDN(hostname) ? (
                    <p className="text-[11px] text-red-600 dark:text-red-400">
                      Please enter a valid fully-qualified domain name (e.g. play.example.com).
                    </p>
                  ) : (
                    <p className="text-[11px] text-gray-500 dark:text-gray-400">
                      Must be an active zone in your Cloudflare account.
                    </p>
                  )}
                </div>

                {/* Cloudflare Token */}
                <div className="space-y-1.5">
                  <label
                    htmlFor="cloudflare-tcp-token"
                    className="block text-xs font-semibold text-gray-700 dark:text-gray-300"
                  >
                    Cloudflare API Token {exposure?.has_cloudflare_credentials && !isRotatingToken && !isReclaimRequired ? "(Stored)" : <span className="text-red-500">*</span>}
                  </label>
                  <div className="relative">
                    <input
                      id="cloudflare-tcp-token"
                      type={showToken ? "text" : "password"}
                      value={cloudflareToken}
                      onChange={(e) => setCloudflareToken(e.target.value)}
                      placeholder={
                        exposure?.has_cloudflare_credentials && !isRotatingToken && !isReclaimRequired
                          ? "••••••••••••••••••••••••••••••••"
                          : "Enter Cloudflare API token..."
                      }
                      className="w-full px-3 py-2 pr-10 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken(!showToken)}
                      aria-label={showToken ? "Hide token" : "Show token"}
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

              {/* Mandatory Checkbox Gate (F-75-03) */}
              <div className="pt-1">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acknowledgedWarning}
                    onChange={(e) => setAcknowledgedWarning(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700"
                  />
                  <span className="text-xs text-gray-700 dark:text-gray-300 font-medium">
                    I understand that players must use Modflared or cloudflared client to connect.
                  </span>
                </label>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={
                    isUpdating ||
                    !isValidFQDN(hostname) ||
                    !acknowledgedWarning ||
                    (!cloudflareToken && (!exposure?.has_cloudflare_credentials || isRotatingToken || isReclaimRequired))
                  }
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
                >
                  {isUpdating ? "Configuring..." : "Enable Cloudflare Tunnel"}
                </button>

                {exposure?.has_cloudflare_credentials && !isRotatingToken && !isReclaimRequired && (
                  <button
                    type="button"
                    onClick={() => {
                      setIsRotatingToken(true);
                      setCloudflareToken("");
                    }}
                    className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  >
                    Rotate Token
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Method Switch Typed Confirmation Modal (F-75-17) */}
      <Modal
        open={Boolean(pendingMethod)}
        onClose={() => {
          setPendingMethod(null);
          setSwitchConfirmInput("");
        }}
        title={
          <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
            <Icon name="alert" size={20} />
            <span>Switch Exposure Method?</span>
          </div>
        }
        description="Changing exposure method will disconnect active tunnels and re-provision targets under the new method. Active player connections will be dropped."
        size="md"
        closeOnBackdrop={false}
        closeOnEscape={true}
        closeButtonAriaLabel="Close dialog"
        initialFocusRef={switchInputRef}
      >
        <div className="space-y-4">
          <div className="space-y-2 rounded-lg bg-amber-50 p-3.5 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40">
            <label
              htmlFor="switch-typed-input"
              className="block text-xs font-semibold text-amber-900 dark:text-amber-300"
            >
              Type <span className="font-mono underline">SWITCH</span> to confirm:
            </label>
            <input
              ref={switchInputRef}
              id="switch-typed-input"
              type="text"
              value={switchConfirmInput}
              onChange={(e) => setSwitchConfirmInput(e.target.value)}
              placeholder='Type "SWITCH"'
              className="w-full px-3 py-2 rounded-lg border border-amber-300 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-amber-500 focus:border-transparent outline-none transition-all"
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={() => {
                setPendingMethod(null);
                setSwitchConfirmInput("");
              }}
              className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmSwitch}
              disabled={switchConfirmInput.trim() !== "SWITCH"}
              className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-medium transition-colors disabled:opacity-40 shadow-sm"
            >
              Switch Method
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
