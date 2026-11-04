import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Banner } from "./Banner";

describe("Banner Primitive", () => {
  it("renders title, description and icon", () => {
    render(
      <Banner
        variant="warning"
        title="WebSocket Reconnecting"
        description="Attempting to restore live event stream..."
      />
    );
    expect(screen.getByText("WebSocket Reconnecting")).toBeInTheDocument();
    expect(screen.getByText("Attempting to restore live event stream...")).toBeInTheDocument();
  });

  it("handles dismiss action", () => {
    const onDismiss = vi.fn();
    render(<Banner title="Notice" onDismiss={onDismiss} />);
    fireEvent.click(screen.getByLabelText("Dismiss banner"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
