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
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
        <p className="text-sm text-gray-500">Loading registration status...</p>
      </div>
    );
  }

  const isGlobalMode = systemStatus?.access_mode === "GLOBAL";
  const isInviteOnlyLocked = isGlobalMode && !tokenVerified;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold text-center mb-6 text-gray-900 dark:text-gray-100">
          onx-manager
        </h1>

        <form
          onSubmit={handleSubmit}
          className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 space-y-4"
        >
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {tokenVerified ? "Accept Invitation" : "Create account"}
          </h2>

          {displayError && (
            <div className="px-3 py-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg">
              {displayError}
            </div>
          )}

          {isInviteOnlyLocked && (
            <div className="space-y-3">
              <div className="p-3 text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                This instance uses invitation-only registration. Please enter your invitation token below.
              </div>

              <div>
                <label htmlFor="inviteToken" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Invitation Token
                </label>
                <div className="flex gap-2">
                  <input
                    id="inviteToken"
                    type="text"
                    value={inviteToken}
                    onChange={(e) => setInviteToken(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="Enter token"
                  />
                  <button
                    type="button"
                    onClick={handleClickVerify}
                    disabled={verifyingToken || !inviteToken.trim()}
                    className="px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-800 dark:text-gray-200 text-xs font-medium border border-gray-300 dark:border-gray-600 disabled:opacity-50"
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
                <div className="px-3 py-1.5 text-xs text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800 flex items-center justify-between">
                  <span>Invitation verified!</span>
                  <button
                    type="button"
                    onClick={handleChangeToken}
                    className="text-xs text-gray-500 hover:underline"
                  >
                    Change
                  </button>
                </div>
              )}

              <div>
                <label htmlFor="displayName" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Display name
                </label>
                <input
                  id="displayName"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Your name"
                  autoComplete="name"
                  required
                />
              </div>

              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  value={emailValue}
                  onChange={(e) => !emailLocked && setEmail(e.target.value)}
                  disabled={emailLocked}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-75 disabled:bg-gray-100 dark:disabled:bg-gray-800"
                  placeholder="you@example.com"
                  autoComplete="email"
                  required
                />
              </div>

              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
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
                <label htmlFor="passwordConfirm" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Confirm password
                </label>
                <div className="relative">
                  <input
                    id="passwordConfirm"
                    type={showPasswordConfirm ? "text" : "password"}
                    value={passwordConfirm}
                    onChange={(e) => setPasswordConfirm(e.target.value)}
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="Repeat password"
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPasswordConfirm((v) => !v)}
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
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
                className="w-full py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Creating account..." : tokenVerified ? "Accept & Complete Account" : "Create account"}
              </button>
            </>
          )}

          <p className="text-sm text-center text-gray-500 dark:text-gray-400 pt-1">
            Already have an account?{" "}
            <Link to="/login" className="text-blue-600 dark:text-blue-400 hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
