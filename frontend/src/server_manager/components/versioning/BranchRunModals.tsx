import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { useHostResources } from "@/server_manager/hooks/useHostResources";
import { HostResourceBudgetBar } from "@/server_manager/components/HostResourceBudgetBar";
import type {
  BranchConsoleLogsResponse,
  DataTemplate,
  DataTemplateSource,
  PortSet,
  ServerActivityLog,
  ServerBranch,
  SetPortSetRequest,
  StartBranchRunRequest,
  StartBranchRunResponse,
  StopBranchRunResponse,
} from "@/server_manager/types";

const inputClass =
  "w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50";
const labelClass = "block text-xs font-medium text-text-secondary mb-1";
const secondaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const primaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover shadow-xs transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";

function extractErrorInfo(
  err: unknown,
  fallback: string,
): { code: string | null; status: number | null; message: string } {
  const rec = err as { code?: unknown; status?: unknown; message?: unknown } | null;
  return {
    code: typeof rec?.code === "string" ? rec.code : null,
    status: typeof rec?.status === "number" ? rec.status : null,
    message: err instanceof Error && err.message ? err.message : fallback,
  };
}

function describeError(err: unknown, fallback: string): string {
  const info = extractErrorInfo(err, fallback);
  if (info.code && info.status) return `${info.code} (HTTP ${info.status}): ${info.message}`;
  if (info.code) return `${info.code}: ${info.message}`;
  if (info.status) return `HTTP ${info.status}: ${info.message}`;
  return info.message;
}

function describePortError(err: unknown): string {
  const info = extractErrorInfo(err, "Failed to update the branch port set.");
  if (info.code === "DUPLICATE_PORT_SET") {
    return `Port conflict (DUPLICATE_PORT_SET): ${info.message}`;
  }
  if (info.code === "BRANCH_RUNTIME_ACTIVE") {
    return `Branch runtime active (BRANCH_RUNTIME_ACTIVE): ${info.message}`;
  }
  return describeError(err, "Failed to update the branch port set.");
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatTimestamp(timestamp: number): string {
  const ms = timestamp > 1e11 ? timestamp : timestamp * 1000;
  return new Date(ms).toLocaleString();
}

function templateStatusClasses(status: string): string {
  if (status === "ready") {
    return "bg-status-success-bg text-status-success border-status-success-border";
  }
  if (status === "cloning") {
    return "bg-status-info-bg text-status-info border-status-info-border animate-pulse";
  }
  if (status === "failed") {
    return "bg-status-danger-bg text-status-danger border-status-danger-border";
  }
  return "bg-surface-elevated text-text-muted border-border-default";
}

function parseOptionalInteger(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function isValidPort(port: number | null): boolean {
  return port !== null && Number.isInteger(port) && port >= 1024 && port <= 65535;
}

// ==========================================
// 1. Start Branch Run Modal
// ==========================================
export interface StartBranchRunModalProps {
  isOpen: boolean;
  serverId: string;
  branchName: string;
  dataTemplates: DataTemplate[];
  portSet: PortSet | null;
  onStarted: (result: StartBranchRunResponse) => void;
  onClose: () => void;
}

export function StartBranchRunModal({
  isOpen,
  serverId,
  branchName,
  dataTemplates,
  portSet,
  onStarted,
  onClose,
}: StartBranchRunModalProps) {
  const [isPending, setIsPending] = useState(false);
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Start Branch Run"
      description={`Launch an isolated container for branch '${branchName}' from its last committed SHA.`}
      size="lg"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      {isOpen && (
        <StartBranchRunBody
          serverId={serverId}
          branchName={branchName}
          dataTemplates={dataTemplates}
          portSet={portSet}
          isPending={isPending}
          onPendingChange={setIsPending}
          onStarted={onStarted}
          onClose={onClose}
        />
      )}
    </Modal>
  );
}

interface StartBranchRunBodyProps {
  serverId: string;
  branchName: string;
  dataTemplates: DataTemplate[];
  portSet: PortSet | null;
  isPending: boolean;
  onPendingChange: (pending: boolean) => void;
  onStarted: (result: StartBranchRunResponse) => void;
  onClose: () => void;
}

function StartBranchRunBody({
  serverId,
  branchName,
  dataTemplates,
  portSet,
  isPending,
  onPendingChange,
  onStarted,
  onClose,
}: StartBranchRunBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { data: hostBudget } = useHostResources();
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [allowPublicTestJoin, setAllowPublicTestJoin] = useState(false);
  const [includeQuery, setIncludeQuery] = useState(false);
  const [useCustomPorts, setUseCustomPorts] = useState(false);
  const [gamePort, setGamePort] = useState("");
  const [rconPort, setRconPort] = useState("");
  const [queryPort, setQueryPort] = useState("");
  const [memoryMb, setMemoryMb] = useState("");
  const [cpuCores, setCpuCores] = useState("");
  const [error, setError] = useState<string | null>(null);

  const readyTemplates = dataTemplates.filter((t) => t.status === "ready");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isPending) return;
    setError(null);

    const payload: StartBranchRunRequest = {
      data_template_id: selectedTemplateId || null,
      allow_public_test_join: allowPublicTestJoin,
      include_query: includeQuery,
    };

    if (useCustomPorts) {
      const parsedGamePort = parseOptionalInteger(gamePort);
      const parsedRconPort = parseOptionalInteger(rconPort);
      const parsedQueryPort = parseOptionalInteger(queryPort);
      if (!isValidPort(parsedGamePort) || !isValidPort(parsedRconPort)) {
        setError("Game and RCON ports must be between 1024 and 65535.");
        return;
      }
      if (queryPort.trim() && !isValidPort(parsedQueryPort)) {
        setError("Query port must be between 1024 and 65535.");
        return;
      }
      payload.port_set = {
        game_port: parsedGamePort as number,
        rcon_port: parsedRconPort as number,
        query_port: parsedQueryPort,
      };
    }

    const memoryValue = parseOptionalInteger(memoryMb);
    if (memoryMb.trim() && (memoryValue === null || memoryValue < 256)) {
      setError("Memory override must be at least 256 MB.");
      return;
    }
    if (memoryValue !== null) payload.requested_memory_mb = memoryValue;

    const cpuValue = parseOptionalInteger(cpuCores);
    if (cpuCores.trim() && (cpuValue === null || cpuValue < 1)) {
      setError("CPU core override must be at least 1.");
      return;
    }
    if (cpuValue !== null) payload.requested_cpu_cores = cpuValue;

    onPendingChange(true);
    try {
      const result = await api.startBranchRun(serverId, branchName, payload);
      onStarted(result);
      onClose();
    } catch (err: unknown) {
      setError(describeError(err, "Failed to start the branch run."));
    } finally {
      onPendingChange(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          {error}
        </div>
      )}

      <div>
        <label htmlFor="branch-run-template" className={labelClass}>
          Data Template
        </label>
        <select
          id="branch-run-template"
          aria-label="Data Template"
          value={selectedTemplateId}
          onChange={(e) => setSelectedTemplateId(e.target.value)}
          disabled={isPending}
          className={inputClass}
        >
          <option value="">Fresh world from seed</option>
          {readyTemplates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.file_count} files)
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-page p-3 space-y-1.5">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            aria-label="Allow Public Test Join"
            checked={allowPublicTestJoin}
            onChange={(e) => setAllowPublicTestJoin(e.target.checked)}
            disabled={isPending}
            className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
          />
          <span className="text-xs font-semibold text-text-primary">
            Allow Public Test Join
          </span>
        </label>
        <p className="text-[11px] text-text-muted pl-6">
          Off by default: enforces whitelist from an ephemeral Class-C copy.
          Enable only to allow non-whitelisted players to join.
        </p>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-page p-3 space-y-2.5">
        <div className="text-xs font-semibold text-text-primary">Port Set Configuration</div>
        {portSet ? (
          <p className="text-[11px] text-text-secondary">
            Using assigned ports: Game {portSet.game_port}, RCON {portSet.rcon_port}
          </p>
        ) : (
          <p className="text-[11px] text-text-muted">
            No port set assigned. Ports will be auto-allocated on start.
          </p>
        )}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            aria-label="Specify custom port set"
            checked={useCustomPorts}
            onChange={(e) => setUseCustomPorts(e.target.checked)}
            disabled={isPending}
            className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
          />
          <span className="text-xs text-text-secondary">Specify custom port set</span>
        </label>

        {!useCustomPorts && !portSet && (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              aria-label="Include Query Port"
              checked={includeQuery}
              onChange={(e) => setIncludeQuery(e.target.checked)}
              disabled={isPending}
              className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
            />
            <span className="text-xs text-text-secondary">Include Query Port</span>
          </label>
        )}

        {useCustomPorts && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div>
              <label htmlFor="branch-run-game-port" className={labelClass}>
                Game Port
              </label>
              <input
                id="branch-run-game-port"
                type="number"
                min={1024}
                max={65535}
                value={gamePort}
                onChange={(e) => setGamePort(e.target.value)}
                disabled={isPending}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="branch-run-rcon-port" className={labelClass}>
                RCON Port
              </label>
              <input
                id="branch-run-rcon-port"
                type="number"
                min={1024}
                max={65535}
                value={rconPort}
                onChange={(e) => setRconPort(e.target.value)}
                disabled={isPending}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="branch-run-query-port" className={labelClass}>
                Query Port (optional)
              </label>
              <input
                id="branch-run-query-port"
                type="number"
                min={1024}
                max={65535}
                value={queryPort}
                onChange={(e) => setQueryPort(e.target.value)}
                disabled={isPending}
                className={inputClass}
              />
            </div>
          </div>
        )}
      </div>

      {hostBudget && (
        <HostResourceBudgetBar
          budget={hostBudget}
          requestedRamMb={parseOptionalInteger(memoryMb)}
          requestedCpuCores={parseOptionalInteger(cpuCores)}
          compact
        />
      )}

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label htmlFor="branch-run-memory" className={labelClass}>
            Memory (MB)
          </label>
          <input
            id="branch-run-memory"
            type="number"
            min={256}
            max={hostBudget?.allocatable_ram_mb}
            value={memoryMb}
            onChange={(e) => setMemoryMb(e.target.value)}
            disabled={isPending}
            placeholder="Default"
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="branch-run-cpu" className={labelClass}>
            CPU Cores
          </label>
          <input
            id="branch-run-cpu"
            type="number"
            min={1}
            max={hostBudget?.allocatable_cpus ? Math.floor(hostBudget.allocatable_cpus) : undefined}
            value={cpuCores}
            onChange={(e) => setCpuCores(e.target.value)}
            disabled={isPending}
            placeholder="Default"
            className={inputClass}
          />
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onClose}
          disabled={isPending}
          className={secondaryButtonClass}
        >
          Cancel
        </button>
        <button type="submit" disabled={isPending} className={primaryButtonClass}>
          <Icon name="play" size={13} />
          {isPending ? "Starting..." : "Start Branch Run"}
        </button>
      </div>
    </form>
  );
}

// ==========================================
// 2. Stop Branch Run Modal
// ==========================================
export interface StopBranchRunModalProps {
  isOpen: boolean;
  serverId: string;
  branchName: string;
  runtimeId?: string | null;
  onStopped: (result: StopBranchRunResponse) => void;
  onClose: () => void;
}

export function StopBranchRunModal({
  isOpen,
  serverId,
  branchName,
  runtimeId,
  onStopped,
  onClose,
}: StopBranchRunModalProps) {
  const [isPending, setIsPending] = useState(false);
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Stop Branch Run"
      description={`Stop the active runtime for branch '${branchName}'.`}
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      {isOpen && (
        <StopBranchRunBody
          serverId={serverId}
          branchName={branchName}
          runtimeId={runtimeId}
          isPending={isPending}
          onPendingChange={setIsPending}
          onStopped={onStopped}
          onClose={onClose}
        />
      )}
    </Modal>
  );
}

interface StopBranchRunBodyProps {
  serverId: string;
  branchName: string;
  runtimeId?: string | null;
  isPending: boolean;
  onPendingChange: (pending: boolean) => void;
  onStopped: (result: StopBranchRunResponse) => void;
  onClose: () => void;
}

function StopBranchRunBody({
  serverId,
  branchName,
  runtimeId,
  isPending,
  onPendingChange,
  onStopped,
  onClose,
}: StopBranchRunBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [keepPortAssignment, setKeepPortAssignment] = useState(false);
  const [saveTemplate, setSaveTemplate] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submitDisabled = isPending || (saveTemplate && !templateName.trim());

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitDisabled) return;
    setError(null);
    onPendingChange(true);
    try {
      const result = await api.stopBranchRun(serverId, branchName, {
        runtime_id: runtimeId ?? undefined,
        keep_port_assignment: keepPortAssignment,
        ...(saveTemplate
          ? {
              save_template_name: templateName.trim(),
              save_template_description: templateDescription.trim(),
            }
          : {}),
      });
      onStopped(result);
      onClose();
    } catch (err: unknown) {
      setError(describeError(err, "Failed to stop the branch run."));
    } finally {
      onPendingChange(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          {error}
        </div>
      )}

      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          aria-label="Keep Port Assignment"
          checked={keepPortAssignment}
          onChange={(e) => setKeepPortAssignment(e.target.checked)}
          disabled={isPending}
          className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
        />
        <span className="text-xs text-text-secondary">
          Keep Port Assignment
        </span>
      </label>

      <div className="space-y-2.5">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            aria-label="Save Data Template before stop"
            checked={saveTemplate}
            onChange={(e) => setSaveTemplate(e.target.checked)}
            disabled={isPending}
            className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
          />
          <span className="text-xs text-text-secondary">
            Save Data Template before stop
          </span>
        </label>

        {saveTemplate && (
          <div className="space-y-2 rounded-lg border border-border-subtle bg-surface-page p-3">
            <div>
              <label htmlFor="stop-template-name" className={labelClass}>
                Template Name
              </label>
              <input
                id="stop-template-name"
                type="text"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                maxLength={100}
                required
                disabled={isPending}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="stop-template-description" className={labelClass}>
                Template Description (optional)
              </label>
              <input
                id="stop-template-description"
                type="text"
                value={templateDescription}
                onChange={(e) => setTemplateDescription(e.target.value)}
                maxLength={500}
                disabled={isPending}
                className={inputClass}
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onClose}
          disabled={isPending}
          className={secondaryButtonClass}
        >
          Cancel
        </button>
        <button type="submit" disabled={submitDisabled} className={primaryButtonClass}>
          <Icon name="stop" size={13} />
          {isPending ? "Stopping..." : "Stop Branch Run"}
        </button>
      </div>
    </form>
  );
}

// ==========================================
// 3. Branch Port Set Modal
// ==========================================
export interface BranchPortSetModalProps {
  isOpen: boolean;
  serverId: string;
  branchName: string;
  portSet: PortSet | null;
  onUpdated: (portSet: PortSet) => void;
  onClose: () => void;
}

export function BranchPortSetModal({
  isOpen,
  serverId,
  branchName,
  portSet,
  onUpdated,
  onClose,
}: BranchPortSetModalProps) {
  const [isPending, setIsPending] = useState(false);
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Branch Port Set Configuration"
      description={`Reserve host ports for branch '${branchName}'.`}
      size="lg"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      {isOpen && (
        <BranchPortSetBody
          serverId={serverId}
          branchName={branchName}
          portSet={portSet}
          onPendingChange={setIsPending}
          onUpdated={onUpdated}
          onClose={onClose}
        />
      )}
    </Modal>
  );
}

interface PluginPortRow {
  id: number;
  name: string;
  port: string;
}

interface BranchPortSetBodyProps {
  serverId: string;
  branchName: string;
  portSet: PortSet | null;
  onPendingChange: (pending: boolean) => void;
  onUpdated: (portSet: PortSet) => void;
  onClose: () => void;
}

function BranchPortSetBody({
  serverId,
  branchName,
  portSet,
  onPendingChange,
  onUpdated,
  onClose,
}: BranchPortSetBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [gamePort, setGamePort] = useState(portSet ? String(portSet.game_port) : "");
  const [rconPort, setRconPort] = useState(portSet ? String(portSet.rcon_port) : "");
  const [queryPort, setQueryPort] = useState(
    portSet?.query_port !== null && portSet?.query_port !== undefined
      ? String(portSet.query_port)
      : "",
  );
  const [pluginRows, setPluginRows] = useState<PluginPortRow[]>(() =>
    Object.entries(portSet?.plugin_ports ?? {}).map(([name, port], index) => ({
      id: index + 1,
      name,
      port: String(port),
    })),
  );
  const nextRowId = useRef(Object.keys(portSet?.plugin_ports ?? {}).length + 1);
  const [includeQuery, setIncludeQuery] = useState(false);
  const [pluginPortNames, setPluginPortNames] = useState("");
  const [isAllocating, setIsAllocating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyPortSet = (nextPortSet: PortSet) => {
    setGamePort(String(nextPortSet.game_port));
    setRconPort(String(nextPortSet.rcon_port));
    setQueryPort(
      nextPortSet.query_port !== null && nextPortSet.query_port !== undefined
        ? String(nextPortSet.query_port)
        : "",
    );
    setPluginRows(
      Object.entries(nextPortSet.plugin_ports ?? {}).map(([name, port]) => ({
        id: nextRowId.current++,
        name,
        port: String(port),
      })),
    );
  };

  const handleAllocate = async () => {
    setError(null);
    setIsAllocating(true);
    onPendingChange(true);
    try {
      const names = pluginPortNames
        .split(",")
        .map((name) => name.trim())
        .filter((name) => name.length > 0)
        .slice(0, 16);
      const result = await api.allocateBranchPortSet(serverId, branchName, {
        include_query: includeQuery,
        plugin_port_names: names,
      });
      applyPortSet(result.port_set);
      onUpdated(result.port_set);
    } catch (err: unknown) {
      setError(describePortError(err));
    } finally {
      setIsAllocating(false);
      onPendingChange(false);
    }
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    const parsedGamePort = parseOptionalInteger(gamePort);
    const parsedRconPort = parseOptionalInteger(rconPort);
    const parsedQueryPort = parseOptionalInteger(queryPort);
    if (!isValidPort(parsedGamePort) || !isValidPort(parsedRconPort)) {
      setError("Game and RCON ports must be between 1024 and 65535.");
      return;
    }
    if (queryPort.trim() && !isValidPort(parsedQueryPort)) {
      setError("Query port must be between 1024 and 65535.");
      return;
    }

    const pluginPorts: Record<string, number> = {};
    for (const row of pluginRows) {
      const name = row.name.trim();
      if (!name && !row.port.trim()) continue;
      if (!name) {
        setError("Plugin port rows require a name.");
        return;
      }
      const parsedPluginPort = parseOptionalInteger(row.port);
      if (!isValidPort(parsedPluginPort)) {
        setError(`Plugin port '${name}' must be between 1024 and 65535.`);
        return;
      }
      pluginPorts[name] = parsedPluginPort as number;
    }

    const payload: SetPortSetRequest = {
      game_port: parsedGamePort as number,
      rcon_port: parsedRconPort as number,
      query_port: parsedQueryPort,
      plugin_ports: pluginPorts,
    };

    setIsSaving(true);
    onPendingChange(true);
    try {
      const result = await api.setBranchPortSet(serverId, branchName, payload);
      applyPortSet(result.port_set);
      onUpdated(result.port_set);
    } catch (err: unknown) {
      setError(describePortError(err));
    } finally {
      setIsSaving(false);
      onPendingChange(false);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          {error}
        </div>
      )}

      <div className="rounded-lg border border-border-subtle bg-surface-page p-3 text-xs">
        <div className="font-semibold text-text-primary mb-1">Current Port Set</div>
        {portSet ? (
          <div className="flex flex-wrap gap-3 font-mono text-text-secondary">
            <span>Game: {portSet.game_port}</span>
            <span>RCON: {portSet.rcon_port}</span>
            {typeof portSet.query_port === "number" && (
              <span>Query: {portSet.query_port}</span>
            )}
            {Object.entries(portSet.plugin_ports ?? {}).map(([name, port]) => (
              <span key={name}>
                {name}: {port}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-text-muted">No port set assigned</span>
        )}
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-page p-3 space-y-2.5">
        <div className="text-xs font-semibold text-text-primary">Auto-Allocate Port Set</div>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            aria-label="Include Query Port"
            checked={includeQuery}
            onChange={(e) => setIncludeQuery(e.target.checked)}
            disabled={isAllocating || isSaving}
            className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
          />
          <span className="text-xs text-text-secondary">Include Query Port</span>
        </label>
        <div>
          <label htmlFor="plugin-port-names" className={labelClass}>
            Plugin Port Names (comma-separated)
          </label>
          <input
            id="plugin-port-names"
            type="text"
            value={pluginPortNames}
            onChange={(e) => setPluginPortNames(e.target.value)}
            disabled={isAllocating || isSaving}
            placeholder="e.g. dynmap, bluemap"
            className={inputClass}
          />
        </div>
        <button
          type="button"
          onClick={handleAllocate}
          disabled={isAllocating || isSaving}
          className={secondaryButtonClass}
        >
          <Icon name="network" size={13} />
          {isAllocating ? "Allocating..." : "Auto-Allocate Port Set"}
        </button>
      </div>

      <form onSubmit={handleSave} className="rounded-lg border border-border-subtle bg-surface-page p-3 space-y-2.5">
        <div className="text-xs font-semibold text-text-primary">Manual Port Set Editor</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <div>
            <label htmlFor="port-set-game-input" className={labelClass}>
              Game Port
            </label>
            <input
              id="port-set-game-input"
              type="number"
              min={1024}
              max={65535}
              required
              value={gamePort}
              onChange={(e) => setGamePort(e.target.value)}
              disabled={isSaving}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="port-set-rcon-input" className={labelClass}>
              RCON Port
            </label>
            <input
              id="port-set-rcon-input"
              type="number"
              min={1024}
              max={65535}
              required
              value={rconPort}
              onChange={(e) => setRconPort(e.target.value)}
              disabled={isSaving}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="port-set-query-input" className={labelClass}>
              Query Port (optional)
            </label>
            <input
              id="port-set-query-input"
              type="number"
              min={1024}
              max={65535}
              value={queryPort}
              onChange={(e) => setQueryPort(e.target.value)}
              disabled={isSaving}
              className={inputClass}
            />
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-[11px] font-semibold text-text-secondary">Plugin Ports</div>
          {pluginRows.map((row) => (
            <div key={row.id} className="flex items-center gap-2">
              <input
                type="text"
                value={row.name}
                onChange={(e) =>
                  setPluginRows((prev) =>
                    prev.map((item) =>
                      item.id === row.id ? { ...item, name: e.target.value } : item,
                    ),
                  )
                }
                aria-label={`Plugin port name ${row.id}`}
                placeholder="plugin-name"
                disabled={isSaving}
                className="flex-1 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
              />
              <input
                type="number"
                min={1024}
                max={65535}
                value={row.port}
                onChange={(e) =>
                  setPluginRows((prev) =>
                    prev.map((item) =>
                      item.id === row.id ? { ...item, port: e.target.value } : item,
                    ),
                  )
                }
                aria-label={`Plugin port value ${row.id}`}
                placeholder="port"
                disabled={isSaving}
                className="w-28 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() =>
                  setPluginRows((prev) => prev.filter((item) => item.id !== row.id))
                }
                aria-label={`Remove plugin port ${row.id}`}
                disabled={isSaving}
                className="rounded-lg border border-border-default bg-surface-card p-1.5 text-text-muted hover:text-status-danger hover:bg-surface-hover transition-colors cursor-pointer disabled:opacity-50"
              >
                <Icon name="trash" size={12} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => {
              const id = nextRowId.current++;
              setPluginRows((prev) => [...prev, { id, name: "", port: "" }]);
            }}
            disabled={isSaving}
            className={secondaryButtonClass}
          >
            <Icon name="plus" size={12} />
            Add Plugin Port
          </button>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving || isAllocating}
            className={secondaryButtonClass}
          >
            Cancel
          </button>
          <button type="submit" disabled={isSaving || isAllocating} className={primaryButtonClass}>
            <Icon name="check" size={13} />
            {isSaving ? "Saving..." : "Save Port Set"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ==========================================
// 4. Data Templates Modal
// ==========================================
export interface DataTemplatesModalProps {
  isOpen: boolean;
  serverId: string;
  branches: ServerBranch[];
  selectedBranch: string;
  initialMode?: "list" | "save-branch";
  activeRuntimeId?: string | null;
  onClose: () => void;
  onTemplatesChanged: () => void;
}

export function DataTemplatesModal({
  isOpen,
  serverId,
  branches,
  selectedBranch,
  initialMode = "list",
  activeRuntimeId,
  onClose,
  onTemplatesChanged,
}: DataTemplatesModalProps) {
  const [isPending, setIsPending] = useState(false);
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Data Templates"
      description="Quiescent snapshots used to seed future branch runs."
      size="xl"
      showCloseButton
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      {isOpen && (
        <DataTemplatesBody
          serverId={serverId}
          branches={branches}
          selectedBranch={selectedBranch}
          initialMode={initialMode}
          activeRuntimeId={activeRuntimeId}
          onPendingChange={setIsPending}
          onClose={onClose}
          onTemplatesChanged={onTemplatesChanged}
        />
      )}
    </Modal>
  );
}

interface DataTemplatesBodyProps {
  serverId: string;
  branches: ServerBranch[];
  selectedBranch: string;
  initialMode: "list" | "save-branch";
  activeRuntimeId?: string | null;
  onPendingChange: (pending: boolean) => void;
  onClose: () => void;
  onTemplatesChanged: () => void;
}

function DataTemplatesBody({
  serverId,
  branches,
  selectedBranch,
  initialMode,
  activeRuntimeId,
  onPendingChange,
  onClose,
  onTemplatesChanged,
}: DataTemplatesBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const nonMainBranches = branches.filter((b) => b.name !== "main");
  const [activeTab, setActiveTab] = useState<"list" | "create">(
    initialMode === "save-branch" ? "create" : "list",
  );
  const [templates, setTemplates] = useState<DataTemplate[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<DataTemplateSource>(
    initialMode === "save-branch" ? "branch" : "live",
  );
  const [sourceBranch, setSourceBranch] = useState(
    selectedBranch !== "main"
      ? selectedBranch
      : nonMainBranches[0]?.name ?? "",
  );
  const [asyncMode, setAsyncMode] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api.listDataTemplates(serverId);
        if (!cancelled) setTemplates(Array.isArray(data) ? data : []);
      } catch (err: unknown) {
        if (!cancelled) {
          setError(describeError(err, "Failed to load Data Templates."));
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [serverId, api, reloadKey]);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Template name is required.");
      return;
    }
    if (initialMode === "save-branch") {
      if (!selectedBranch || selectedBranch === "main") {
        setError("Select a non-main branch runtime before saving a Data Template.");
        return;
      }
    } else if (source === "branch" && !sourceBranch) {
      setError("Select a source branch for the Data Template.");
      return;
    }

    setIsCreating(true);
    onPendingChange(true);
    try {
      if (initialMode === "save-branch") {
        await api.saveBranchDataTemplate(serverId, selectedBranch, {
          name: name.trim(),
          description: description.trim(),
          runtime_id: activeRuntimeId ?? undefined,
        });
      } else {
        await api.createDataTemplate(serverId, {
          name: name.trim(),
          description: description.trim(),
          source,
          branch_name: source === "branch" ? sourceBranch : null,
          async_mode: asyncMode,
        });
      }
      setName("");
      setDescription("");
      setAsyncMode(false);
      setReloadKey((key) => key + 1);
      setActiveTab("list");
      onTemplatesChanged();
    } catch (err: unknown) {
      setError(describeError(err, "Failed to create the Data Template."));
    } finally {
      setIsCreating(false);
      onPendingChange(false);
    }
  };

  const handleDelete = async (template: DataTemplate) => {
    setError(null);
    setDeletingId(template.id);
    onPendingChange(true);
    try {
      await api.deleteDataTemplate(serverId, template.id);
      setReloadKey((key) => key + 1);
      onTemplatesChanged();
    } catch (err: unknown) {
      setError(describeError(err, "Failed to delete the Data Template."));
    } finally {
      setDeletingId(null);
      onPendingChange(false);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          {error}
        </div>
      )}

      <div role="tablist" aria-label="Data Templates sections" className="flex gap-1 border-b border-border-subtle pb-2">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "list"}
          onClick={() => setActiveTab("list")}
          className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
            activeTab === "list"
              ? "bg-accent-primary text-white"
              : "text-text-secondary hover:bg-surface-hover"
          }`}
        >
          Saved Templates
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "create"}
          onClick={() => setActiveTab("create")}
          className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
            activeTab === "create"
              ? "bg-accent-primary text-white"
              : "text-text-secondary hover:bg-surface-hover"
          }`}
        >
          Create Template
        </button>
      </div>

      {activeTab === "list" ? (
        <div className="space-y-2 max-h-[50vh] overflow-y-auto pr-1">
          {templates.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
              No Data Templates saved yet. Create one from the live server or a
              branch runtime to seed future branch runs.
            </p>
          ) : (
            templates.map((template) => (
              <div
                key={template.id}
                className="rounded-lg border border-border-subtle bg-surface-page p-3 space-y-1.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-text-primary">
                      {template.name}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${templateStatusClasses(template.status)}`}
                    >
                      {template.status}
                    </span>
                  </div>
                  <button
                    type="button"
                    aria-label={`Delete template ${template.name}`}
                    onClick={() => handleDelete(template)}
                    disabled={deletingId === template.id}
                    className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-card px-2 py-1 text-[11px] font-medium text-status-danger hover:bg-status-danger-bg transition-colors cursor-pointer disabled:opacity-50"
                  >
                    <Icon name="trash" size={11} />
                    {deletingId === template.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
                {template.description && (
                  <p className="text-xs text-text-secondary">{template.description}</p>
                )}
                <div className="flex flex-wrap items-center gap-3 text-[11px] text-text-muted">
                  <span>
                    {template.source_branch_name
                      ? `Branch: ${template.source_branch_name}`
                      : "Live Server"}
                  </span>
                  {template.source_commit_sha && (
                    <span className="font-mono">
                      {template.source_commit_sha.slice(0, 8)}
                    </span>
                  )}
                  <span>{template.file_count} files</span>
                  <span>{formatBytes(template.total_bytes)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
        <form onSubmit={handleCreate} className="space-y-3">
          {initialMode === "save-branch" && (
            <div className="rounded-lg border border-status-info-border bg-status-info-bg p-3 text-[11px] text-status-info">
              Saving a quiescent snapshot from branch runtime &lsquo;{selectedBranch}&rsquo;.
            </div>
          )}
          <div>
            <label htmlFor="data-template-name-input" className={labelClass}>
              Template Name
            </label>
            <input
              id="data-template-name-input"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              required
              disabled={isCreating}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="data-template-desc-input" className={labelClass}>
              Description (optional)
            </label>
            <input
              id="data-template-desc-input"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              disabled={isCreating}
              className={inputClass}
            />
          </div>

          {initialMode !== "save-branch" && (
            <>
              <div>
                <label htmlFor="data-template-source-select" className={labelClass}>
                  Source
                </label>
                <select
                  id="data-template-source-select"
                  aria-label="Template Source"
                  value={source}
                  onChange={(e) => setSource(e.target.value === "branch" ? "branch" : "live")}
                  disabled={isCreating}
                  className={inputClass}
                >
                  <option value="live">Live Server</option>
                  <option value="branch">Branch Runtime</option>
                </select>
              </div>
              {source === "branch" && (
                <div>
                  <label htmlFor="data-template-branch-select" className={labelClass}>
                    Source Branch
                  </label>
                  <select
                    id="data-template-branch-select"
                    aria-label="Source Branch"
                    value={sourceBranch}
                    onChange={(e) => setSourceBranch(e.target.value)}
                    disabled={isCreating}
                    className={inputClass}
                  >
                    {nonMainBranches.map((branch) => (
                      <option key={branch.id} value={branch.name}>
                        {branch.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  aria-label="Run clone in background (async)"
                  checked={asyncMode}
                  onChange={(e) => setAsyncMode(e.target.checked)}
                  disabled={isCreating}
                  className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
                />
                <span className="text-xs text-text-secondary">
                  Run clone in background (async)
                </span>
              </label>
            </>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isCreating}
              className={secondaryButtonClass}
            >
              Cancel
            </button>
            <button type="submit" disabled={isCreating} className={primaryButtonClass}>
              <Icon name="database" size={13} />
              {isCreating ? "Saving..." : "Create Template"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

// ==========================================
// 5. Branch Console & Activity Modal
// ==========================================
export interface BranchConsoleActivityModalProps {
  isOpen: boolean;
  serverId: string;
  branchName: string;
  isRuntimeActive: boolean;
  initialTab?: "console" | "activity";
  onClose: () => void;
}

export function BranchConsoleActivityModal({
  isOpen,
  serverId,
  branchName,
  isRuntimeActive,
  initialTab = "console",
  onClose,
}: BranchConsoleActivityModalProps) {
  const [isPending, setIsPending] = useState(false);
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Branch Console & Activity"
      description={`Branch '${branchName}'`}
      size="xl"
      showCloseButton
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      {isOpen && (
        <BranchConsoleActivityBody
          serverId={serverId}
          branchName={branchName}
          isRuntimeActive={isRuntimeActive}
          initialTab={initialTab}
          onPendingChange={setIsPending}
          onClose={onClose}
        />
      )}
    </Modal>
  );
}

interface BranchConsoleActivityBodyProps {
  serverId: string;
  branchName: string;
  isRuntimeActive: boolean;
  initialTab: "console" | "activity";
  onPendingChange: (pending: boolean) => void;
  onClose: () => void;
}

interface CommandOutput {
  command: string;
  output: string;
}

function BranchConsoleActivityBody({
  serverId,
  branchName,
  isRuntimeActive,
  initialTab,
  onPendingChange,
  onClose,
}: BranchConsoleActivityBodyProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [activeTab, setActiveTab] = useState<"console" | "activity">(initialTab);
  const [tail, setTail] = useState(200);
  const [consoleLines, setConsoleLines] = useState<string[]>([]);
  const [isConsoleLoading, setIsConsoleLoading] = useState(true);
  const [consoleUnavailable, setConsoleUnavailable] = useState(false);
  const [consoleReloadKey, setConsoleReloadKey] = useState(0);
  const [command, setCommand] = useState("");
  const [commandOutputs, setCommandOutputs] = useState<CommandOutput[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [activityLogs, setActivityLogs] = useState<ServerActivityLog[]>([]);
  const [isActivityLoading, setIsActivityLoading] = useState(true);
  const [activityReloadKey, setActivityReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== "console" || !isRuntimeActive) return;
    let cancelled = false;
    const load = async () => {
      try {
        const result: BranchConsoleLogsResponse = await api.getBranchConsole(
          serverId,
          branchName,
          tail,
        );
        if (!cancelled) {
          setConsoleLines(Array.isArray(result.lines) ? result.lines : []);
          setConsoleUnavailable(false);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const info = extractErrorInfo(err, "Failed to load branch console logs.");
          if (info.status === 404) {
            setConsoleUnavailable(true);
          } else {
            setError(describeError(err, "Failed to load branch console logs."));
          }
        }
      } finally {
        if (!cancelled) setIsConsoleLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [activeTab, isRuntimeActive, serverId, branchName, tail, api, consoleReloadKey]);

  useEffect(() => {
    if (activeTab !== "activity") return;
    let cancelled = false;
    const load = async () => {
      try {
        const result = await api.getServerActivity(serverId, {
          branch: branchName,
          limit: 50,
        });
        if (!cancelled) {
          setActivityLogs(Array.isArray(result.items) ? result.items : []);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(describeError(err, "Failed to load branch activity."));
        }
      } finally {
        if (!cancelled) setIsActivityLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [activeTab, serverId, branchName, api, activityReloadKey]);

  const handleSendCommand = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = command.trim();
    if (!trimmed || trimmed.includes("\n") || trimmed.includes("\r")) {
      setError("Enter a single-line RCON command.");
      return;
    }
    if (!isRuntimeActive || consoleUnavailable) return;
    setError(null);
    setIsSending(true);
    onPendingChange(true);
    try {
      const result = await api.sendBranchConsoleCommand(serverId, branchName, {
        command: trimmed,
      });
      setCommandOutputs((prev) => [
        ...prev,
        { command: result.command || trimmed, output: result.output },
      ]);
      setCommand("");
    } catch (err: unknown) {
      setError(describeError(err, "Failed to send the RCON command."));
    } finally {
      setIsSending(false);
      onPendingChange(false);
    }
  };

  const commandInputDisabled = !isRuntimeActive || consoleUnavailable || isSending;
  const inactiveMessage = `No active runtime for branch '${branchName}'. Start the branch to inspect container logs and dispatch RCON commands.`;

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Branch console and activity tabs" className="flex gap-1 border-b border-border-subtle pb-2">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "console"}
          onClick={() => setActiveTab("console")}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
            activeTab === "console"
              ? "bg-accent-primary text-white"
              : "text-text-secondary hover:bg-surface-hover"
          }`}
        >
          <Icon name="terminal" size={12} />
          Console
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "activity"}
          onClick={() => setActiveTab("activity")}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
            activeTab === "activity"
              ? "bg-accent-primary text-white"
              : "text-text-secondary hover:bg-surface-hover"
          }`}
        >
          <Icon name="clock" size={12} />
          Branch Activity
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          {error}
        </div>
      )}

      {activeTab === "console" ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              Tail
              <select
                aria-label="Console tail lines"
                value={tail}
                onChange={(e) => setTail(Number(e.target.value))}
                className="rounded-lg border border-border-default bg-surface-page px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
              >
                <option value={100}>100</option>
                <option value={200}>200</option>
                <option value={500}>500</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => {
                setIsConsoleLoading(true);
                setConsoleReloadKey((key) => key + 1);
              }}
              disabled={!isRuntimeActive || consoleUnavailable}
              className={secondaryButtonClass}
            >
              <Icon name="restart" size={12} />
              Refresh Logs
            </button>
          </div>

          {!isRuntimeActive || consoleUnavailable ? (
            <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
              {inactiveMessage}
            </div>
          ) : (
            <>
              <pre
                data-testid="branch-console-output"
                className="max-h-[35vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-border-subtle bg-surface-page p-3 text-xs font-mono text-text-primary"
              >
                {isConsoleLoading
                  ? "Loading branch console logs..."
                  : consoleLines.length > 0
                    ? consoleLines.join("\n")
                    : "No log lines yet."}
              </pre>

              {commandOutputs.length > 0 && (
                <pre
                  data-testid="branch-command-output"
                  className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border-subtle bg-surface-elevated p-3 text-xs font-mono text-status-success"
                >
                  {commandOutputs
                    .map((entry) => `> ${entry.command}\n${entry.output}`)
                    .join("\n\n")}
                </pre>
              )}
            </>
          )}

          <form onSubmit={handleSendCommand} className="flex items-center gap-2">
            <input
              type="text"
              aria-label="Branch RCON command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              disabled={commandInputDisabled}
              placeholder="Enter RCON command (e.g. list, seed, time set day)..."
              className="flex-1 rounded-lg border border-border-default bg-surface-page px-3 py-2 text-xs font-mono text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-primary disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={commandInputDisabled || !command.trim()}
              className={primaryButtonClass}
            >
              {isSending ? "Sending..." : "Send Command"}
            </button>
          </form>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => {
                setIsActivityLoading(true);
                setActivityReloadKey((key) => key + 1);
              }}
              className={secondaryButtonClass}
            >
              <Icon name="restart" size={12} />
              Refresh
            </button>
          </div>

          {isActivityLoading ? (
            <div className="rounded-lg border border-border-subtle bg-surface-page p-4 text-xs text-text-muted">
              Loading branch activity...
            </div>
          ) : activityLogs.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
              No activity recorded for branch &lsquo;{branchName}&rsquo; yet.
            </div>
          ) : (
            <div className="max-h-[50vh] space-y-2 overflow-y-auto pr-1">
              {activityLogs.map((log) => (
                <div
                  key={log.id}
                  className="rounded-lg border border-border-subtle bg-surface-page p-3 space-y-1.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1 rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-semibold text-text-secondary">
                      <Icon name="activity" size={11} />
                      {log.event_type}
                    </span>
                    <span className="text-[11px] text-text-muted">
                      {log.actor_id || log.actor_type}
                    </span>
                    <span className="ml-auto font-mono text-[11px] text-text-muted">
                      {formatTimestamp(log.timestamp)}
                    </span>
                  </div>
                  <div className="text-sm font-semibold text-text-primary">{log.summary}</div>
                  {log.details && Object.keys(log.details).length > 0 && (
                    <details className="text-[11px] text-text-secondary">
                      <summary className="cursor-pointer font-medium text-accent-primary">
                        Details
                      </summary>
                      <pre className="mt-1 overflow-x-auto rounded bg-surface-elevated p-2 font-mono text-[11px]">
                        {JSON.stringify(log.details, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex justify-end border-t border-border-subtle pt-3">
        <button type="button" onClick={onClose} className={secondaryButtonClass}>
          Close
        </button>
      </div>
    </div>
  );
}
