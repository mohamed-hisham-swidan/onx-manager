import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ProvisioningProgress } from "./ProvisioningProgress";
import { useProvisionProgressStore } from "@/stores/provisionProgressStore";
import type { ProvisioningSnapshot } from "@/server_manager/types";

const navigateMock = vi.fn();
const startServerMock = vi.fn().mockResolvedValue({ status: "starting" });
const retryProvisioningMock = vi.fn().mockResolvedValue({ status: "provisioning" });

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    startServer: startServerMock,
    retryProvisioning: retryProvisioningMock,
  }),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  subscribeChannels: vi.fn(),
  unsubscribeChannels: vi.fn(),
}));

function makeRunningSnapshot(overrides: Partial<ProvisioningSnapshot> = {}): ProvisioningSnapshot {
  return {
    server_id: "srv-1",
    server_name: "Purpur Realm",
    server_type: "purpur",
    minecraft_version: "1.21.11",
    mode: "simple",
    status: "running",
    started_at: new Date(Date.now()).toISOString(),
    finished_at: null,
    elapsed_ms: 0,
    current_step_id: "download_core",
    percent: 40,
    message: "Downloading purpur-1.21.11-2568.jar...",
    error: null,
    failed_step_id: null,
    steps: [
      {
        id: "prepare_workspace",
        label: "Prepare Workspace",
        status: "completed",
        detail: "server.properties & eula.txt",
        elapsed_ms: 120,
      },
      {
        id: "download_core",
        label: "Download Server Core",
        status: "running",
        detail: "purpur-1.21.11-2568.jar · 64%",
        elapsed_ms: 0,
      },
      { id: "verify_and_install", label: "Verify & Install", status: "pending", elapsed_ms: 0 },
      { id: "prepare_runtime", label: "Prepare Runtime", status: "pending", elapsed_ms: 0 },
      { id: "finalize", label: "Finalize", status: "pending", elapsed_ms: 0 },
    ],
    active_transfer: {
      filename: "purpur-1.21.11-2568.jar",
      bytes_downloaded: Math.round(28.4 * 1024 * 1024),
      total_bytes: Math.round(44.2 * 1024 * 1024),
      percent: 64,
      speed_bps: 4.8 * 1024 * 1024,
      eta_seconds: 3,
      file_index: 1,
      file_total: 2,
      phase: "downloading",
    },
    activity: [
      {
        timestamp: "2026-11-26T12:00:00Z",
        message: "Created workspace and server.properties",
        level: "info",
      },
      {
        timestamp: "2026-11-26T12:00:01Z",
        message: "Downloading purpur-1.21.11-2568.jar (44.2 MB)",
        level: "info",
      },
    ],
    artifacts: [],
    ...overrides,
  };
}

describe("ProvisioningProgress", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProvisionProgressStore.getState().clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ticks live elapsed timer while active and freezes immediately on completion", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-26T12:00:00Z"));

    const runningSnap = makeRunningSnapshot({
      started_at: new Date("2026-11-26T12:00:00Z").toISOString(),
    });
    useProvisionProgressStore.getState().setSnapshot("srv-1", runningSnap);

    render(
      <MemoryRouter>
        <ProvisioningProgress serverId="srv-1" />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("provisioning-elapsed-timer")).toHaveTextContent("00:00");

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByTestId("provisioning-elapsed-timer")).toHaveTextContent("00:05");

    act(() => {
      useProvisionProgressStore.getState().setSnapshot("srv-1", {
        ...runningSnap,
        status: "completed",
        percent: 100,
        elapsed_ms: 5000,
        active_transfer: null,
        steps: runningSnap.steps.map((s) => ({ ...s, status: "completed", elapsed_ms: 1000 })),
        artifacts: [
          {
            id: "core_jar",
            label: "Server JAR",
            value: "purpur-1.21.11-2568.jar · 44.2 MB · Verified",
            status: "verified",
          },
          {
            id: "runtime",
            label: "Runtime & Mode",
            value: "Java 21 · Simple Mode",
            status: "ready",
          },
          {
            id: "config",
            label: "Configuration",
            value: "server.properties, eula.txt · Port 25565",
            status: "completed",
          },
        ],
      });
    });

    expect(screen.getByTestId("provisioning-elapsed-timer")).toHaveTextContent("Completed in 5s");

    // Advance more time: frozen timer must NOT change
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.getByTestId("provisioning-elapsed-timer")).toHaveTextContent("Completed in 5s");
  });

  it("renders active download progress bar with filename, file counter, MB/MB, speed, ETA, 5-step timeline and activity", () => {
    useProvisionProgressStore.getState().setSnapshot("srv-1", makeRunningSnapshot());

    render(
      <MemoryRouter>
        <ProvisioningProgress serverId="srv-1" />
      </MemoryRouter>,
    );

    const bar = screen.getByRole("progressbar", { name: "Download progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "64");

    const banner = screen.getByTestId("provisioning-transfer-banner");
    expect(banner).toHaveTextContent("purpur-1.21.11-2568.jar");
    expect(banner).toHaveTextContent("File 1 of 2");
    expect(banner).toHaveTextContent("64%");
    expect(banner).toHaveTextContent("28.4 MB / 44.2 MB");
    expect(banner).toHaveTextContent("4.8 MB/s");
    expect(banner).toHaveTextContent("~3s left");

    // 5-step timeline
    const timeline = screen.getByTestId("provisioning-step-timeline");
    expect(timeline).toHaveTextContent("Prepare Workspace");
    expect(timeline).toHaveTextContent("Download Server Core");
    expect(timeline).toHaveTextContent("Verify & Install");
    expect(timeline).toHaveTextContent("Prepare Runtime");
    expect(timeline).toHaveTextContent("Finalize");
    expect(screen.getByTestId("provisioning-step-prepare_workspace")).toHaveAttribute(
      "data-status",
      "completed",
    );
    expect(screen.getByTestId("provisioning-step-download_core")).toHaveAttribute(
      "data-status",
      "running",
    );

    // Activity feed
    const activity = screen.getByTestId("provisioning-activity-feed");
    expect(activity).toHaveTextContent("Created workspace and server.properties");
    expect(activity).toHaveTextContent("Downloading purpur-1.21.11-2568.jar (44.2 MB)");
  });

  it("renders installer pulse banner during Forge/NeoForge library installation", () => {
    useProvisionProgressStore.getState().setSnapshot(
      "srv-1",
      makeRunningSnapshot({
        server_type: "neoforge",
        current_step_id: "verify_and_install",
        active_transfer: {
          filename: "neoforge-installer.jar",
          bytes_downloaded: 0,
          total_bytes: null,
          percent: 55,
          speed_bps: null,
          eta_seconds: null,
          file_index: 1,
          file_total: 1,
          phase: "installing",
        },
      }),
    );

    render(
      <MemoryRouter>
        <ProvisioningProgress serverId="srv-1" />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("provisioning-transfer-banner")).toHaveTextContent(
      "Installing loader libraries...",
    );
    expect(screen.getByRole("progressbar", { name: "Installer progress" })).toHaveAttribute(
      "aria-valuenow",
      "55",
    );
  });

  it("renders What Was Created & Installed completion summary card and actions", async () => {
    const user = userEvent.setup();
    useProvisionProgressStore.getState().setSnapshot(
      "srv-1",
      makeRunningSnapshot({
        status: "completed",
        percent: 100,
        elapsed_ms: 24000,
        active_transfer: null,
        steps: [
          { id: "prepare_workspace", label: "Prepare Workspace", status: "completed", elapsed_ms: 1000 },
          { id: "download_core", label: "Download Server Core", status: "completed", elapsed_ms: 12000 },
          { id: "verify_and_install", label: "Verify & Install", status: "completed", elapsed_ms: 3000 },
          { id: "prepare_runtime", label: "Prepare Runtime", status: "completed", elapsed_ms: 5000 },
          { id: "finalize", label: "Finalize", status: "completed", elapsed_ms: 3000 },
        ],
        artifacts: [
          {
            id: "core_jar",
            label: "Server JAR",
            value: "purpur-1.21.11-2568.jar · 44.2 MB · Verified",
            status: "verified",
          },
          {
            id: "runtime",
            label: "Runtime & Mode",
            value: "Java 21 · Simple Mode",
            status: "ready",
          },
          {
            id: "config",
            label: "Configuration",
            value: "server.properties, eula.txt · Port 25565",
            status: "completed",
          },
        ],
      }),
    );

    render(
      <MemoryRouter>
        <ProvisioningProgress serverId="srv-1" />
      </MemoryRouter>,
    );

    const summary = screen.getByTestId("provisioning-completion-summary");
    expect(summary).toHaveTextContent("What Was Created & Installed");
    expect(summary).toHaveTextContent("purpur-1.21.11-2568.jar · 44.2 MB · Verified");
    expect(summary).toHaveTextContent("Java 21 · Simple Mode");
    expect(summary).toHaveTextContent("server.properties, eula.txt · Port 25565");
    expect(screen.getByTestId("provisioning-elapsed-timer")).toHaveTextContent("Completed in 24s");

    await user.click(screen.getByRole("button", { name: /Open Server Console/i }));
    expect(navigateMock).toHaveBeenCalledWith("/servers/srv-1/console");

    await user.click(screen.getByRole("button", { name: /Start Server Now/i }));
    expect(startServerMock).toHaveBeenCalledWith("srv-1");
  });

  it("highlights failed step, freezes elapsed timer, and invokes Retry Provisioning on failure", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    useProvisionProgressStore.getState().setSnapshot(
      "srv-1",
      makeRunningSnapshot({
        status: "failed",
        elapsed_ms: 12000,
        failed_step_id: "verify_and_install",
        error: "Installer exited with code 1",
        active_transfer: null,
        steps: [
          { id: "prepare_workspace", label: "Prepare Workspace", status: "completed", elapsed_ms: 500 },
          { id: "download_core", label: "Download Server Core", status: "completed", elapsed_ms: 4500 },
          {
            id: "verify_and_install",
            label: "Verify & Install",
            status: "failed",
            detail: "Installer exited with code 1",
            elapsed_ms: 7000,
          },
          { id: "prepare_runtime", label: "Prepare Runtime", status: "pending", elapsed_ms: 0 },
          { id: "finalize", label: "Finalize", status: "pending", elapsed_ms: 0 },
        ],
      }),
    );

    render(
      <MemoryRouter>
        <ProvisioningProgress serverId="srv-1" onRetryProvisioning={onRetry} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("provisioning-elapsed-timer")).toHaveTextContent("Failed after 12s");
    expect(screen.getByTestId("provisioning-step-verify_and_install")).toHaveAttribute(
      "data-status",
      "failed",
    );
    expect(screen.getByTestId("provisioning-failure-summary")).toHaveTextContent(
      "Installer exited with code 1",
    );

    await user.click(screen.getByTestId("provisioning-retry-btn"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
