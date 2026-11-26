export type AddressKind = "playit" | "cloudflare" | "local" | null;

export interface ResolvedAddress {
  address: string | null;
  kind: AddressKind;
}

const DOCKER_BRIDGE_IPV4_RE = /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/;

export function isUnplayableDockerOrWildcardHost(host?: string | null): boolean {
  if (!host) return true;
  const trimmed = host.trim();
  if (!trimmed) return true;
  if (trimmed === "0.0.0.0" || trimmed === "::" || trimmed === "[::]" || trimmed === "*") {
    return true;
  }
  return DOCKER_BRIDGE_IPV4_RE.test(trimmed);
}

function resolveBrowserFallbackHost(): string {
  if (typeof window !== "undefined") {
    const hostname = window.location?.hostname?.trim();
    if (
      hostname &&
      hostname !== "localhost" &&
      hostname !== "127.0.0.1" &&
      hostname !== "::1" &&
      hostname !== "[::1]"
    ) {
      return hostname;
    }
  }
  return "localhost";
}

export function resolveAccessAddress(
  server: {
    deployment_host?: string | null;
    deployment_port?: number | null;
    public_address?: string | null;
    port: number;
  },
  exposure?: {
    desired_state?: string;
    aggregate_status?: string;
    method?: string;
    targets?: Array<{ public_address: string | null }>;
  } | null,
): ResolvedAddress {
  if (
    exposure?.desired_state === "ENABLED" &&
    exposure.aggregate_status === "ACTIVE" &&
    exposure.targets?.[0]?.public_address
  ) {
    const kind: AddressKind =
      exposure.method === "cloudflare_tcp" || exposure.method?.startsWith("cloudflare")
        ? "cloudflare"
        : "playit";
    return {
      address: exposure.targets[0].public_address,
      kind,
    };
  }

  const serverPublic = server.public_address?.trim();
  if (serverPublic) {
    return {
      address: serverPublic,
      kind: serverPublic.includes(".ply.gg") ? "playit" : "cloudflare",
    };
  }

  if (server.deployment_host) {
    const host = isUnplayableDockerOrWildcardHost(server.deployment_host)
      ? resolveBrowserFallbackHost()
      : server.deployment_host.trim();
    return {
      address: `${host}:${server.deployment_port ?? server.port}`,
      kind: "local",
    };
  }

  return {
    address: null,
    kind: null,
  };
}
