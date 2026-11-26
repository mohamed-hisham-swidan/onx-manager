import { useId } from "react";

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fillColor?: string;
  minDomain?: number;
  maxDomain?: number;
}

export function Sparkline({
  data,
  width = 120,
  height = 32,
  color = "var(--accent-primary)",
  fillColor,
  minDomain,
  maxDomain,
}: SparklineProps) {
  const gradId = `sparkline-grad-${useId().replace(/:/g, "")}`;

  if (data.length < 2) return <div style={{ width, height }} />;

  const min = minDomain !== undefined ? minDomain : Math.min(...data);
  const max = maxDomain !== undefined ? Math.max(maxDomain, min + 1e-6) : Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);

  const points = data.map((v, i) => {
    const normalized = Math.max(0, Math.min(1, (v - min) / range));
    const y = height - normalized * (height - 4) - 2;
    return `${(i * stepX).toFixed(2)},${y.toFixed(2)}`;
  });
  const line = points.join(" ");
  const area = `0,${height} ${line} ${width},${height}`;

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="overflow-visible"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={fillColor ?? `url(#${gradId})`} />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
