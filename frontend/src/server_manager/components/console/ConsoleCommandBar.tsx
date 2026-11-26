import { useRef, useState } from "react";

export interface ConsoleCommandBarProps {
  onSend: (command: string) => void;
  isSending: boolean;
  isRunning: boolean;
  canConsole: boolean;
  commandHistory: string[];
}

interface QuickCommandChip {
  label: string;
  command: string;
  prefillOnly?: boolean;
}

const QUICK_COMMANDS: QuickCommandChip[] = [
  { label: "list", command: "list" },
  { label: "tps", command: "tps" },
  { label: "save-all", command: "save-all" },
  { label: "whitelist list", command: "whitelist list" },
  { label: "say", command: "say ", prefillOnly: true },
];

export function ConsoleCommandBar({
  onSend,
  isSending,
  isRunning,
  canConsole,
  commandHistory,
}: ConsoleCommandBarProps) {
  const [input, setInput] = useState("");
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const draftRef = useRef("");
  const inputRef = useRef<HTMLInputElement>(null);

  const isDisabled = !canConsole || !isRunning;

  const placeholder = !canConsole
    ? "Console commands require console permission..."
    : !isRunning
      ? "Server is offline — start the server to send commands..."
      : "Enter a command... (↑/↓ for history)";

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isSending || isDisabled) return;
    onSend(trimmed);
    setInput("");
    setHistoryIndex(-1);
    draftRef.current = "";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowUp") {
      if (commandHistory.length === 0) return;
      e.preventDefault();
      if (historyIndex === -1) {
        draftRef.current = input;
      }
      const nextIndex = Math.min(historyIndex + 1, commandHistory.length - 1);
      setHistoryIndex(nextIndex);
      setInput(commandHistory[commandHistory.length - 1 - nextIndex] ?? "");
    } else if (e.key === "ArrowDown") {
      if (historyIndex === -1) return;
      e.preventDefault();
      const nextIndex = historyIndex - 1;
      setHistoryIndex(nextIndex);
      if (nextIndex < 0) {
        setInput(draftRef.current);
      } else {
        setInput(commandHistory[commandHistory.length - 1 - nextIndex] ?? "");
      }
    }
  };

  const handleChipClick = (chip: QuickCommandChip) => {
    if (isDisabled || isSending) return;
    if (chip.prefillOnly) {
      setInput(chip.command);
      setHistoryIndex(-1);
      inputRef.current?.focus();
      return;
    }
    onSend(chip.command);
  };

  return (
    <div className="space-y-2">
      {/* Quick Admin Command Chips */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[11px] font-medium text-text-muted mr-0.5">Quick:</span>
        {QUICK_COMMANDS.map((chip) => (
          <button
            key={chip.label}
            type="button"
            data-testid={`quick-cmd-${chip.label.replace(/\s+/g, "-")}`}
            disabled={isDisabled || isSending}
            onClick={() => handleChipClick(chip)}
            className="px-2 py-0.5 rounded-md border border-border-subtle bg-surface-muted text-text-secondary hover:text-text-primary hover:bg-surface-hover font-mono text-[11px] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            /{chip.label}
          </button>
        ))}
      </div>

      {/* Command Input Form */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          ref={inputRef}
          data-testid="console-command-input"
          value={input}
          disabled={isDisabled}
          onChange={(e) => {
            setInput(e.target.value);
            setHistoryIndex(-1);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="flex-1 px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary placeholder:text-text-muted font-mono focus:outline-none focus:ring-2 focus:ring-border-focus disabled:opacity-60 disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          data-testid="console-send-btn"
          disabled={isDisabled || isSending || !input.trim()}
          className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isSending ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}
