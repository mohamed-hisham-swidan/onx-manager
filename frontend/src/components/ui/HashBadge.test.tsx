import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HashBadge } from "./HashBadge";

describe("HashBadge", () => {
  it("renders shortened hash with default prefix and length", () => {
    render(<HashBadge hash="28b54bc1264d4251958bd741fe82690b" />);

    expect(screen.getByText("#28b54bc")).toBeInTheDocument();
  });

  it("copies full hash to clipboard when clicked", async () => {
    const user = userEvent.setup();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: writeTextMock },
      configurable: true,
    });

    render(<HashBadge hash="28b54bc1264d4251958bd741fe82690b" />);

    const badge = screen.getByRole("button");
    await user.click(badge);

    expect(writeTextMock).toHaveBeenCalledWith("28b54bc1264d4251958bd741fe82690b");
    expect(screen.getByText("Copied!")).toBeInTheDocument();
  });

  it("returns null if hash is empty", () => {
    const { container } = render(<HashBadge hash="" />);
    expect(container.firstChild).toBeNull();
  });
});
