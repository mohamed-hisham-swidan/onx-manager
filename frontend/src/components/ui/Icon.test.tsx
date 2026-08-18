import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Icon } from "./Icon";

describe("Icon", () => {
  it("renders an svg with the given name", () => {
    const { container } = render(<Icon name="server" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("applies a size", () => {
    const { container } = render(<Icon name="server" size={24} />);
    expect(container.querySelector("svg")).toHaveAttribute("width", "24");
    expect(container.querySelector("svg")).toHaveAttribute("height", "24");
  });

  it("renders modrinth and curseforge brand icons", () => {
    const { container: c1 } = render(<Icon name="modrinth" />);
    expect(c1.querySelector("svg")).toBeInTheDocument();

    const { container: c2 } = render(<Icon name="curseforge" />);
    expect(c2.querySelector("svg")).toBeInTheDocument();
  });

  it("renders new overview icons (globe, clock, cpu, hard-drive)", () => {
    const names = ["globe", "clock", "cpu", "hard-drive"] as const;
    names.forEach((name) => {
      const { container } = render(<Icon name={name} />);
      expect(container.querySelector("svg")).toBeInTheDocument();
    });
  });
});
