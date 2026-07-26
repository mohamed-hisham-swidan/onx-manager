import { create } from "zustand";

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
  isAuthenticated: boolean;
  login: (accessToken: string, refreshToken: string, expiresIn: number) => void;
  setTokens: (accessToken: string, refreshToken: string, expiresIn: number) => void;
  logout: () => void;
  getAccessToken: () => string | null;
}

export const useAuthStore = create<AuthState>((set, get) => {
  const stored = loadAuth();
  const valid = stored && !isExpired(stored);

  return {
    accessToken: valid ? stored!.accessToken : null,
    refreshToken: valid ? stored!.refreshToken : null,
    isAuthenticated: valid ?? false,

    login: (accessToken, refreshToken, expiresIn) => {
      const auth: StoredAuth = { accessToken, refreshToken, expiresIn, acquiredAt: Date.now() };
      saveAuth(auth);
      set({ accessToken, refreshToken, isAuthenticated: true });
    },

    setTokens: (accessToken, refreshToken, expiresIn) => {
      const auth: StoredAuth = { accessToken, refreshToken, expiresIn, acquiredAt: Date.now() };
      saveAuth(auth);
      set({ accessToken, refreshToken, isAuthenticated: true });
    },

    logout: () => {
      clearAuth();
      set({ accessToken: null, refreshToken: null, isAuthenticated: false });
    },

    getAccessToken: () => get().accessToken,
  };
});
