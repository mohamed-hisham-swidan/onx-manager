import { useState, useMemo, type FormEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createApiClient } from "@/services/api";
import { useAuthStore } from "@/stores/authStore";
import { BrandLogo } from "@/components/brand/BrandLogo";
import { VoxelBanner } from "@/components/brand/VoxelBanner";

function extractInviteToken(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";

  const pathMatch = trimmed.match(/\/invite\/([^/?#]+)/i);
  if (pathMatch?.[1]) {
    try {
      return decodeURIComponent(pathMatch[1]).trim();
    } catch {
      return pathMatch[1].trim();
    }
  }

  const queryMatch = trimmed.match(/[?&]token=([^&#]+)/i);
  if (queryMatch?.[1]) {
    try {
      return decodeURIComponent(queryMatch[1]).trim();
    } catch {
      return queryMatch[1].trim();
    }
  }

  return trimmed;
}

export function RegisterPage() {
  const api = useMemo(() => createApiClient(window.location.origin, () => null), []);
  const [searchParams] = useSearchParams();
  const tokenFromUrl = searchParams.get("token") || "";
  const initialToken = extractInviteToken(tokenFromUrl);

  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);

  const { data: systemStatus, isLoading: statusLoading } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: () => api.getSetupStatus(),
  });

  const [inviteToken, setInviteToken] = useState(initialToken);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showPasswordConfirm, setShowPasswordConfirm] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [activeVerifyToken, setActiveVerifyToken] = useState(initialToken);

  const verifyQuery = useQuery({
    queryKey: ["invite", "verify", activeVerifyToken],
    queryFn: () => api.verifyInvite(activeVerifyToken.trim()),
    enabled: !!activeVerifyToken.trim(),
    retry: false,
  });

  const verification = verifyQuery.data;
  const tokenVerified = verification?.valid === true;
  const verifyingToken = verifyQuery.isFetching;

  const requestError = verifyQuery.error instanceof Error ? verifyQuery.error.message : "";
  const verificationError = verification && !verification.valid ? "Invalid or expired invitation token." : "";
  const verifyError = requestError || verificationError;
  const displayError = error || verifyError;

  const verifiedEmail = verification?.valid ? verification.email ?? "" : "";
  const isGlobalMode = systemStatus?.access_mode === "GLOBAL";
  const isInviteOnlyLocked = isGlobalMode && !tokenVerified;

  const handleClickVerify = () => {
    setError("");
    const tok = extractInviteToken(inviteToken);
    if (!tok) return;
    setInviteToken(tok);
    if (tok === activeVerifyToken) {
      void verifyQuery.refetch();
    } else {
      setActiveVerifyToken(tok);
    }
  };

  const handleChangeToken = () => {
    setActiveVerifyToken("");
    setInviteToken("");
    setError("");
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isInviteOnlyLocked) {
      handleClickVerify();
      return;
    }
    setError("");

    const trimmedUsername = username.trim();
    if (!trimmedUsername || !password) {
      setError("Username and password are required");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (password !== passwordConfirm) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);
    try {
      const verifiedTok = activeVerifyToken || extractInviteToken(inviteToken);
      if (tokenVerified && verifiedTok) {
        // Token invitation registration
        const res = await api.acceptInvite({
          token: verifiedTok,
          username: trimmedUsername,
          display_name: trimmedUsername,
          password,
          ...(verifiedEmail ? { email: verifiedEmail } : {}),
        });
        login(res.access_token, res.refresh_token, res.expires_in);
        navigate("/");
      } else {
        // Standard LOCAL registration
        await api.createUser({
          username: trimmedUsername,
          display_name: trimmedUsername,
          password,
        });
        navigate("/login?registered=1");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  if (statusLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-page px-4">
        <p className="text-sm text-text-muted">Loading registration status...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-page px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <VoxelBanner variant="auth" className="mb-2" />
          <h1 className="text-center">
            <BrandLogo variant="full" size="md" />
          </h1>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface-card rounded-xl shadow-xs border border-border-default p-6 space-y-4"
        >
          <h2 className="text-lg font-semibold text-text-primary">
            {tokenVerified ? "Accept Invitation" : "Create account"}
          </h2>

          {displayError && (
            <div className="px-3 py-2 text-sm text-status-danger bg-status-danger/10 border border-status-danger/20 rounded-lg">
              {displayError}
            </div>
          )}

          {isInviteOnlyLocked && (
            <div className="space-y-3">
              <div className="p-3 text-xs text-status-warning bg-status-warning-bg rounded-lg border border-status-warning-border">
                This instance uses invitation-only registration. Please enter your invitation token below.
              </div>

              <div>
                <label htmlFor="inviteToken" className="block text-sm font-medium text-text-secondary mb-1">
                  Invitation Token
                </label>
                <div className="flex gap-2">
                  <input
                    id="inviteToken"
                    type="text"
                    value={inviteToken}
                    onChange={(e) => {
                      setInviteToken(e.target.value);
                      setError("");
                      if (activeVerifyToken) {
                        setActiveVerifyToken("");
                      }
                    }}
                    className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
                    placeholder="Enter token"
                  />
                  <button
                    type="button"
                    onClick={handleClickVerify}
                    disabled={verifyingToken || !inviteToken.trim()}
                    className="px-3 py-2 rounded-lg bg-surface-elevated hover:bg-surface-card text-text-secondary text-xs font-medium border border-border-default disabled:opacity-50 transition-colors"
                  >
                    {verifyingToken ? "Verifying..." : "Verify"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {(!isInviteOnlyLocked || tokenVerified) && (
            <>
              {tokenVerified && (
                <div className="px-3 py-1.5 text-xs text-status-success bg-status-success/10 rounded-lg border border-status-success/20 space-y-1">
                  <div className="flex items-center justify-between">
                    <span>Invitation verified!</span>
                    <button
                      type="button"
                      onClick={handleChangeToken}
                      className="text-xs text-text-muted hover:underline"
                    >
                      Change
                    </button>
                  </div>
                  {verifiedEmail && (
                    <p>
                      Restricted to: <strong>{verifiedEmail}</strong>
                    </p>
                  )}
                </div>
              )}

              <div>
                <label htmlFor="username" className="block text-sm font-medium text-text-secondary mb-1">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
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
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-text-muted hover:text-text-primary"
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
                  Confirm password
                </label>
                <div className="relative">
                  <input
                    id="passwordConfirm"
                    type={showPasswordConfirm ? "text" : "password"}
                    value={passwordConfirm}
                    onChange={(e) => setPasswordConfirm(e.target.value)}
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-border-default bg-surface-page text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
                    placeholder="Repeat password"
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPasswordConfirm((v) => !v)}
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-text-muted hover:text-text-primary"
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
                disabled={loading}
                className="w-full py-2 px-4 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Creating account..." : tokenVerified ? "Accept & Complete Account" : "Create account"}
              </button>
            </>
          )}

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
