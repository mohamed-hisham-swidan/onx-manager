import { describe, it, expect } from "vitest";
import { resolveAccessAddress } from "./accessAddress";

describe("resolveAccessAddress", () => {
  it("returns playit address when exposure is ENABLED and ACTIVE", () => {
    const res = resolveAccessAddress(
      { deployment_host: "127.0.0.1", deployment_port: 25565, port: 25565 },
      {
        desired_state: "ENABLED",
        aggregate_status: "ACTIVE",
        method: "playit",
        targets: [{ public_address: "survival.ply.gg:12345" }],
      },
    );
    expect(res).toEqual({
      address: "survival.ply.gg:12345",
      kind: "playit",
    });
  });

  it("returns cloudflare address when exposure method is cloudflare_tcp and ACTIVE", () => {
    const res = resolveAccessAddress(
      { deployment_host: "127.0.0.1", deployment_port: 25565, port: 25565 },
      {
        desired_state: "ENABLED",
        aggregate_status: "ACTIVE",
        method: "cloudflare_tcp",
        targets: [{ public_address: "mc.example.com" }],
      },
    );
    expect(res).toEqual({
      address: "mc.example.com",
      kind: "cloudflare",
    });
  });

  it("falls back to local when exposure is ENABLED but not ACTIVE", () => {
    const res = resolveAccessAddress(
      { deployment_host: "192.168.1.100", deployment_port: null, port: 25565 },
      {
        desired_state: "ENABLED",
        aggregate_status: "STARTING",
        method: "playit",
        targets: [{ public_address: "survival.ply.gg:12345" }],
      },
    );
    expect(res).toEqual({
      address: "192.168.1.100:25565",
      kind: "local",
    });
  });

  it("falls back to local when exposure target has no public_address", () => {
    const res = resolveAccessAddress(
      { deployment_host: "10.0.0.5", deployment_port: 25570, port: 25565 },
      {
        desired_state: "ENABLED",
        aggregate_status: "ACTIVE",
        method: "playit",
        targets: [{ public_address: null }],
      },
    );
    expect(res).toEqual({
      address: "10.0.0.5:25570",
      kind: "local",
    });
  });

  it("returns local address when exposure is null/undefined", () => {
    const res = resolveAccessAddress(
      { deployment_host: "192.168.1.50", deployment_port: 25565, port: 25565 },
      null,
    );
    expect(res).toEqual({
      address: "192.168.1.50:25565",
      kind: "local",
    });
  });

  it("returns null address and kind when no deployment host is set and exposure is not active", () => {
    const res = resolveAccessAddress(
      { deployment_host: null, deployment_port: null, port: 25565 },
      null,
    );
    expect(res).toEqual({
      address: null,
      kind: null,
    });
  });

  it("filters Docker bridge IPs (172.16-31.x.x) and wildcard 0.0.0.0 to browser host fallback", () => {
    expect(
      resolveAccessAddress(
        { deployment_host: "172.17.0.5", deployment_port: 25565, port: 25565 },
        null,
      ),
    ).toEqual({
      address: "localhost:25565",
      kind: "local",
    });

    expect(
      resolveAccessAddress(
        { deployment_host: "0.0.0.0", deployment_port: null, port: 25570 },
        null,
      ),
    ).toEqual({
      address: "localhost:25570",
      kind: "local",
    });
  });

  it("uses server.public_address when exposure query is absent", () => {
    expect(
      resolveAccessAddress(
        {
          deployment_host: "172.17.0.5",
          deployment_port: 25565,
          public_address: "play.example.gg:25565",
          port: 25565,
        },
        null,
      ),
    ).toEqual({
      address: "play.example.gg:25565",
      kind: "cloudflare",
    });
  });
});
