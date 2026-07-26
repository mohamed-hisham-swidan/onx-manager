import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerConfigEditor } from "./ServerConfigEditor";

const mockServer = {
  server_id: "srv-1",
  name: "Test",
  server_type: "vanilla",
  minecraft_version: "1.20.4",
  status: "running",
  group_id: "default",
  port: 25565,
  motd: "Welcome!",
  max_players: 20,
  gamemode: "survival",
  difficulty: "normal",
  min_memory_mb: 1024,
  max_memory_mb: 2048,
  java_args: "-Xmx2G",
  spawn_protection: 16,
  pvp: true,
  enable_command_block: false,
  online_mode: true,
  whitelist: false,
  view_distance: 10,
  simulation_distance: 10,
  provider: null,
  deployment_host: null,
  deployment_port: null,
  deployment_pid: null,
  location_type: null,
  location_uri: null,
  root_path: null,
  working_directory: null,
  startup_jar: null,
  startup_command: null,
  primary_world: null,
  created_at: "",
  updated_at: "",
};

vi.mock("@/server_manager/hooks/useServers", () => ({
  useUpdateServer: vi.fn(() => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false })),
}));

function renderEditor() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ServerConfigEditor serverId="srv-1" server={mockServer} />
    </QueryClientProvider>,
  );
}

describe("ServerConfigEditor", () => {
  it("renders form fields", () => {
    renderEditor();
    expect(screen.getByText("Save Configuration")).toBeInTheDocument();
    expect(screen.getByDisplayValue("1024")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2048")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Welcome!")).toBeInTheDocument();
  });

  it("renders save button", () => {
    renderEditor();
    expect(screen.getByText("Save Configuration")).toBeInTheDocument();
  });
});
