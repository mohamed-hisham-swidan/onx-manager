import { create } from "zustand";
import { resetAuthenticatedApi } from "../services/api";
import { queryClient } from "../services/queryClient";

const STORAGE_KEY = "mcs_auth";

interface StoredAuth {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  acquiredAt: number;
}

function loadAuth(): StoredAuth | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
}

function saveAuth(data: StoredAuth) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function clearAuth() {
  localStorage.removeItem(STORAGE_KEY);
}

function isExpired(auth: StoredAuth): boolean {
  return Date.now() - auth.acquiredAt > auth.expiresIn * 1000;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  isAuthenticated: boolean;
  login: (accessToken: string, refreshToken: string, expiresIn: number) => void;
  setTokens: (accessToken: string, refreshToken: string, expiresIn: number) => void;
  logout: () => void;
  getAccessToken: () => string | null;
  isTokenExpiringSoon: (thresholdSeconds?: number) => boolean;
  refreshAuth: () => Promise<boolean>;
}

export const useAuthStore = create<AuthState>((set, get) => {
  const stored = loadAuth();
  const valid = stored && !isExpired(stored);

  return {
    accessToken: valid ? stored!.accessToken : null,
    refreshToken: stored ? stored.refreshToken : null,
    expiresAt: valid ? stored!.acquiredAt + stored!.expiresIn * 1000 : null,
    isAuthenticated: valid ?? false,

    login: (accessToken, refreshToken, expiresIn) => {
      const now = Date.now();
      const auth: StoredAuth = { accessToken, refreshToken, expiresIn, acquiredAt: now };
      saveAuth(auth);
      set({ accessToken, refreshToken, expiresAt: now + expiresIn * 1000, isAuthenticated: true });
    },

    setTokens: (accessToken, refreshToken, expiresIn) => {
      const now = Date.now();
      const auth: StoredAuth = { accessToken, refreshToken, expiresIn, acquiredAt: now };
      saveAuth(auth);
      set({ accessToken, refreshToken, expiresAt: now + expiresIn * 1000, isAuthenticated: true });
    },

    logout: () => {
      clearAuth();
      resetAuthenticatedApi();
      queryClient.clear();
      set({ accessToken: null, refreshToken: null, expiresAt: null, isAuthenticated: false });
    },

    getAccessToken: () => get().accessToken,

    isTokenExpiringSoon: (thresholdSeconds = 30) => {
      const state = get();
      if (!state.accessToken) return true;
      if (state.expiresAt !== null) {
        return Date.now() >= state.expiresAt - thresholdSeconds * 1000;
      }
      return false;
    },

    refreshAuth: async () => {
      const state = get();
      const rf = state.refreshToken || (loadAuth()?.refreshToken ?? null);
      if (!rf) return false;
      const origin =
        typeof window !== "undefined" && window.location && window.location.origin
          ? window.location.origin
          : "http://localhost:8000";
      try {
        const res = await fetch(`${origin}/api/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rf }),
        });
        if (!res.ok) {
          get().logout();
          return false;
        }
        const data = (await res.json()) as {
          access_token: string;
          refresh_token: string;
          expires_in: number;
        };
        get().setTokens(data.access_token, data.refresh_token, data.expires_in);
        return true;
      } catch {
        get().logout();
        return false;
      }
    },
  };
});
