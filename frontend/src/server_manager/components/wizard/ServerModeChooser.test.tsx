import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ServerModeChooser } from "./ServerModeChooser";

describe("ServerModeChooser", () => {
  it("renders Simple mode card with active status and descriptive text", () => {
    const onChange = vi.fn();
    render(<ServerModeChooser value="simple" onChange={onChange} />);

    expect(screen.getByText("Server Mode")).toBeInTheDocument();
    const simpleCard = screen.getByTestId("server-mode-simple");
    expect(simpleCard).toBeInTheDocument();
    expect(screen.getByText("Simple")).toBeInTheDocument();
    expect(
      screen.getByText("Git-free server. Recommended for most servers."),
    ).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("does not render Advanced mode option in P1", () => {
    const onChange = vi.fn();
    render(<ServerModeChooser value="simple" onChange={onChange} />);

    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced")).not.toBeInTheDocument();
  });

  it("calls onChange with 'simple' when the Simple card is clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<ServerModeChooser value="simple" onChange={onChange} />);

    const simpleCard = screen.getByTestId("server-mode-simple");
    await user.click(simpleCard);

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("simple");
  });

  it("disables button when disabled prop is true", () => {
    const onChange = vi.fn();
    render(<ServerModeChooser value="simple" onChange={onChange} disabled={true} />);

    const simpleCard = screen.getByTestId("server-mode-simple");
    expect(simpleCard).toBeDisabled();
  });
});
