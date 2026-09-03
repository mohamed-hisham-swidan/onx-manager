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
});
