import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ServerBanner } from "./ServerBanner";

describe("ServerBanner", () => {
  it("renders procedural background banner", () => {
    const { container } = render(
      <ServerBanner seed="survival-main">
        <span data-testid="badge">Online</span>
      </ServerBanner>
    );

    expect(container.firstChild).toBeInTheDocument();
    expect(screen.getByTestId("badge")).toBeInTheDocument();
  });

  it("applies custom banner URL when provided", () => {
    const { container } = render(
      <ServerBanner
        seed="survival-main"
        customBannerUrl="https://example.com/banner.png"
      />
    );

    const banner = container.firstChild as HTMLElement;
    expect(banner.style.backgroundImage).toContain("example.com/banner.png");
  });
});
