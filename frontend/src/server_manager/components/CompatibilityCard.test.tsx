import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CompatibilityCard, groupGameVersions, environmentLabels } from "./CompatibilityCard";
import { platformProjectType } from "@/server_manager/data/platforms";

describe("groupGameVersions", () => {
  it("keeps a lone version exact", () => {
    expect(groupGameVersions(["26.2"])).toEqual(["26.2"]);
    expect(groupGameVersions(["1.17.1"])).toEqual(["1.17.1"]);
  });

  it("collapses a line that includes the bare base release to major.minor.x", () => {
    expect(groupGameVersions(["1.21", "1.21.1"])).toEqual(["1.21.x"]);
    expect(groupGameVersions(["26.1", "26.1.1", "26.1.2"])).toEqual(["26.1.x"]);
    expect(groupGameVersions(["1.18", "1.18.1", "1.18.2"])).toEqual(["1.18.x"]);
  });

  it("merges consecutive base-covered lines into a line range", () => {
    expect(
      groupGameVersions([
        "1.17", "1.17.1",
        "1.18", "1.18.1", "1.18.2",
        "1.19", "1.19.1",
      ]),
    ).toEqual(["1.17–1.19"]);
    expect(groupGameVersions(["1.18", "1.18.1", "1.19", "1.19.1"])).toEqual([
      "1.18–1.19",
    ]);
  });

  it("does not merge a gap-covered line or an exact single line into a range", () => {
    expect(
      groupGameVersions(["1.18", "1.18.1", "1.19", "1.19.1", "1.20.1", "1.20.4"]),
    ).toEqual(["1.20.x", "1.18–1.19"]);
    expect(groupGameVersions(["1.17.1", "1.18", "1.18.1", "1.19", "1.19.1"])).toEqual([
      "1.18–1.19",
      "1.17.1",
    ]);
  });

  it("does not merge across majors or into an exact line", () => {
    expect(
      groupGameVersions(["26.1", "26.1.1", "26.2", "1.21", "1.21.1"]),
    ).toEqual(["26.2", "26.1.x", "1.21.x"]);
  });

  it("renders a gap-free contiguous run as a range", () => {
    expect(groupGameVersions(["1.16.3", "1.16.4", "1.16.5"])).toEqual([
      "1.16.3–1.16.5",
    ]);
    expect(groupGameVersions(["1.18.1", "1.18.2"])).toEqual(["1.18.1–1.18.2"]);
  });

  it("collapses a non-contiguous run without a base to major.minor.x", () => {
    expect(groupGameVersions(["1.20.1", "1.20.2", "1.20.4"])).toEqual([
      "1.20.x",
    ]);
    expect(groupGameVersions(["1.19.2", "1.19.4"])).toEqual(["1.19.x"]);
  });

  it("sorts numeric lines newest-first", () => {
    expect(
      groupGameVersions(["1.20.1", "26.1", "1.21.1", "1.21.10", "26.1.4"]),
    ).toEqual(["26.1.x", "1.21.x", "1.20.1"]);
  });

  it("keeps non-numeric versions raw, after numeric lines", () => {
    expect(groupGameVersions(["26.2", "26.2-rc-1", "26.2-rc-2"])).toEqual([
      "26.2",
      "26.2-rc-2",
      "26.2-rc-1",
    ]);
    expect(groupGameVersions(["24w14potato"])).toEqual(["24w14potato"]);
  });

  it("reproduces the Modrinth-style summary for a wide-support project", () => {
    expect(
      groupGameVersions([
        "1.16.3", "1.16.4", "1.16.5",
        "1.17", "1.17.1",
        "1.18", "1.18.1", "1.18.2",
        "1.19", "1.19.1", "1.19.2", "1.19.3", "1.19.4",
        "1.20", "1.20.1", "1.20.2", "1.20.3", "1.20.4", "1.20.5", "1.20.6",
        "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5", "1.21.6",
        "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11",
        "26.1", "26.1.1", "26.1.2",
        "26.2",
      ]),
    ).toEqual([
      "26.2",
      "26.1.x",
      "1.17–1.21",
      "1.16.3–1.16.5",
    ]);
  });
});

describe("environmentLabels", () => {
  it("returns 'Client and server' when both are required/optional", () => {
    expect(environmentLabels("required", "required")).toEqual(["Client and server"]);
    expect(environmentLabels("optional", "optional")).toEqual(["Client and server"]);
    expect(environmentLabels("optional", "required")).toEqual(["Client and server"]);
  });

  it("returns single environment when only one is present", () => {
    expect(environmentLabels("required", "unsupported")).toEqual(["Client-side"]);
    expect(environmentLabels(null, "optional")).toEqual(["Server-side"]);
  });

  it("returns empty array when both are null/unsupported", () => {
    expect(environmentLabels(null, null)).toEqual([]);
    expect(environmentLabels("unsupported", "unsupported")).toEqual([]);
    expect(environmentLabels(undefined, undefined)).toEqual([]);
  });
});

describe("platformProjectType", () => {
  it("maps server loaders to plugin and mod-loaders to mod", () => {
    expect(platformProjectType("paper", "plugin")).toBe("plugin");
    expect(platformProjectType("Spigot", "plugin")).toBe("plugin");
    expect(platformProjectType("velocity", "plugin")).toBe("plugin");
    expect(platformProjectType("fabric", "plugin")).toBe("mod");
    expect(platformProjectType("NeoForge", "plugin")).toBe("mod");
    expect(platformProjectType("quilt", "plugin")).toBe("mod");
    expect(platformProjectType("minecraft", "plugin")).toBe("plugin");
  });
});

describe("CompatibilityCard", () => {
  it("renders platform pills as links when buildPlatformHref is provided", () => {
    render(
      <MemoryRouter>
        <CompatibilityCard
          gameVersions={[]}
          loaders={["paper", "fabric"]}
          buildPlatformHref={(loader) => `/marketplace?type=plugin&loader=${loader}`}
        />
      </MemoryRouter>,
    );

    const paper = screen.getByRole("link", { name: "Paper" });
    expect(paper).toHaveAttribute("href", "/marketplace?type=plugin&loader=paper");
    const fabric = screen.getByRole("link", { name: "Fabric" });
    expect(fabric).toHaveAttribute("href", "/marketplace?type=plugin&loader=fabric");
  });

  it("renders platform pills as plain spans when no href builder is given", () => {
    render(
      <CompatibilityCard
        gameVersions={[]}
        loaders={["paper"]}
      />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Paper")).toBeInTheDocument();
    const pill = screen.getByText("Paper").closest("span");
    expect(pill?.querySelector("svg")).toBeInTheDocument();
    expect(pill?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("renders game versions and platform pills", () => {
    render(
      <CompatibilityCard
        gameVersions={["1.21", "1.21.1"]}
        loaders={["paper", "spigot"]}
        clientSide="optional"
        serverSide="required"
      />,
    );

    expect(screen.getByText("Compatibility")).toBeInTheDocument();
    expect(screen.getByText("1.21.x")).toBeInTheDocument();
    expect(screen.getByText("Paper")).toBeInTheDocument();
    expect(screen.getByText("Spigot")).toBeInTheDocument();
    expect(screen.getByText("Client and server")).toBeInTheDocument();
  });

  it("hides supported environments section when both are null", () => {
    render(
      <CompatibilityCard
        gameVersions={["1.21"]}
        loaders={["paper"]}
        clientSide={null}
        serverSide={null}
      />,
    );

    expect(screen.queryByTestId("supported-environments-section")).not.toBeInTheDocument();
  });
});
