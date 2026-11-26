import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Icon, type IconName } from "@/components/ui/Icon";

export interface ServerIconProps {
  serverId: string;
  name?: string;
  serverName?: string;
  serverType?: string;
  status?: string;
  iconDataUrl?: string | null;
  size?: number;
  className?: string;
}

function getLoaderGlyph(serverType?: string): IconName | null {
  switch ((serverType ?? "").trim().toLowerCase()) {
    case "paper":
    case "purpur":
    case "folia":
    case "fabric":
    case "forge":
    case "neoforge":
    case "quilt":
    case "spigot":
    case "bukkit":
    case "velocity":
    case "bungeecord":
    case "waterfall":
    case "vanilla":
      return (serverType ?? "").trim().toLowerCase() as IconName;
    default:
      return null;
  }
}

export function ServerIcon({
  serverId,
  name,
  serverName,
  serverType,
  iconDataUrl,
  size = 40,
  className = "",
}: ServerIconProps) {
  const displayName = serverName ?? name;
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);

  const shouldFallbackFetch = iconDataUrl === undefined && Boolean(serverId);

  const { data: blob, isError } = useQuery({
    queryKey: ["servers", serverId, "server-icon"],
    queryFn: () => api.downloadServerFile(serverId, "server-icon.png"),
    enabled: shouldFallbackFetch,
    retry: false,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (!shouldFallbackFetch || !blob) {
      return;
    }
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      return;
    }

    let isMounted = true;
    try {
      const url = URL.createObjectURL(blob);
      queueMicrotask(() => {
        if (isMounted) {
          setBlobUrl(url);
          setImgError(false);
        }
      });

      return () => {
        isMounted = false;
        if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
          URL.revokeObjectURL(url);
        }
      };
    } catch {
      queueMicrotask(() => {
        if (isMounted) {
          setImgError(true);
        }
      });
    }
  }, [blob, shouldFallbackFetch]);

  const directUrl = typeof iconDataUrl === "string" && iconDataUrl.trim().length > 0 ? iconDataUrl : null;
  const fetchedUrl = shouldFallbackFetch && blob ? blobUrl : null;
  const shownUrl = directUrl ?? fetchedUrl;
  const showDefault = imgError || (shouldFallbackFetch ? isError || !shownUrl : !directUrl);

  const loaderIconName: IconName = getLoaderGlyph(serverType) ?? "server";

  return (
    <div
      data-testid="server-icon"
      className={`relative shrink-0 ${className}`}
      style={{ width: size, height: size }}
      title={displayName ? `${displayName} icon` : undefined}
    >
      <div className="flex h-full w-full items-center justify-center overflow-hidden rounded-xl border border-border-subtle bg-surface-muted text-text-secondary">
        {showDefault ? (
          <span
            data-testid="server-icon-default"
            data-loader-icon={loaderIconName}
            className="flex h-full w-full items-center justify-center select-none"
          >
            <Icon
              name={loaderIconName}
              size={Math.round(size * 0.52)}
              aria-hidden="true"
            />
          </span>
        ) : (
          <img
            data-testid="server-icon-img"
            src={shownUrl ?? undefined}
            alt=""
            onError={() => setImgError(true)}
            className="h-full w-full object-cover"
            style={{ imageRendering: "pixelated" }}
          />
        )}
      </div>
    </div>
  );
}
