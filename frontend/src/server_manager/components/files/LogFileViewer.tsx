import React, { useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/States";
import { useClipboard } from "@/hooks/useClipboard";
import { formatBytes } from "@/server_manager/utils/format";
import {
  getLevelTagClass,
  getLevelTextClass,
  parseConsoleLine,
  tokenizeConsoleLine,
  type ConsoleLevelFilter,
} from "@/server_manager/components/console/consoleLogParser";
import type { FileContentResponse, FileItem } from "@/server_manager/types";
import { extractApiErrorMessage } from "./filesUtils";

export interface LogFileViewerProps {
  file: FileItem;
  contentResponse?: FileContentResponse | null;
  isLoading: boolean;
  error: unknown;
  compact?: boolean;
  onRetry: () => void;
  onClose: () => void;
  onDownload: (file: FileItem) => void;
}

function renderHighlightedText(text: string, query: string): ReactNode {
  const trimmed = query.trim();
  if (!trimmed) return text;

  const lowerText = text.toLowerCase();
  const lowerQuery = trimmed.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let matchIdx = lowerText.indexOf(lowerQuery, cursor);
  let keyIdx = 0;

  while (matchIdx !== -1) {
    if (matchIdx > cursor) {
      parts.push(text.slice(cursor, matchIdx));
    }
    parts.push(
      <mark
        key={keyIdx++}
        className="bg-terminal-highlight-bg text-terminal-text rounded-xs px-0.5"
      >
        {text.slice(matchIdx, matchIdx + trimmed.length)}
      </mark>,
    );
    cursor = matchIdx + trimmed.length;
    matchIdx = lowerText.indexOf(lowerQuery, cursor);
  }

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts.length > 0 ? parts : text;
}

export const LogFileViewer: React.FC<LogFileViewerProps> = ({
  file,
  contentResponse,
  isLoading,
  error,
  compact = false,
  onRetry,
  onClose,
  onDownload,
}) => {
  const viewportRef = useRef<HTMLDivElement>(null);
  const { copy } = useClipboard();
  const [searchQuery, setSearchQuery] = useState("");
  const [levelFilter, setLevelFilter] = useState<ConsoleLevelFilter>("all");

  const [prevPath, setPrevPath] = useState(file.path);
  if (file.path !== prevPath) {
    setPrevPath(file.path);
    setSearchQuery("");
    setLevelFilter("all");
  }

  const rawLines = useMemo(() => {
    const content = contentResponse?.content;
    if (!content) return [];
    const lines = content.replace(/\r\n/g, "\n").split("\n");
    if (lines.length > 0 && lines[lines.length - 1] === "") {
      lines.pop();
    }
    return lines;
  }, [contentResponse?.content]);

  const parsedLines = useMemo(
    () => rawLines.map((raw, idx) => parseConsoleLine(raw, idx)),
    [rawLines],
  );

  const levelCounts = useMemo(() => {
    let info = 0;
    let warn = 0;
    let errorCount = 0;
    for (const entry of parsedLines) {
      if (entry.level === "info") info++;
      else if (entry.level === "warn") warn++;
      else if (entry.level === "error") errorCount++;
    }
    return { all: parsedLines.length, info, warn, error: errorCount };
  }, [parsedLines]);

  const filteredLines = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return parsedLines.filter((entry) => {
      if (levelFilter !== "all" && entry.level !== levelFilter) {
        return false;
      }
      if (!q) return true;
      return entry.display.toLowerCase().includes(q);
    });
  }, [parsedLines, levelFilter, searchQuery]);

  const isBinaryArchive = Boolean(contentResponse?.is_binary);
  const isCompressedArchive = Boolean(contentResponse?.is_compressed);
  const isTruncated = Boolean(contentResponse?.truncated);

  const handleCopy = () => {
    const text = filteredLines.map((l) => l.display).join("\n");
    void copy(text, "Log lines copied to clipboard");
  };

  const handleJumpToEnd = () => {
    if (viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  };

  const filterButtons: Array<{ id: ConsoleLevelFilter; label: string; count: number }> = [
    { id: "all", label: "All", count: levelCounts.all },
    { id: "info", label: "INFO", count: levelCounts.info },
    { id: "warn", label: "WARN", count: levelCounts.warn },
    { id: "error", label: "ERROR", count: levelCounts.error },
  ];

  return (
    <div
      data-testid="log-file-viewer"
      className="flex flex-col flex-1 min-h-0 min-w-0 h-full rounded-xl border border-terminal-border bg-terminal-bg text-terminal-text overflow-hidden shadow-xs"
    >
      {/* Toolbar Row 1 */}
      <div className="shrink-0 bg-terminal-surface border-b border-terminal-border select-none">
        <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 border-b border-terminal-border/60">
          <div className="flex items-center gap-2 min-w-0">
            {!compact && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Back to logs"
                className="inline-flex items-center justify-center rounded-md border border-terminal-border bg-terminal-bg p-1 text-terminal-muted hover:text-terminal-text transition-colors cursor-pointer shrink-0"
              >
                <Icon name="chevron-left" size={14} />
              </button>
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs font-semibold text-terminal-text truncate">
                  {file.name}
                </span>
                <span
                  data-testid="log-viewer-readonly-badge"
                  className="inline-flex items-center gap-1 rounded-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-[10px] font-semibold text-terminal-info"
                >
                  <Icon name="lock" size={10} />
                  Read-Only · Live
                </span>
                {isCompressedArchive && !isBinaryArchive && (
                  <span className="inline-flex items-center rounded-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-[10px] font-mono text-terminal-muted">
                    Decompressed .gz
                  </span>
                )}
              </div>
              <p className="text-[11px] font-mono text-terminal-muted truncate">{file.path}</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              type="button"
              data-testid="log-viewer-copy-btn"
              disabled={filteredLines.length === 0 || isBinaryArchive}
              onClick={handleCopy}
              className="inline-flex items-center gap-1 rounded-md border border-terminal-border bg-terminal-bg px-2 py-1 text-[11px] font-sans text-terminal-muted hover:text-terminal-text disabled:opacity-40 transition-colors cursor-pointer"
            >
              <Icon name="copy" size={12} />
              <span>Copy</span>
            </button>
            <button
              type="button"
              data-testid="log-viewer-download-btn"
              onClick={() => onDownload(file)}
              className="inline-flex items-center gap-1 rounded-md border border-terminal-border bg-terminal-bg px-2 py-1 text-[11px] font-sans text-terminal-muted hover:text-terminal-text transition-colors cursor-pointer"
            >
              <Icon name="download" size={12} />
              <span>Download</span>
            </button>
            <button
              type="button"
              data-testid="log-viewer-jump-end-btn"
              disabled={filteredLines.length === 0 || isBinaryArchive}
              onClick={handleJumpToEnd}
              className="inline-flex items-center gap-1 rounded-md border border-terminal-border bg-terminal-bg px-2 py-1 text-[11px] font-sans text-terminal-muted hover:text-terminal-text disabled:opacity-40 transition-colors cursor-pointer"
            >
              <Icon name="chevron-down" size={12} />
              <span>Jump to End</span>
            </button>
            <button
              type="button"
              data-testid="log-viewer-close-btn"
              aria-label="Close viewer"
              onClick={onClose}
              className="inline-flex items-center justify-center rounded-md border border-terminal-border bg-terminal-bg p-1 text-terminal-muted hover:text-terminal-text transition-colors cursor-pointer"
            >
              <Icon name="x" size={13} />
            </button>
          </div>
        </div>

        {/* Truncation Notice */}
        {isTruncated && (
          <div
            data-testid="log-viewer-truncated-notice"
            className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border/60 bg-status-warning-bg px-3.5 py-1.5 text-[11px] text-terminal-warn"
          >
            <span>
              Showing trailing 5 MB window
              {contentResponse?.total_size_bytes
                ? ` of ${formatBytes(contentResponse.total_size_bytes)}`
                : ""}{" "}
              — Download for complete log.
            </span>
          </div>
        )}

        {/* Toolbar Row 2: In-file search & level filters */}
        <div className="flex flex-wrap items-center justify-between gap-2 bg-terminal-bg/60 px-3 py-1.5 text-xs">
          <div className="flex items-center gap-2 flex-1 min-w-[180px] max-w-md">
            <div className="relative flex-1">
              <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2 text-terminal-muted">
                <Icon name="search" size={12} />
              </span>
              <input
                type="text"
                data-testid="log-viewer-search-input"
                aria-label="Find in log"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Find in log..."
                className="w-full rounded-md border border-terminal-border bg-terminal-bg py-1 pl-7 pr-7 font-mono text-xs text-terminal-text placeholder:text-terminal-muted focus:border-border-focus focus:outline-none"
              />
              {searchQuery && (
                <button
                  type="button"
                  aria-label="Clear log search"
                  onClick={() => setSearchQuery("")}
                  className="absolute inset-y-0 right-0 flex items-center pr-2 text-terminal-muted hover:text-terminal-text cursor-pointer"
                >
                  <Icon name="x" size={11} />
                </button>
              )}
            </div>
            {searchQuery && (
              <span
                data-testid="log-viewer-search-matches"
                className="whitespace-nowrap font-sans text-[11px] text-terminal-muted"
              >
                {filteredLines.length} {filteredLines.length === 1 ? "match" : "matches"}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1" role="group" aria-label="Filter log level">
            {filterButtons.map((btn) => {
              const active = levelFilter === btn.id;
              const activeTone =
                btn.id === "error"
                  ? "border-status-danger-border bg-status-danger-bg text-terminal-error"
                  : btn.id === "warn"
                    ? "border-status-warning-border bg-status-warning-bg text-terminal-warn"
                    : btn.id === "info"
                      ? "border-terminal-info bg-terminal-bg text-terminal-info"
                      : "border-terminal-border bg-terminal-surface text-terminal-text";
              return (
                <button
                  key={btn.id}
                  type="button"
                  data-testid={`log-viewer-filter-${btn.id}`}
                  aria-pressed={active}
                  onClick={() => setLevelFilter(btn.id)}
                  className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-sans text-[11px] font-medium transition-colors cursor-pointer ${
                    active
                      ? activeTone
                      : "border-transparent text-terminal-muted hover:bg-terminal-bg hover:text-terminal-text"
                  }`}
                >
                  <span>{btn.label}</span>
                  {(btn.id === "warn" || btn.id === "error" || btn.count > 0) && (
                    <span className="font-mono text-[10px] opacity-85">
                      {btn.id === "warn" || btn.id === "error" ? `(${btn.count})` : btn.count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Body */}
      <div
        ref={viewportRef}
        data-testid="log-viewer-viewport"
        className="flex-1 min-h-0 overflow-y-auto px-4 py-3 font-mono text-xs leading-6 select-text space-y-0.5"
      >
        {isLoading ? (
          <div className="flex h-48 items-center justify-center font-sans text-sm text-terminal-muted">
            Loading log file...
          </div>
        ) : error ? (
          <div className="p-4 font-sans">
            <ErrorState
              title="Failed to load log"
              message={extractApiErrorMessage(error, "Unable to read log file")}
              onRetry={onRetry}
            />
          </div>
        ) : isBinaryArchive ? (
          <div className="flex h-56 flex-col items-center justify-center gap-3 p-6 text-center font-sans">
            <Icon name="file" size={36} className="text-terminal-muted" />
            <div>
              <h3 className="text-sm font-semibold text-terminal-text">
                {isCompressedArchive ? "Compressed Archive" : "Binary Log File"}
              </h3>
              <p className="mt-1 text-xs text-terminal-muted">
                Compressed archive — download to inspect
              </p>
            </div>
            <Button
              type="button"
              variant="primary"
              size="sm"
              icon="download"
              onClick={() => onDownload(file)}
            >
              Download
            </Button>
          </div>
        ) : filteredLines.length === 0 ? (
          <p className="font-sans text-terminal-muted">
            {searchQuery || levelFilter !== "all"
              ? "No log lines matching your active filter."
              : "This log file is empty."}
          </p>
        ) : (
          filteredLines.map((entry) => {
            const tokens = tokenizeConsoleLine(entry.display, entry.level);
            const messageClass = getLevelTextClass(entry.level, tokens.isMilestone);
            return (
              <div
                key={entry.id}
                data-log-level={entry.level}
                className="whitespace-pre-wrap break-all text-terminal-text"
              >
                {tokens.isoPrefix && (
                  <span data-log-token="iso" className="text-terminal-timestamp">
                    {renderHighlightedText(tokens.isoPrefix, searchQuery)}
                  </span>
                )}
                {tokens.headerPrefix && (
                  <span data-log-token="timestamp" className="text-terminal-timestamp">
                    {renderHighlightedText(tokens.headerPrefix, searchQuery)}
                  </span>
                )}
                {tokens.levelTag && (
                  <span data-log-token="level" className={getLevelTagClass(tokens.levelTag)}>
                    {renderHighlightedText(tokens.levelTag, searchQuery)}
                  </span>
                )}
                {tokens.headerSuffix && (
                  <span data-log-token="header-close" className="text-terminal-timestamp">
                    {renderHighlightedText(tokens.headerSuffix, searchQuery)}
                  </span>
                )}
                {tokens.sourceTag && (
                  <>
                    <span data-log-token="source" className="text-terminal-source font-medium">
                      {renderHighlightedText(tokens.sourceTag, searchQuery)}
                    </span>
                    {tokens.sourceSeparator}
                  </>
                )}
                {tokens.message && (
                  <span data-log-token="message" className={messageClass}>
                    {renderHighlightedText(tokens.message, searchQuery)}
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
