export type AddressKind = "playit" | "cloudflare" | "local" | null;

export interface ResolvedAddress {
  address: string | null;
  kind: AddressKind;
}

export function resolveAccessAddress(
  server: { deployment_host?: string | null; deployment_port?: number | null; port: number },
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

  if (server.deployment_host) {
    return {
      address: `${server.deployment_host}:${server.deployment_port ?? server.port}`,
      kind: "local",
    };
  }

  return {
    address: null,
    kind: null,
  };
}
