import { useState, useMemo, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/authStore";
import { createApiClient } from "@/services/api";
import { BrandLogo } from "@/components/brand/BrandLogo";

export function SetupPage() {
  const api = useMemo(() => createApiClient(window.location.origin, () => null), []);
  const queryClient = useQueryClient();
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [accessMode, setAccessMode] = useState<"LOCAL" | "GLOBAL">("LOCAL");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [alreadyInitialized, setAlreadyInitialized] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!displayName.trim() || !email.trim() || !password) {
      setError("All fields are required.");
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

    setLoading(true);
    try {
      const res = await api.bootstrapInstance({
        display_name: displayName.trim(),
        email: email.trim(),
        password,
        access_mode: accessMode,
      });

      login(res.access_token, res.refresh_token, res.expires_in);
      await queryClient.invalidateQueries({ queryKey: ["systemStatus"] });
      navigate("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Bootstrap failed";
      setError(msg);

      if (msg.toLowerCase().includes("already initialized")) {
        setAlreadyInitialized(true);
        await queryClient.invalidateQueries({ queryKey: ["systemStatus"] });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGoToLogin = () => {
    queryClient.invalidateQueries({ queryKey: ["systemStatus"] });
    navigate("/login");
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-page px-4 py-8">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="flex justify-center mb-2">
            <BrandLogo variant="full" size="md" />
          </div>
          <p className="text-sm text-text-muted mt-1">
            First-time Instance Setup
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface-card rounded-xl shadow-xs border border-border-default p-6 space-y-5"
        >
          <div className="border-b border-border-subtle pb-3">
            <h2 className="text-lg font-semibold text-text-primary">
              Create Owner Account
            </h2>
            <p className="text-xs text-text-muted mt-0.5">
              This account will have full Owner privileges over this instance.
            </p>
          </div>

          {error && (
            <div role="alert" className="px-3 py-2 text-sm text-status-danger bg-status-danger-bg border border-status-danger-border rounded-lg space-y-2">
              <p>{error}</p>
              {alreadyInitialized && (
                <button
                  type="button"
                  onClick={handleGoToLogin}
                  className="px-3 py-1 bg-status-danger hover:opacity-90 text-white text-xs font-medium rounded-lg transition-colors"
                >
                  Go to Login Page
                </button>
              )}
            </div>
          )}

          <div>
            <label htmlFor="displayName" className="block text-sm font-medium text-text-secondary mb-1">
              Display Name
            </label>
            <input
              id="displayName"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-border-focus"
              placeholder="System Owner"
              required
            />
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-text-secondary mb-1">
              Owner Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-border-focus"
              placeholder="owner@example.com"
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
            <label htmlFor="confirmPassword" className="block text-sm font-medium text-text-secondary mb-1">
              Confirm Password
            </label>
            <input
              id="confirmPassword"
              type={showPassword ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-card text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-border-focus"
              placeholder="Re-enter password"
              autoComplete="new-password"
              required
            />
          </div>

          <div className="space-y-2 pt-2 border-t border-border-subtle">
            <label className="block text-sm font-medium text-text-secondary">
              Access Mode
            </label>
            <div className="grid grid-cols-1 gap-3">
              <label
                className={`flex items-start p-3 rounded-lg border cursor-pointer transition-colors ${
                  accessMode === "LOCAL"
                    ? "border-accent-primary bg-accent-primary/10"
                    : "border-border-default hover:border-border-strong"
                }`}
              >
                <input
                  type="radio"
                  name="accessMode"
                  value="LOCAL"
                  checked={accessMode === "LOCAL"}
                  onChange={() => setAccessMode("LOCAL")}
                  className="mt-0.5 text-accent-primary focus:ring-accent-primary"
                />
                <div className="ml-3">
                  <span className="block text-sm font-medium text-text-primary">
                    Local Mode
                  </span>
                  <span className="block text-xs text-text-muted mt-0.5">
                    Open registration. Anyone on the local network can register and receives Viewer access by default.
                  </span>
                </div>
              </label>

              <label
                className={`flex items-start p-3 rounded-lg border cursor-pointer transition-colors ${
                  accessMode === "GLOBAL"
                    ? "border-accent-primary bg-accent-primary/10"
                    : "border-border-default hover:border-border-strong"
                }`}
              >
                <input
                  type="radio"
                  name="accessMode"
                  value="GLOBAL"
                  checked={accessMode === "GLOBAL"}
                  onChange={() => setAccessMode("GLOBAL")}
                  className="mt-0.5 text-accent-primary focus:ring-accent-primary"
                />
                <div className="ml-3">
                  <span className="block text-sm font-medium text-text-primary">
                    Global Mode
                  </span>
                  <span className="block text-xs text-text-muted mt-0.5">
                    Invite-only. Registration is restricted to users with a valid invitation token link.
                  </span>
                </div>
              </label>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-4"
          >
            {loading ? "Initializing System..." : "Complete Setup & Create Owner"}
          </button>
        </form>
      </div>
    </div>
  );
}
