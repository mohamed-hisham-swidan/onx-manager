import { useSearchParams } from "react-router-dom";
import { useSettings } from "@/server_manager/hooks/useSettings";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";
import { ApiError } from "@/services/api";
import { ErrorState, ForbiddenState, Skeleton } from "@/components/ui/States";
import { SettingsShell } from "@/server_manager/components/settings/SettingsShell";
import { GeneralSettingsTab } from "@/server_manager/components/settings/GeneralSettingsTab";
import { AppearanceSettingsSection } from "@/server_manager/components/AppearanceSettingsSection";
import { ModpacksCacheTab } from "@/server_manager/components/settings/ModpacksCacheTab";
import { AccessSection } from "@/server_manager/components/AccessSection";
import { UsersPermissionsSection } from "@/server_manager/components/UsersPermissionsSection";
import { ApiKeysPage } from "@/server_manager/pages/ApiKeysPage";
import {
  useSettingsPermissions,
  type SettingsTabId,
} from "@/server_manager/components/settings/settingsModel";

const VALID_TABS = new Set<SettingsTabId>([
  "general",
  "appearance",
  "integrations",
  "access",
  "users",
  "api-keys",
]);

function resolveTab(rawTab: string | null): {
  tab: SettingsTabId;
  initialSubTab: "users" | "invitations";
} {
  if (!rawTab || rawTab === "system") {
    return { tab: "general", initialSubTab: "users" };
  }
  if (rawTab === "invitations") {
    return { tab: "users", initialSubTab: "invitations" };
  }
  if (VALID_TABS.has(rawTab as SettingsTabId)) {
    return { tab: rawTab as SettingsTabId, initialSubTab: "users" };
  }
  return { tab: "general", initialSubTab: "users" };
}

function isForbiddenError(err: unknown): boolean {
  if (err instanceof ApiError && err.status === 403) return true;
  if (err instanceof Error && /\b403\b|forbidden|permission/i.test(err.message)) return true;
  return false;
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { tab: activeTab, initialSubTab } = resolveTab(searchParams.get("tab"));

  const handleTabChange = (tabId: SettingsTabId) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (tabId === "general") {
          next.delete("tab");
        } else {
          next.set("tab", tabId);
        }
        return next;
      },
      { replace: true },
    );
  };

  const { data: settings, isLoading, error, refetch } = useSettings();
  const { isLocal, showFullControls, showFullVpsControls, toggleShowFullVpsControls } =
    useDeploymentProfile();
  const { isOwner, isAdminOrOwner, hasResolvedUser } = useSettingsPermissions();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-48" />
        <div className="space-y-4">
          <Skeleton className="h-36 w-full rounded-xl" />
          <Skeleton className="h-36 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  const isSettingsForbidden = Boolean(error && isForbiddenError(error));
  const canBypassSettings403 =
    isSettingsForbidden && (activeTab === "appearance" || activeTab === "api-keys");

  if (error && !isSettingsForbidden) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load settings"}
        onRetry={() => refetch()}
      />
    );
  }

  if (!settings && !isSettingsForbidden) {
    return <ErrorState message="Settings not available" />;
  }

  const isNonOwnerOnAccess = hasResolvedUser && !isOwner && activeTab === "access";
  const isNonAdminOnRestricted =
    hasResolvedUser &&
    !isAdminOrOwner &&
    (activeTab === "general" || activeTab === "integrations" || activeTab === "users");

  return (
    <SettingsShell
      activeTab={activeTab}
      onTabChange={handleTabChange}
      version={settings?.version}
      isLocal={isLocal}
      showFullControls={showFullControls}
      showFullVpsControls={showFullVpsControls}
      onToggleVpsControls={toggleShowFullVpsControls}
      isOwner={isOwner}
      isAdminOrOwner={!hasResolvedUser || isAdminOrOwner}
    >
      {isSettingsForbidden && !canBypassSettings403 ? (
        <ForbiddenState
          title="Settings Access Restricted"
          message="You do not have permission to view panel settings."
        />
      ) : isNonOwnerOnAccess ? (
        <ForbiddenState
          title="Owner Access Required"
          message="Only the instance Owner can configure panel exposure and access mode."
        />
      ) : isNonAdminOnRestricted ? (
        <ForbiddenState
          title="Settings Access Restricted"
          message="Only instance Owners and Administrators can access this section."
        />
      ) : activeTab === "general" && settings ? (
        <GeneralSettingsTab settings={settings} />
      ) : activeTab === "appearance" ? (
        <AppearanceSettingsSection />
      ) : activeTab === "integrations" ? (
        <ModpacksCacheTab />
      ) : activeTab === "access" ? (
        <AccessSection />
      ) : activeTab === "users" ? (
        <UsersPermissionsSection initialSubTab={initialSubTab} />
      ) : (
        <ApiKeysPage />
      )}
    </SettingsShell>
  );
}
