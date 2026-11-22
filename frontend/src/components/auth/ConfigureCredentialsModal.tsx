import { useContext, useState, type FormEvent } from "react";
import { QueryClientContext } from "@tanstack/react-query";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import { queryClient as defaultQueryClient } from "@/services/queryClient";
import { useAuthStore } from "@/stores/authStore";
import { toast } from "@/stores/toastStore";

export interface ConfigureCredentialsModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void | Promise<void>;
  reason?: string;
}

export function ConfigureCredentialsModal({
  open,
  onClose,
  onSuccess,
  reason,
}: ConfigureCredentialsModalProps) {
  const ctxClient = useContext(QueryClientContext);
  const queryClient = ctxClient ?? defaultQueryClient;
  const login = useAuthStore((s) => s.login);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleClose = () => {
    if (submitting) return;
    setError("");
    onClose();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    const trimmedUsername = username.trim();
    if (!trimmedUsername || !password) {
      setError("Username and password are required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const api = createAuthenticatedApi();
      const res = await api.configureCredentials({
        username: trimmedUsername,
        display_name: trimmedUsername,
        password,
      });

      login(res.access_token, res.refresh_token, res.expires_in);
      await queryClient.invalidateQueries({ queryKey: ["systemStatus"] });
      await queryClient.invalidateQueries({ queryKey: ["currentUser"] });

      toast(
        "success",
        "Credentials Configured",
        "Passwordless local mode is now disabled. Signed in with your new credentials.",
      );

      setUsername("");
      setPassword("");
      setConfirmPassword("");
      onClose();
      await onSuccess?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to configure credentials";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Set Administrator Username & Password"
      description={
        reason ||
        "External exposure and remote access require an administrator username and password. Once configured, passwordless local login will be disabled."
      }
      size="md"
      closeOnBackdrop={false}
      closeOnEscape={!submitting}
      closeButtonAriaLabel="Close credentials dialog"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div
            role="alert"
            className="px-3 py-2 text-xs text-status-danger bg-status-danger-bg border border-status-danger-border rounded-lg"
          >
            {error}
          </div>
        )}

        <div>
          <label
            htmlFor="cred-username"
            className="block text-xs font-semibold text-text-secondary mb-1"
          >
            Username
          </label>
          <input
            id="cred-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="admin"
            autoComplete="username"
            disabled={submitting}
            required
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary disabled:opacity-50"
          />
        </div>

        <div>
          <label
            htmlFor="cred-password"
            className="block text-xs font-semibold text-text-secondary mb-1"
          >
            Password
          </label>
          <div className="relative">
            <input
              id="cred-password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              autoComplete="new-password"
              disabled={submitting}
              required
              className="w-full px-3 py-2 pr-16 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 px-3 text-xs text-text-muted hover:text-text-primary"
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        <div>
          <label
            htmlFor="cred-confirm-password"
            className="block text-xs font-semibold text-text-secondary mb-1"
          >
            Confirm Password
          </label>
          <input
            id="cred-confirm-password"
            type={showPassword ? "text" : "password"}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Re-enter password"
            autoComplete="new-password"
            disabled={submitting}
            required
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary disabled:opacity-50"
          />
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="px-4 py-2 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50 cursor-pointer"
          >
            {submitting ? "Saving Credentials..." : "Save Credentials & Continue"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
