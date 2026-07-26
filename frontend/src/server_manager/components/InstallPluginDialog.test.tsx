import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InstallPluginDialog } from "./InstallPluginDialog";

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  useInstallPlugin: vi.fn(() => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false })),
}));

function renderDialog() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <InstallPluginDialog serverId="srv-1" onDone={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("InstallPluginDialog", () => {
  it("renders form", () => {
    renderDialog();
    expect(screen.getByText("Install Plugin")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Plugin name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Version (e.g. 1.0.0)")).toBeInTheDocument();
  });

  it("renders install button", () => {
    renderDialog();
    expect(screen.getByText("Install")).toBeInTheDocument();
  });
});
