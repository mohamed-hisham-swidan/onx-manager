import React from "react";

export interface ServerBannerProps {
  seed: string;
  customBannerUrl?: string | null;
  height?: number | string;
  className?: string;
  children?: React.ReactNode;
}

// Deterministic seed number generator
function hashSeed(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

export const ServerBanner: React.FC<ServerBannerProps> = ({
  seed,
  customBannerUrl,
  height = 64,
  className = "",
  children,
}) => {
  const hash = hashSeed(seed || "onx-server");
  const variant = hash % 5;

  // Semantic gradient variants using CSS variables / semantic theme tokens
  const gradientStyles: React.CSSProperties[] = [
    // Deep obsidian with emerald aurora
    {
      background:
        "radial-gradient(ellipse at 80% 20%, var(--status-success-bg), transparent 60%), radial-gradient(ellipse at 20% 80%, var(--accent-primary) 0%, transparent 60%), var(--surface-page)",
    },
    // Purple / Purpur engine theme
    {
      background:
        "radial-gradient(ellipse at 70% 30%, var(--status-info-bg), transparent 60%), radial-gradient(ellipse at 30% 70%, var(--accent-primary) 0%, transparent 60%), var(--surface-page)",
    },
    // Amber / Twilight forge theme
    {
      background:
        "radial-gradient(ellipse at 60% 30%, var(--status-warning-bg), transparent 60%), radial-gradient(ellipse at 20% 80%, var(--status-info-bg) 0%, transparent 60%), var(--surface-page)",
    },
    // Cobalt command center theme
    {
      background:
        "radial-gradient(ellipse at 50% 10%, var(--accent-primary) 0%, transparent 70%), var(--surface-page)",
    },
    // Deep Void slate theme
    {
      background:
        "radial-gradient(ellipse at 90% 90%, var(--surface-hover), transparent 60%), radial-gradient(ellipse at 10% 20%, var(--surface-active), transparent 60%), var(--surface-page)",
    },
  ];

  return (
    <div
      className={`relative w-full overflow-hidden ${className}`}
      style={{
        height: typeof height === "number" ? `${height}px` : height,
        ...(customBannerUrl
          ? {
              backgroundImage: `url(${customBannerUrl})`,
              backgroundSize: "cover",
              backgroundPosition: "center",
            }
          : gradientStyles[variant]),
      }}
    >
      {/* Subtle grid pattern overlay */}
      <div
        className="absolute inset-0 opacity-15 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(var(--border-subtle) 1px, transparent 1px), linear-gradient(90deg, var(--border-subtle) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />

      {/* Bottom vignette to smoothly blend into the card body */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "linear-gradient(to top, var(--surface-card) 4%, rgba(0, 0, 0, 0.4) 60%, transparent 100%)",
        }}
      />

      {/* Floating Children (Status badges, engine pills) */}
      {children && <div className="relative h-full w-full p-3">{children}</div>}
    </div>
  );
};
