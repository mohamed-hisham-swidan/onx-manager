import { describe, it, expect, afterEach } from "vitest";
import { resolveJoinAddress } from "./serversUtils";
import type { ServerResponse } from "@/server_manager/types";

function makeServer(overrides: Partial<ServerResponse> = {}): ServerResponse {
  return {
    server_id: "srv-1",
    name: "Test Server",
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
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

describe("resolveJoinAddress", () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, "location", {
      value: originalLocation,
      configurable: true,
    });
  });

  it("prefers public_address when present", () => {
    const result = resolveJoinAddress(
      makeServer({
        public_address: "play.example.gg:25565",
        deployment_host: "172.17.0.2",
      }),
    );
    expect(result).toEqual({
      address: "play.example.gg:25565",
      isPublic: true,
    });
  });

  it.each(["0.0.0.0", "::", "[::]", "*", "172.17.0.2", "172.18.4.12", "172.31.255.1", undefined])(
    "falls back to localhost:port locally when deployment_host is %s",
    (host) => {
      Object.defineProperty(window, "location", {
        value: { ...originalLocation, hostname: "localhost" },
        configurable: true,
      });

      const result = resolveJoinAddress(makeServer({ deployment_host: host, port: 25567 }));
      expect(result).toEqual({
        address: "localhost:25567",
        isPublic: false,
      });
    },
  );

  it("uses remote window.location.hostname when accessed over LAN/VPS and deployment_host is Docker bridge IP", () => {
    Object.defineProperty(window, "location", {
      value: { ...originalLocation, hostname: "panel.myvps.net" },
      configurable: true,
    });

    const result = resolveJoinAddress(
      makeServer({ deployment_host: "172.17.0.2", port: 25565 }),
    );
    expect(result).toEqual({
      address: "panel.myvps.net:25565",
      isPublic: false,
    });
  });

  it("preserves explicit non-bridge deployment_host", () => {
    const result = resolveJoinAddress(
      makeServer({ deployment_host: "192.168.1.50", port: 25566 }),
    );
    expect(result).toEqual({
      address: "192.168.1.50:25566",
      isPublic: false,
    });
  });
});
