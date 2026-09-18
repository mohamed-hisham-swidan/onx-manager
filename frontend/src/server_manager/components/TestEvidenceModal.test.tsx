import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestEvidenceModal } from "./TestEvidenceModal";
import type { ServerTestRun, EvidenceBundle } from "@/server_manager/types";

const mockGetTestEvidence = vi.fn();
vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getTestEvidence: mockGetTestEvidence,
  }),
}));

const mockCopy = vi.fn();
vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({
    copy: mockCopy,
  }),
}));

const mockTestRun: ServerTestRun = {
  id: "test-run-12345678",
  server_id: "srv-1",
  commit_id: "abcdef1234567890",
  node_id: "node-1",
  status: "FAILED",
  ephemeral_port: null,
  log_output: null,
  failure_reason: "Server crashed during mod initialization",
  created_at: "2026-09-18T12:00:00Z",
  expires_at: null,
  bot_count: 0,
  duration_minutes: 5,
  placement_mode: "local",
  bot_tech: "mock",
  test_definition_id: "def-1",
  evidence_bundle: null,
  artifacts_purged: false,
};

const sampleEvidence: EvidenceBundle = {
  test_id: "test-run-12345678",
  server_id: "srv-1",
  commit_id: "abcdef1234567890",
  runtime: {
    exit_code: 1,
    container_id: "cnt-99",
    ip_address: "172.18.0.2",
    port: 25565,
  },
  assertions: {
    boot_passed: false,
  },
  crash_analysis: {
    stack_trace: "net.minecraftforge.fml.ModLoadingException: Mod ironchest failed\n  at net.minecraftforge...",
    root_cause: "ModLoadingException: Mod ironchest failed",
    failure_reason: "Failed mod loading stage",
    suspected_culprit_mods: ["ironchest.jar", "jei.jar"],
  },
  log_tail: [],
};

describe("TestEvidenceModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <TestEvidenceModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        testRun={mockTestRun}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("fetches and renders structured evidence bundle when open", async () => {
    mockGetTestEvidence.mockResolvedValueOnce(sampleEvidence);

    render(
      <TestEvidenceModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        testRun={mockTestRun}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Test Diagnostic Evidence")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockGetTestEvidence).toHaveBeenCalledWith("srv-1", "test-run-12345678");
    });

    // Check summary badges
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("NO")).toBeInTheDocument();
    expect(screen.getByText("Retained on Disk")).toBeInTheDocument();

    // Check culprit mods
    expect(screen.getByText("Suspected Culprit Mods")).toBeInTheDocument();
    expect(screen.getByText("ironchest.jar")).toBeInTheDocument();
    expect(screen.getByText("jei.jar")).toBeInTheDocument();

    // Check stack trace snippet
    expect(screen.getByText(/net.minecraftforge.fml.ModLoadingException/)).toBeInTheDocument();
  });

  it("copies raw JSON evidence bundle to clipboard when Copy JSON is clicked", async () => {
    const user = userEvent.setup();
    mockGetTestEvidence.mockResolvedValueOnce(sampleEvidence);

    render(
      <TestEvidenceModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        testRun={mockTestRun}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Suspected Culprit Mods")).toBeInTheDocument();
    });

    const copyBtn = screen.getByRole("button", { name: /Copy Diagnostic JSON/i });
    await user.click(copyBtn);

    expect(mockCopy).toHaveBeenCalledWith(
      JSON.stringify(sampleEvidence, null, 2),
      "Evidence bundle copied to clipboard"
    );
  });

  it("displays error message if fetching evidence fails", async () => {
    mockGetTestEvidence.mockRejectedValueOnce(new Error("Network timeout loading evidence"));

    render(
      <TestEvidenceModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        testRun={mockTestRun}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Network timeout loading evidence")).toBeInTheDocument();
    });
  });
});
