import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { StatusOverviewCards } from "./StatusOverviewCards";
import type { ServerResponse } from "@/server_manager/types";

function renderCards(counts: Record<string, number>, servers: ServerResponse[] = []) {
  return render(
    <MemoryRouter>
      <StatusOverviewCards counts={counts} servers={servers} />
    </MemoryRouter>,
  );
}

const mockServers: ServerResponse[] = [
  {
    server_id: "srv-online-1",
    name: "Survival Alpha",
    server_type: "paper",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    created_at: "",
    updated_at: "",
  },
  {
    server_id: "srv-stopped-1",
    name: "Creative Flat",
    server_type: "vanilla",
    minecraft_version: "1.21",
    status: "stopped",
    group_id: "default",
    port: 25566,
    motd: "",
    max_players: 10,
    gamemode: "creative",
    difficulty: "peaceful",
    created_at: "",
    updated_at: "",
  },
  {
    server_id: "srv-starting-1",
    name: "Minigames Lobby",
    server_type: "velocity",
    minecraft_version: "1.21.4",
    status: "starting",
    group_id: "default",
    port: 25577,
    motd: "",
    max_players: 100,
    gamemode: "adventure",
    difficulty: "easy",
    created_at: "",
    updated_at: "",
  },
  {
    server_id: "srv-crashed-1",
    name: "Modded Hardcore",
    server_type: "fabric",
    minecraft_version: "1.20.1",
    status: "crashed",
    group_id: "default",
    port: 25568,
    motd: "",
    max_players: 5,
    gamemode: "survival",
    difficulty: "hard",
    created_at: "",
    updated_at: "",
  },
];

describe("StatusOverviewCards", () => {
  it("renders the 3 main cards: Fleet Status, Active Operations, and System Health", () => {
    renderCards({});
    expect(screen.getByRole("region", { name: "Fleet Status" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Active Operations" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "System Health" })).toBeInTheDocument();
  });

  describe("Card 1: Fleet Status (Online / Offline / Total)", () => {
    it("renders zero values when counts are empty", () => {
      renderCards({});
      expect(screen.getByRole("link", { name: "0 Total" })).toHaveAttribute("href", "/servers");
      expect(screen.getByRole("link", { name: "0 Online" })).toHaveAttribute("href", "/servers?status=running");
      expect(screen.getByRole("link", { name: "0 Offline" })).toHaveAttribute("href", "/servers?status=stopped");
    });

    it("renders accurate counts and links for online and offline servers", () => {
      renderCards({ running: 5, stopped: 3, created: 2 });
      expect(screen.getByRole("link", { name: "10 Total" })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "5 Online" })).toBeInTheDocument();
      // stopped (3) + created (2) = 5 offline
      expect(screen.getByRole("link", { name: "5 Offline" })).toBeInTheDocument();
    });
  });

  describe("Card 2: Active Operations (Starting, Stopping, Installing, Restoring)", () => {
    it("renders Idle state when no transitions are active and hides card on mobile", () => {
      renderCards({});
      const activeOpsRegion = screen.getByRole("region", { name: "Active Operations" });
      expect(activeOpsRegion).toHaveClass("hidden");
      expect(activeOpsRegion).toHaveClass("md:flex");
      expect(screen.getByText("Idle")).toBeInTheDocument();
      expect(screen.getByText("Fleet Stable")).toBeInTheDocument();
      expect(screen.getByText("0 starting, stopping, or installing")).toBeInTheDocument();
    });

    it("displays in-flight operations with live tags and server name when servers are transitioning (visible on mobile)", () => {
      renderCards(
        { starting: 1, stopping: 2, provisioning: 1 },
        mockServers,
      );
      const activeOpsRegion = screen.getByRole("region", { name: "Active Operations" });
      expect(activeOpsRegion).not.toHaveClass("hidden");
      expect(activeOpsRegion).toHaveClass("flex");
      expect(screen.getByText("4 In-Flight")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "1 Starting" })).toHaveAttribute("href", "/servers?status=starting");
      expect(screen.getByRole("link", { name: "2 Stopping" })).toHaveAttribute("href", "/servers?status=stopping");
      expect(screen.getByRole("link", { name: "1 Installing" })).toHaveAttribute("href", "/servers?status=provisioning");
      // Shows transitioning server name
      expect(screen.getByText("Minigames Lobby")).toBeInTheDocument();
    });
  });

  describe("Card 3: System Health & Problem Navigation", () => {
    it("renders Healthy operational state when there are 0 problems", () => {
      renderCards({ running: 2, stopped: 1 });
      expect(screen.getByText("Healthy")).toBeInTheDocument();
      expect(screen.getByText("All Systems Operational")).toBeInTheDocument();
      expect(screen.getByText("0 crashed or broken servers")).toBeInTheDocument();
    });

    it("displays problem alert and prominent CTA linking directly to inspect the broken server", () => {
      renderCards(
        { running: 1, stopped: 1, starting: 1, crashed: 1 },
        mockServers,
      );
      expect(screen.getByText("1 Attention Needed")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "1 Crashed" })).toHaveAttribute("href", "/servers?status=crashed");

      // Direct button to move/navigate to the broken server
      const inspectBtn = screen.getByRole("link", { name: /Inspect Modded Hardcore/i });
      expect(inspectBtn).toBeInTheDocument();
      expect(inspectBtn).toHaveAttribute("href", "/servers/srv-crashed-1");
    });

    it("links to filtered problem list when multiple problem servers exist", () => {
      const twoProblems: ServerResponse[] = [
        ...mockServers,
        {
          server_id: "srv-broken-2",
          name: "Broken World",
          server_type: "vanilla",
          minecraft_version: "1.21",
          status: "broken",
          group_id: "default",
          port: 25569,
          motd: "",
          max_players: 10,
          gamemode: "survival",
          difficulty: "easy",
          created_at: "",
          updated_at: "",
        },
      ];

      renderCards({ crashed: 1, broken: 1 }, twoProblems);
      expect(screen.getByText("2 Attention Needed")).toBeInTheDocument();
      // First problem in list is srv-crashed-1
      expect(screen.getByRole("link", { name: /Inspect Modded Hardcore/i })).toHaveAttribute(
        "href",
        "/servers/srv-crashed-1",
      );
    });

    it("falls back to status filter URL when server array is not provided", () => {
      renderCards({ broken: 2 });
      expect(screen.getByText("2 Attention Needed")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /View Problem Servers \(2\)/i })).toHaveAttribute(
        "href",
        "/servers?status=broken",
      );
    });
  });
});
