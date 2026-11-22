import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import {
  isModpackSupportedLoader,
  isPaperFamilyLoader,
} from "@/server_manager/utils/loaderCapabilities";
import type {
  ServerP55SettingsResponse,
  ServerP55SettingsUpdateRequest,
} from "@/server_manager/types";

const DEFAULT_ALLOWED_HOSTS = [
  "cdn.modrinth.com",
  "edge.forgecdn.net",
  "mediafilez.forgecdn.net",
  "maven.fabricmc.net",
  "maven.quiltmc.org",
  "maven.neoforged.net",
  "maven.minecraftforge.net",
  "fill-data.papermc.io",
  "piston-data.mojang.com",
  "libraries.minecraft.net",
  "github.com",
  "objects.githubusercontent.com",
];

const HOSTNAME_PATTERN =
  /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

interface SettingsDraft {
  health_gate_boot_timeout_seconds: number;
  install_optional_server_files: boolean;
  allow_experimental_paper_builds: boolean;
  download_host_allowlist: string[];
}

function fromResponse(response: ServerP55SettingsResponse): SettingsDraft {
  return {
    health_gate_boot_timeout_seconds: response.health_gate_boot_timeout_seconds,
    install_optional_server_files: response.install_optional_server_files,
    allow_experimental_paper_builds: response.allow_experimental_paper_builds,
    download_host_allowlist: [...response.download_host_allowlist],
  };
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Failed to save settings";
}

function ToggleRow({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-border-subtle last:border-b-0">
      <div className="space-y-1">
        <label htmlFor={id} className="text-sm font-semibold text-text-primary">
          {label}
        </label>
        <p className="text-xs text-text-muted leading-relaxed">{description}</p>
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-accent-primary focus:ring-offset-2 ${
          checked ? "bg-accent-primary" : "bg-border-default"
        }`}
      >
        <span
          aria-hidden="true"
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-xs transition duration-200 ease-in-out ${
            checked ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}

export function ServerP55SettingsCard({
  serverId,
  serverType,
}: {
  serverId: string;
  serverType?: string;
}) {
  const showModpackOptionalToggle =
    serverType === undefined || isModpackSupportedLoader(serverType);
  const showPaperExperimentalToggle =
    serverType === undefined || isPaperFamilyLoader(serverType);
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const hasSettingsApi = typeof api.getServerP55Settings === "function";

  const settingsQuery = useQuery({
    queryKey: queryKeys.p55.serverSettings(serverId),
    queryFn: async () => api.getServerP55Settings?.(serverId) ?? null,
    enabled: hasSettingsApi && Boolean(serverId),
  });

  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [customHost, setCustomHost] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [customHostError, setCustomHostError] = useState<string | null>(null);

  const data = settingsQuery.data ?? null;
  const current = draft ?? (data ? fromResponse(data) : null);

  if (!hasSettingsApi || !current) {
    return null;
  }

  const timeout = current.health_gate_boot_timeout_seconds;
  const timeoutInvalid = timeout < 300 || timeout > 900;
  const defaultHosts =
    data?.default_allowed_hosts && data.default_allowed_hosts.length > 0
      ? data.default_allowed_hosts
      : DEFAULT_ALLOWED_HOSTS;

  function update(patch: Partial<SettingsDraft>) {
    setDraft({ ...current!, ...patch });
    setNotice(null);
    setError(null);
  }

  function handleAddHost() {
    const candidate = customHost.trim().toLowerCase();
    if (!candidate) return;
    if (!HOSTNAME_PATTERN.test(candidate)) {
      setCustomHostError(
        "Enter a lowercase domain hostname only (no scheme, port, wildcard, or IP literal).",
      );
      return;
    }
    if (current!.download_host_allowlist.includes(candidate)) {
      setCustomHostError("That hostname is already in the allowlist.");
      return;
    }
    setCustomHost("");
    setCustomHostError(null);
    update({
      download_host_allowlist: [...current!.download_host_allowlist, candidate],
    });
  }

  function handleRemoveHost(host: string) {
    update({
      download_host_allowlist: current!.download_host_allowlist.filter(
        (item) => item !== host,
      ),
    });
  }

  async function handleSave() {
    if (typeof api.updateServerP55Settings !== "function") return;
    if (timeoutInvalid) {
      setError("Health Gate boot timeout must be between 300 and 900 seconds.");
      return;
    }
    const body: ServerP55SettingsUpdateRequest = {
      health_gate_boot_timeout_seconds: current!.health_gate_boot_timeout_seconds,
      install_optional_server_files: current!.install_optional_server_files,
      allow_experimental_paper_builds: current!.allow_experimental_paper_builds,
      download_host_allowlist: current!.download_host_allowlist,
    };
    setIsSaving(true);
    setNotice(null);
    setError(null);
    try {
      const saved = await api.updateServerP55Settings(serverId, body);
      setDraft(fromResponse(saved));
      setNotice("Modpack & upgrade settings saved.");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.p55.serverSettings(serverId),
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section
      data-testid="server-p55-settings-card"
      className="rounded-2xl border border-border-default bg-surface-card shadow-xs"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 p-5 border-b border-border-subtle">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-primary/10 text-accent-primary">
              <Icon name="modrinth" size={16} />
            </span>
            <h3 className="text-base font-bold text-text-primary">
              {showModpackOptionalToggle
                ? "Modpack & Upgrade Settings"
                : "1-Click Upgrade Settings"}
            </h3>
          </div>
          <p className="text-xs text-text-muted max-w-2xl">
            {showModpackOptionalToggle
              ? "Tune the 1-Click Safe Upgrade Health Gate, optional server mod handling, and trusted download hosts for this server."
              : showPaperExperimentalToggle
                ? "Tune the 1-Click Safe Upgrade Health Gate and experimental Paper builds for this server."
                : "Tune the 1-Click Safe Upgrade Health Gate and trusted download hosts for this server."}
          </p>
        </div>
        <Button
          type="button"
          data-testid="save-p55-settings-btn"
          size="sm"
          variant="primary"
          icon="save"
          loading={isSaving}
          disabled={timeoutInvalid}
          onClick={handleSave}
        >
          Save Modpack & Upgrade Settings
        </Button>
      </div>

      {notice && (
        <div className="px-5 pt-4">
          <Banner variant="success" title={notice} />
        </div>
      )}
      {error && (
        <div className="px-5 pt-4">
          <Banner variant="danger" title={error} />
        </div>
      )}

      <div className="px-5 py-4 border-b border-border-subtle space-y-2">
        <label
          htmlFor="p55-health-timeout"
          className="text-sm font-semibold text-text-primary"
        >
          Health Gate Boot Timeout
        </label>
        <p className="text-xs text-text-muted leading-relaxed">
          How long the 4-step race-free Health Gate waits for a heavy modpack to boot
          before restoring the pre-upgrade server. Default 300 seconds (5 min); maximum
          900 seconds (15 min).
        </p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <input
            id="p55-health-timeout"
            type="number"
            min={300}
            max={900}
            step={30}
            value={Number.isFinite(timeout) ? timeout : 300}
            onChange={(event) =>
              update({
                health_gate_boot_timeout_seconds:
                  event.target.value === "" ? 0 : Number(event.target.value),
              })
            }
            className="w-32 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
          <span className="text-xs text-text-muted">seconds (300–900)</span>
          {timeoutInvalid && (
            <span className="text-xs font-medium text-status-danger">
              Must be between 300 and 900 seconds.
            </span>
          )}
        </div>
      </div>

      {showModpackOptionalToggle && (
        <ToggleRow
          id="p55-install-optional"
          label="Install Optional Server Files"
          description="Include entries marked env.server = optional when inspecting modpacks. Disable to keep optional server-side mods out by default."
          checked={current.install_optional_server_files}
          onChange={(checked) => update({ install_optional_server_files: checked })}
        />
      )}

      {showPaperExperimentalToggle && (
        <ToggleRow
          id="p55-experimental-paper"
          label="Allow Experimental Paper Builds"
          description="When no STABLE Paper Fill v3 build exists for the target Minecraft version, permit falling back to an EXPERIMENTAL build."
          checked={current.allow_experimental_paper_builds}
          onChange={(checked) => update({ allow_experimental_paper_builds: checked })}
        />
      )}

      <div className="px-5 py-4 space-y-3">
        <div className="space-y-1">
          <h4 className="text-sm font-semibold text-text-primary">
            Extra Allowed Download Hosts
          </h4>
          <p className="text-xs text-text-muted leading-relaxed">
            Custom lowercase domain hostnames trusted in addition to the panel
            defaults. IP literals, schemes, ports, and wildcards are rejected.
          </p>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {current.download_host_allowlist.length === 0 ? (
            <span className="text-xs text-text-muted">No custom hosts configured.</span>
          ) : (
            current.download_host_allowlist.map((host) => (
              <span
                key={host}
                className="inline-flex items-center gap-1 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-2.5 py-0.5 font-mono text-[11px] text-accent-primary"
              >
                {host}
                <button
                  type="button"
                  aria-label={`Remove ${host}`}
                  onClick={() => handleRemoveHost(host)}
                  className="rounded-full p-0.5 hover:bg-accent-primary/20 cursor-pointer"
                >
                  <Icon name="x" size={10} />
                </button>
              </span>
            ))
          )}
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label
              htmlFor="p55-custom-host"
              className="mb-1 block text-[11px] font-medium text-text-muted"
            >
              Add Custom Hostname
            </label>
            <input
              id="p55-custom-host"
              value={customHost}
              onChange={(event) => {
                setCustomHost(event.target.value);
                setCustomHostError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  handleAddHost();
                }
              }}
              placeholder="mirror.example.com"
              className="w-64 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
          </div>
          <Button type="button" size="sm" variant="secondary" icon="plus" onClick={handleAddHost}>
            Add Host
          </Button>
        </div>
        {customHostError && (
          <p className="text-xs font-medium text-status-danger">{customHostError}</p>
        )}

        <div className="pt-1 space-y-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
            Panel Default Hosts (read-only)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {defaultHosts.map((host) => (
              <span
                key={host}
                className="inline-flex items-center rounded-full border border-border-default bg-surface-elevated px-2.5 py-0.5 font-mono text-[11px] text-text-muted"
              >
                {host}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
