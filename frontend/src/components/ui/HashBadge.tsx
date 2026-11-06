import React, { useState } from "react";
import { Icon } from "./Icon";

export interface HashBadgeProps {
  hash: string;
  length?: number;
  copyable?: boolean;
  prefix?: string;
  className?: string;
}

export const HashBadge: React.FC<HashBadgeProps> = ({
  hash,
  length = 7,
  copyable = true,
  prefix = "#",
  className = "",
}) => {
  const [copied, setCopied] = useState(false);

  if (!hash) return null;

  const displayHash = `${prefix}${hash.slice(0, length)}`;

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!copyable) return;
    navigator.clipboard?.writeText(hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      disabled={!copyable}
      title={copyable ? (copied ? "Copied!" : `Full ID: ${hash} (click to copy)`) : hash}
      className={`group inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface-elevated px-2 py-0.5 font-mono text-[11px] tabular-nums text-text-secondary transition-colors ${
        copyable
          ? "cursor-pointer hover:border-border-default hover:bg-surface-hover hover:text-text-primary"
          : "cursor-default"
      } ${className}`}
    >
      <span>{copied ? "Copied!" : displayHash}</span>
      {copyable && !copied && (
        <Icon
          name="copy"
          size={12}
          className="text-text-muted opacity-60 transition-opacity group-hover:opacity-100"
        />
      )}
    </button>
  );
};
