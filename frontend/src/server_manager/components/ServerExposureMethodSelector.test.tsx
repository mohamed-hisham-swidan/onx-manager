import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ServerExposureMethodSelector } from "./ServerExposureMethodSelector";
import type { ServerExposureResponse, AgentStatusResponse } from "@/types";

const mockExposure: ServerExposureResponse = {
  server_id: "srv-123",
  method: "playit",
  desired_state: "ENABLED",
  aggregate_status: "ACTIVE",
  has_cloudflare_credentials: false,
  cloudflare_tunnel_id: null,
  error_code: null,
  error_message: null,
  targets: [
    {
      id: "tgt-1",
      exposure_id: "exp-1",
      protocol: "tcp",
      service_type: "java",
      local_port: 25565,
      public_address: "foo.ply.gg:12345",
      status: "ACTIVE",
      error_code: null,
      error_message: null,
      dashboard_url: null,
      setup_instructions: null,
    },
  ],
};

const mockAgent: AgentStatusResponse = {
  claimed: true,
  process_status: "RUNNING",
  desired_agent_running: true,
  last_health_at: null,
  claim_active: false,
  claim_expires_at: null,
};

describe("ServerExposureMethodSelector modal behavior (FIX-3)", () => {
  function renderSelector(onSelectMethod = vi.fn()) {
    return render(
      <ServerExposureMethodSelector
        exposure={mockExposure}
        agent={mockAgent}
        draftMethod="playit"
        onSelectMethod={onSelectMethod}
        onSaveExposure={vi.fn()}
        onGenerateClaim={vi.fn()}
        onResetAgent={vi.fn()}
        claimData={null}
      />
    );
  }

  it("renders dialog with accessible title, focuses inside, and supports Escape", async () => {
    renderSelector();
    const cfCard = screen.getByText("Cloudflare TCP");
    fireEvent.click(cfCard);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Switch Exposure Method?")).toBeInTheDocument();

    const input = screen.getByPlaceholderText('Type "SWITCH"');
    await waitFor(() => {
      expect(document.activeElement).toBe(input);
    });

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("does not close on backdrop click or content click", async () => {
    renderSelector();
    const cfCard = screen.getByText("Cloudflare TCP");
    fireEvent.click(cfCard);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(dialog);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("enables switch button only when SWITCH is typed, and Cancel button closes dialog", async () => {
    const onSelectMethod = vi.fn();
    renderSelector(onSelectMethod);
    const cfCard = screen.getByText("Cloudflare TCP");
    fireEvent.click(cfCard);

    const input = screen.getByPlaceholderText('Type "SWITCH"');
    const switchBtn = screen.getByRole("button", { name: "Switch Method" });
    const cancelBtn = screen.getByRole("button", { name: "Cancel" });

    expect(switchBtn).toBeDisabled();

    fireEvent.change(input, { target: { value: "SWITCH" } });
    expect(switchBtn).not.toBeDisabled();

    fireEvent.click(cancelBtn);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(onSelectMethod).not.toHaveBeenCalled();
  });
});
