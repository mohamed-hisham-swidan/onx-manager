import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  ConnectGitHubModal,
  DisconnectGitHubModal,
  GitHubWebhookDeliveriesModal,
  RotateGitHubCredentialsModal,
} from "./GitHubModals";
import type {
  GitHubConnectionStatusResponse,
  GitHubWebhookDeliveryResponse,
} from "@/server_manager/types";

const mockApi = {
  generateGitHubDeployKey: vi.fn(),
  connectGitHub: vi.fn(),
  rotateGitHubCredentials: vi.fn(),
  disconnectGitHub: vi.fn(),
  listGitHubWebhookDeliveries: vi.fn(),
  redeliverGitHubWebhook: vi.fn(),
};

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => mockApi,
}));

function buildStatus(
  overrides: Partial<GitHubConnectionStatusResponse> = {},
): GitHubConnectionStatusResponse {
  return {
    server_id: "s1",
    connected: true,
    remote_url: "https://github.com/owner/repo.git",
    auth_method: "pat",
    credential_hint: "…abcd",
    deploy_public_key: null,
    webhook_enabled: false,
    webhook_path: null,
    sync_status: "idle",
    needs_reauth: false,
    last_error_code: null,
    last_error_message: null,
    last_fetch_at: null,
    last_push_at: null,
    remote_default_branch: "main",
    remote_head_sha: null,
    branches: [],
    created_at: null,
    updated_at: null,
    generated_webhook_secret: null,
    ...overrides,
  };
}

const delivery: GitHubWebhookDeliveryResponse = {
  id: "d-1",
  server_id: "s1",
  delivery_id: "del-abc",
  event_type: "push",
  ref: "refs/heads/main",
  before_sha: "1111111111111111",
  after_sha: "2222222222222222",
  payload_sha256: "sha",
  signature_valid: true,
  status: "processed",
  operation_id: "op-1",
  error_message: null,
  redelivery_count: 2,
  received_at: "2026-09-14T10:00:00Z",
  processed_at: "2026-09-14T10:00:05Z",
};

describe("GitHubModals", () => {
  const clipboardWriteText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: clipboardWriteText },
      configurable: true,
    });
  });

  it("ConnectGitHubModal connects with a PAT and omits webhook fields", async () => {
    const onConnected = vi.fn();
    const onClose = vi.fn();
    const response = buildStatus();
    mockApi.connectGitHub.mockResolvedValue(response);

    render(
      <ConnectGitHubModal
        isOpen
        serverId="s1"
        onConnected={onConnected}
        onClose={onClose}
      />,
    );

    fireEvent.change(screen.getByLabelText("GitHub Repository URL"), {
      target: { value: "https://github.com/owner/repo.git" },
    });
    fireEvent.change(screen.getByLabelText("Personal Access Token (PAT)"), {
      target: { value: "ghp_token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect Repository" }));

    await waitFor(() => expect(mockApi.connectGitHub).toHaveBeenCalledTimes(1));
    expect(mockApi.connectGitHub).toHaveBeenCalledWith("s1", {
      remote_url: "https://github.com/owner/repo.git",
      auth_method: "pat",
      credential_secret: "ghp_token",
      enable_webhook: false,
    });
    await waitFor(() => expect(onConnected).toHaveBeenCalledWith(response));
    expect(onClose).toHaveBeenCalled();
  });

  it("ConnectGitHubModal generates a deploy key, copies it, and shows the one-time webhook secret", async () => {
    const onConnected = vi.fn();
    const onClose = vi.fn();
    mockApi.generateGitHubDeployKey.mockResolvedValue({
      server_id: "s1",
      public_key_openssh: "ssh-ed25519 AAAAC3Nza test@onx",
      private_key_pem: "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY-----",
      fingerprint_sha256: "SHA256:abcdefghijklmnop",
    });
    const response = buildStatus({
      auth_method: "ssh_deploy_key",
      webhook_enabled: true,
      webhook_path: "/api/v1/webhooks/github/s1",
      generated_webhook_secret: "whsec_one_time_value",
    });
    mockApi.connectGitHub.mockResolvedValue(response);

    render(
      <ConnectGitHubModal
        isOpen
        serverId="s1"
        onConnected={onConnected}
        onClose={onClose}
      />,
    );

    fireEvent.change(screen.getByLabelText("GitHub Repository URL"), {
      target: { value: "git@github.com:owner/repo.git" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ed25519 SSH Deploy Key" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Generate Ed25519 Deploy Key" }),
    );

    expect(
      await screen.findByText("SHA256:abcdefghijklmnop"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("deploy-public-key-box")).toHaveValue(
      "ssh-ed25519 AAAAC3Nza test@onx",
    );

    fireEvent.click(screen.getByRole("button", { name: "Copy Public Key" }));
    expect(clipboardWriteText).toHaveBeenCalledWith(
      "ssh-ed25519 AAAAC3Nza test@onx",
    );

    fireEvent.click(
      screen.getByLabelText("Enable GitHub Webhook (HMAC-SHA256)"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Connect Repository" }));

    await waitFor(() => expect(mockApi.connectGitHub).toHaveBeenCalledTimes(1));
    expect(mockApi.connectGitHub).toHaveBeenCalledWith("s1", {
      remote_url: "git@github.com:owner/repo.git",
      auth_method: "ssh_deploy_key",
      credential_secret:
        "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY-----",
      enable_webhook: true,
      deploy_public_key: "ssh-ed25519 AAAAC3Nza test@onx",
    });

    const banner = await screen.findByTestId("one-time-webhook-secret-banner");
    expect(banner).toHaveTextContent("whsec_one_time_value");
    expect(screen.getByTestId("generated-webhook-secret-value")).toHaveTextContent(
      "whsec_one_time_value",
    );
    expect(banner).toHaveTextContent("/api/v1/webhooks/github/s1");
    expect(onConnected).toHaveBeenCalledWith(response);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("ConnectGitHubModal blocks short webhook secrets and renders backend auth errors", async () => {
    const onConnected = vi.fn();
    const onClose = vi.fn();

    render(
      <ConnectGitHubModal
        isOpen
        serverId="s1"
        onConnected={onConnected}
        onClose={onClose}
      />,
    );

    fireEvent.change(screen.getByLabelText("GitHub Repository URL"), {
      target: { value: "https://github.com/owner/repo.git" },
    });
    fireEvent.change(screen.getByLabelText("Personal Access Token (PAT)"), {
      target: { value: "ghp_token" },
    });
    fireEvent.click(
      screen.getByLabelText("Enable GitHub Webhook (HMAC-SHA256)"),
    );
    fireEvent.change(
      screen.getByLabelText("Custom Webhook Secret (optional, min 16 chars)"),
      { target: { value: "too-short" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Connect Repository" }));

    expect(
      await screen.findByText(
        "Custom webhook secret must be at least 16 characters.",
      ),
    ).toBeInTheDocument();
    expect(mockApi.connectGitHub).not.toHaveBeenCalled();

    mockApi.connectGitHub.mockRejectedValue(
      Object.assign(new Error("GitHub rejected the credential"), {
        code: "GITHUB_AUTH_FAILED",
        status: 409,
        detail: { needs_reauth: true },
      }),
    );
    fireEvent.change(
      screen.getByLabelText("Custom Webhook Secret (optional, min 16 chars)"),
      { target: { value: "long-enough-secret-value" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Connect Repository" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("GitHub authentication failed");
    expect(alert).toHaveTextContent("GITHUB_AUTH_FAILED");
    expect(onConnected).not.toHaveBeenCalled();
  });

  it("RotateGitHubCredentialsModal requires an action and supports webhook disable without conflicts", async () => {
    const onRotated = vi.fn();
    const onClose = vi.fn();
    const currentStatus = buildStatus({ webhook_enabled: true });
    const rotated = buildStatus({ generated_webhook_secret: null });

    const { unmount } = render(
      <RotateGitHubCredentialsModal
        isOpen
        serverId="s1"
        currentStatus={currentStatus}
        onRotated={onRotated}
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rotate Credentials" }));
    expect(
      await screen.findByText(
        "Select at least one credential or webhook rotation action.",
      ),
    ).toBeInTheDocument();
    expect(mockApi.rotateGitHubCredentials).not.toHaveBeenCalled();

    mockApi.rotateGitHubCredentials.mockResolvedValue(
      buildStatus({ generated_webhook_secret: "whsec_rotated" }),
    );
    fireEvent.change(
      screen.getByLabelText("New Personal Access Token (optional)"),
      { target: { value: "ghp_new_token" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Rotate Credentials" }));

    await waitFor(() =>
      expect(mockApi.rotateGitHubCredentials).toHaveBeenCalledWith("s1", {
        credential_secret: "ghp_new_token",
      }),
    );
    expect(
      await screen.findByTestId("one-time-webhook-secret-banner"),
    ).toHaveTextContent("whsec_rotated");
    expect(onRotated).toHaveBeenCalled();

    unmount();
    vi.clearAllMocks();
    mockApi.rotateGitHubCredentials.mockResolvedValue(rotated);

    render(
      <RotateGitHubCredentialsModal
        isOpen
        serverId="s1"
        currentStatus={currentStatus}
        onRotated={onRotated}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByLabelText("Disable webhook"));
    fireEvent.click(screen.getByRole("button", { name: "Rotate Credentials" }));

    await waitFor(() =>
      expect(mockApi.rotateGitHubCredentials).toHaveBeenCalledWith("s1", {
        disable_webhook: true,
      }),
    );
    const payload = mockApi.rotateGitHubCredentials.mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect(payload).not.toHaveProperty("enable_webhook");
    expect(payload).not.toHaveProperty("regenerate_webhook_secret");
    expect(payload).not.toHaveProperty("webhook_secret");
    await waitFor(() => expect(onRotated).toHaveBeenCalledWith(rotated));
    expect(onClose).toHaveBeenCalled();
  });

  it("DisconnectGitHubModal preserves local history and purges deliveries only when opted in", async () => {
    const onDisconnected = vi.fn();
    const onClose = vi.fn();
    const result = {
      server_id: "s1",
      disconnected: true,
      remote_url: "https://github.com/owner/repo.git",
      local_history_preserved: true,
      purged_deliveries: 0,
    };
    mockApi.disconnectGitHub.mockResolvedValue(result);

    const { unmount } = render(
      <DisconnectGitHubModal
        isOpen
        serverId="s1"
        remoteUrl="https://github.com/owner/repo.git"
        onDisconnected={onDisconnected}
        onClose={onClose}
      />,
    );

    expect(
      screen.getByText(/Local Git history is preserved/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect GitHub" }));

    await waitFor(() =>
      expect(mockApi.disconnectGitHub).toHaveBeenCalledWith("s1", false),
    );
    expect(onDisconnected).toHaveBeenCalledWith(result);
    expect(onClose).toHaveBeenCalled();

    unmount();
    vi.clearAllMocks();
    mockApi.disconnectGitHub.mockResolvedValue({
      ...result,
      purged_deliveries: 3,
    });

    render(
      <DisconnectGitHubModal
        isOpen
        serverId="s1"
        remoteUrl="https://github.com/owner/repo.git"
        onDisconnected={onDisconnected}
        onClose={onClose}
      />,
    );
    fireEvent.click(
      screen.getByLabelText("Also purge stored webhook delivery history"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Disconnect GitHub" }));

    await waitFor(() =>
      expect(mockApi.disconnectGitHub).toHaveBeenCalledWith("s1", true),
    );
    expect(onDisconnected).toHaveBeenCalledWith({
      ...result,
      purged_deliveries: 3,
    });
  });

  it("GitHubWebhookDeliveriesModal lists deliveries and redelivers them", async () => {
    const onRedelivered = vi.fn();
    const onClose = vi.fn();
    mockApi.listGitHubWebhookDeliveries.mockResolvedValue([delivery]);
    mockApi.redeliverGitHubWebhook.mockResolvedValue({
      server_id: "s1",
      delivery_id: "del-abc",
      event_type: "push",
      status: "queued",
      deduplicated: false,
      redelivered: true,
      redelivery_count: 3,
      operation_id: "op-9",
      received_at: "2026-09-14T10:00:00Z",
    });

    render(
      <GitHubWebhookDeliveriesModal
        isOpen
        serverId="s1"
        webhookEnabled
        webhookPath="/api/v1/webhooks/github/s1"
        onRedelivered={onRedelivered}
        onClose={onClose}
      />,
    );

    expect(await screen.findByText("del-abc")).toBeInTheDocument();
    expect(screen.getByText("refs/heads/main")).toBeInTheDocument();
    expect(screen.getByText("Valid HMAC")).toBeInTheDocument();
    expect(screen.getByText("processed")).toBeInTheDocument();
    expect(screen.getByText("Redeliveries: 2")).toBeInTheDocument();
    expect(screen.getByText("Operation: op-1")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Redeliver del-abc" }),
    );

    await waitFor(() =>
      expect(mockApi.redeliverGitHubWebhook).toHaveBeenCalledWith(
        "s1",
        "del-abc",
      ),
    );
    expect(await screen.findByTestId("webhook-redeliver-success")).toHaveTextContent(
      "Delivery del-abc queued for redelivery (operation op-9)",
    );
    await waitFor(() =>
      expect(mockApi.listGitHubWebhookDeliveries).toHaveBeenCalledTimes(2),
    );
    expect(onRedelivered).toHaveBeenCalled();
  });

  it("GitHubWebhookDeliveriesModal renders the empty state", async () => {
    mockApi.listGitHubWebhookDeliveries.mockResolvedValue([]);

    render(
      <GitHubWebhookDeliveriesModal
        isOpen
        serverId="s1"
        webhookEnabled={false}
        webhookPath={null}
        onClose={vi.fn()}
      />,
    );

    expect(
      await screen.findByText("No webhook deliveries recorded yet."),
    ).toBeInTheDocument();
    expect(screen.getByText("Webhook Disabled")).toBeInTheDocument();
  });
});
