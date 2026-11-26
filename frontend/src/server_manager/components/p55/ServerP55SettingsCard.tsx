import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
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

const TIMEOUT_QUICK_CHIPS = [300, 600, 900] as const;

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
  disabled = false,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-border-subtle last:border-b-0">
      <div className="space-y-1">
        <label htmlFor={id} className="text-sm font-medium text-text-primary">
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
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-45 disabled:cursor-not-allowed ${
          checked ? "bg-accent-primary" : "bg-border-default"
        }`}
      >
        <span
          aria-hidden="true"
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-accent-contrast-text shadow-xs transition duration-200 ease-in-out ${
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
  readOnly = false,
}: {
  serverId: string;
  serverType?: string;
  readOnly?: boolean;
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
  const [rawTimeout, setRawTimeout] = useState<string | null>(null);
  const [customHost, setCustomHost] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [customHostError, setCustomHostError] = useState<string | null>(null);
  const [showDefaultHosts, setShowDefaultHosts] = useState(false);

  const data = settingsQuery.data ?? null;
  const baseline = useMemo(() => (data ? fromResponse(data) : null), [data]);
  const current = draft ?? baseline;

  if (!hasSettingsApi || !current || !baseline) {
    return null;
  }

  const parsedTimeoutForValidation =
    rawTimeout !== null
      ? rawTimeout.trim() === ""
        ? null
        : Number(rawTimeout)
      : current.health_gate_boot_timeout_seconds;

  const timeoutInvalid =
    parsedTimeoutForValidation !== null &&
    (!Number.isFinite(parsedTimeoutForValidation) ||
      parsedTimeoutForValidation < 300 ||
      parsedTimeoutForValidation > 900);

  const effectiveTimeoutForDirty =
    rawTimeout !== null &&
    rawTimeout.trim() !== "" &&
    Number.isFinite(Number(rawTimeout))
      ? Math.round(Number(rawTimeout))
      : current.health_gate_boot_timeout_seconds;

  const isDirty =
    effectiveTimeoutForDirty !== baseline.health_gate_boot_timeout_seconds ||
    current.install_optional_server_files !==
      baseline.install_optional_server_files ||
    current.allow_experimental_paper_builds !==
      baseline.allow_experimental_paper_builds ||
    current.download_host_allowlist.length !==
      baseline.download_host_allowlist.length ||
    current.download_host_allowlist.some(
      (host, idx) => host !== baseline.download_host_allowlist[idx],
    );

  const defaultHosts =
    data?.default_allowed_hosts && data.default_allowed_hosts.length > 0
      ? data.default_allowed_hosts
      : DEFAULT_ALLOWED_HOSTS;

  function update(patch: Partial<SettingsDraft>) {
    if (readOnly) return;
    setDraft({ ...current!, ...patch });
  }

  function handleTimeoutChange(value: string) {
    if (readOnly) return;
    setRawTimeout(value);
    if (value.trim() !== "") {
      const num = Number(value);
      if (Number.isFinite(num)) {
        update({ health_gate_boot_timeout_seconds: Math.round(num) });
      }
    }
  }

  function handleTimeoutBlur() {
    if (rawTimeout === null) return;
    if (rawTimeout.trim() === "" || isNaN(Number(rawTimeout))) {
      setRawTimeout(null);
      return;
    }
    const clamped = Math.min(900, Math.max(300, Math.round(Number(rawTimeout))));
    update({ health_gate_boot_timeout_seconds: clamped });
    setRawTimeout(null);
  }

  function handleAddHost() {
    if (readOnly) return;
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
    if (readOnly) return;
    update({
      download_host_allowlist: current!.download_host_allowlist.filter(
        (item) => item !== host,
      ),
    });
  }

  function handleReset() {
    setDraft(null);
    setRawTimeout(null);
    setCustomHostError(null);
  }

  async function handleSave() {
    if (readOnly || typeof api.updateServerP55Settings !== "function") return;
    let effectiveTimeout = current!.health_gate_boot_timeout_seconds;
    if (rawTimeout !== null) {
      if (rawTimeout.trim() === "" || isNaN(Number(rawTimeout))) {
        effectiveTimeout = baseline!.health_gate_boot_timeout_seconds;
      } else {
        effectiveTimeout = Math.round(Number(rawTimeout));
      }
      setRawTimeout(null);
    }
    if (effectiveTimeout < 300 || effectiveTimeout > 900) {
      toast(
        "error",
        "Invalid boot timeout",
        "Health Gate boot timeout must be between 300 and 900 seconds.",
      );
      return;
    }

    const body: ServerP55SettingsUpdateRequest = {
      health_gate_boot_timeout_seconds: effectiveTimeout,
      install_optional_server_files: current!.install_optional_server_files,
      allow_experimental_paper_builds: current!.allow_experimental_paper_builds,
      download_host_allowlist: current!.download_host_allowlist,
    };
    setIsSaving(true);
    try {
      const saved = await api.updateServerP55Settings(serverId, body);
      setDraft(fromResponse(saved));
      toast("success", "Upgrade settings saved", "Modpack & upgrade settings saved.");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.p55.serverSettings(serverId),
      });
    } catch (err) {
      toast("error", "Save failed", errorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }

  const displayedTimeout =
    rawTimeout !== null
      ? rawTimeout
      : String(
          Number.isFinite(current.health_gate_boot_timeout_seconds)
            ? current.health_gate_boot_timeout_seconds
            : 300,
        );

  return (
    <section
      data-testid="server-p55-settings-card"
      className="rounded-xl border border-border-subtle bg-surface-card overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-border-subtle bg-surface-muted/40">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-text-primary">
              {showModpackOptionalToggle
                ? "Modpack & Change Version Settings"
                : "Change Version Settings"}
            </h3>
            {isDirty && !readOnly && (
              <span className="inline-flex items-center gap-1 rounded-full bg-status-warning-bg px-2 py-0.5 text-[10px] font-medium text-status-warning">
                <span className="h-1.5 w-1.5 rounded-full bg-status-warning" />
                Unsaved
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted">
            {showModpackOptionalToggle
              ? "Safe upgrade timeout, optional mods, and trusted download hosts."
              : "Safe upgrade timeout and trusted download hosts."}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!isDirty || isSaving || readOnly}
            onClick={handleReset}
          >
            Reset
          </Button>
          <Button
            type="button"
            data-testid="save-p55-settings-btn"
            size="sm"
            variant="primary"
            icon="save"
            loading={isSaving}
            disabled={!isDirty || timeoutInvalid || readOnly}
            onClick={handleSave}
          >
            Save Upgrade Settings
          </Button>
        </div>
      </div>

      <div className="px-5 py-4 border-b border-border-subtle space-y-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="space-y-0.5">
            <label
              htmlFor="p55-health-timeout"
              className="text-sm font-medium text-text-primary"
            >
              Health Gate Boot Timeout
            </label>
            <p className="text-xs text-text-muted">
              Max boot wait before restoring the pre-upgrade server (300–900s).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              id="p55-health-timeout"
              type="number"
              min={300}
              max={900}
              step={30}
              disabled={readOnly}
              value={displayedTimeout}
              onChange={(event) => handleTimeoutChange(event.target.value)}
              onBlur={handleTimeoutBlur}
              className="w-28 rounded-lg border border-border-subtle bg-surface-page px-3 py-1.5 font-mono text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
            />
            <span className="text-xs text-text-muted">sec</span>
            <div className="flex items-center gap-1">
              {TIMEOUT_QUICK_CHIPS.map((secs) => (
                <button
                  key={secs}
                  type="button"
                  disabled={readOnly}
                  onClick={() => {
                    setRawTimeout(null);
                    update({ health_gate_boot_timeout_seconds: secs });
                  }}
                  className={`rounded-md border px-2 py-1 text-[11px] font-medium cursor-pointer disabled:opacity-45 ${
                    current.health_gate_boot_timeout_seconds === secs &&
                    rawTimeout === null
                      ? "border-accent-primary bg-accent-primary/12 text-accent-primary"
                      : "border-border-subtle bg-surface-muted text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {secs}s
                </button>
              ))}
            </div>
          </div>
        </div>
        {timeoutInvalid && (
          <p className="text-xs font-medium text-status-danger">
            Must be between 300 and 900 seconds.
          </p>
        )}
      </div>

      {showModpackOptionalToggle && (
        <ToggleRow
          id="p55-install-optional"
          label="Install Optional Server Files"
          description="Include entries marked env.server = optional when inspecting modpacks."
          checked={current.install_optional_server_files}
          disabled={readOnly}
          onChange={(checked) =>
            update({ install_optional_server_files: checked })
          }
        />
      )}

      {showPaperExperimentalToggle && (
        <ToggleRow
          id="p55-experimental-paper"
          label="Allow Experimental Paper Builds"
          description="Fallback to an experimental Paper build if no stable build exists."
          checked={current.allow_experimental_paper_builds}
          disabled={readOnly}
          onChange={(checked) =>
            update({ allow_experimental_paper_builds: checked })
          }
        />
      )}

      <div className="px-5 py-4 space-y-3">
        <div className="space-y-0.5">
          <h4 className="text-sm font-medium text-text-primary">
            Extra Allowed Download Hosts
          </h4>
          <p className="text-xs text-text-muted">
            Trusted custom hostnames added to the panel default allowlist.
          </p>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {current.download_host_allowlist.length === 0 ? (
            <span className="text-xs text-text-muted">
              No custom hosts configured.
            </span>
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
                  disabled={readOnly}
                  onClick={() => handleRemoveHost(host)}
                  className="rounded-full p-0.5 hover:bg-accent-primary/20 cursor-pointer disabled:opacity-40"
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
              disabled={readOnly}
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
              className="w-64 rounded-lg border border-border-subtle bg-surface-page px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            icon="plus"
            disabled={readOnly}
            onClick={handleAddHost}
          >
            Add Host
          </Button>
        </div>
        {customHostError && (
          <p className="text-xs font-medium text-status-danger">
            {customHostError}
          </p>
        )}

        <div className="pt-1">
          <button
            type="button"
            aria-expanded={showDefaultHosts}
            onClick={() => setShowDefaultHosts((prev) => !prev)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-text-primary cursor-pointer"
          >
            <Icon
              name={showDefaultHosts ? "chevron-down" : "chevron-right"}
              size={13}
            />
            <span>View {defaultHosts.length} default hosts</span>
          </button>

          {showDefaultHosts && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {defaultHosts.map((host) => (
                <span
                  key={host}
                  className="inline-flex items-center rounded-full border border-border-subtle bg-surface-muted px-2.5 py-0.5 font-mono text-[11px] text-text-muted"
                >
                  {host}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
