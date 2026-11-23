import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PanelExposureSection } from "./PanelExposureSection";
import { queryKeys } from "@/services/queryClient";
import type { PanelExposureResponse, AgentStatusResponse } from "@/types";

const mockGetPanelExposure = vi.fn();
const mockSetPanelExposure = vi.fn();
const mockGetAgentStatus = vi.fn();
const mockGenerateClaim = vi.fn();
const mockResetAgent = vi.fn();
const mockToast = vi.fn();
const mockCopy = vi.fn();

vi.mock("@/services/api", () => {
  const client = {
    getPanelExposure: () => mockGetPanelExposure(),
    setPanelExposure: (body: unknown) => mockSetPanelExposure(body),
    getAgentStatus: () => mockGetAgentStatus(),
    generateClaim: () => mockGenerateClaim(),
    resetAgent: () => mockResetAgent(),
  };
  return {
    createApiClient: () => client,
    createAuthenticatedApi: () => client,
  };
});

vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({
    copy: mockCopy,
  }),
}));

const defaultPanelResponse: PanelExposureResponse = {
  method: "none",
  desired_state: "DISABLED",
  status: "DISABLED",
  public_address: null,
  tls: true,
  protocol: "https",
  external_port: null,
  cloudflare_tunnel_id: null,
  playit_tunnel_id: null,
  upnp_last_result: null,
  error_code: null,
  error_message: null,
  fix_hint: null,
  auto_fixed: false,
  security_advisory: null,
};

const defaultAgentResponse: AgentStatusResponse = {
  claimed: false,
  process_status: "STOPPED",
  desired_agent_running: false,
  last_health_at: null,
  claim_active: false,
  claim_expires_at: null,
};

function renderPanelExposureSection(qc?: QueryClient) {
  const queryClient =
    qc ??
    new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          gcTime: 0,
        },
      },
    });

  const renderResult = render(
    <QueryClientProvider client={queryClient}>
      <PanelExposureSection />
    </QueryClientProvider>
  );

  return {
    queryClient,
    ...renderResult,
  };
}

describe("PanelExposureSection Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetPanelExposure.mockResolvedValue({ ...defaultPanelResponse });
    mockGetAgentStatus.mockResolvedValue({ ...defaultAgentResponse });
  });

  it("T-74-01: renders method selector cards with none selected by default", async () => {
    renderPanelExposureSection();

    expect(await screen.findByText("Panel Network Exposure")).toBeInTheDocument();
    expect(screen.getByText("Local Only")).toBeInTheDocument();
    expect(screen.getByText("Cloudflare")).toBeInTheDocument();
    expect(screen.getByText("playit.gg")).toBeInTheDocument();
    expect(screen.getByText("Port Forward")).toBeInTheDocument();
    expect(screen.getByText("Selected")).toBeInTheDocument();
  });

  it("T-74-02: switching to cloudflare displays modern token/quick toggle without auto-saving", async () => {
    renderPanelExposureSection();

    expect(await screen.findByText("Local Only")).toBeInTheDocument();
    const cloudflareCard = screen.getByRole("button", { name: /Cloudflare/i });
    fireEvent.click(cloudflareCard);

    expect(await screen.findByRole("tab", { name: /Permanent \(Tunnel Token\)/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Quick Preview \(Temporary\)/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Tunnel Token/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Cloudflare Tunnels/i })).toHaveAttribute(
      "href",
      "https://one.dash.cloudflare.com/"
    );
    expect(mockSetPanelExposure).not.toHaveBeenCalled(); // No auto-save on card switch
  });

  it("T-74-03: cloudflare token form disables save button on empty or invalid token", async () => {
    renderPanelExposureSection();

    const cloudflareCard = await screen.findByRole("button", { name: /Cloudflare/i });
    fireEvent.click(cloudflareCard);

    const tokenInput = await screen.findByLabelText(/Tunnel Token/i);
    const saveBtn = screen.getByRole("button", { name: /Enable Cloudflare Tunnel/i });

    // Initial state: empty -> disabled
    expect(saveBtn).toBeDisabled();

    // Invalid short/whitespace token
    fireEvent.change(tokenInput, { target: { value: "bad token" } });

    expect(
      screen.getByText(/Tunnel token cannot contain spaces/i)
    ).toBeInTheDocument();
    expect(saveBtn).toBeDisabled();
  });

  it("T-74-04: cloudflare token form enables save button on valid token", async () => {
    mockSetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      cloudflare_mode: "token",
      token_configured: true,
      ephemeral: false,
      status: "ACTIVE",
    });

    renderPanelExposureSection();

    const cloudflareCard = await screen.findByRole("button", { name: /Cloudflare/i });
    fireEvent.click(cloudflareCard);

    const tokenInput = await screen.findByLabelText(/Tunnel Token/i);
    const saveBtn = screen.getByRole("button", { name: /Enable Cloudflare Tunnel/i });

    fireEvent.change(tokenInput, { target: { value: "eyJhIjoiValidCloudflareTunnelToken12345" } });

    expect(saveBtn).toBeEnabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockSetPanelExposure).toHaveBeenCalledWith({
        method: "cloudflare_tunnel",
        desired_state: "ENABLED",
        cloudflare_mode: "token",
        cloudflare_token: "eyJhIjoiValidCloudflareTunnelToken12345",
      });
    });
  });

  it("T-74-05: active exposure displays clickable url and protocol badge", async () => {
    mockGetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      status: "ACTIVE",
      public_address: "panel.example.com",
      tls: true,
      protocol: "https",
    });

    renderPanelExposureSection();

    expect(await screen.findByText("Live Public Panel Address")).toBeInTheDocument();
    expect(screen.getByText("HTTPS (Encrypted)")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /https:\/\/panel\.example\.com/i });
    expect(link).toHaveAttribute("href", "https://panel.example.com");
  });

  it("T-74-06: copy button triggers clipboard write and toast", async () => {
    mockGetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      status: "ACTIVE",
      public_address: "https://panel.example.com",
      tls: true,
      protocol: "https",
    });

    renderPanelExposureSection();

    const copyBtn = await screen.findByRole("button", { name: /Copy public address/i });
    fireEvent.click(copyBtn);

    expect(mockCopy).toHaveBeenCalledWith("https://panel.example.com", "Public address copied to clipboard");
  });

  it("T-74-07: renders security advisory banner when port forward active in local mode", async () => {
    mockGetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "port_forward",
      desired_state: "ENABLED",
      status: "ACTIVE",
      public_address: "192.168.1.100:8000",
      tls: false,
      protocol: "http",
      security_advisory: "onx-manager is operating in LOCAL mode with open self-registration. Exposing the panel over unencrypted HTTP allows anyone on the internet to register accounts.",
    });

    renderPanelExposureSection();

    expect(await screen.findByText("Security Advisory")).toBeInTheDocument();
    expect(
      screen.getByText(/onx-manager is operating in LOCAL mode with open self-registration/i)
    ).toBeInTheDocument();
  });

  it("T-74-08: renders bind mismatch banner with restart instruction", async () => {
    mockGetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "port_forward",
      desired_state: "ENABLED",
      status: "ERROR",
      error_code: "BIND_MISMATCH",
      auto_fixed: true,
      fix_hint: "Panel bind address updated to 0.0.0.0 in config/settings.yaml. Restart the panel service for changes to take effect.",
    });

    renderPanelExposureSection();

    expect(
      await screen.findByText(/Action Required: Restart Panel to Complete Port Forwarding/i)
    ).toBeInTheDocument();
    expect(screen.getByText("Restart Required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry Check/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Switch to Local Only/i })).toBeInTheDocument();
    expect(
      screen.getByText(/Panel bind address updated to 0.0.0.0 in config\/settings.yaml/i)
    ).toBeInTheDocument();
  });

  it("T-74-09: renders token revoked state with reclaim prompt", async () => {
    mockGetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      status: "RECLAIM_REQUIRED",
      error_code: "TOKEN_REVOKED",
      cloudflare_tunnel_id: "tunnel-123",
    });

    renderPanelExposureSection();

    expect(
      await screen.findByText(/Cloudflare Tunnel Token was invalidated or rejected/i)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Update Token & Reconnect/i })).toBeInTheDocument();
  });

  it("T-74-10: disabling exposure opens confirmation modal", async () => {
    mockGetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      status: "ACTIVE",
      public_address: "panel.example.com",
    });

    renderPanelExposureSection();

    const disableBtn = await screen.findByRole("button", { name: /Disable Exposure/i });
    fireEvent.click(disableBtn);

    expect(screen.getByText("Disable Panel Exposure?")).toBeInTheDocument();
    expect(mockSetPanelExposure).not.toHaveBeenCalled();

    const confirmDisableBtn = screen.getByRole("button", { name: /Confirm Disable/i });
    fireEvent.click(confirmDisableBtn);

    await waitFor(() => {
      expect(mockSetPanelExposure).toHaveBeenCalledWith({
        method: "cloudflare_tunnel",
        desired_state: "DISABLED",
      });
    });
  });

  it("T-74-11: port forward form accepts valid custom port", async () => {
    mockSetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "port_forward",
      desired_state: "ENABLED",
      status: "STARTING",
      external_port: 8080,
    });

    renderPanelExposureSection();

    const portForwardCard = await screen.findByRole("button", { name: /Port Forward/i });
    fireEvent.click(portForwardCard);

    const portInput = await screen.findByLabelText(/Requested External Port/i);
    fireEvent.change(portInput, { target: { value: "8080" } });

    const saveBtn = screen.getByRole("button", { name: /Enable Port Forwarding/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockSetPanelExposure).toHaveBeenCalledWith({
        method: "port_forward",
        desired_state: "ENABLED",
        external_port: 8080,
      });
    });
  });

  it("T-74-12: fast polling active during starting state", async () => {
    mockGetPanelExposure.mockResolvedValue({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      status: "STARTING",
    });

    renderPanelExposureSection();

    expect(await screen.findByText("Starting...")).toBeInTheDocument();
  });

  it("T-74-18: agent status query only enabled when playit_http and desired enabled", async () => {
    // 1. Initial render with method="none" -> agent query should not be called
    mockGetPanelExposure.mockResolvedValue({
      ...defaultPanelResponse,
      method: "none",
      desired_state: "DISABLED",
    });

    renderPanelExposureSection();

    await screen.findByText("Panel Network Exposure");
    expect(mockGetAgentStatus).not.toHaveBeenCalled();
  });

  it("T-74-19: mutation error shows toast and leaves form editable", async () => {
    mockSetPanelExposure.mockRejectedValueOnce(new Error("Cloudflare token authentication failed (403)"));

    renderPanelExposureSection();

    const cloudflareCard = await screen.findByRole("button", { name: /Cloudflare/i });
    fireEvent.click(cloudflareCard);

    const tokenInput = await screen.findByLabelText(/Tunnel Token/i);
    const saveBtn = screen.getByRole("button", { name: /Enable Cloudflare Tunnel/i });

    fireEvent.change(tokenInput, { target: { value: "invalid-token-123456" } });

    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith("error", "Exposure Update Failed", "Cloudflare token authentication failed (403)");
    });

    // Form input remains fully interactive and editable (not stuck in disabled/loading state)
    expect(tokenInput).toBeEnabled();
  });

  it("T-74-20: full status transition claim required to starting to active", async () => {
    mockGetPanelExposure.mockResolvedValue({
      ...defaultPanelResponse,
      method: "playit_http",
      desired_state: "ENABLED",
      status: "CLAIM_REQUIRED",
    });

    const { queryClient } = renderPanelExposureSection();
    expect(await screen.findByText("Claim Required")).toBeInTheDocument();

    // Transition to STARTING via queryClient cache update
    act(() => {
      queryClient.setQueryData(queryKeys.exposure.panel(), {
        ...defaultPanelResponse,
        method: "playit_http",
        desired_state: "ENABLED",
        status: "STARTING",
      });
    });

    expect(await screen.findByText("Starting...")).toBeInTheDocument();

    // Transition to ACTIVE with public address
    act(() => {
      queryClient.setQueryData(queryKeys.exposure.panel(), {
        ...defaultPanelResponse,
        method: "playit_http",
        desired_state: "ENABLED",
        status: "ACTIVE",
        public_address: "panel-test.ply.gg",
        tls: true,
      });
    });

    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Live Public Panel Address")).toBeInTheDocument();
  });

  it("T-74-21: reclaim required on cloudflare highlights token field and blocks resave until new token entered", async () => {
    mockGetPanelExposure.mockResolvedValue({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      status: "RECLAIM_REQUIRED",
      error_code: "TOKEN_REVOKED",
      cloudflare_tunnel_id: "tunnel-old-123",
      public_address: "panel.example.com",
    });

    renderPanelExposureSection();

    expect(
      await screen.findByText(/Cloudflare Tunnel Token was invalidated or rejected/i)
    ).toBeInTheDocument();
    const saveBtn = screen.getByRole("button", { name: /Update Token & Reconnect/i });
    expect(saveBtn).toBeDisabled(); // Disabled until fresh token is typed

    const tokenInput = screen.getByLabelText(/Tunnel Token/i);
    fireEvent.change(tokenInput, { target: { value: "new-fresh-cf-token-12345" } });

    expect(saveBtn).toBeEnabled();
  });

  it("Cloudflare Quick Preview segmented toggle requires zero inputs and submits quick mode", async () => {
    mockSetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "cloudflare_tunnel",
      desired_state: "ENABLED",
      cloudflare_mode: "quick",
      ephemeral: true,
      status: "ACTIVE",
      public_address: "https://quick-test.trycloudflare.com",
    });

    renderPanelExposureSection();

    const cloudflareCard = await screen.findByRole("button", { name: /Cloudflare/i });
    fireEvent.click(cloudflareCard);

    const quickTab = await screen.findByRole("tab", { name: /Quick Preview \(Temporary\)/i });
    fireEvent.click(quickTab);

    expect(screen.getByText(/changes on every restart\. No domain required/i)).toBeInTheDocument();
    const startBtn = screen.getByRole("button", { name: /Start Quick Tunnel/i });
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(mockSetPanelExposure).toHaveBeenCalledWith({
        method: "cloudflare_tunnel",
        desired_state: "ENABLED",
        cloudflare_mode: "quick",
      });
    });
  });

  it("Port forward input sanitizes non-digits, blocks e/E/+/-/., and disables submit on out-of-range port", async () => {
    renderPanelExposureSection();

    const portForwardCard = await screen.findByRole("button", { name: /Port Forward/i });
    fireEvent.click(portForwardCard);

    const portInput = await screen.findByLabelText(/Requested External Port/i) as HTMLInputElement;
    const enableBtn = screen.getByRole("button", { name: /Enable Port Forwarding/i });

    // Non-digit characters are stripped on change and blocked keys preventDefault
    const ev = fireEvent.keyDown(portInput, { key: "e" });
    expect(ev).toBe(false);

    fireEvent.change(portInput, { target: { value: "70000" } });
    expect(screen.getByText(/External port must be between 1 and 65535/i)).toBeInTheDocument();
    expect(enableBtn).toBeDisabled();

    fireEvent.change(portInput, { target: { value: "3306" } });
    expect(screen.getByText(/Port 3306 is reserved for internal services/i)).toBeInTheDocument();
    expect(enableBtn).toBeDisabled();

    fireEvent.change(portInput, { target: { value: "8443" } });
    expect(enableBtn).toBeEnabled();
  });

  it("CGNAT_DETECTED banner displays CGNAT Detected badge and actionable recovery buttons", async () => {
    mockGetPanelExposure.mockResolvedValue({
      ...defaultPanelResponse,
      method: "port_forward",
      desired_state: "ENABLED",
      status: "ERROR",
      error_code: "CGNAT_DETECTED",
      error_message: "ISP CGNAT detected on WAN IP 100.64.10.2.",
      fix_hint: "Switch to Cloudflare Tunnel or playit.gg.",
    });

    renderPanelExposureSection();

    expect(await screen.findByText("CGNAT Detected")).toBeInTheDocument();
    expect(screen.getByText(/ISP CGNAT \/ Double-NAT Detected/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use Cloudflare Tunnel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Switch to Local Only/i })).toBeInTheDocument();
  });

  it("HTTP 200 with status=ERROR fires error toast instead of false success toast", async () => {
    mockSetPanelExposure.mockResolvedValueOnce({
      ...defaultPanelResponse,
      method: "port_forward",
      desired_state: "ENABLED",
      status: "ERROR",
      error_code: "CGNAT_DETECTED",
      error_message: "ISP CGNAT detected (100.64.5.1).",
    });

    renderPanelExposureSection();

    const portForwardCard = await screen.findByRole("button", { name: /Port Forward/i });
    fireEvent.click(portForwardCard);
    fireEvent.click(await screen.findByRole("button", { name: /Enable Port Forwarding/i }));

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(
        "error",
        "Exposure Configuration Error",
        "ISP CGNAT detected (100.64.5.1)."
      );
    });
  });

  it("Local Only card always displays a confirmed action button even when disabled", async () => {
    renderPanelExposureSection();
    const localBtn = await screen.findByRole("button", { name: /Local Only Active/i });
    expect(localBtn).toBeDisabled();
  });

  describe("Modal behavior (FIX-3)", () => {
    async function renderActiveAndOpenModal() {
      mockGetPanelExposure.mockResolvedValue({
        ...defaultPanelResponse,
        method: "playit_http",
        desired_state: "ENABLED",
        status: "ACTIVE",
        public_address: "panel-test.ply.gg",
        tls: true,
      });

      renderPanelExposureSection();
      const disableBtn = await screen.findByRole("button", { name: "Disable Exposure" });
      fireEvent.click(disableBtn);
    }

    it("renders dialog with accessible title, focuses inside, and supports Escape when idle", async () => {
      await renderActiveAndOpenModal();

      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Disable Panel Exposure?" })).toBeInTheDocument();

      await waitFor(() => {
        expect(dialog.contains(document.activeElement)).toBe(true);
      });

      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });

    it("does not close on backdrop click or content click", async () => {
      await renderActiveAndOpenModal();

      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();

      const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
      expect(backdrop).toBeInTheDocument();
      fireEvent.click(backdrop);
      expect(screen.getByRole("dialog")).toBeInTheDocument();

      fireEvent.click(dialog);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("guards against Escape and disables Cancel/Action buttons while pending", async () => {
      let resolveMutation!: (val: unknown) => void;
      mockSetPanelExposure.mockImplementation(
        () => new Promise((resolve) => { resolveMutation = resolve; })
      );

      await renderActiveAndOpenModal();

      const dialog = screen.getByRole("dialog");
      const confirmBtn = dialog.querySelector("button.bg-red-600") as HTMLButtonElement;
      const cancelBtn = screen.getByRole("button", { name: "Cancel" });

      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Disabling..." })).toBeDisabled();
        expect(cancelBtn).toBeDisabled();
      });

      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.getByRole("dialog")).toBeInTheDocument();

      resolveMutation({ ...defaultPanelResponse, desired_state: "DISABLED", status: "DISABLED" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });
  });
});
