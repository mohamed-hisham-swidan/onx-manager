import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useEffectiveConnectionState } from "@/stores/wsStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { ConnectionState } from "@/websocket/types";
import { BrandLogo } from "@/components/brand/BrandLogo";
import {
  SKIN_PRESETS,
  ACCENT_PRESETS,
  type Skin,
} from "@/tokens/storageKeys";

const WS_DOT: Record<ConnectionState, { dot: string; text: string; label: string; present: boolean }> = {
  connected: { dot: "bg-status-success", text: "text-status-success", label: "Live", present: true },
  connecting: { dot: "bg-text-muted", text: "text-text-muted", label: "Connecting…", present: true },
  reconnecting: { dot: "bg-status-warning", text: "text-status-warning", label: "Reconnecting…", present: true },
  disconnected: { dot: "bg-status-danger", text: "text-status-danger", label: "Offline", present: true },
  degraded: { dot: "bg-status-warning", text: "text-status-warning", label: "Degraded", present: true },
};

export function TopBar() {
  const logout = useAuthStore((s) => s.logout);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const skin = useUIStore((s) => s.skin);
  const setSkin = useUIStore((s) => s.setSkin);
  const density = useUIStore((s) => s.density);
  const setDensity = useUIStore((s) => s.setDensity);
  const toggleDensity = useUIStore((s) => s.toggleDensity);
  const accent = useUIStore((s) => s.accent);
  const setAccent = useUIStore((s) => s.setAccent);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleMobileSidebar = useUIStore((s) => s.toggleMobileSidebar);

  const operations = useOperationStore((s) => s.operations);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const openDrawer = useOperationStore((s) => s.openDrawer);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);

  const connectionState = useEffectiveConnectionState();
  const navigate = useNavigate();

  const [showWsDiagnostics, setShowWsDiagnostics] = useState(false);
  const [showThemeStudio, setShowThemeStudio] = useState(false);

  const activeOpList = Object.values(operations).filter(
    (op) => op.status === "RUNNING" || op.status === "PREPARING" || op.status === "QUEUED"
  );
  const hasActiveOps = activeOpList.length > 0;

  const ws = WS_DOT[connectionState] || WS_DOT.disconnected;

  const handleLogout = useCallback(() => {
    const api = createAuthenticatedApi();
    if (refreshToken) {
      api.logout({ refresh_token: refreshToken }).catch(() => {});
    }
    logout();
    navigate("/login");
  }, [refreshToken, logout, navigate]);

  const handleToggleSidebar = () => {
    if (typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches) {
      toggleSidebar();
    } else {
      toggleMobileSidebar();
    }
  };

  const handleToggleOpsDrawer = () => {
    if (activeDrawerId) {
      closeDrawer();
    } else if (hasActiveOps) {
      openDrawer(activeOpList[0].id);
    } else {
      const allOps = Object.values(operations);
      if (allOps.length > 0) {
        openDrawer(allOps[allOps.length - 1].id);
      }
    }
  };

  const handleToggleSkin = () => {
    const skinOrder: Skin[] = ["graphite", "azure", "emerald", "amethyst", "amber", "crimson"];
    const nextIdx = (skinOrder.indexOf(skin) + 1) % skinOrder.length;
    setSkin(skinOrder[nextIdx]);
  };

  return (
    <header className="fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-border-subtle bg-surface-card px-4 text-text-primary shadow-2xs">
      <div className="flex items-center gap-3">
        {isAuthenticated && (
          <button
            onClick={handleToggleSidebar}
            className="rounded-lg p-1.5 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus cursor-pointer"
            aria-label={sidebarOpen || mobileSidebarOpen ? "Close sidebar" : "Open sidebar"}
          >
            <Icon name="menu" size={22} />
          </button>
        )}
        <BrandLogo variant="full" size="sm" />
      </div>

      {isAuthenticated && (
        <div className="flex items-center gap-2">
          {/* Operations Drawer Trigger */}
          <button
            type="button"
            onClick={handleToggleOpsDrawer}
            aria-label="Background Operations"
            title={hasActiveOps ? `${activeOpList.length} operation(s) in progress` : "Background Operations"}
            className={`relative rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer ${
              hasActiveOps ? "text-accent-primary" : ""
            }`}
          >
            <Icon name="activity" size={18} />
            {hasActiveOps && (
              <span className="absolute right-1.5 top-1.5 flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-primary opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent-primary" />
              </span>
            )}
          </button>

          {/* WebSocket Pill & Diagnostic Popover */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setShowWsDiagnostics((v) => !v);
                setShowThemeStudio(false);
              }}
              className="flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-muted/50 px-2.5 py-1 transition-colors hover:bg-surface-hover cursor-pointer"
              role="status"
              aria-label={`Socket ${connectionState}`}
              title={
                connectionState === ConnectionState.DEGRADED
                  ? "WebSocket connected, but 1 or more subscriptions were rejected"
                  : `Live updates: ${connectionState === "connected" ? "connected" : connectionState}`
              }
            >
              <span className={`h-2 w-2 rounded-full ${ws.dot}`} />
              <span className={`text-xs font-semibold ${ws.text}`}>{ws.label}</span>
            </button>

            {showWsDiagnostics && (
              <div className="absolute right-0 top-full mt-2 w-64 rounded-xl border border-border-subtle bg-surface-card p-3 shadow-xl z-50 text-xs">
                <div className="flex items-center justify-between pb-2 border-b border-border-subtle font-semibold">
                  <span>Connection Diagnostics</span>
                  <button
                    onClick={() => setShowWsDiagnostics(false)}
                    className="text-text-muted hover:text-text-primary cursor-pointer"
                  >
                    <Icon name="x" size={14} />
                  </button>
                </div>
                <div className="mt-2 space-y-1.5 text-text-secondary">
                  <div className="flex justify-between">
                    <span>Status:</span>
                    <span className="font-medium text-text-primary capitalize">{connectionState}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Skin:</span>
                    <span className="font-medium text-text-primary capitalize">{skin}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Accent:</span>
                    <span className="font-medium text-text-primary capitalize">{accent}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Density:</span>
                    <span className="font-medium text-text-primary capitalize">{density}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Appearance & Theme Studio Popover Trigger */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setShowThemeStudio((v) => !v);
                setShowWsDiagnostics(false);
              }}
              className={`rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer ${
                showThemeStudio ? "bg-surface-hover text-accent-primary" : ""
              }`}
              aria-label="Appearance options"
              aria-expanded={showThemeStudio}
              title="Theme Studio & Appearance options"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width={18}
                height={18}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />
                <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
                <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />
                <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
                <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
              </svg>
            </button>

            {showThemeStudio && (
              <div
                className="absolute right-0 top-full mt-2 w-80 rounded-xl border border-border-subtle bg-surface-card p-3.5 shadow-xl z-50 text-xs text-text-primary"
                role="dialog"
                aria-label="Theme Studio"
              >
                <div className="flex items-center justify-between pb-2.5 border-b border-border-subtle">
                  <div className="flex items-center gap-1.5 font-semibold text-text-primary">
                    <span className="h-2 w-2 rounded-full bg-accent-primary" />
                    <span>Theme Studio</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowThemeStudio(false)}
                    className="rounded p-1 text-text-muted hover:bg-surface-hover hover:text-text-primary cursor-pointer"
                    aria-label="Close appearance popover"
                  >
                    <Icon name="x" size={14} />
                  </button>
                </div>

                {/* Skins Grid */}
                <div className="mt-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-semibold text-text-secondary uppercase tracking-wider text-[10px]">
                      Skin ({skin})
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {SKIN_PRESETS.map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => setSkin(preset.id)}
                        className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors cursor-pointer ${
                          skin === preset.id
                            ? "border-accent-primary bg-surface-active font-semibold text-text-primary"
                            : "border-border-subtle bg-surface-page/40 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                        }`}
                      >
                        <span
                          className="h-3.5 w-3.5 shrink-0 rounded-full border border-border-default"
                          style={{ backgroundColor: preset.preview.accent }}
                        />
                        <span className="truncate">{preset.name}</span>
                        <span className="sr-only">{preset.legacyName || preset.name}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Accent Swatches */}
                <div className="mt-3.5">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-semibold text-text-secondary uppercase tracking-wider text-[10px]">
                      Accent Color ({accent})
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-1 rounded-lg border border-border-subtle bg-surface-page/30 p-1.5">
                    {ACCENT_PRESETS.map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => setAccent(preset.id)}
                        aria-label={`Accent ${preset.name}`}
                        title={preset.name}
                        className={`relative flex h-6 w-6 items-center justify-center rounded-full border transition-transform hover:scale-110 cursor-pointer ${
                          accent === preset.id
                            ? "border-border-focus ring-2 ring-border-focus"
                            : "border-border-subtle"
                        }`}
                        style={{
                          backgroundColor:
                            preset.id === "theme" ? "var(--color-surface-hover)" : preset.swatch,
                        }}
                      >
                        {preset.id === "theme" ? (
                          <span className="text-[10px] font-bold text-text-muted">A</span>
                        ) : accent === preset.id ? (
                          <span className="h-1.5 w-1.5 rounded-full bg-accent-contrast-text" />
                        ) : null}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Mode & Density Controls */}
                <div className="mt-3.5 space-y-2 border-t border-border-subtle pt-3">
                  <div className="flex items-center justify-between">
                    <span className="text-text-secondary font-medium">Mode</span>
                    <div className="flex rounded-lg border border-border-subtle bg-surface-page/30 p-0.5">
                      <button
                        type="button"
                        onClick={() => setTheme("dark")}
                        className={`flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors cursor-pointer ${
                          theme === "dark"
                            ? "bg-surface-elevated font-semibold text-text-primary shadow-xs"
                            : "text-text-muted hover:text-text-primary"
                        }`}
                      >
                        <Icon name="moon" size={12} />
                        <span>Dark</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setTheme("light")}
                        className={`flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors cursor-pointer ${
                          theme === "light"
                            ? "bg-surface-elevated font-semibold text-text-primary shadow-xs"
                            : "text-text-muted hover:text-text-primary"
                        }`}
                      >
                        <Icon name="sun" size={12} />
                        <span>Light</span>
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-text-secondary font-medium">Density</span>
                    <div className="flex rounded-lg border border-border-subtle bg-surface-page/30 p-0.5">
                      <button
                        type="button"
                        onClick={() => setDensity("comfortable")}
                        className={`rounded-md px-2.5 py-1 transition-colors cursor-pointer ${
                          density === "comfortable"
                            ? "bg-surface-elevated font-semibold text-text-primary shadow-xs"
                            : "text-text-muted hover:text-text-primary"
                        }`}
                      >
                        Comfortable
                      </button>
                      <button
                        type="button"
                        onClick={() => setDensity("compact")}
                        className={`rounded-md px-2.5 py-1 transition-colors cursor-pointer ${
                          density === "compact"
                            ? "bg-surface-elevated font-semibold text-text-primary shadow-xs"
                            : "text-text-muted hover:text-text-primary"
                        }`}
                      >
                        Compact
                      </button>
                    </div>
                  </div>
                </div>

                {/* Footer link to settings */}
                <div className="mt-3.5 border-t border-border-subtle pt-2.5 flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      setShowThemeStudio(false);
                      navigate("/settings?tab=appearance");
                    }}
                    className="flex items-center gap-1 text-xs text-text-accent hover:underline cursor-pointer"
                  >
                    <span>Appearance settings</span>
                    <Icon name="chevron-right" size={12} />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Skin Toggle (Quick Cycle) */}
          <button
            type="button"
            onClick={handleToggleSkin}
            className="hidden sm:inline-flex items-center gap-1 rounded-lg border border-border-subtle px-2 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Toggle skin"
            title={`Current skin: ${skin}. Click to toggle.`}
          >
            <span className="h-2 w-2 rounded-full bg-accent-primary" />
            <span className="capitalize">{skin}</span>
          </button>

          {/* Density Toggle (Comfortable / Compact) */}
          <button
            type="button"
            onClick={toggleDensity}
            className="hidden sm:inline-flex items-center rounded-lg border border-border-subtle px-2 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Toggle density"
            title={`Density: ${density}. Click to switch.`}
          >
            <span className="capitalize">{density}</span>
          </button>

          {/* Theme Toggle (Dark / Light) */}
          <button
            onClick={toggleTheme}
            className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            aria-label="Toggle theme"
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
          </button>

          {/* Logout */}
          <button
            onClick={handleLogout}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-status-danger-bg hover:text-status-danger cursor-pointer"
          >
            Logout
          </button>
        </div>
      )}
    </header>
  );
}
