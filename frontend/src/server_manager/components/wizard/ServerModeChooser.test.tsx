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

  it("does not render Advanced mode option when advancedEnabled is omitted or false", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ServerModeChooser value="simple" onChange={onChange} />,
    );

    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced")).not.toBeInTheDocument();

    rerender(
      <ServerModeChooser
        value="simple"
        onChange={onChange}
        advancedEnabled={false}
      />,
    );
    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();
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
    render(
      <ServerModeChooser
        value="simple"
        onChange={onChange}
        disabled={true}
        advancedEnabled={true}
      />,
    );

    expect(screen.getByTestId("server-mode-simple")).toBeDisabled();
    expect(screen.getByTestId("server-mode-advanced")).toBeDisabled();
  });

  it("renders Advanced card with Preview badge and description when advancedEnabled is true", () => {
    const onChange = vi.fn();
    render(
      <ServerModeChooser
        value="simple"
        onChange={onChange}
        advancedEnabled={true}
      />,
    );

    const advancedCard = screen.getByTestId("server-mode-advanced");
    expect(advancedCard).toBeInTheDocument();
    expect(screen.getByText("Advanced")).toBeInTheDocument();
    expect(screen.getByText("POSIX Advanced")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Git-backed server with branches, safe upgrades, and commit history.",
      ),
    ).toBeInTheDocument();
    // Simple card should show Active badge when value="simple"
    expect(screen.getByText("Active")).toBeInTheDocument();
    // Advanced card should not have selected styling
    expect(advancedCard.className).toContain("border-border-default");
  });

  it("calls onChange with 'advanced' when Advanced card is clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ServerModeChooser
        value="simple"
        onChange={onChange}
        advancedEnabled={true}
      />,
    );

    const advancedCard = screen.getByTestId("server-mode-advanced");
    await user.click(advancedCard);

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("advanced");
  });

  it("applies selected styling to Advanced card and hides Simple Active badge when value is 'advanced'", () => {
    const onChange = vi.fn();
    render(
      <ServerModeChooser
        value="advanced"
        onChange={onChange}
        advancedEnabled={true}
      />,
    );

    const simpleCard = screen.getByTestId("server-mode-simple");
    const advancedCard = screen.getByTestId("server-mode-advanced");

    // Simple Active badge absent when value="advanced"
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    // Simple card has unselected styling
    expect(simpleCard.className).toContain("border-border-default");
    // Advanced card has selected styling
    expect(advancedCard.className).toContain("border-accent-primary");
    expect(advancedCard.className).toContain("bg-accent-primary/15");
  });
});
