import { useContext } from "react";
import { QueryClient, QueryClientContext, useQuery } from "@tanstack/react-query";
import * as apiModule from "@/services/api";
import { useUIStore } from "@/stores/uiStore";
import type { AuthMode, DeploymentProfile, SystemStatusResponse } from "@/types";

const noopQueryClient = new QueryClient({
  defaultOptions: { queries: { enabled: false, retry: false } },
});

function resolveSetupStatusReader(): (() => Promise<SystemStatusResponse>) | null {
  try {
    const authFactory = apiModule.createAuthenticatedApi;
    if (typeof authFactory === "function") {
      const client = authFactory() as Partial<ReturnType<typeof apiModule.createApiClient>>;
      if (typeof client?.getSetupStatus === "function") {
        return () => client.getSetupStatus!();
      }
    }
  } catch {
    // Test mocks may omit createAuthenticatedApi from @/services/api.
  }

  try {
    const clientFactory = apiModule.createApiClient;
    if (typeof clientFactory === "function" && typeof window !== "undefined") {
      const client = clientFactory(
        window.location.origin,
        () => null,
      ) as Partial<ReturnType<typeof apiModule.createApiClient>>;
      if (typeof client?.getSetupStatus === "function") {
        return () => client.getSetupStatus!();
      }
    }
  } catch {
    // Test mocks may omit createApiClient from @/services/api.
  }

  return null;
}

export interface DeploymentProfileState {
  profile: DeploymentProfile;
  hasExplicitProfile: boolean;
  isLocal: boolean;
  isVps: boolean;
  authMode: AuthMode;
  passwordConfigured: boolean;
  isLocalZeroLogin: boolean;
  showFullControls: boolean;
  showFullVpsControls: boolean;
  setShowFullVpsControls: (show: boolean) => void;
  toggleShowFullVpsControls: () => void;
}

export function useDeploymentProfile(): DeploymentProfileState {
  const ctxClient = useContext(QueryClientContext);
  const showFullVpsControls = useUIStore((s) => s.showFullVpsControls);
  const setShowFullVpsControls = useUIStore((s) => s.setShowFullVpsControls);
  const toggleShowFullVpsControls = useUIStore((s) => s.toggleShowFullVpsControls);

  const readSetupStatus = resolveSetupStatusReader();
  const canQuery = Boolean(ctxClient) && readSetupStatus !== null;

  const { data } = useQuery<SystemStatusResponse | undefined>(
    {
      queryKey: ["systemStatus"],
      queryFn: () => readSetupStatus!(),
      enabled: canQuery,
      staleTime: 1000 * 30,
    },
    ctxClient ?? noopQueryClient,
  );

  const rawProfile = data?.deployment_profile;
  const hasExplicitProfile = rawProfile === "local" || rawProfile === "vps";
  const profile: DeploymentProfile = rawProfile === "local" ? "local" : "vps";
  const isLocal = profile === "local";
  const isVps = profile === "vps";
  const authMode: AuthMode = data?.auth_mode === "local_zero_login" ? "local_zero_login" : "jwt";
  const isLocalZeroLogin = authMode === "local_zero_login";
  const passwordConfigured = data?.password_configured ?? !isLocalZeroLogin;
  const showFullControls = isVps || showFullVpsControls;

  return {
    profile,
    hasExplicitProfile,
    isLocal,
    isVps,
    authMode,
    passwordConfigured,
    isLocalZeroLogin,
    showFullControls,
    showFullVpsControls,
    setShowFullVpsControls,
    toggleShowFullVpsControls,
  };
}
