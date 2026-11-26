import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerCard } from "./ServerCard";
import type { ServerResponse } from "@/server_manager/types";

const runningServer: ServerResponse = {
  server_id: "srv-1",
  name: "Purpur Survival",
  server_type: "purpur",
  minecraft_version: "1.21.11",
  status: "running",
  group_id: "default",
  port: 25565,
  motd: "Welcome",
  max_players: 20,
  gamemode: "survival",
  difficulty: "normal",
  mode: "simple",
  max_memory_mb: 4096,
  uptime_seconds: 43980, // 12h 13m
  deployment_host: "172.17.0.2",
  icon_data_url: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

describe("ServerCard", () => {
  it("renders uptime outside Players cell, loader fallback icon, and non-bridge address", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ServerCard
            server={runningServer}
            telemetry={{
              players: 0,
              tps: 20.0,
              ramUsedMb: 1024,
              ramLimitMb: 4096,
              cpuPercent: 12.5,
              hasLiveMetrics: true,
            }}
            isDeleting={false}
            isBusy={false}
            isStartCooldown={false}
            copiedAddressId={null}
            canPower={true}
            onStart={vi.fn()}
            onStop={vi.fn()}
            onRestart={vi.fn()}
            onRetryProvisioning={vi.fn()}
            onCopyAddress={vi.fn()}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const card = screen.getByTestId("server-card-srv-1");
    expect(card).toHaveTextContent("1.21.11");
    expect(card).toHaveTextContent("Simple");
    expect(card).toHaveTextContent("0 / 20");
    expect(card).toHaveTextContent("20.0");
    expect(card).toHaveTextContent("localhost:25565");
    expect(card).not.toHaveTextContent("172.17.0.2");
    expect(screen.queryByRole("button", { name: /Delete/i })).not.toBeInTheDocument();

    // Uptime is placed in header metadata strip, not inside the Players label container
    const uptimeEl = screen.getByTestId("server-card-uptime");
    expect(uptimeEl).toHaveTextContent("Up 12h 13m");
    const playersLabel = screen.getByText("Players");
    expect(playersLabel.parentElement).not.toHaveTextContent("Up 12h 13m");

    // Neutral loader icon rendered instead of two-letter monogram
    const fallbackIcon = screen.getByTestId("server-icon-default");
    expect(fallbackIcon).toHaveAttribute("data-loader-icon", "purpur");
    expect(fallbackIcon).toHaveTextContent("");
  });
});
