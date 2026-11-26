import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerIcon } from "./ServerIcon";

const mockDownloadServerFile = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    downloadServerFile: (...args: unknown[]) => mockDownloadServerFile(...args),
  }),
}));

function renderComponent(props: { serverId: string; name?: string; size?: number }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ServerIcon {...props} />
    </QueryClientProvider>
  );
}

describe("ServerIcon", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    URL.createObjectURL = vi.fn(() => "blob:http://localhost/mock-icon-url");
    URL.revokeObjectURL = vi.fn();
  });

  it("renders default when fetch fails", async () => {
    mockDownloadServerFile.mockRejectedValue(new Error("404 Not Found"));

    renderComponent({ serverId: "srv-fail", name: "Alpha Server" });

    expect(await screen.findByTestId("server-icon-default")).toBeInTheDocument();
    expect(screen.queryByTestId("server-icon-img")).not.toBeInTheDocument();
  });

  it("renders default icon on 401, 403, or 404 response", async () => {
    mockDownloadServerFile.mockRejectedValue({ status: 404, message: "File not found" });

    renderComponent({ serverId: "srv-404", name: "Missing Icon Server" });

    expect(await screen.findByTestId("server-icon-default")).toBeInTheDocument();
    expect(screen.queryByTestId("server-icon-img")).not.toBeInTheDocument();
  });

  it("renders img when blob returns", async () => {
    const fakeBlob = new Blob(["fake-icon-content"], { type: "image/png" });
    mockDownloadServerFile.mockResolvedValue(fakeBlob);

    renderComponent({ serverId: "srv-ok", name: "Beta Server" });

    const img = await screen.findByTestId("server-icon-img");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "blob:http://localhost/mock-icon-url");
    expect(img).toHaveAttribute("alt", "");
    expect(img.style.imageRendering).toBe("pixelated");
    expect(screen.queryByTestId("server-icon-default")).not.toBeInTheDocument();
  });

  it("revokes object URL on unmount", async () => {
    const fakeBlob = new Blob(["fake-icon-content"], { type: "image/png" });
    mockDownloadServerFile.mockResolvedValue(fakeBlob);

    const { unmount } = renderComponent({ serverId: "srv-unmount", name: "Unmount Server" });

    await screen.findByTestId("server-icon-img");
    expect(URL.createObjectURL).toHaveBeenCalledWith(fakeBlob);

    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:http://localhost/mock-icon-url");
  });

  it("renders direct iconDataUrl without calling downloadServerFile", async () => {
    const dataUrl = "data:image/png;base64,iVBORw0KGgo=";
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ServerIcon
          serverId="srv-direct"
          serverName="Direct Icon"
          iconDataUrl={dataUrl}
          status="running"
          size={52}
        />
      </QueryClientProvider>
    );

    const img = await screen.findByTestId("server-icon-img");
    expect(img).toHaveAttribute("src", dataUrl);
    expect(mockDownloadServerFile).not.toHaveBeenCalled();
  });

  it("renders neutral loader emblem fallback when iconDataUrl is null without fetching or monogram", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ServerIcon
          serverId="srv-null"
          serverName="Alpha World"
          serverType="paper"
          iconDataUrl={null}
          status="running"
          size={52}
        />
      </QueryClientProvider>
    );

    const fallback = screen.getByTestId("server-icon-default");
    expect(fallback).toBeInTheDocument();
    expect(fallback).toHaveAttribute("data-loader-icon", "paper");
    expect(fallback).toHaveTextContent("");
    expect(fallback).not.toHaveTextContent("AW");
    expect(mockDownloadServerFile).not.toHaveBeenCalled();
  });

  it("falls back to generic server icon when serverType is unknown", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ServerIcon
          serverId="srv-unknown"
          serverName="Custom Proxy"
          serverType="custom-unknown"
          iconDataUrl={null}
          status="stopped"
          size={48}
        />
      </QueryClientProvider>
    );

    const fallback = screen.getByTestId("server-icon-default");
    expect(fallback).toHaveAttribute("data-loader-icon", "server");
    expect(fallback).toHaveTextContent("");
  });
});
