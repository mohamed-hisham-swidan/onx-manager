import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import type {
  ConnectGitHubRequest,
  GenerateGitHubDeployKeyResponse,
  GitHubAuthMethod,
  GitHubConnectionStatusResponse,
  GitHubDisconnectResponse,
  GitHubWebhookDeliveryResponse,
  GitHubWebhookIngestResponse,
  RotateGitHubCredentialsRequest,
} from "@/server_manager/types";

const inputClass =
  "w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50";
const labelClass = "block text-xs font-medium text-text-secondary mb-1";
const secondaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const primaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shadow-xs transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const dangerButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg border border-status-danger-border bg-status-danger-bg px-3.5 py-1.5 text-xs font-semibold text-status-danger hover:bg-status-danger/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const errorAlertClass =
  "rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger";
const badgeClass =
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold";

interface ParsedApiError {
  code: string | null;
  status: number | null;
  message: string;
  detail: Record<string, unknown> | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseApiError(err: unknown, fallback: string): ParsedApiError {
  const rec = isRecord(err) ? err : null;
  const rawDetail = rec?.detail;
  const detail = isRecord(rawDetail) ? rawDetail : null;
  const detailMessage =
    detail && typeof detail.message === "string" ? detail.message : null;
  return {
    code: typeof rec?.code === "string" ? rec.code : null,
    status: typeof rec?.status === "number" ? rec.status : null,
    message:
      err instanceof Error && err.message
        ? err.message
        : detailMessage ?? fallback,
    detail,
  };
}

function formatGitHubError(err: unknown, fallback: string): string {
  const info = parseApiError(err, fallback);
  let base = fallback;
  if (info.code === "GIT_REMOTE_URL_INVALID") {
    base =
      "Invalid GitHub repository URL. Use https://github.com/owner/repo.git for PAT or git@github.com:owner/repo.git for SSH deploy keys.";
  } else if (info.code === "GITHUB_AUTH_FAILED") {
    base =
      "GitHub authentication failed. Verify the credential has Contents (Read and write) permission, then rotate or reconnect.";
  } else if (info.code === "VALIDATION_ERROR") {
    base = "The GitHub request was rejected by validation.";
  }

  const parts = [base];
  if (info.message && info.message !== base) {
    parts.push(info.message);
  }
  if (info.code) {
    parts.push(
      info.status ? `(${info.code} · HTTP ${info.status})` : `(${info.code})`,
    );
  } else if (info.status) {
    parts.push(`(HTTP ${info.status})`);
  }
  return parts.join(" ");
}

function useCopyFeedback() {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const copy = useCallback((text: string, key: string) => {
    const clipboard = navigator.clipboard;
    if (clipboard?.writeText) {
      void clipboard.writeText(text).catch(() => undefined);
    }
    setCopiedKey(key);
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = window.setTimeout(() => setCopiedKey(null), 2000);
  }, []);

  return { copiedKey, copy };
}

interface AuthMethodToggleProps {
  value: GitHubAuthMethod;
  onChange: (value: GitHubAuthMethod) => void;
  disabled?: boolean;
}

function AuthMethodToggle({
  value,
  onChange,
  disabled = false,
}: AuthMethodToggleProps) {
  return (
    <div
      role="group"
      aria-label="Authentication Method"
      className="grid grid-cols-1 gap-2 sm:grid-cols-2"
    >
      <button
        type="button"
        aria-pressed={value === "pat"}
        onClick={() => onChange("pat")}
        disabled={disabled}
        className={`rounded-lg border px-3 py-2 text-left text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50 ${
          value === "pat"
            ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
            : "border-border-default bg-surface-page text-text-secondary hover:bg-surface-hover"
        }`}
      >
        Fine-Grained PAT
      </button>
      <button
        type="button"
        aria-pressed={value === "ssh_deploy_key"}
        onClick={() => onChange("ssh_deploy_key")}
        disabled={disabled}
        className={`rounded-lg border px-3 py-2 text-left text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50 ${
          value === "ssh_deploy_key"
            ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
            : "border-border-default bg-surface-page text-text-secondary hover:bg-surface-hover"
        }`}
      >
        Ed25519 SSH Deploy Key
      </button>
    </div>
  );
}

interface DeployKeyDisplayProps {
  generatedKey: GenerateGitHubDeployKeyResponse;
  copied: boolean;
  onCopyPublicKey: () => void;
}

function DeployKeyDisplay({
  generatedKey,
  copied,
  onCopyPublicKey,
}: DeployKeyDisplayProps) {
  return (
    <div className="space-y-2 rounded-lg border border-border-subtle bg-surface-page p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-text-primary">
          SHA-256 Fingerprint
        </div>
        <button
          type="button"
          onClick={onCopyPublicKey}
          className={secondaryButtonClass}
        >
          <Icon name="copy" size={12} />
          {copied ? "Copied!" : "Copy Public Key"}
        </button>
      </div>
      <p
        data-testid="deploy-key-fingerprint"
        className="break-all font-mono text-[11px] text-text-secondary"
      >
        {generatedKey.fingerprint_sha256}
      </p>
      <label htmlFor="deploy-public-key" className={labelClass}>
        OpenSSH Public Key
      </label>
      <textarea
        id="deploy-public-key"
        data-testid="deploy-public-key-box"
        readOnly
        value={generatedKey.public_key_openssh}
        rows={4}
        className={`${inputClass} font-mono text-[11px]`}
      />
      <p className="text-[11px] text-text-muted">
        Add this public key under GitHub Repo -&gt; Settings -&gt; Deploy keys
        and enable &quot;Allow write access&quot; before clicking Connect.
      </p>
    </div>
  );
}

interface OneTimeWebhookSecretPanelProps {
  secret: string;
  webhookPath: string | null;
  copiedKey: string | null;
  onCopy: (text: string, key: string) => void;
  onDone: () => void;
}

function OneTimeWebhookSecretPanel({
  secret,
  webhookPath,
  copiedKey,
  onCopy,
  onDone,
}: OneTimeWebhookSecretPanelProps) {
  return (
    <div className="space-y-4">
      <div
        role="status"
        data-testid="one-time-webhook-secret-banner"
        className="space-y-3 rounded-lg border border-status-warning-border bg-status-warning-bg p-4 text-xs text-status-warning"
      >
        <div className="flex items-start gap-2">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
          <div className="space-y-1">
            <h3 className="text-sm font-semibold">
              Repository Connected — Save Your One-Time Webhook Secret
            </h3>
            <p>
              This secret is shown only once and cannot be retrieved again.
              Store it securely before closing this dialog.
            </p>
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="text-[11px] font-semibold">Webhook Secret</div>
          <div className="flex flex-wrap items-center gap-2">
            <code
              data-testid="generated-webhook-secret-value"
              className="min-w-0 flex-1 break-all rounded-lg border border-status-warning-border bg-surface-card px-3 py-2 font-mono text-[11px] text-text-primary"
            >
              {secret}
            </code>
            <button
              type="button"
              onClick={() => onCopy(secret, "secret")}
              className={secondaryButtonClass}
            >
              <Icon name="copy" size={12} />
              {copiedKey === "secret" ? "Copied!" : "Copy Secret"}
            </button>
          </div>
        </div>

        {webhookPath && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-semibold">Webhook Path</div>
            <div className="flex flex-wrap items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded-lg border border-border-default bg-surface-card px-3 py-2 font-mono text-[11px] text-text-primary">
                {webhookPath}
              </code>
              <button
                type="button"
                onClick={() => onCopy(webhookPath, "path")}
                className={secondaryButtonClass}
              >
                <Icon name="copy" size={12} />
                {copiedKey === "path" ? "Copied!" : "Copy Webhook Path"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <button type="button" onClick={onDone} className={primaryButtonClass}>
          <Icon name="check" size={13} />
          Done
        </button>
      </div>
    </div>
  );
}

// ==========================================
// 1. Connect GitHub Modal
// ==========================================
export interface ConnectGitHubModalProps {
  isOpen: boolean;
  serverId: string;
  onConnected: (status: GitHubConnectionStatusResponse) => void;
  onClose: () => void;
}

export function ConnectGitHubModal({
  isOpen,
  serverId,
  onConnected,
  onClose,
}: ConnectGitHubModalProps) {
  if (!isOpen) return null;
  return (
    <ConnectGitHubBody
      serverId={serverId}
      onConnected={onConnected}
      onClose={onClose}
    />
  );
}

interface ConnectGitHubBodyProps {
  serverId: string;
  onConnected: (status: GitHubConnectionStatusResponse) => void;
  onClose: () => void;
}

function ConnectGitHubBody({
  serverId,
  onConnected,
  onClose,
}: ConnectGitHubBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { copiedKey, copy } = useCopyFeedback();
  const [isPending, setIsPending] = useState(false);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [authMethod, setAuthMethod] = useState<GitHubAuthMethod>("pat");
  const [patToken, setPatToken] = useState("");
  const [deployComment, setDeployComment] = useState("");
  const [generatedKey, setGeneratedKey] =
    useState<GenerateGitHubDeployKeyResponse | null>(null);
  const [sshPrivateKey, setSshPrivateKey] = useState("");
  const [deployPublicKey, setDeployPublicKey] = useState("");
  const [isGeneratingKey, setIsGeneratingKey] = useState(false);
  const [enableWebhook, setEnableWebhook] = useState(false);
  const [webhookSecret, setWebhookSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [oneTimeResult, setOneTimeResult] =
    useState<GitHubConnectionStatusResponse | null>(null);

  const credential =
    authMethod === "pat" ? patToken.trim() : sshPrivateKey.trim();
  const canSubmit = Boolean(remoteUrl.trim()) && Boolean(credential);

  const handleGenerateKey = async () => {
    if (isGeneratingKey || isPending) return;
    setError(null);
    setIsGeneratingKey(true);
    try {
      const comment = deployComment.trim();
      const result = await api.generateGitHubDeployKey(
        serverId,
        comment ? { comment } : undefined,
      );
      setGeneratedKey(result);
      setSshPrivateKey(result.private_key_pem);
      setDeployPublicKey(result.public_key_openssh);
    } catch (err: unknown) {
      setError(
        formatGitHubError(err, "Failed to generate an Ed25519 deploy key."),
      );
    } finally {
      setIsGeneratingKey(false);
    }
  };

  const submitConnect = async () => {
    if (isPending) return;
    const trimmedUrl = remoteUrl.trim();
    const trimmedSecret = webhookSecret.trim();
    if (!trimmedUrl || !credential) {
      setError("Repository URL and authentication credential are required.");
      return;
    }
    if (
      enableWebhook &&
      trimmedSecret.length > 0 &&
      trimmedSecret.length < 16
    ) {
      setError("Custom webhook secret must be at least 16 characters.");
      return;
    }

    setError(null);
    setIsPending(true);
    try {
      const payload: ConnectGitHubRequest = {
        remote_url: trimmedUrl,
        auth_method: authMethod,
        credential_secret: credential,
        enable_webhook: enableWebhook,
        ...(authMethod === "ssh_deploy_key" && deployPublicKey.trim()
          ? { deploy_public_key: deployPublicKey.trim() }
          : {}),
        ...(enableWebhook && trimmedSecret
          ? { webhook_secret: trimmedSecret }
          : {}),
      };
      const response = await api.connectGitHub(serverId, payload);
      onConnected(response);
      if (response.generated_webhook_secret) {
        setOneTimeResult(response);
      } else {
        onClose();
      }
    } catch (err: unknown) {
      setError(
        formatGitHubError(err, "Failed to connect the GitHub repository."),
      );
    } finally {
      setIsPending(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submitConnect();
  };

  if (oneTimeResult?.generated_webhook_secret) {
    return (
      <Modal
        open={true}
        onClose={onClose}
        title="Connect GitHub Repository"
        size="lg"
        showCloseButton={false}
        closeOnBackdrop={false}
        closeOnEscape={true}
      >
        <OneTimeWebhookSecretPanel
          secret={oneTimeResult.generated_webhook_secret}
          webhookPath={oneTimeResult.webhook_path}
          copiedKey={copiedKey}
          onCopy={copy}
          onDone={onClose}
        />
      </Modal>
    );
  }

  return (
    <Modal
      open={true}
      onClose={onClose}
      title="Connect GitHub Repository"
      size="lg"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className={secondaryButtonClass}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submitConnect()}
            disabled={isPending || !canSubmit}
            className={primaryButtonClass}
          >
            <Icon name="check" size={13} />
            {isPending ? "Connecting..." : "Connect Repository"}
          </button>
        </div>
      }
    >
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div role="alert" className={errorAlertClass}>
          {error}
        </div>
      )}

      <div>
        <label htmlFor="connect-github-remote-url" className={labelClass}>
          GitHub Repository URL
        </label>
        <input
          id="connect-github-remote-url"
          type="text"
          value={remoteUrl}
          onChange={(e) => setRemoteUrl(e.target.value)}
          disabled={isPending}
          placeholder={
            authMethod === "pat"
              ? "https://github.com/owner/repo.git"
              : "git@github.com:owner/repo.git"
          }
          className={inputClass}
        />
        <p className="mt-1 text-[11px] text-text-muted">
          Credentials are never stored in .git/config. HTTPS is used for PAT;
          SSH is used for Deploy Key.
        </p>
      </div>

      <div>
        <span className={labelClass}>Authentication Method</span>
        <AuthMethodToggle
          value={authMethod}
          onChange={setAuthMethod}
          disabled={isPending || isGeneratingKey}
        />
      </div>

      {authMethod === "pat" ? (
        <div>
          <label htmlFor="connect-github-pat" className={labelClass}>
            Personal Access Token (PAT)
          </label>
          <input
            id="connect-github-pat"
            type="password"
            autoComplete="off"
            value={patToken}
            onChange={(e) => setPatToken(e.target.value)}
            disabled={isPending}
            className={inputClass}
          />
          <p className="mt-1 text-[11px] text-text-muted">
            Use a fine-grained PAT scoped only to this repository with Contents
            (Read and write) permission.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <div>
            <label htmlFor="connect-github-key-comment" className={labelClass}>
              Key Comment
            </label>
            <input
              id="connect-github-key-comment"
              type="text"
              value={deployComment}
              onChange={(e) => setDeployComment(e.target.value)}
              maxLength={128}
              disabled={isPending || isGeneratingKey}
              placeholder="onx-server-deploy-key"
              className={inputClass}
            />
          </div>
          <button
            type="button"
            onClick={handleGenerateKey}
            disabled={isPending || isGeneratingKey}
            className={secondaryButtonClass}
          >
            <Icon name="plus" size={13} />
            {isGeneratingKey
              ? "Generating..."
              : "Generate Ed25519 Deploy Key"}
          </button>

          {generatedKey && (
            <>
              <DeployKeyDisplay
                generatedKey={generatedKey}
                copied={copiedKey === "public-key"}
                onCopyPublicKey={() =>
                  copy(generatedKey.public_key_openssh, "public-key")
                }
              />
              <p className="text-[11px] font-medium text-status-success">
                Private key generated and ready to encrypt in ONX vault
              </p>
            </>
          )}

          <details className="rounded-lg border border-border-subtle bg-surface-page p-3">
            <summary className="cursor-pointer text-[11px] font-medium text-accent-primary">
              Paste an existing SSH private key instead
            </summary>
            <div className="mt-2">
              <label htmlFor="connect-github-ssh-key" className={labelClass}>
                SSH Private Key (PEM)
              </label>
              <textarea
                id="connect-github-ssh-key"
                value={sshPrivateKey}
                onChange={(e) => setSshPrivateKey(e.target.value)}
                rows={4}
                disabled={isPending}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                className={`${inputClass} font-mono text-[11px]`}
              />
            </div>
          </details>
        </div>
      )}

      <div className="space-y-2 rounded-lg border border-border-subtle bg-surface-page p-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            aria-label="Enable GitHub Webhook (HMAC-SHA256)"
            checked={enableWebhook}
            onChange={(e) => setEnableWebhook(e.target.checked)}
            disabled={isPending}
            className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
          />
          <span className="text-xs font-semibold text-text-primary">
            Enable GitHub Webhook (HMAC-SHA256)
          </span>
        </label>

        {enableWebhook && (
          <div>
            <label htmlFor="connect-github-webhook-secret" className={labelClass}>
              Custom Webhook Secret (optional, min 16 chars)
            </label>
            <input
              id="connect-github-webhook-secret"
              type="password"
              autoComplete="off"
              value={webhookSecret}
              onChange={(e) => setWebhookSecret(e.target.value)}
              disabled={isPending}
              className={inputClass}
            />
            <p className="mt-1 text-[11px] text-text-muted">
              Leave blank to auto-generate a cryptographically random secret
              (shown once after connecting).
            </p>
          </div>
        )}
      </div>
    </form>
    </Modal>
  );
}

// ==========================================
// 2. Rotate GitHub Credentials Modal
// ==========================================
export interface RotateGitHubCredentialsModalProps {
  isOpen: boolean;
  serverId: string;
  currentStatus: GitHubConnectionStatusResponse | null;
  onRotated: (status: GitHubConnectionStatusResponse) => void;
  onClose: () => void;
}

type WebhookRotationAction = "keep" | "enable_or_rotate" | "disable";

export function RotateGitHubCredentialsModal({
  isOpen,
  serverId,
  currentStatus,
  onRotated,
  onClose,
}: RotateGitHubCredentialsModalProps) {
  if (!isOpen) return null;
  return (
    <RotateGitHubCredentialsBody
      serverId={serverId}
      currentStatus={currentStatus}
      onRotated={onRotated}
      onClose={onClose}
    />
  );
}

interface RotateGitHubCredentialsBodyProps {
  serverId: string;
  currentStatus: GitHubConnectionStatusResponse | null;
  onRotated: (status: GitHubConnectionStatusResponse) => void;
  onClose: () => void;
}

function RotateGitHubCredentialsBody({
  serverId,
  currentStatus,
  onRotated,
  onClose,
}: RotateGitHubCredentialsBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { copiedKey, copy } = useCopyFeedback();
  const [isPending, setIsPending] = useState(false);
  const initialAuthMethod: GitHubAuthMethod =
    currentStatus?.auth_method === "ssh_deploy_key" ? "ssh_deploy_key" : "pat";
  const [authMethod, setAuthMethod] =
    useState<GitHubAuthMethod>(initialAuthMethod);
  const [patToken, setPatToken] = useState("");
  const [generatedKey, setGeneratedKey] =
    useState<GenerateGitHubDeployKeyResponse | null>(null);
  const [sshPrivateKey, setSshPrivateKey] = useState("");
  const [deployPublicKey, setDeployPublicKey] = useState("");
  const [isGeneratingKey, setIsGeneratingKey] = useState(false);
  const [webhookAction, setWebhookAction] =
    useState<WebhookRotationAction>("keep");
  const [regenerateWebhookSecret, setRegenerateWebhookSecret] =
    useState(false);
  const [customWebhookSecret, setCustomWebhookSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [oneTimeResult, setOneTimeResult] =
    useState<GitHubConnectionStatusResponse | null>(null);

  const handleGenerateKey = async () => {
    if (isGeneratingKey || isPending) return;
    setError(null);
    setIsGeneratingKey(true);
    try {
      const result = await api.generateGitHubDeployKey(serverId);
      setGeneratedKey(result);
      setSshPrivateKey(result.private_key_pem);
      setDeployPublicKey(result.public_key_openssh);
    } catch (err: unknown) {
      setError(
        formatGitHubError(err, "Failed to generate an Ed25519 deploy key."),
      );
    } finally {
      setIsGeneratingKey(false);
    }
  };

  const submitRotate = async () => {
    if (isPending) return;

    const credential =
      authMethod === "pat" ? patToken.trim() : sshPrivateKey.trim();
    const trimmedCustomSecret = customWebhookSecret.trim();
    const authMethodChanged = authMethod !== initialAuthMethod;
    const hasCredentialAction = Boolean(credential) || authMethodChanged;
    const hasWebhookAction = webhookAction !== "keep";

    if (!hasCredentialAction && !hasWebhookAction) {
      setError(
        "Select at least one credential or webhook rotation action.",
      );
      return;
    }
    if (
      webhookAction === "enable_or_rotate" &&
      !regenerateWebhookSecret &&
      trimmedCustomSecret.length > 0 &&
      trimmedCustomSecret.length < 16
    ) {
      setError("Custom webhook secret must be at least 16 characters.");
      return;
    }

    const payload: RotateGitHubCredentialsRequest = {};
    if (authMethodChanged) payload.auth_method = authMethod;
    if (credential) payload.credential_secret = credential;
    if (authMethod === "ssh_deploy_key" && deployPublicKey.trim()) {
      payload.deploy_public_key = deployPublicKey.trim();
    }
    if (webhookAction === "disable") {
      payload.disable_webhook = true;
    } else if (webhookAction === "enable_or_rotate") {
      if (regenerateWebhookSecret) {
        payload.regenerate_webhook_secret = true;
      } else if (trimmedCustomSecret) {
        payload.enable_webhook = true;
        payload.webhook_secret = trimmedCustomSecret;
      } else {
        payload.enable_webhook = true;
      }
    }

    setError(null);
    setIsPending(true);
    try {
      const response = await api.rotateGitHubCredentials(serverId, payload);
      onRotated(response);
      if (response.generated_webhook_secret) {
        setOneTimeResult(response);
      } else {
        onClose();
      }
    } catch (err: unknown) {
      setError(
        formatGitHubError(err, "Failed to rotate GitHub credentials."),
      );
    } finally {
      setIsPending(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submitRotate();
  };

  if (oneTimeResult?.generated_webhook_secret) {
    return (
      <Modal
        open={true}
        onClose={onClose}
        title="Rotate GitHub Credentials & Webhook"
        size="lg"
        showCloseButton={false}
        closeOnBackdrop={false}
        closeOnEscape={true}
      >
        <OneTimeWebhookSecretPanel
          secret={oneTimeResult.generated_webhook_secret}
          webhookPath={oneTimeResult.webhook_path}
          copiedKey={copiedKey}
          onCopy={copy}
          onDone={onClose}
        />
      </Modal>
    );
  }

  return (
    <Modal
      open={true}
      onClose={onClose}
      title="Rotate GitHub Credentials & Webhook"
      size="lg"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className={secondaryButtonClass}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submitRotate()}
            disabled={isPending}
            className={primaryButtonClass}
          >
            <Icon name="restart" size={13} />
            {isPending ? "Rotating..." : "Rotate Credentials"}
          </button>
        </div>
      }
    >
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div role="alert" className={errorAlertClass}>
          {error}
        </div>
      )}

      <div className="space-y-3 rounded-lg border border-border-subtle bg-surface-page p-3">
        <div className="text-xs font-semibold text-text-primary">
          Credential Rotation
        </div>
        <AuthMethodToggle
          value={authMethod}
          onChange={setAuthMethod}
          disabled={isPending || isGeneratingKey}
        />

        {authMethod === "pat" ? (
          <div>
            <label htmlFor="rotate-github-pat" className={labelClass}>
              New Personal Access Token (optional)
            </label>
            <input
              id="rotate-github-pat"
              type="password"
              autoComplete="off"
              value={patToken}
              onChange={(e) => setPatToken(e.target.value)}
              disabled={isPending}
              className={inputClass}
            />
          </div>
        ) : (
          <div className="space-y-3">
            <button
              type="button"
              onClick={handleGenerateKey}
              disabled={isPending || isGeneratingKey}
              className={secondaryButtonClass}
            >
              <Icon name="plus" size={13} />
              {isGeneratingKey
                ? "Generating..."
                : "Generate New Ed25519 Deploy Key"}
            </button>
            {generatedKey && (
              <>
                <DeployKeyDisplay
                  generatedKey={generatedKey}
                  copied={copiedKey === "rotate-public-key"}
                  onCopyPublicKey={() =>
                    copy(generatedKey.public_key_openssh, "rotate-public-key")
                  }
                />
                <p className="text-[11px] font-medium text-status-success">
                  Private key generated and ready to encrypt in ONX vault
                </p>
              </>
            )}
            <div>
              <label htmlFor="rotate-github-ssh-key" className={labelClass}>
                SSH Private Key (PEM)
              </label>
              <textarea
                id="rotate-github-ssh-key"
                value={sshPrivateKey}
                onChange={(e) => setSshPrivateKey(e.target.value)}
                rows={4}
                disabled={isPending}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                className={`${inputClass} font-mono text-[11px]`}
              />
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2.5 rounded-lg border border-border-subtle bg-surface-page p-3">
        <div className="text-xs font-semibold text-text-primary">
          Webhook Action
        </div>
        <div role="radiogroup" aria-label="Webhook Action" className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="webhook-rotation-action"
              value="keep"
              checked={webhookAction === "keep"}
              onChange={() => setWebhookAction("keep")}
              disabled={isPending}
              className="border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
            />
            <span className="text-xs text-text-secondary">
              Keep current webhook settings
            </span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="webhook-rotation-action"
              value="enable_or_rotate"
              checked={webhookAction === "enable_or_rotate"}
              onChange={() => setWebhookAction("enable_or_rotate")}
              disabled={isPending}
              className="border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
            />
            <span className="text-xs text-text-secondary">
              Enable / Rotate webhook secret
            </span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="webhook-rotation-action"
              value="disable"
              checked={webhookAction === "disable"}
              onChange={() => setWebhookAction("disable")}
              disabled={isPending}
              className="border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
            />
            <span className="text-xs text-text-secondary">Disable webhook</span>
          </label>
        </div>

        {webhookAction === "enable_or_rotate" && (
          <div className="space-y-2 rounded-lg border border-border-subtle bg-surface-card p-2.5">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                aria-label="Auto-generate new webhook secret"
                checked={regenerateWebhookSecret}
                onChange={(e) => setRegenerateWebhookSecret(e.target.checked)}
                disabled={isPending}
                className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
              />
              <span className="text-xs text-text-secondary">
                Auto-generate new webhook secret
              </span>
            </label>
            {!regenerateWebhookSecret && (
              <div>
                <label
                  htmlFor="rotate-github-webhook-secret"
                  className={labelClass}
                >
                  Custom Webhook Secret (min 16 chars)
                </label>
                <input
                  id="rotate-github-webhook-secret"
                  type="password"
                  autoComplete="off"
                  value={customWebhookSecret}
                  onChange={(e) => setCustomWebhookSecret(e.target.value)}
                  disabled={isPending}
                  className={inputClass}
                />
              </div>
            )}
          </div>
        )}

        {webhookAction === "disable" && (
          <p className="text-[11px] text-text-muted">
            Webhook delivery ingestion will be disabled. Local Git history is
            not affected.
          </p>
        )}
      </div>
    </form>
    </Modal>
  );
}

// ==========================================
// 3. Disconnect GitHub Modal
// ==========================================
export interface DisconnectGitHubModalProps {
  isOpen: boolean;
  serverId: string;
  remoteUrl: string | null;
  onDisconnected: (result: GitHubDisconnectResponse) => void;
  onClose: () => void;
}

export function DisconnectGitHubModal({
  isOpen,
  serverId,
  remoteUrl,
  onDisconnected,
  onClose,
}: DisconnectGitHubModalProps) {
  if (!isOpen) return null;
  return (
    <DisconnectGitHubBody
      serverId={serverId}
      remoteUrl={remoteUrl}
      onDisconnected={onDisconnected}
      onClose={onClose}
    />
  );
}

interface DisconnectGitHubBodyProps {
  serverId: string;
  remoteUrl: string | null;
  onDisconnected: (result: GitHubDisconnectResponse) => void;
  onClose: () => void;
}

function DisconnectGitHubBody({
  serverId,
  remoteUrl,
  onDisconnected,
  onClose,
}: DisconnectGitHubBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [isPending, setIsPending] = useState(false);
  const [purgeDeliveries, setPurgeDeliveries] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitDisconnect = async () => {
    if (isPending) return;
    setError(null);
    setIsPending(true);
    try {
      const result = await api.disconnectGitHub(serverId, purgeDeliveries);
      onDisconnected(result);
      onClose();
    } catch (err: unknown) {
      setError(
        formatGitHubError(err, "Failed to disconnect the GitHub repository."),
      );
    } finally {
      setIsPending(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submitDisconnect();
  };

  return (
    <Modal
      open={true}
      onClose={onClose}
      title="Disconnect GitHub Repository"
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className={secondaryButtonClass}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submitDisconnect()}
            disabled={isPending}
            className={dangerButtonClass}
          >
            <Icon name="x" size={13} />
            {isPending ? "Disconnecting..." : "Disconnect GitHub"}
          </button>
        </div>
      }
    >
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div role="alert" className={errorAlertClass}>
          {error}
        </div>
      )}

      {remoteUrl && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-text-secondary">Remote:</span>
          <span className="max-w-full truncate rounded-md border border-border-default bg-surface-page px-2 py-0.5 font-mono text-[11px] text-text-primary">
            {remoteUrl}
          </span>
        </div>
      )}

      <div className="flex items-start gap-2 rounded-lg border border-status-info-border bg-status-info-bg p-3 text-xs text-status-info">
        <Icon name="info" size={14} className="mt-0.5 shrink-0" />
        <p>
          Local Git history is preserved. All local commits, branches, tags, and
          snapshots remain intact on this server. Only the remote link, stored
          credentials, and webhook configuration will be removed.
        </p>
      </div>

      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          aria-label="Also purge stored webhook delivery history"
          checked={purgeDeliveries}
          onChange={(e) => setPurgeDeliveries(e.target.checked)}
          disabled={isPending}
          className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
        />
        <span className="text-xs text-text-secondary">
          Also purge stored webhook delivery history
        </span>
      </label>
    </form>
    </Modal>
  );
}

// ==========================================
// 4. GitHub Webhook Deliveries Modal
// ==========================================
export interface GitHubWebhookDeliveriesModalProps {
  isOpen: boolean;
  serverId: string;
  webhookEnabled: boolean;
  webhookPath: string | null;
  onRedelivered?: (result: GitHubWebhookIngestResponse) => void;
  onClose: () => void;
}

export function GitHubWebhookDeliveriesModal({
  isOpen,
  serverId,
  webhookEnabled,
  webhookPath,
  onRedelivered,
  onClose,
}: GitHubWebhookDeliveriesModalProps) {
  const [redeliveringId, setRedeliveringId] = useState<string | null>(null);
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="GitHub Webhook Deliveries"
      size="2xl"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={redeliveringId === null}
      footer={
        <div className="flex justify-end">
          <button type="button" onClick={onClose} className={secondaryButtonClass}>
            Close
          </button>
        </div>
      }
    >
      {isOpen && (
        <GitHubWebhookDeliveriesBody
          serverId={serverId}
          webhookEnabled={webhookEnabled}
          webhookPath={webhookPath}
          onRedelivered={onRedelivered}
          onRedeliveringChange={setRedeliveringId}
          onClose={onClose}
        />
      )}
    </Modal>
  );
}

interface GitHubWebhookDeliveriesBodyProps {
  serverId: string;
  webhookEnabled: boolean;
  webhookPath: string | null;
  onRedelivered?: (result: GitHubWebhookIngestResponse) => void;
  onRedeliveringChange: (deliveryId: string | null) => void;
  onClose: () => void;
}

function deliveryStatusClasses(status: string): string {
  if (status === "processed" || status === "queued") {
    return "border-status-success-border bg-status-success-bg text-status-success";
  }
  if (status === "deduplicated") {
    return "border-status-warning-border bg-status-warning-bg text-status-warning";
  }
  if (status === "failed") {
    return "border-status-danger-border bg-status-danger-bg text-status-danger";
  }
  return "border-border-default bg-surface-elevated text-text-muted";
}

function formatDeliveryTimestamp(value: string | null): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function GitHubWebhookDeliveriesBody({
  serverId,
  webhookEnabled,
  webhookPath,
  onRedelivered,
  onRedeliveringChange,
  onClose: _onClose,
}: GitHubWebhookDeliveriesBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { copiedKey, copy } = useCopyFeedback();
  const [deliveries, setDeliveries] = useState<GitHubWebhookDeliveryResponse[]>(
    [],
  );
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [redeliveringId, setRedeliveringId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await api.listGitHubWebhookDeliveries(serverId, 50);
        if (!active) return;
        setDeliveries(Array.isArray(result) ? result : []);
        setError(null);
      } catch (err: unknown) {
        if (!active) return;
        setError(
          formatGitHubError(err, "Failed to load GitHub webhook deliveries."),
        );
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [serverId, reloadNonce, api]);

  const handleRefresh = () => {
    setIsLoading(true);
    setSuccess(null);
    setReloadNonce((nonce) => nonce + 1);
  };

  const handleRedeliver = async (delivery: GitHubWebhookDeliveryResponse) => {
    if (redeliveringId !== null) return;
    setError(null);
    setSuccess(null);
    setRedeliveringId(delivery.delivery_id);
    onRedeliveringChange(delivery.delivery_id);
    try {
      const result = await api.redeliverGitHubWebhook(
        serverId,
        delivery.delivery_id,
      );
      setSuccess(
        `Delivery ${result.delivery_id} queued for redelivery${
          result.operation_id ? ` (operation ${result.operation_id})` : ""
        }`,
      );
      setReloadNonce((nonce) => nonce + 1);
      onRedelivered?.(result);
    } catch (err: unknown) {
      setError(
        formatGitHubError(err, "Failed to redeliver the GitHub webhook."),
      );
    } finally {
      setRedeliveringId(null);
      onRedeliveringChange(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-page p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`${badgeClass} ${
              webhookEnabled
                ? "border-status-success-border bg-status-success-bg text-status-success"
                : "border-border-default bg-surface-elevated text-text-muted"
            }`}
          >
            <Icon name="bell" size={11} />
            {webhookEnabled ? "Webhook Active" : "Webhook Disabled"}
          </span>
          {webhookPath && (
            <>
              <code
                title={webhookPath}
                className="max-w-[24rem] truncate rounded-md border border-border-default bg-surface-card px-2 py-0.5 font-mono text-[11px] text-text-secondary"
              >
                {webhookPath}
              </code>
              <button
                type="button"
                onClick={() => copy(webhookPath, "webhook-path")}
                aria-label="Copy webhook path"
                className={secondaryButtonClass}
              >
                <Icon name="copy" size={12} />
                {copiedKey === "webhook-path" ? "Copied!" : "Copy Path"}
              </button>
            </>
          )}
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className={secondaryButtonClass}
        >
          <Icon name="restart" size={13} />
          Refresh
        </button>
      </div>

      {error && (
        <div role="alert" className={errorAlertClass}>
          {error}
        </div>
      )}

      {success && (
        <div
          role="status"
          data-testid="webhook-redeliver-success"
          className="rounded-lg border border-status-success-border bg-status-success-bg p-3 text-xs text-status-success"
        >
          {success}
        </div>
      )}

      {isLoading ? (
        <div className="rounded-lg border border-border-subtle bg-surface-page p-4 text-xs text-text-muted">
          Loading webhook deliveries...
        </div>
      ) : deliveries.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
          No webhook deliveries recorded yet.
        </div>
      ) : (
        <div className="max-h-[55vh] space-y-2 overflow-y-auto pr-1">
          {deliveries.map((delivery) => (
            <div
              key={delivery.id}
              className="space-y-1.5 rounded-lg border border-border-subtle bg-surface-page p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  title={delivery.delivery_id}
                  className="max-w-[18rem] truncate font-mono text-[11px] font-semibold text-text-primary"
                >
                  {delivery.delivery_id}
                </span>
                <span className="inline-flex items-center rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-semibold text-text-secondary">
                  {delivery.event_type}
                </span>
                {delivery.ref && (
                  <span className="font-mono text-[11px] text-text-secondary">
                    {delivery.ref}
                  </span>
                )}
                <span
                  className={`${badgeClass} ${
                    delivery.signature_valid
                      ? "border-status-success-border bg-status-success-bg text-status-success"
                      : "border-status-danger-border bg-status-danger-bg text-status-danger"
                  }`}
                >
                  <Icon
                    name={delivery.signature_valid ? "check" : "alert"}
                    size={11}
                  />
                  {delivery.signature_valid
                    ? "Valid HMAC"
                    : "Invalid Signature"}
                </span>
                <span
                  className={`${badgeClass} ${deliveryStatusClasses(
                    delivery.status,
                  )}`}
                >
                  {delivery.status}
                </span>
                {delivery.redelivery_count > 0 && (
                  <span className="text-[11px] text-text-muted">
                    Redeliveries: {delivery.redelivery_count}
                  </span>
                )}
                <span className="ml-auto text-[11px] text-text-muted">
                  {formatDeliveryTimestamp(delivery.received_at)}
                </span>
              </div>

              {(delivery.before_sha || delivery.after_sha) && (
                <div className="font-mono text-[11px] text-text-secondary">
                  {delivery.before_sha ? delivery.before_sha.slice(0, 8) : "—"}{" "}
                  →{" "}
                  {delivery.after_sha ? delivery.after_sha.slice(0, 8) : "—"}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2">
                {delivery.operation_id && (
                  <span className="rounded border border-border-default bg-surface-card px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
                    Operation: {delivery.operation_id}
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`Redeliver ${delivery.delivery_id}`}
                  onClick={() => handleRedeliver(delivery)}
                  disabled={redeliveringId !== null}
                  className={`${secondaryButtonClass} ml-auto`}
                >
                  <Icon name="restart" size={12} />
                  {redeliveringId === delivery.delivery_id
                    ? "Redelivering..."
                    : "Redeliver"}
                </button>
              </div>

              {delivery.error_message && (
                <p className="rounded border border-status-danger-border bg-status-danger-bg p-2 text-[11px] text-status-danger">
                  {delivery.error_message}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

    </div>
  );
}
