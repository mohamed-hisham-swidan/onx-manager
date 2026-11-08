import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";

export interface ServerIconProps {
  serverId: string;
  name?: string;
  size?: number;
  className?: string;
}

export function ServerIcon({
  serverId,
  name,
  size = 40,
  className = "",
}: ServerIconProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);

  const { data: blob, isError } = useQuery({
    queryKey: ["servers", serverId, "server-icon"],
    queryFn: () => api.downloadServerFile(serverId, "server-icon.png"),
    retry: false,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (!blob) {
      setImageUrl(null);
      return;
    }
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      return;
    }

    try {
      const url = URL.createObjectURL(blob);
      setImageUrl(url);
      setImgError(false);

      return () => {
        if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
          URL.revokeObjectURL(url);
        }
        setImageUrl(null);
      };
    } catch {
      setImgError(true);
    }
  }, [blob]);

  const showDefault = isError || imgError || !imageUrl;

  return (
    <div
      data-testid="server-icon"
      className={`relative flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-muted ${className}`}
      style={{ width: size, height: size }}
      title={name ? `${name} icon` : undefined}
    >
      {showDefault ? (
        <span data-testid="server-icon-default" className="flex items-center justify-center">
          <Icon
            name="server"
            size={Math.round(size * 0.55)}
            className="text-text-muted"
            aria-hidden="true"
          />
        </span>
      ) : (
        <img
          data-testid="server-icon-img"
          src={imageUrl}
          alt=""
          onError={() => setImgError(true)}
          className="h-full w-full object-cover"
          style={{ imageRendering: "pixelated" }}
        />
      )}
    </div>
  );
}
