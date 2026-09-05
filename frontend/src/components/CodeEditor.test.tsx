import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeEditor } from "./CodeEditor";

describe("CodeEditor (ISS-051)", () => {
  it("mounts with file content, line numbers gutter, and detected language", () => {
    render(
      <CodeEditor
        value={"server-port=25565\nmotd=Minecraft\npvp=true"}
        onChange={vi.fn()}
        filename="server.properties"
      />
    );

    expect(screen.getByTestId("code-editor")).toBeInTheDocument();
    expect(screen.getByText("Properties")).toBeInTheDocument();
    expect(screen.getByText("3 lines")).toBeInTheDocument();

    const textarea = screen.getByRole("textbox", { name: /code editor/i }) as HTMLTextAreaElement;
    expect(textarea.value).toBe("server-port=25565\nmotd=Minecraft\npvp=true");
  });

  it("updates value when user types in the editor", async () => {
    const user = userEvent.setup();
    const handleChange = vi.fn();

    render(
      <CodeEditor
        value="initial"
        onChange={handleChange}
        filename="config.yml"
      />
    );

    const textarea = screen.getByRole("textbox", { name: /code editor/i }) as HTMLTextAreaElement;
    await user.type(textarea, " extra");

    expect(handleChange).toHaveBeenCalled();
  });

  it("handles Tab key by inserting spaces instead of losing focus", () => {
    const handleChange = vi.fn();
    render(
      <CodeEditor
        value="hello"
        onChange={handleChange}
        filename="run.sh"
      />
    );

    const textarea = screen.getByRole("textbox", { name: /code editor/i }) as HTMLTextAreaElement;
    textarea.selectionStart = 0;
    textarea.selectionEnd = 0;

    fireEvent.keyDown(textarea, { key: "Tab" });

    expect(handleChange).toHaveBeenCalledWith("  hello");
  });

  it("sets wrap='off' on textarea to avoid visual line-drift", () => {
    render(
      <CodeEditor
        value="line1\nline2"
        onChange={vi.fn()}
        filename="server.properties"
      />
    );

    const textarea = screen.getByRole("textbox", { name: /code editor/i }) as HTMLTextAreaElement;
    expect(textarea.getAttribute("wrap")).toBe("off");
  });

  it("forwards wheel scrolling on the line numbers gutter to the scroll container", () => {
    render(
      <CodeEditor
        value={"line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\nline 9\nline 10"}
        onChange={vi.fn()}
        filename="server.properties"
      />
    );

    const scrollContainer = screen.getByTestId("editor-scroll-container");
    const gutter = screen.getByTestId("editor-gutter");
    scrollContainer.scrollTop = 0;

    fireEvent.wheel(gutter, { deltaY: 120 });
    expect(scrollContainer.scrollTop).toBe(120);
  });

  it("renders gutter as a <pre> element matching content typography (ISS-070)", () => {
    render(
      <CodeEditor
        value={"line 1\nline 2\nline 3"}
        onChange={vi.fn()}
        filename="server.properties"
      />
    );

    const gutter = screen.getByTestId("editor-gutter");
    expect(gutter.tagName.toLowerCase()).toBe("pre");
    expect(gutter.className).toContain("text-sm");
    expect(gutter.className).toContain("leading-6");
    expect(gutter.className).toContain("whitespace-pre");
    expect(gutter.className).toContain("h-[560px]");
    expect(gutter.textContent).toBe("1\n2\n3");
  });

  it("syncs gutter scrollTop with scroll container on scroll event (ISS-070)", () => {
    render(
      <CodeEditor
        value={Array.from({ length: 50 }, (_, i) => `line ${i + 1}`).join("\n")}
        onChange={vi.fn()}
        filename="server.properties"
      />
    );

    const scrollContainer = screen.getByTestId("editor-scroll-container");
    const gutter = screen.getByTestId("editor-gutter");

    scrollContainer.scrollTop = 240;
    fireEvent.scroll(scrollContainer);

    expect(gutter.scrollTop).toBe(240);
  });

  it("contains textarea internal scroll and resets it while transferring to scroll container (ISS-070)", () => {
    render(
      <CodeEditor
        value={Array.from({ length: 50 }, (_, i) => `line ${i + 1}`).join("\n")}
        onChange={vi.fn()}
        filename="server.properties"
      />
    );

    const scrollContainer = screen.getByTestId("editor-scroll-container");
    const textarea = screen.getByRole("textbox", { name: /code editor/i }) as HTMLTextAreaElement;

    scrollContainer.scrollTop = 0;
    textarea.scrollTop = 50;
    textarea.scrollLeft = 20;
    fireEvent.scroll(textarea);

    expect(scrollContainer.scrollTop).toBe(50);
    expect(scrollContainer.scrollLeft).toBe(20);
    expect(textarea.scrollTop).toBe(0);
    expect(textarea.scrollLeft).toBe(0);
  });
});
