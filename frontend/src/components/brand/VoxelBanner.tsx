/**
 * ONX Manager Abstract Voxel Banner (Phase 7)
 *
 * Original abstract pixel/voxel visual art built strictly from geometric cubes
 * and crisp grid rects (shapeRendering="crispEdges").
 *
 * NON-NEGOTIABLE IP GUARDRAIL:
 * Pure original abstract geometry only. Zero Mojang/Minecraft IP (no creeper faces,
 * no grass block textures, no swords, no ores, no look-alike elements).
 * Fully themed via CSS currentColor and semantic design tokens.
 */

export interface VoxelBannerProps {
  variant?: "dashboard" | "auth" | "empty";
  className?: string;
}

export function VoxelBanner({ variant = "dashboard", className = "" }: VoxelBannerProps) {
  if (variant === "auth") {
    // Compact abstract voxel cluster for login and registration headers
    return (
      <svg
        viewBox="0 0 160 80"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        shapeRendering="crispEdges"
        className={`w-full max-w-[200px] h-auto mx-auto ${className}`}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="vb-auth-grad" x1="0" y1="0" x2="160" y2="80" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--accent-primary, #2563eb)" stopOpacity="0.8" />
            <stop offset="100%" stopColor="var(--text-accent, #38bdf8)" stopOpacity="0.4" />
          </linearGradient>
        </defs>

        {/* Base Grid Platform */}
        <g opacity="0.35" fill="currentColor">
          <rect x="50" y="55" width="60" height="4" />
          <rect x="40" y="59" width="80" height="4" />
          <rect x="60" y="63" width="40" height="3" />
        </g>

        {/* Tier 1 Voxel Layer */}
        <g fill="currentColor" opacity="0.2">
          <rect x="64" y="44" width="32" height="10" />
          <rect x="56" y="40" width="16" height="12" />
          <rect x="88" y="42" width="16" height="10" />
        </g>

        {/* Tier 2 Voxel Stratum */}
        <g fill="currentColor" opacity="0.4">
          <rect x="68" y="32" width="24" height="12" />
          <rect x="60" y="30" width="12" height="10" />
          <rect x="88" y="34" width="12" height="8" />
        </g>

        {/* Tier 3 Voxel Monolith Apex */}
        <g fill="url(#vb-auth-grad)">
          <rect x="72" y="18" width="16" height="14" />
          <rect x="76" y="10" width="8" height="8" />
        </g>

        {/* Orbiting Geometric Spark Voxels */}
        <rect x="48" y="24" width="4" height="4" fill="var(--accent-primary, #2563eb)" opacity="0.9" />
        <rect x="108" y="20" width="5" height="5" fill="var(--border-focus, #60a5fa)" opacity="0.85" />
        <rect x="118" y="36" width="3" height="3" fill="currentColor" opacity="0.5" />
        <rect x="38" y="38" width="3" height="3" fill="currentColor" opacity="0.5" />
      </svg>
    );
  }

  if (variant === "empty") {
    // Solitary floating geometric voxel core for EmptyState cards
    return (
      <svg
        viewBox="0 0 120 120"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        shapeRendering="crispEdges"
        className={`w-28 h-28 mx-auto ${className}`}
        aria-hidden="true"
      >
        {/* Isometric Cube 1 - Main Core */}
        {/* Top Face */}
        <polygon points="60,20 90,35 60,50 30,35" fill="var(--accent-primary, #2563eb)" opacity="0.75" />
        {/* Left Face */}
        <polygon points="30,35 60,50 60,85 30,70" fill="currentColor" opacity="0.35" />
        {/* Right Face */}
        <polygon points="60,50 90,35 90,70 60,85" fill="currentColor" opacity="0.55" />

        {/* Floating Mini Satellite Voxels */}
        <polygon points="98,15 110,21 98,27 86,21" fill="var(--border-focus, #60a5fa)" opacity="0.9" />
        <polygon points="86,21 98,27 98,37 86,31" fill="currentColor" opacity="0.4" />
        <polygon points="98,27 110,21 110,31 98,37" fill="currentColor" opacity="0.6" />

        <polygon points="22,75 32,80 22,85 12,80" fill="var(--accent-primary, #2563eb)" opacity="0.6" />
        <polygon points="12,80 22,85 22,93 12,88" fill="currentColor" opacity="0.3" />
        <polygon points="22,85 32,80 32,88 22,93" fill="currentColor" opacity="0.5" />

        {/* Ground Projection Shadow */}
        <ellipse cx="60" cy="104" rx="36" ry="8" fill="currentColor" opacity="0.08" />
      </svg>
    );
  }

  // Dashboard Wide Panoramic Voxel Horizon
  return (
    <div className={`relative overflow-hidden rounded-xl border border-border-subtle bg-gradient-to-r from-surface-card via-surface-elevated to-surface-card ${className}`}>
      <svg
        viewBox="0 0 960 140"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        shapeRendering="crispEdges"
        preserveAspectRatio="xMidYMid slice"
        className="w-full h-28 sm:h-32 text-text-primary opacity-60 dark:opacity-40 select-none pointer-events-none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="vb-dash-core" x1="400" y1="20" x2="560" y2="120" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--accent-primary, #2563eb)" stopOpacity="0.6" />
            <stop offset="100%" stopColor="var(--border-focus, #60a5fa)" stopOpacity="0.15" />
          </linearGradient>
        </defs>

        {/* Ambient Grid Lines */}
        <g stroke="currentColor" strokeWidth="1" opacity="0.15">
          <line x1="0" y1="40" x2="960" y2="40" />
          <line x1="0" y1="80" x2="960" y2="80" />
          <line x1="0" y1="120" x2="960" y2="120" />
          <line x1="160" y1="0" x2="160" y2="140" />
          <line x1="320" y1="0" x2="320" y2="140" />
          <line x1="480" y1="0" x2="480" y2="140" />
          <line x1="640" y1="0" x2="640" y2="140" />
          <line x1="800" y1="0" x2="800" y2="140" />
        </g>

        {/* Background Mountainous Voxel Silhouettes */}
        <g fill="currentColor" opacity="0.12">
          <rect x="40" y="60" width="80" height="80" />
          <rect x="70" y="44" width="40" height="96" />
          <rect x="180" y="70" width="60" height="70" />
          <rect x="740" y="50" width="90" height="90" />
          <rect x="770" y="35" width="45" height="105" />
          <rect x="850" y="65" width="70" height="75" />
        </g>

        {/* Mid-Ground Voxel Ridge & Strata */}
        <g fill="currentColor" opacity="0.22">
          <rect x="100" y="80" width="120" height="60" />
          <rect x="130" y="68" width="60" height="72" />
          <rect x="260" y="90" width="100" height="50" />
          <rect x="620" y="85" width="110" height="55" />
          <rect x="690" y="72" width="70" height="68" />
        </g>

        {/* Center Floating Voxel Island & Citadel Formation */}
        <g fill="url(#vb-dash-core)">
          <rect x="420" y="88" width="120" height="52" />
          <rect x="440" y="72" width="80" height="68" />
          <rect x="460" y="56" width="40" height="84" />
          <rect x="472" y="38" width="16" height="102" />
          <rect x="476" y="26" width="8" height="114" />
        </g>

        {/* Floating Data Spire Nodes */}
        <rect x="360" y="48" width="8" height="8" fill="var(--accent-primary, #2563eb)" opacity="0.8" />
        <rect x="362" y="56" width="4" height="24" fill="var(--accent-primary, #2563eb)" opacity="0.5" />
        <rect x="590" y="42" width="10" height="10" fill="var(--border-focus, #60a5fa)" opacity="0.75" />
        <rect x="594" y="52" width="2" height="30" fill="var(--border-focus, #60a5fa)" opacity="0.4" />

        {/* Atmospheric Floating Dust / Star Pixels */}
        <rect x="220" y="24" width="3" height="3" fill="currentColor" opacity="0.5" />
        <rect x="290" y="36" width="4" height="4" fill="currentColor" opacity="0.4" />
        <rect x="670" y="28" width="4" height="4" fill="currentColor" opacity="0.5" />
        <rect x="730" y="18" width="3" height="3" fill="currentColor" opacity="0.4" />
      </svg>
    </div>
  );
}
