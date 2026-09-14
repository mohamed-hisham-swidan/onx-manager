import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CrashReportViewerModal } from "./CrashReportViewerModal";
import type { CrashReportSummary } from "@/server_manager/types";

const mockCopy = vi.fn();
vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({ copy: mockCopy }),
}));

const sampleReports: CrashReportSummary[] = [
  {
    filename: "crash-2026-09-14_01.00.00-server.txt",
    timestamp: "2026-09-14T01:00:00Z",
    failure_code: "MOD_CRASH",
    blamed_mod: "ironchest",
    stack_trace_snippet:
      "net.minecraftforge.fml.ModLoadingException: Mod ironchest encountered an error\n\tat net.minecraftforge.fml.FMLModContainer.acceptEvent(FMLModContainer.java:124)",
    suggested_remediation: "Check or disable the conflicting or failing mod: ironchest",
    raw_content:
      "---- Minecraft Crash Report ----\nTime: 2026-09-14 01:00:00 UTC\nDescription: Mod loading error\n\nnet.minecraftforge.fml.ModLoadingException: Mod ironchest encountered an error\n-- System Details --\nDetails:\n\tMinecraft Version: 1.20.1",
  },
  {
    filename: "crash-2026-09-13_12.00.00-server.txt",
    timestamp: "2026-09-13T12:00:00Z",
    failure_code: "MEMORY_EXHAUSTED",
    blamed_mod: null,
    stack_trace_snippet: "java.lang.OutOfMemoryError: Java heap space",
    suggested_remediation: "Increase -Xmx in launch config or reduce world size",
    raw_content: "java.lang.OutOfMemoryError: Java heap space\n-- System Details --",
  },
];

describe("CrashReportViewerModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <CrashReportViewerModal
        isOpen={false}
        onClose={vi.fn()}
        reports={sampleReports}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders empty state when reports array is empty", () => {
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={vi.fn()}
        reports={[]}
      />
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("No crash reports found")).toBeInTheDocument();
  });

  it("renders loading state when isLoading is true", () => {
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={vi.fn()}
        reports={[]}
        isLoading={true}
      />
    );
    expect(screen.getByText("Loading crash reports...")).toBeInTheDocument();
  });

  it("renders crash report details with blamed mod callout and stack trace snippet", () => {
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={vi.fn()}
        reports={sampleReports}
        serverName="test-server"
      />
    );

    expect(screen.getByText("Crash Report Inspector")).toBeInTheDocument();
    expect(screen.getByText("Server: test-server")).toBeInTheDocument();
    expect(screen.getByTestId("failure-code-badge")).toHaveTextContent("MOD_CRASH");

    // Blamed mod callout
    const blamedCallout = screen.getByTestId("blamed-mod-callout");
    expect(blamedCallout).toBeInTheDocument();
    expect(blamedCallout).toHaveTextContent("ironchest");

    // Remediation tip
    expect(
      screen.getByText("Check or disable the conflicting or failing mod: ironchest")
    ).toBeInTheDocument();

    // Stack trace snippet
    const snippet = screen.getByTestId("stack-trace-snippet");
    expect(snippet).toHaveTextContent("ModLoadingException");
    expect(snippet).toHaveTextContent("ironchest");
  });

  it("copies snippet on Copy Snippet button click", async () => {
    const user = userEvent.setup();
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={vi.fn()}
        reports={sampleReports}
      />
    );

    const copyBtn = screen.getByRole("button", { name: /Copy Snippet/i });
    await user.click(copyBtn);

    expect(mockCopy).toHaveBeenCalledWith(
      sampleReports[0].stack_trace_snippet,
      "Stack trace snippet copied!"
    );
  });

  it("toggles full crash report viewer and copies full content", async () => {
    const user = userEvent.setup();
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={vi.fn()}
        reports={sampleReports}
      />
    );

    expect(screen.queryByTestId("full-crash-content")).not.toBeInTheDocument();

    const toggleBtn = screen.getByRole("button", { name: /View Full Crash Report/i });
    await user.click(toggleBtn);

    const fullContent = screen.getByTestId("full-crash-content");
    expect(fullContent).toBeInTheDocument();
    expect(fullContent).toHaveTextContent("---- Minecraft Crash Report ----");

    const copyFullBtn = screen.getByRole("button", { name: /Copy Full Report/i });
    await user.click(copyFullBtn);

    expect(mockCopy).toHaveBeenCalledWith(
      sampleReports[0].raw_content,
      "Full crash report copied!"
    );
  });

  it("switches report when clicking report selector button", async () => {
    const user = userEvent.setup();
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={vi.fn()}
        reports={sampleReports}
      />
    );

    // Switch to second report (MEMORY_EXHAUSTED)
    const secondReportBtn = screen.getByRole("button", {
      name: sampleReports[1].filename,
    });
    await user.click(secondReportBtn);

    expect(screen.getByTestId("failure-code-badge")).toHaveTextContent("MEMORY_EXHAUSTED");
    expect(screen.queryByTestId("blamed-mod-callout")).not.toBeInTheDocument();
    expect(
      screen.getByText("Increase -Xmx in launch config or reduce world size")
    ).toBeInTheDocument();
  });

  it("calls onClose when Close button or ESC key is pressed", async () => {
    const user = userEvent.setup();
    const handleClose = vi.fn();
    render(
      <CrashReportViewerModal
        isOpen={true}
        onClose={handleClose}
        reports={sampleReports}
      />
    );

    const closeBtn = screen.getByRole("button", { name: "Close" });
    await user.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(handleClose).toHaveBeenCalledTimes(2);
  });
});
