/**
 * ONX Manager Brand Logo (Phase 7)
 *
 * Official SVG brand wordmark and abstract swirl/vortex mark.
 * Designed with pure geometric curves and clean typography.
 * Themed via currentColor and semantic design tokens.
 * Zero external font or image dependencies.
 */

export interface BrandLogoProps {
  variant?: "full" | "mark" | "wordmark";
  size?: "sm" | "md" | "lg" | number;
  monochrome?: boolean;
  className?: string;
}

const SIZES = {
  sm: { height: 24, markSize: 24, fontSize: 14 },
  md: { height: 32, markSize: 32, fontSize: 18 },
  lg: { height: 48, markSize: 48, fontSize: 24 },
};

// Abstract Geometric Vortex / Swirl Mark
function VortexMark({ size, monochrome }: { size: number; monochrome?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="onx-vortex-grad-1" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="var(--accent-primary, #2563eb)" />
          <stop offset="100%" stopColor="var(--border-focus, #60a5fa)" />
        </linearGradient>
        <linearGradient id="onx-vortex-grad-2" x1="40" y1="0" x2="0" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="var(--text-accent, #38bdf8)" />
          <stop offset="100%" stopColor="var(--accent-primary, #2563eb)" />
        </linearGradient>
      </defs>

      {/* Central Singularity Core */}
      <circle
        cx="20"
        cy="20"
        r="3.5"
        fill={monochrome ? "currentColor" : "url(#onx-vortex-grad-1)"}
      />

      {/* Arm 1 - North-East Inward Spiral */}
      <path
        d="M20 4C28.8366 4 36 11.1634 36 20C36 23.5 34.5 27 32 29.5C29.5 32 26 33 22 32C17 31 15 26 18 22C20 19 24 19 25 21C26 23 24 25 22 25"
        stroke={monochrome ? "currentColor" : "url(#onx-vortex-grad-1)"}
        strokeWidth="3.2"
        strokeLinecap="round"
        fill="none"
      />

      {/* Arm 2 - South-West Counter Spiral */}
      <path
        d="M20 36C11.1634 36 4 28.8366 4 20C4 16.5 5.5 13 8 10.5C10.5 8 14 7 18 8C23 9 25 14 22 18C20 21 16 21 15 19C14 17 16 15 18 15"
        stroke={monochrome ? "currentColor" : "url(#onx-vortex-grad-2)"}
        strokeWidth="3.2"
        strokeLinecap="round"
        fill="none"
        opacity={monochrome ? 0.75 : 0.9}
      />

      {/* Arm 3 - Orbital Particle Nodes */}
      <circle cx="20" cy="4" r="2" fill={monochrome ? "currentColor" : "var(--accent-hover, #1d4ed8)"} />
      <circle cx="20" cy="36" r="2" fill={monochrome ? "currentColor" : "var(--text-accent, #38bdf8)"} />
      <circle cx="4" cy="20" r="1.5" fill="currentColor" opacity="0.6" />
      <circle cx="36" cy="20" r="1.5" fill="currentColor" opacity="0.6" />
    </svg>
  );
}

// Clean Geometric Wordmark Typography
function Wordmark({ fontSize }: { fontSize: number }) {
  return (
    <div className="flex items-baseline tracking-tight select-none">
      <span className="font-black text-text-primary uppercase tracking-wider" style={{ fontSize }}>
        ONX
      </span>
      <span className="ml-1.5 font-light text-text-secondary" style={{ fontSize: fontSize * 0.9 }}>
        Manager
      </span>
      <span className="sr-only">onx-manager</span>
    </div>
  );
}

export function BrandLogo({
  variant = "full",
  size = "md",
  monochrome = false,
  className = "",
}: BrandLogoProps) {
  const dimensions = typeof size === "number" ? { height: size, markSize: size, fontSize: size * 0.55 } : SIZES[size];

  if (variant === "mark") {
    return (
      <div className={`inline-flex items-center justify-center ${className}`} title="ONX Manager">
        <VortexMark size={dimensions.markSize} monochrome={monochrome} />
      </div>
    );
  }

  if (variant === "wordmark") {
    return (
      <div className={`inline-flex items-center ${className}`}>
        <Wordmark fontSize={dimensions.fontSize} />
      </div>
    );
  }

  // Full lockup
  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`}>
      <VortexMark size={dimensions.markSize} monochrome={monochrome} />
      <Wordmark fontSize={dimensions.fontSize} />
    </div>
  );
}
