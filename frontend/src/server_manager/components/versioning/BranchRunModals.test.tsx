import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  BranchConsoleActivityModal,
  BranchPortSetModal,
  DataTemplatesModal,
  StartBranchRunModal,
  StopBranchRunModal,
} from "./BranchRunModals";
import { ApiError } from "@/services/api";
import type { DataTemplate, PortSet, ServerBranch } from "@/server_manager/types";

const mockApi = {
  startBranchRun: vi.fn(),
  stopBranchRun: vi.fn(),
  allocateBranchPortSet: vi.fn(),
  setBranchPortSet: vi.fn(),
  listDataTemplates: vi.fn(),
  createDataTemplate: vi.fn(),
  deleteDataTemplate: vi.fn(),
  saveBranchDataTemplate: vi.fn(),
  getBranchConsole: vi.fn(),
  sendBranchConsoleCommand: vi.fn(),
  getServerActivity: vi.fn(),
};

vi.mock("@/services/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code: string;
    constructor(status: number, code: string, message: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  createAuthenticatedApi: () => mockApi,
}));

const readyTemplate: DataTemplate = {
  id: "tpl-1",
  server_id: "s1",
  name: "seed-1",
  description: "Known good world",
  source_branch_name: "feat-trial",
  source_commit_sha: "abcdef1234567890",
  file_count: 42,
  total_bytes: 2048,
  status: "ready",
  operation_id: null,
  created_at: "2026-09-14T10:00:00Z",
  updated_at: "2026-09-14T10:00:00Z",
};

const mockBranches: ServerBranch[] = [
  {
    id: "b-main",
    server_id: "s1",
    name: "main",
    head_commit_id: "c1",
    created_at: "2026-09-14T10:00:00Z",
  },
  {
    id: "b-trial",
    server_id: "s1",
    name: "feat-trial",
    head_commit_id: "c2",
    created_at: "2026-09-14T11:00:00Z",
  },
];

const mockPortSet: PortSet = {
  game_port: 25610,
  rcon_port: 25611,
  query_port: 25612,
  plugin_ports: { dynmap: 25613 },
};

describe("BranchRunModals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.startBranchRun.mockResolvedValue({
      runtime_id: "rt-1",
      server_id: "s1",
      branch_name: "feat-trial",
      commit_sha: "abcdef1234567890",
      container_name: "onx-feat-trial",
      container_id: "container-1",
      port_set: mockPortSet,
      data_template_id: "tpl-1",
      allow_public_test_join: true,
      uncommitted_changes_warning: false,
      memory_max_mb: 2048,
      cpu_cores: 2,
    });
    mockApi.stopBranchRun.mockResolvedValue({
      runtime_id: "rt-1",
      server_id: "s1",
      branch_name: "feat-trial",
      status: "stopped",
      exit_code: 0,
      oom_killed: false,
      saved_template_id: null,
      saved_template_name: null,
    });
    mockApi.allocateBranchPortSet.mockResolvedValue({
      server_id: "s1",
      branch_name: "feat-trial",
      port_set: mockPortSet,
    });
    mockApi.setBranchPortSet.mockResolvedValue({
      server_id: "s1",
      branch_name: "feat-trial",
      port_set: mockPortSet,
    });
    mockApi.listDataTemplates.mockResolvedValue([readyTemplate]);
    mockApi.createDataTemplate.mockResolvedValue(readyTemplate);
    mockApi.deleteDataTemplate.mockResolvedValue({
      status: "deleted",
      server_id: "s1",
      template_id: "tpl-1",
    });
    mockApi.saveBranchDataTemplate.mockResolvedValue(readyTemplate);
    mockApi.getBranchConsole.mockResolvedValue({
      server_id: "s1",
      branch_name: "feat-trial",
      runtime_id: "rt-1",
      container_name: "onx-feat-trial",
      lines: ["[INFO] Server started", "[INFO] Done"],
    });
    mockApi.sendBranchConsoleCommand.mockResolvedValue({
      server_id: "s1",
      branch_name: "feat-trial",
      runtime_id: "rt-1",
      command: "list",
      output: "There are 2 of 20 players online.",
    });
    mockApi.getServerActivity.mockResolvedValue({
      items: [
        {
          id: "act-1",
          server_id: "s1",
          timestamp: 1789390000,
          event_type: "versioning.branch_run_started",
          actor_type: "user",
          actor_id: "admin",
          summary: "Branch run started",
          details: { branch: "feat-trial" },
          branch_name: "feat-trial",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
  });

  describe("StartBranchRunModal", () => {
    it("renders defaults with public join unchecked and submits the selected template", async () => {
      const onStarted = vi.fn();
      const onClose = vi.fn();
      render(
        <StartBranchRunModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          dataTemplates={[readyTemplate]}
          portSet={null}
          onStarted={onStarted}
          onClose={onClose}
        />,
      );

      expect(screen.getByRole("dialog", { name: "Start Branch Run" })).toBeInTheDocument();
      expect(screen.getByLabelText("Data Template")).toHaveValue("");
      expect(screen.getByText("Fresh world from seed")).toBeInTheDocument();
      expect(screen.getByLabelText("Allow Public Test Join")).not.toBeChecked();

      fireEvent.change(screen.getByLabelText("Data Template"), { target: { value: "tpl-1" } });
      fireEvent.click(screen.getByLabelText("Allow Public Test Join"));
      fireEvent.click(screen.getByRole("button", { name: "Start Branch Run" }));

      await waitFor(() => {
        expect(mockApi.startBranchRun).toHaveBeenCalledWith(
          "s1",
          "feat-trial",
          expect.objectContaining({
            data_template_id: "tpl-1",
            allow_public_test_join: true,
          }),
        );
      });
      expect(onStarted).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });

    it("surfaces a 409 BRANCH_CONCURRENCY_LIMIT without closing", async () => {
      mockApi.startBranchRun.mockRejectedValueOnce(
        new ApiError(409, "BRANCH_CONCURRENCY_LIMIT", "Branch concurrency limit reached"),
      );
      const onStarted = vi.fn();
      const onClose = vi.fn();
      render(
        <StartBranchRunModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          dataTemplates={[]}
          portSet={null}
          onStarted={onStarted}
          onClose={onClose}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Start Branch Run" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("BRANCH_CONCURRENCY_LIMIT");
      expect(onStarted).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByRole("dialog", { name: "Start Branch Run" })).toBeInTheDocument();
    });

    it("closes on Escape when not pending", () => {
      const onClose = vi.fn();
      render(
        <StartBranchRunModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          dataTemplates={[]}
          portSet={null}
          onStarted={vi.fn()}
          onClose={onClose}
        />,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe("StopBranchRunModal", () => {
    it("submits keep_port_assignment and a saved template name", async () => {
      const onStopped = vi.fn();
      const onClose = vi.fn();
      render(
        <StopBranchRunModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          runtimeId="rt-1"
          onStopped={onStopped}
          onClose={onClose}
        />,
      );

      fireEvent.click(screen.getByLabelText("Keep Port Assignment"));
      fireEvent.click(screen.getByLabelText("Save Data Template before stop"));
      fireEvent.change(screen.getByLabelText("Template Name"), { target: { value: "after-test" } });
      fireEvent.change(screen.getByLabelText("Template Description (optional)"), {
        target: { value: "post verification" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Stop Branch Run" }));

      await waitFor(() => {
        expect(mockApi.stopBranchRun).toHaveBeenCalledWith("s1", "feat-trial", {
          runtime_id: "rt-1",
          keep_port_assignment: true,
          save_template_name: "after-test",
          save_template_description: "post verification",
        });
      });
      expect(onStopped).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });

    it("disables submit while saving a template with an empty name", () => {
      render(
        <StopBranchRunModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          onStopped={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      fireEvent.click(screen.getByLabelText("Save Data Template before stop"));
      expect(screen.getByRole("button", { name: "Stop Branch Run" })).toBeDisabled();
    });

    it("surfaces a 409 HOT_CLONE_REFUSED inline", async () => {
      mockApi.stopBranchRun.mockRejectedValueOnce(
        new ApiError(409, "HOT_CLONE_REFUSED", "Runtime is not quiescent"),
      );
      const onClose = vi.fn();
      render(
        <StopBranchRunModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          onStopped={vi.fn()}
          onClose={onClose}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Stop Branch Run" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("HOT_CLONE_REFUSED");
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("BranchPortSetModal", () => {
    it("auto-allocates and populates the manual port fields", async () => {
      const onUpdated = vi.fn();
      render(
        <BranchPortSetModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          portSet={null}
          onUpdated={onUpdated}
          onClose={vi.fn()}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Auto-Allocate Port Set" }));

      await waitFor(() => {
        expect(mockApi.allocateBranchPortSet).toHaveBeenCalledWith("s1", "feat-trial", {
          include_query: false,
          plugin_port_names: [],
        });
      });
      expect(screen.getByLabelText("Game Port")).toHaveValue(25610);
      expect(screen.getByLabelText("RCON Port")).toHaveValue(25611);
      expect(screen.getByLabelText("Query Port (optional)")).toHaveValue(25612);
      expect(onUpdated).toHaveBeenCalledWith(mockPortSet);
    });

    it("saves a manual port set without forbidden container fields", async () => {
      render(
        <BranchPortSetModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          portSet={null}
          onUpdated={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      fireEvent.change(screen.getByLabelText("Game Port"), { target: { value: "25610" } });
      fireEvent.change(screen.getByLabelText("RCON Port"), { target: { value: "25611" } });
      fireEvent.click(screen.getByRole("button", { name: "Save Port Set" }));

      await waitFor(() => {
        expect(mockApi.setBranchPortSet).toHaveBeenCalledWith("s1", "feat-trial", {
          game_port: 25610,
          rcon_port: 25611,
          query_port: null,
          plugin_ports: {},
        });
      });
      const payload = mockApi.setBranchPortSet.mock.calls[0][2] as Record<string, unknown>;
      expect(payload).not.toHaveProperty("container_game_port");
      expect(payload).not.toHaveProperty("container_rcon_port");
    });

    it("highlights a 409 DUPLICATE_PORT_SET conflict", async () => {
      mockApi.setBranchPortSet.mockRejectedValueOnce(
        new ApiError(409, "DUPLICATE_PORT_SET", "Port 25610 already allocated"),
      );
      render(
        <BranchPortSetModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          portSet={null}
          onUpdated={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      fireEvent.change(screen.getByLabelText("Game Port"), { target: { value: "25610" } });
      fireEvent.change(screen.getByLabelText("RCON Port"), { target: { value: "25611" } });
      fireEvent.click(screen.getByRole("button", { name: "Save Port Set" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Port conflict (DUPLICATE_PORT_SET)",
      );
    });
  });

  describe("DataTemplatesModal", () => {
    it("lists templates and creates a live template", async () => {
      const onTemplatesChanged = vi.fn();
      render(
        <DataTemplatesModal
          isOpen
          serverId="s1"
          branches={mockBranches}
          selectedBranch="feat-trial"
          onClose={vi.fn()}
          onTemplatesChanged={onTemplatesChanged}
        />,
      );

      expect(await screen.findByText("seed-1")).toBeInTheDocument();
      expect(screen.getByText("Branch: feat-trial")).toBeInTheDocument();
      expect(screen.getByText("42 files")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Create Template" }));
      fireEvent.change(screen.getByLabelText("Template Name"), { target: { value: "live-snapshot" } });
      fireEvent.click(screen.getByRole("button", { name: "Create Template" }));

      await waitFor(() => {
        expect(mockApi.createDataTemplate).toHaveBeenCalledWith(
          "s1",
          expect.objectContaining({
            name: "live-snapshot",
            source: "live",
            branch_name: null,
            async_mode: false,
          }),
        );
      });
      expect(onTemplatesChanged).toHaveBeenCalled();
    });

    it("creates a branch template and reveals the branch selector", async () => {
      render(
        <DataTemplatesModal
          isOpen
          serverId="s1"
          branches={mockBranches}
          selectedBranch="main"
          onClose={vi.fn()}
          onTemplatesChanged={vi.fn()}
        />,
      );

      await screen.findByText("seed-1");
      fireEvent.click(screen.getByRole("tab", { name: "Create Template" }));
      fireEvent.change(screen.getByLabelText("Template Name"), { target: { value: "branch-snapshot" } });
      fireEvent.change(screen.getByLabelText("Template Source"), { target: { value: "branch" } });
      expect(screen.getByLabelText("Source Branch")).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("Source Branch"), { target: { value: "feat-trial" } });
      fireEvent.click(screen.getByRole("button", { name: "Create Template" }));

      await waitFor(() => {
        expect(mockApi.createDataTemplate).toHaveBeenCalledWith(
          "s1",
          expect.objectContaining({
            name: "branch-snapshot",
            source: "branch",
            branch_name: "feat-trial",
          }),
        );
      });
    });

    it("surfaces a 409 HOT_CLONE_REFUSED on create", async () => {
      mockApi.createDataTemplate.mockRejectedValueOnce(
        new ApiError(409, "HOT_CLONE_REFUSED", "RCON quiesce required"),
      );
      render(
        <DataTemplatesModal
          isOpen
          serverId="s1"
          branches={mockBranches}
          selectedBranch="feat-trial"
          onClose={vi.fn()}
          onTemplatesChanged={vi.fn()}
        />,
      );

      await screen.findByText("seed-1");
      fireEvent.click(screen.getByRole("tab", { name: "Create Template" }));
      fireEvent.change(screen.getByLabelText("Template Name"), { target: { value: "hot" } });
      fireEvent.click(screen.getByRole("button", { name: "Create Template" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("HOT_CLONE_REFUSED");
    });

    it("surfaces a 409 active-runtime protection error on delete", async () => {
      mockApi.deleteDataTemplate.mockRejectedValueOnce(
        new ApiError(409, "DATA_TEMPLATE_IN_USE", "Data template is currently in use by an active runtime"),
      );
      render(
        <DataTemplatesModal
          isOpen
          serverId="s1"
          branches={mockBranches}
          selectedBranch="feat-trial"
          onClose={vi.fn()}
          onTemplatesChanged={vi.fn()}
        />,
      );

      await screen.findByText("seed-1");
      fireEvent.click(screen.getByRole("button", { name: "Delete template seed-1" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Data template is currently in use by an active runtime",
      );
      expect(mockApi.deleteDataTemplate).toHaveBeenCalledWith("s1", "tpl-1");
    });
  });

  describe("BranchConsoleActivityModal", () => {
    it("loads console logs, dispatches RCON commands, and clears the input", async () => {
      render(
        <BranchConsoleActivityModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          isRuntimeActive
          onClose={vi.fn()}
        />,
      );

      expect(await screen.findByTestId("branch-console-output")).toHaveTextContent(
        "[INFO] Server started",
      );
      expect(mockApi.getBranchConsole).toHaveBeenCalledWith("s1", "feat-trial", 200);

      const commandInput = screen.getByLabelText("Branch RCON command");
      fireEvent.change(commandInput, { target: { value: "list" } });
      fireEvent.click(screen.getByRole("button", { name: "Send Command" }));

      await waitFor(() => {
        expect(mockApi.sendBranchConsoleCommand).toHaveBeenCalledWith("s1", "feat-trial", {
          command: "list",
        });
      });
      expect(await screen.findByTestId("branch-command-output")).toHaveTextContent(
        "There are 2 of 20 players online.",
      );
      expect(commandInput).toHaveValue("");
    });

    it("loads branch-scoped activity from the activity tab", async () => {
      render(
        <BranchConsoleActivityModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          isRuntimeActive
          onClose={vi.fn()}
        />,
      );

      await screen.findByTestId("branch-console-output");
      fireEvent.click(screen.getByRole("tab", { name: "Branch Activity" }));

      expect(await screen.findByText("Branch run started")).toBeInTheDocument();
      expect(mockApi.getServerActivity).toHaveBeenCalledWith("s1", {
        branch: "feat-trial",
        limit: 50,
      });
    });

    it("shows a calm inactive message and disables RCON input", async () => {
      render(
        <BranchConsoleActivityModal
          isOpen
          serverId="s1"
          branchName="feat-trial"
          isRuntimeActive={false}
          onClose={vi.fn()}
        />,
      );

      expect(
        await screen.findByText(/No active runtime for branch 'feat-trial'/),
      ).toBeInTheDocument();
      expect(screen.getByLabelText("Branch RCON command")).toBeDisabled();
      expect(mockApi.getBranchConsole).not.toHaveBeenCalled();
    });
  });
});
