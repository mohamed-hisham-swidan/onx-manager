import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CommitDiffModal } from "./CommitDiffModal";

const mockDiffCommits = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    diffCommits: (...args: unknown[]) => mockDiffCommits(...args),
  }),
}));

describe("CommitDiffModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders real config file paths when configs are arrays (not numeric indices 0, 1)", async () => {
    mockDiffCommits.mockResolvedValue({
      from_commit_id: "aaaaaaa1111111",
      to_commit_id: "bbbbbbb2222222",
      has_changes: true,
      server_type: null,
      minecraft_version: null,
      configs: {
        added: ["config/new-plugin.yml"],
        modified: ["server.properties", "paper-global.yml"],
        removed: ["old-config.yml"],
      },
      mods: { added: [], removed: [], modified: [] },
      env_vars: {},
    });

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="aaaaaaa1111111"
        toCommitId="bbbbbbb2222222"
      />,
    );

    const configsTab = await screen.findByRole("button", { name: /Config Files \(4\)/i });
    fireEvent.click(configsTab);

    await waitFor(() => {
      expect(screen.getByText("+ config/new-plugin.yml")).toBeInTheDocument();
      expect(screen.getByText("~ server.properties")).toBeInTheDocument();
      expect(screen.getByText("~ paper-global.yml")).toBeInTheDocument();
      expect(screen.getByText("- old-config.yml")).toBeInTheDocument();
    });

    expect(screen.queryByText("+ 0")).not.toBeInTheDocument();
    expect(screen.queryByText("~ 0")).not.toBeInTheDocument();
  });
});
