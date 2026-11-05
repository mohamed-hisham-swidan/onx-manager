import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { VersionList } from "./VersionList";
import type { PluginVersionResponse } from "@/types";

const mockVersions: PluginVersionResponse[] = [
  {
    version_id: "v1",
    project_id: "proj1",
    name: "Version 2.21.0",
    version_number: "2.21.0",
    game_versions: ["1.21", "1.21.1"],
    loaders: ["paper", "spigot"],
    files: [{ filename: "test.jar", url: "", size_bytes: 1048576, sha1: "", sha512: "", primary: true }],
    dependencies: [],
    date_published: "2026-08-01",
  },
  {
    version_id: "v2",
    project_id: "proj1",
    name: "Version 2.20.0",
    version_number: "2.20.0",
    game_versions: ["1.20.4"],
    loaders: ["paper"],
    files: [{ filename: "test2.jar", url: "", size_bytes: 524288, sha1: "", sha512: "", primary: true }],
    dependencies: [],
    date_published: "2026-07-01",
  },
];

describe("VersionList", () => {
  it("renders a vertical list of versions", () => {
    const handleSelect = vi.fn();
    render(<VersionList versions={mockVersions} onSelectVersion={handleSelect} />);

    expect(screen.getByText("2.21.0")).toBeInTheDocument();
    expect(screen.getByText("2.20.0")).toBeInTheDocument();
  });

  it("highlights selected/recommended version", () => {
    const handleSelect = vi.fn();
    render(
      <VersionList
        versions={mockVersions}
        selectedVersion={mockVersions[0]}
        onSelectVersion={handleSelect}
      />,
    );

    expect(screen.getByText("Recommended")).toBeInTheDocument();
  });

  it("displays notice message if provided", () => {
    const handleSelect = vi.fn();
    render(
      <VersionList
        versions={mockVersions}
        notice="Compatibility is unconfirmed for this server version."
        onSelectVersion={handleSelect}
      />,
    );

    expect(screen.getByText("Compatibility is unconfirmed for this server version.")).toBeInTheDocument();
  });

  it("calls onSelectVersion when a version row or install button is clicked", () => {
    const handleSelect = vi.fn();
    render(<VersionList versions={mockVersions} onSelectVersion={handleSelect} />);

    const installButtons = screen.getAllByRole("button", { name: /install/i });
    fireEvent.click(installButtons[1]);

    expect(handleSelect).toHaveBeenCalledWith(mockVersions[1]);
  });

  it("calls onSelectVersion when a version row is activated with keyboard Enter or Space", () => {
    const handleSelect = vi.fn();
    render(<VersionList versions={mockVersions} onSelectVersion={handleSelect} />);

    const row = screen.getByRole("button", { name: `Select version ${mockVersions[0].version_number}` });
    fireEvent.keyDown(row, { key: "Enter" });
    expect(handleSelect).toHaveBeenCalledWith(mockVersions[0]);

    fireEvent.keyDown(row, { key: " " });
    expect(handleSelect).toHaveBeenCalledTimes(2);
  });
});
