export interface BrandLogoProps {
  variant?: "full" | "mark" | "wordmark";
  size?: "sm" | "md" | "lg" | number;
  className?: string;
  "aria-label"?: string;
  "aria-hidden"?: boolean;
}

const SIZES = {
  sm: { height: 24, markSize: 24, fontSize: 14 },
  md: { height: 32, markSize: 32, fontSize: 18 },
  lg: { height: 48, markSize: 48, fontSize: 24 },
};

function BrandMarkSvg({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0"
      aria-hidden="true"
    >
      <rect width="64" height="64" rx="16" fill="var(--brand-mark-2)" />
      <g fill="none" strokeWidth="5.5" strokeLinecap="round" stroke="var(--brand-mark-1)">
        <path d="M12 12 L52 52" />
        <path d="M52 12 L12 52" />
      </g>
      <circle
        cx="32"
        cy="32"
        r="13"
        fill="var(--brand-mark-2)"
        stroke="var(--brand-mark-1)"
        strokeWidth="5.5"
      />
    </svg>
  );
}

function Wordmark({ fontSize }: { fontSize: number }) {
  return (
    <div className="flex items-baseline tracking-tight select-none">
      <span
        className="font-black uppercase tracking-wider text-[var(--brand-ink)]"
        style={{ fontSize }}
      >
        ONX
      </span>
      <span
        className="ml-1.5 font-light text-[var(--brand-ink)] opacity-85"
        style={{ fontSize: fontSize * 0.9 }}
      >
        Manager
      </span>
      <span className="sr-only">onx-manager</span>
    </div>
  );
}

export function BrandLogo({
  variant = "full",
  size = "md",
  className = "",
  "aria-label": ariaLabel,
  "aria-hidden": ariaHidden,
}: BrandLogoProps) {
  const dimensions =
    typeof size === "number"
      ? { height: size, markSize: size, fontSize: size * 0.55 }
      : SIZES[size];

  if (variant === "mark") {
    return (
      <div
        className={`inline-flex items-center justify-center ${className}`}
        role="img"
        aria-label={ariaLabel || "ONX Manager"}
        aria-hidden={ariaHidden}
        title="ONX Manager"
      >
        <BrandMarkSvg size={dimensions.markSize} />
        <span className="sr-only">onx-manager</span>
      </div>
    );
  }

  if (variant === "wordmark") {
    return (
      <div
        className={`inline-flex items-center ${className}`}
        role="img"
        aria-label={ariaLabel || "ONX Manager"}
        aria-hidden={ariaHidden}
      >
        <Wordmark fontSize={dimensions.fontSize} />
      </div>
    );
  }

  // Full variant (mark + wordmark)
  return (
    <div
      className={`inline-flex items-center gap-2.5 ${className}`}
      role="img"
      aria-label={ariaLabel || "ONX Manager"}
      aria-hidden={ariaHidden}
    >
      <BrandMarkSvg size={dimensions.markSize} />
      <Wordmark fontSize={dimensions.fontSize} />
    </div>
  );
}
