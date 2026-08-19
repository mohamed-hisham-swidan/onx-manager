import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompatibilityCard, environmentLabels } from "./CompatibilityCard";

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

describe("CompatibilityCard", () => {
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
    expect(screen.getByText("1.21")).toBeInTheDocument();
    expect(screen.getByText("1.21.1")).toBeInTheDocument();
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
