import { useState, useMemo, type FormEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createApiClient } from "@/services/api";
import { useAuthStore } from "@/stores/authStore";

export function RegisterPage() {
  const api = useMemo(() => createApiClient(window.location.origin, () => null), []);
  const [searchParams] = useSearchParams();
  const tokenFromUrl = searchParams.get("token") || "";

  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);

  const { data: systemStatus, isLoading: statusLoading } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: () => api.getSetupStatus(),
  });

  const [inviteToken, setInviteToken] = useState(tokenFromUrl);

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showPasswordConfirm, setShowPasswordConfirm] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [activeVerifyToken, setActiveVerifyToken] = useState(tokenFromUrl);

  const verifyQuery = useQuery({
    queryKey: ["invite", "verify", activeVerifyToken],
    queryFn: () => api.verifyInvite(activeVerifyToken.trim()),
    enabled: !!activeVerifyToken.trim(),
    retry: false,
  });

  const verification = verifyQuery.data;
  const tokenVerified = verification?.valid === true;
  const verifyingToken = verifyQuery.isPending || verifyQuery.isFetching;

  const requestError = verifyQuery.error instanceof Error ? verifyQuery.error.message : "";
  const verificationError = verification && !verification.valid ? "Invalid or expired invitation token." : "";
  const verifyError = requestError || verificationError;
  const displayError = error || verifyError;

  const verifiedEmail = verification?.valid ? verification.email ?? "" : "";
  const emailValue = verifiedEmail ? verifiedEmail : email;
  const emailLocked = Boolean(verifiedEmail);

  const handleClickVerify = () => {
    setError("");
    const tok = inviteToken.trim();
    if (!tok) return;
    setActiveVerifyToken(tok);
  };

  const handleChangeToken = () => {
    setActiveVerifyToken("");
    setInviteToken("");
    setError("");
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!displayName || !emailValue || !password) {
      setError("All fields are required");
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
      if (tokenVerified && inviteToken) {
        // Token invitation registration
        const res = await api.acceptInvite({
          token: inviteToken.trim(),
          email: emailValue,
          password,
          display_name: displayName,
        });
        login(res.access_token, res.refresh_token, res.expires_in);
        navigate("/");
      } else {
        // Standard LOCAL registration
        await api.createUser({ email: emailValue, password, display_name: displayName });
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
      <div className="min-h-screen flex items-center justify-center bg-surface-canvas px-4">
        <p className="text-sm text-text-muted">Loading registration status...</p>
      </div>
    );
  }

  const isGlobalMode = systemStatus?.access_mode === "GLOBAL";
  const isInviteOnlyLocked = isGlobalMode && !tokenVerified;

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-canvas px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold text-center mb-6 text-text-primary tracking-tight">
          onx-manager
        </h1>

        <form
          onSubmit={handleSubmit}
          className="bg-surface-panel rounded-xl shadow-xs border border-border-default p-6 space-y-4"
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
              <div className="p-3 text-xs text-amber-700 dark:text-amber-300 bg-amber-500/10 rounded-lg border border-amber-500/20">
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
                    onChange={(e) => setInviteToken(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
                    placeholder="Enter token"
                  />
                  <button
                    type="button"
                    onClick={handleClickVerify}
                    disabled={verifyingToken || !inviteToken.trim()}
                    className="px-3 py-2 rounded-lg bg-surface-elevated hover:bg-surface-panel text-text-secondary text-xs font-medium border border-border-default disabled:opacity-50 transition-colors"
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
                <div className="px-3 py-1.5 text-xs text-status-online bg-status-online/10 rounded-lg border border-status-online/20 flex items-center justify-between">
                  <span>Invitation verified!</span>
                  <button
                    type="button"
                    onClick={handleChangeToken}
                    className="text-xs text-text-muted hover:underline"
                  >
                    Change
                  </button>
                </div>
              )}

              <div>
                <label htmlFor="displayName" className="block text-sm font-medium text-text-secondary mb-1">
                  Display name
                </label>
                <input
                  id="displayName"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  placeholder="Your name"
                  autoComplete="name"
                  required
                />
              </div>

              <div>
                <label htmlFor="email" className="block text-sm font-medium text-text-secondary mb-1">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  value={emailValue}
                  onChange={(e) => !emailLocked && setEmail(e.target.value)}
                  disabled={emailLocked}
                  className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary disabled:opacity-75 disabled:bg-surface-elevated"
                  placeholder="you@example.com"
                  autoComplete="email"
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
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-border-default bg-surface-canvas text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
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
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-border-default bg-surface-canvas text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent-primary"
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
                className="w-full py-2 px-4 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-fg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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
