import React, { useState, useRef, useEffect, useMemo } from "react";

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  onSave?: () => void;
  filename?: string;
  readOnly?: boolean;
  className?: string;
}

type SupportedLanguage = "properties" | "json" | "yaml" | "toml" | "shell" | "log" | "plaintext";

function detectLanguage(filename?: string): SupportedLanguage {
  if (!filename) return "plaintext";
  const lower = filename.toLowerCase();
  if (lower.endsWith(".json") || lower.endsWith(".json5") || lower.endsWith(".mcmeta")) return "json";
  if (lower.endsWith(".yml") || lower.endsWith(".yaml")) return "yaml";
  if (
    lower.endsWith(".properties") ||
    lower.endsWith(".ini") ||
    lower.endsWith(".cfg") ||
    lower.endsWith(".conf")
  ) {
    return "properties";
  }
  if (lower.endsWith(".toml")) return "toml";
  if (
    lower.endsWith(".sh") ||
    lower.endsWith(".bash") ||
    lower.endsWith(".bat") ||
    lower.endsWith(".cmd")
  ) {
    return "shell";
  }
  if (lower.endsWith(".log") || lower.endsWith(".log.txt")) return "log";
  return "plaintext";
}

const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  properties: "Properties",
  json: "JSON",
  yaml: "YAML",
  toml: "TOML",
  shell: "Shell",
  log: "Log",
  plaintext: "Plain Text",
};

function highlightLogLine(line: string): React.ReactNode[] {
  // Java stack trace frames / Caused by
  if (/^\s+at\s+/.test(line) || /^\s*\.\.\.\s+\d+\s+more/.test(line)) {
    return [<span key="stack" className="text-editor-comment">{line}</span>];
  }
  if (/^(Caused by:|[\w.$]+(?:Exception|Error)(?::|$))/.test(line.trimStart())) {
    return [<span key="exc" className="text-status-danger font-medium">{line}</span>];
  }

  // Standard Minecraft / Java log line: [12:34:56] [Server thread/INFO]: ... or [2026-...] [INFO] ...
  const logMatch = line.match(
    /^((?:\[[^\]]+\]\s*|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*))(\[[^\]]+\])?(.*)$/,
  );
  if (logMatch) {
    const [, prefix, bracket, rest] = logMatch;
    const header = `${prefix}${bracket ?? ""}`;
    let levelClass = "text-editor-text";
    if (/\b(ERROR|FATAL|SEVERE|CRITICAL)\b/i.test(header) || /\b(ERROR|FATAL|SEVERE)\b/.test(rest.slice(0, 24))) {
      levelClass = "text-status-danger font-semibold";
    } else if (/\b(WARN|WARNING)\b/i.test(header) || /\b(WARN|WARNING)\b/.test(rest.slice(0, 24))) {
      levelClass = "text-status-warning font-semibold";
    } else if (/\bINFO\b/i.test(header) || /\bINFO\b/.test(rest.slice(0, 24))) {
      levelClass = "text-status-info font-medium";
    } else if (/\b(DEBUG|TRACE)\b/i.test(header)) {
      levelClass = "text-editor-comment";
    }

    return [
      <span key="ts" className="text-editor-comment">{prefix}</span>,
      bracket ? <span key="lv" className={levelClass}>{bracket}</span> : null,
      <span key="msg" className={/\b(ERROR|FATAL|SEVERE)\b/i.test(header) ? "text-status-danger" : "text-editor-text"}>{rest}</span>,
    ];
  }

  return [line];
}

/**
 * Highlights a single line based on syntax rules using semantic design tokens.
 */
function highlightLine(line: string, lang: SupportedLanguage): React.ReactNode[] {
  if (!line) return [""];

  if (lang === "log") {
    return highlightLogLine(line);
  }

  // 1. Comments
  if (lang === "properties" && (line.trimStart().startsWith("#") || line.trimStart().startsWith("!"))) {
    return [<span key="comment" className="text-editor-comment italic">{line}</span>];
  }
  if ((lang === "yaml" || lang === "toml" || lang === "json") && line.trimStart().startsWith("#")) {
    return [<span key="comment" className="text-editor-comment italic">{line}</span>];
  }
  if (lang === "json" && line.trimStart().startsWith("//")) {
    return [<span key="comment" className="text-editor-comment italic">{line}</span>];
  }
  if (
    lang === "shell" &&
    (line.trimStart().startsWith("#") || line.trimStart().startsWith("REM ") || line.trimStart().startsWith("::"))
  ) {
    return [<span key="comment" className="text-editor-comment italic">{line}</span>];
  }

  // 2. Section Headers: [Section]
  if ((lang === "properties" || lang === "toml") && /^\[.+\]$/.test(line.trim())) {
    return [<span key="section" className="text-editor-keyword font-semibold">{line}</span>];
  }

  // 3. Properties key=value
  if (lang === "properties") {
    const sepIdx = line.indexOf("=");
    if (sepIdx !== -1) {
      const key = line.slice(0, sepIdx);
      const val = line.slice(sepIdx + 1);
      return [
        <span key="key" className="text-editor-key font-medium">{key}</span>,
        <span key="eq" className="text-editor-punctuation">=</span>,
        formatValue(val),
      ];
    }
  }

  // 4. YAML key: value
  if (lang === "yaml") {
    const colonMatch = line.match(/^(\s*(?:-\s+)?)([a-zA-Z0-9_.-]+)(:)(.*)$/);
    if (colonMatch) {
      const [, indent, key, colon, rest] = colonMatch;
      return [
        indent,
        <span key="key" className="text-editor-key font-medium">{key}</span>,
        <span key="colon" className="text-editor-punctuation">{colon}</span>,
        formatValue(rest),
      ];
    }
  }

  // 5. TOML key = value
  if (lang === "toml") {
    const eqIdx = line.indexOf("=");
    if (eqIdx !== -1) {
      const key = line.slice(0, eqIdx);
      const val = line.slice(eqIdx + 1);
      return [
        <span key="key" className="text-editor-key font-medium">{key}</span>,
        <span key="eq" className="text-editor-punctuation">=</span>,
        formatValue(val),
      ];
    }
  }

  // 6. JSON tokens
  if (lang === "json") {
    const jsonKeyMatch = line.match(/^(\s*)("([^"\\]*(\\.[^"\\]*)*)")(\s*:)(.*)$/);
    if (jsonKeyMatch) {
      const [, indent, quotedKey, , , colon, rest] = jsonKeyMatch;
      return [
        indent,
        <span key="jkey" className="text-editor-key font-medium">{quotedKey}</span>,
        <span key="jcol" className="text-editor-punctuation">{colon}</span>,
        formatValue(rest),
      ];
    }
  }

  return [formatValue(line)];
}

function formatValue(str: string): React.ReactNode {
  const trimmed = str.trim();
  const trailingComma = trimmed.endsWith(",") ? trimmed.slice(0, -1).trim() : trimmed;
  if (
    (trailingComma.startsWith('"') && trailingComma.endsWith('"')) ||
    (trailingComma.startsWith("'") && trailingComma.endsWith("'"))
  ) {
    return <span key="val-str" className="text-editor-string">{str}</span>;
  }
  if (/^(true|false|yes|no|on|off|null)$/i.test(trailingComma)) {
    return <span key="val-bool" className="text-editor-keyword font-semibold">{str}</span>;
  }
  if (/^-?\d+(\.\d+)?$/.test(trailingComma)) {
    return <span key="val-num" className="text-editor-number">{str}</span>;
  }
  return str;
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  value,
  onChange,
  onSave,
  filename,
  readOnly = false,
  className = "",
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const gutterRef = useRef<HTMLPreElement>(null);

  const [cursorPos, setCursorPos] = useState({ line: 1, col: 1 });

  const language = useMemo(() => detectLanguage(filename), [filename]);
  const normalizedValue = useMemo(() => value.replace(/\r\n/g, "\n"), [value]);
  const lines = useMemo(() => normalizedValue.split("\n"), [normalizedValue]);
  const lineCount = lines.length;

  const handleScroll = () => {
    if (scrollContainerRef.current && gutterRef.current) {
      gutterRef.current.scrollTop = scrollContainerRef.current.scrollTop;
    }
    requestAnimationFrame(() => {
      if (scrollContainerRef.current && gutterRef.current) {
        gutterRef.current.scrollTop = scrollContainerRef.current.scrollTop;
      }
    });
  };

  const updateCursor = () => {
    if (!textareaRef.current) return;
    const pos = textareaRef.current.selectionStart;
    const textBefore = normalizedValue.slice(0, pos);
    const lineArr = textBefore.split("\n");
    const currentLine = lineArr.length;
    const currentCol = (lineArr[lineArr.length - 1]?.length ?? 0) + 1;

    setCursorPos({
      line: currentLine,
      col: currentCol,
    });

    if (scrollContainerRef.current) {
      const sc = scrollContainerRef.current;
      const lineHeight = 24;
      const paddingTop = 16;
      const caretTop = paddingTop + (currentLine - 1) * lineHeight;

      if (caretTop < sc.scrollTop) {
        sc.scrollTop = caretTop;
      } else if (caretTop + lineHeight > sc.scrollTop + sc.clientHeight) {
        sc.scrollTop = caretTop + lineHeight - sc.clientHeight + paddingTop;
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (!readOnly && onSave) {
        onSave();
      }
      return;
    }

    if (e.key === "Tab") {
      e.preventDefault();
      if (readOnly) return;
      const textarea = textareaRef.current;
      if (!textarea) return;

      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const newValue = value.substring(0, start) + "  " + value.substring(end);
      onChange(newValue);

      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.selectionStart = textareaRef.current.selectionEnd = start + 2;
          updateCursor();
        }
      }, 0);
    }
  };

  useEffect(() => {
    handleScroll();
  }, [value]);

  const hasCustomHeight = /\bh-/.test(className);

  return (
    <div
      data-testid="code-editor"
      className={`flex flex-col border border-border-default rounded-lg overflow-hidden bg-editor-bg shadow-2xs ${
        hasCustomHeight ? "" : "h-[clamp(440px,calc(100dvh-16rem),780px)]"
      } ${className}`}
    >
      {/* Editor Main Canvas */}
      <div className="relative flex flex-1 min-h-0 overflow-hidden">
        {/* Line Numbers Gutter (<pre> mirror) */}
        <pre
          ref={gutterRef}
          data-testid="editor-gutter"
          aria-hidden="true"
          onWheel={(e) => {
            if (scrollContainerRef.current) {
              scrollContainerRef.current.scrollTop += e.deltaY;
            }
            handleScroll();
          }}
          className="w-14 h-full py-4 pr-3 pl-2 m-0 select-none bg-editor-gutter-bg border-r border-border-subtle text-right font-mono text-sm leading-6 whitespace-pre text-editor-gutter-text overflow-hidden shrink-0"
        >
          {Array.from({ length: lineCount }, (_, i) => i + 1).join("\n")}
        </pre>

        {/* Editing Surface: Dedicated Scroll Wrapper with Anchored Scrollbars */}
        <div
          ref={scrollContainerRef}
          data-testid="editor-scroll-container"
          onScroll={handleScroll}
          className="relative flex-1 min-h-0 h-full overflow-auto"
        >
          <div className="relative min-w-full w-max min-h-full">
            {/* Syntax-highlighted underlay */}
            <pre
              ref={preRef}
              aria-hidden="true"
              className="p-4 m-0 font-mono text-sm leading-6 whitespace-pre pointer-events-none text-editor-text bg-transparent select-none"
            >
              {lines.map((line, idx) => (
                <React.Fragment key={idx}>
                  {highlightLine(line, language)}
                  {idx < lineCount - 1 ? "\n" : ""}
                </React.Fragment>
              ))}
            </pre>

            {/* Textarea for typing and selection */}
            <textarea
              ref={textareaRef}
              role="textbox"
              aria-label="Code Editor"
              wrap="off"
              value={value}
              onChange={(e) => {
                if (readOnly) return;
                onChange(e.target.value);
                updateCursor();
              }}
              onScroll={(e) => {
                if (scrollContainerRef.current) {
                  if (e.currentTarget.scrollTop !== 0) {
                    scrollContainerRef.current.scrollTop += e.currentTarget.scrollTop;
                    e.currentTarget.scrollTop = 0;
                  }
                  if (e.currentTarget.scrollLeft !== 0) {
                    scrollContainerRef.current.scrollLeft += e.currentTarget.scrollLeft;
                    e.currentTarget.scrollLeft = 0;
                  }
                }
              }}
              onKeyDown={handleKeyDown}
              onKeyUp={updateCursor}
              onClick={updateCursor}
              onSelect={updateCursor}
              readOnly={readOnly}
              aria-readonly={readOnly || undefined}
              spellCheck={false}
              autoCapitalize="off"
              autoComplete="off"
              autoCorrect="off"
              className={`absolute inset-0 w-full h-full p-4 m-0 font-mono text-sm leading-6 bg-transparent text-transparent caret-editor-text resize-none outline-none overflow-hidden border-none focus:ring-0 selection:bg-accent-primary/25 ${
                readOnly ? "cursor-default" : ""
              }`}
            />
          </div>
        </div>
      </div>

      {/* Status Bar Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-t border-border-subtle bg-editor-gutter-bg text-xs text-editor-gutter-text select-none">
        <div className="flex items-center gap-3">
          <span className="font-medium text-text-secondary">
            {LANGUAGE_LABELS[language]}
          </span>
          <span>
            Ln {cursorPos.line}, Col {cursorPos.col}
          </span>
          {readOnly && (
            <span
              data-testid="editor-readonly-pill"
              className="rounded border border-status-warning-border bg-status-warning-bg px-1.5 py-0.5 text-[11px] font-medium text-status-warning"
            >
              Read-Only
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          {!readOnly && onSave && (
            <span className="hidden sm:inline font-mono text-[11px] text-text-muted">
              Ctrl+S to save
            </span>
          )}
          <span>{lineCount} lines</span>
          <span>{value.length} characters</span>
        </div>
      </div>
    </div>
  );
};
