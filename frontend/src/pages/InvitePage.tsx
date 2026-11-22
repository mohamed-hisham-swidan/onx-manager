import { useState, useMemo, type FormEvent } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createApiClient } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { useAuthStore } from "@/stores/authStore";
import { parseServerDate } from "@/server_manager/utils/format";

export function InvitePage() {
  const { token = "" } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const api = useMemo(() => createApiClient(window.location.origin, () => null), []);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showPasswordConfirm, setShowPasswordConfirm] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const { data: inviteStatus, isLoading, isError, error } = useQuery({
    queryKey: ["verifyInvite", token],
    queryFn: () => api.verifyInvite(token),
    enabled: Boolean(token),
    retry: 1,
  });

  const boundEmail = inviteStatus?.valid && inviteStatus.email ? inviteStatus.email : "";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError("");

    const trimmedUsername = username.trim();
    if (!trimmedUsername || !password) {
      setSubmitError("Username and password are required.");
      return;
    }

    if (password.length < 8) {
      setSubmitError("Password must be at least 8 characters long.");
      return;
    }

    if (password !== passwordConfirm) {
      setSubmitError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await api.acceptInvite({
        token,
        username: trimmedUsername,
        display_name: trimmedUsername,
        password,
        ...(boundEmail ? { email: boundEmail } : {}),
      });

      login(res.access_token, res.refresh_token, res.expires_in);
      navigate("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to redeem invitation";
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-page px-4">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-accent-primary border-t-transparent" />
          <p className="text-sm text-text-muted">Verifying invitation link...</p>
        </div>
      </div>
    );
  }

  if (isError || !inviteStatus || !inviteStatus.valid) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-page px-4 py-8">
        <div className="w-full max-w-md bg-surface-card rounded-xl shadow-xs border border-border-default p-6 text-center space-y-4">
          <div className="w-12 h-12 rounded-full bg-status-danger-bg text-status-danger flex items-center justify-center mx-auto">
            <Icon name="x" size={20} />
          </div>
          <h2 className="text-lg font-semibold text-text-primary">
            Invalid or Expired Invitation
          </h2>
          <p className="text-xs text-text-muted">
            {error instanceof Error ? error.message : "This invitation link is invalid, expired, revoked, or has already reached its maximum usage count."}
          </p>
          <div className="pt-2 flex justify-center gap-3">
            <Link
              to="/login"
              className="px-4 py-2 bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium rounded-lg transition-colors"
            >
              Go to Sign In
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-page px-4 py-8">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-text-primary">
            onx-manager
          </h1>
          <p className="text-sm text-text-muted mt-1">
            Redeem Invitation
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface-card rounded-xl shadow-xs border border-border-default p-6 space-y-4"
        >
          <div className="border-b border-border-subtle pb-3">
            <h2 className="text-lg font-semibold text-text-primary">
              Create Your Account
            </h2>
            <p className="text-xs text-text-muted mt-0.5">
              Complete your profile to accept the invitation and join this instance.
            </p>
          </div>

          {submitError && (
            <div role="alert" className="px-3 py-2 text-sm text-status-danger bg-status-danger-bg border border-status-danger-border rounded-lg">
              {submitError}
            </div>
          )}

          <div className="px-3 py-2 text-xs text-status-success bg-status-success-bg rounded-lg border border-status-success-border space-y-0.5">
            <p className="font-semibold">Invitation Verified!</p>
            {inviteStatus.email && (
              <p>Restricted to: <strong>{inviteStatus.email}</strong></p>
            )}
            {inviteStatus.expires_at && (
              <p>Expires: {parseServerDate(inviteStatus.expires_at)?.toLocaleString() ?? "—"}</p>
            )}
          </div>

          <div>
            <label htmlFor="username" className="block text-sm font-medium text-text-secondary mb-1">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-border-focus"
              placeholder="username"
              autoComplete="username"
              required
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-text-secondary mb-1">
              Password
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 pr-10 rounded-lg border border-border-default bg-surface-card text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-border-focus"
                placeholder="At least 8 characters"
                autoComplete="new-password"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-text-muted hover:text-text-secondary"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="passwordConfirm" className="block text-sm font-medium text-text-secondary mb-1">
              Confirm Password
            </label>
            <div className="relative">
              <input
                id="passwordConfirm"
                type={showPasswordConfirm ? "text" : "password"}
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                className="w-full px-3 py-2 pr-10 rounded-lg border border-border-default bg-surface-card text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-border-focus"
                placeholder="Repeat password"
                autoComplete="new-password"
                required
              />
              <button
                type="button"
                onClick={() => setShowPasswordConfirm((v) => !v)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-text-muted hover:text-text-secondary"
                aria-label={showPasswordConfirm ? "Hide password" : "Show password"}
              >
                {showPasswordConfirm ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-2.5 px-4 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-2"
          >
            {submitting ? "Accepting Invitation..." : "Accept Invitation & Create Account"}
          </button>

          <p className="text-sm text-center text-text-muted pt-1">
            Already have an account?{" "}
            <Link to="/login" className="text-accent-primary hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
