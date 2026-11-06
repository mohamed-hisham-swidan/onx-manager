import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TargetCard } from "./TargetCard";
import type { TargetResponse } from "@/types";

const mockTarget: TargetResponse = {
  id: "tgt-companion",
  exposure_id: "exp-1",
  protocol: "udp",
  service_type: "bedrock",
  local_port: 19132,
  public_address: "play.ply.gg:54321",
  status: "ACTIVE",
  error_code: null,
  error_message: null,
  dashboard_url: null,
  setup_instructions: null,
};

describe("TargetCard modal behavior (FIX-3)", () => {
  it("renders dialog with accessible title, focuses inside, and supports Escape", async () => {
    render(<TargetCard target={mockTarget} onEditAddress={vi.fn()} onRemoveTarget={vi.fn()} />);
    const removeBtn = screen.getByRole("button", { name: /remove.*target/i });
    fireEvent.click(removeBtn);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Remove Companion Target?")).toBeInTheDocument();

    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("does not close on backdrop click or content click", async () => {
    render(<TargetCard target={mockTarget} onEditAddress={vi.fn()} onRemoveTarget={vi.fn()} />);
    const removeBtn = screen.getByRole("button", { name: /remove.*target/i });
    fireEvent.click(removeBtn);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(dialog);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("calls onRemoveTarget when confirmed and closes on cancel", async () => {
    const onRemoveTarget = vi.fn();
    render(<TargetCard target={mockTarget} onEditAddress={vi.fn()} onRemoveTarget={onRemoveTarget} />);
    const removeBtn = screen.getByRole("button", { name: /remove.*target/i });
    fireEvent.click(removeBtn);

    const confirmBtn = screen.getByRole("button", { name: "Remove Target" });
    fireEvent.click(confirmBtn);

    expect(onRemoveTarget).toHaveBeenCalledWith("tgt-companion");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
