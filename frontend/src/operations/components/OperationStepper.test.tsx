import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationStepper } from "./OperationStepper";
import type { OperationStep } from "../types";

describe("OperationStepper — artifacts, 5-check health gate & terminal freeze", () => {
  it("renders per-artifact download progress and 5-check Health Gate checklist", () => {
    const steps: OperationStep[] = [
      {
        id: "s1",
        step_id: "PREPARE_AND_DOWNLOAD",
        sequence: 1,
        status: "IN_PROGRESS",
        progress: 0.65,
        elapsed_ms: 4200,
        message_key: "Preparing backup & downloading target artifacts",
        safe_to_retry: false,
        context: {
          artifacts: [
            { name: "LetMeDespawn.jar", kind: "addon", status: "cached", progress_pct: 100 },
            {
              name: "Purpur 1.21.11",
              kind: "server_core",
              status: "downloading",
              progress_pct: 50,
              bytes_done: 26214400,
              bytes_total: 52428800,
            },
          ],
        },
        started_at: "2026-11-25T10:00:00Z",
        completed_at: null,
      },
      {
        id: "s2",
        step_id: "HEALTH_GATE",
        sequence: 2,
        status: "IN_PROGRESS",
        progress: 0.8,
        elapsed_ms: 22100,
        message_key: "Booting server & running 5-check Health Gate",
        safe_to_retry: false,
        context: {
          checks: [
            { id: "startup_log", label: "Container Boot & Ready Signal", status: "passed", detail: "Done in 22.1s" },
            { id: "local_slp", label: "Local Server Ping (SLP)", status: "passed", detail: "Purpur 1.21.11 · 4ms" },
            { id: "rcon_flush", label: "RCON World Flush", status: "skipped", detail: "RCON disabled in server.properties" },
            { id: "world_nbt", label: "World Save Integrity (NBT)", status: "passed", detail: "DataVersion 4671" },
            { id: "network_reachability", label: "Public Network / Tunnel Probe", status: "warned", detail: "Public address unreachable after 3 attempts" },
          ],
        },
        started_at: "2026-11-25T10:00:10Z",
        completed_at: null,
      },
    ];

    render(
      <OperationStepper
        steps={steps}
        currentStepId="HEALTH_GATE"
        operationStatus="RUNNING"
      />,
    );

    expect(screen.getByTestId("step-artifact-list")).toBeInTheDocument();
    expect(screen.getByTestId("artifact-row-LetMeDespawn.jar")).toHaveTextContent("✓ Cached");
    expect(screen.getByTestId("artifact-row-Purpur 1.21.11")).toHaveTextContent("50%");

    expect(screen.getByTestId("health-gate-checklist")).toBeInTheDocument();
    expect(screen.getByTestId("health-gate-check-startup_log")).toHaveAttribute("data-status", "passed");
    expect(screen.getByTestId("health-gate-check-local_slp")).toHaveTextContent("Purpur 1.21.11 · 4ms");
    expect(screen.getByTestId("health-gate-check-rcon_flush")).toHaveAttribute("data-status", "skipped");
    expect(screen.getByTestId("health-gate-check-world_nbt")).toHaveTextContent("DataVersion 4671");
    expect(screen.getByTestId("health-gate-check-network_reachability")).toHaveAttribute("data-status", "warned");
  });

  it("freezes timers and removes active spinners immediately when parent operation is terminal", () => {
    const staleStart = "2026-11-25T09:00:00Z";
    const steps: OperationStep[] = [
      {
        id: "s-hg",
        step_id: "HEALTH_GATE",
        sequence: 4,
        status: "IN_PROGRESS", // stranded step on a FAILED operation
        progress: 0.4,
        elapsed_ms: 15000,
        message_key: null,
        safe_to_retry: false,
        context: {
          checks: [
            { id: "startup_log", label: "Container Boot & Ready Signal", status: "running", detail: "Waiting..." },
          ],
        },
        started_at: staleStart,
        completed_at: null,
      },
    ];

    render(
      <OperationStepper
        steps={steps}
        currentStepId="HEALTH_GATE"
        nowMs={Date.parse("2026-11-25T10:00:00Z")}
        operationStatus="FAILED"
      />,
    );

    // Must never show an active spinner or live-ticking 3600.0s timer
    expect(screen.queryByTestId("step-icon-in-progress")).not.toBeInTheDocument();
    expect(screen.getByTestId("step-icon-failed")).toBeInTheDocument();
    expect(screen.getByText("15.0s")).toBeInTheDocument();
    expect(screen.queryByText("3600.0s")).not.toBeInTheDocument();
    expect(screen.getByTestId("health-gate-check-startup_log")).toHaveAttribute("data-status", "failed");
  });
});
