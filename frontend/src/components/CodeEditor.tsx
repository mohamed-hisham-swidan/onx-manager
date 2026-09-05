import React, { useState, useRef, useEffect, useMemo } from "react";

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  filename?: string;
  readOnly?: boolean;
  className?: string;
}

type SupportedLanguage = "properties" | "json" | "yaml" | "toml" | "shell" | "plaintext";

function detectLanguage(filename?: string): SupportedLanguage {
  if (!filename) return "plaintext";
  const lower = filename.toLowerCase();
  if (lower.endsWith(".json")) return "json";
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
  return "plaintext";
}

const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  properties: "Properties",
  json: "JSON",
  yaml: "YAML",
  toml: "TOML",
  shell: "Shell",
  plaintext: "Plain Text",
};

/**
 * Highlights a single line based on syntax rules.
 */
function highlightLine(line: string, lang: SupportedLanguage): React.ReactNode[] {
  if (!line) return [""];

  // 1. Comments
  if (lang === "properties" && (line.trimStart().startsWith("#") || line.trimStart().startsWith("!"))) {
    return [<span key="comment" className="text-gray-400 dark:text-gray-500 italic">{line}</span>];
  }
  if ((lang === "yaml" || lang === "toml" || lang === "json") && line.trimStart().startsWith("#")) {
    return [<span key="comment" className="text-gray-400 dark:text-gray-500 italic">{line}</span>];
  }
  if (lang === "json" && line.trimStart().startsWith("//")) {
    return [<span key="comment" className="text-gray-400 dark:text-gray-500 italic">{line}</span>];
  }
  if (lang === "shell" && (line.trimStart().startsWith("#") || line.trimStart().startsWith("REM ") || line.trimStart().startsWith("::"))) {
    return [<span key="comment" className="text-gray-400 dark:text-gray-500 italic">{line}</span>];
  }

  // 2. Section Headers: [Section]
  if ((lang === "properties" || lang === "toml") && /^\[.+\]$/.test(line.trim())) {
    return [<span key="section" className="text-amber-600 dark:text-amber-400 font-semibold">{line}</span>];
  }

  // 3. Properties key=value or key: value
  if (lang === "properties") {
    const sepIdx = line.indexOf("=");
    if (sepIdx !== -1) {
      const key = line.slice(0, sepIdx);
      const val = line.slice(sepIdx + 1);
      return [
        <span key="key" className="text-blue-600 dark:text-blue-400 font-medium">{key}</span>,
        <span key="eq" className="text-gray-500 dark:text-gray-400">=</span>,
        formatValue(val),
      ];
    }
  }

  // 4. YAML key: value
  if (lang === "yaml") {
    const colonMatch = line.match(/^(\s*)([a-zA-Z0-9_-]+)(:)(.*)$/);
    if (colonMatch) {
      const [, indent, key, colon, rest] = colonMatch;
      return [
        indent,
        <span key="key" className="text-blue-600 dark:text-blue-400 font-medium">{key}</span>,
        <span key="colon" className="text-gray-500 dark:text-gray-400">{colon}</span>,
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
        <span key="key" className="text-blue-600 dark:text-blue-400 font-medium">{key}</span>,
        <span key="eq" className="text-gray-500 dark:text-gray-400">=</span>,
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
        <span key="jkey" className="text-blue-600 dark:text-blue-400 font-medium">{quotedKey}</span>,
        <span key="jcol" className="text-gray-500 dark:text-gray-400">{colon}</span>,
        formatValue(rest),
      ];
    }
  }

  // Fallback / plain token formatting
  return [formatValue(line)];
}

function formatValue(str: string): React.ReactNode {
  // Check for string literals
  const trimmed = str.trim();
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return <span key="val-str" className="text-emerald-600 dark:text-emerald-400">{str}</span>;
  }
  // Check for booleans
  if (/^(true|false|yes|no|on|off)$/i.test(trimmed)) {
    return <span key="val-bool" className="text-purple-600 dark:text-purple-400 font-semibold">{str}</span>;
  }
  // Check for numbers
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
    return <span key="val-num" className="text-purple-600 dark:text-purple-400">{str}</span>;
  }
  return str;
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  value,
  onChange,
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
    if (e.key === "Tab") {
      e.preventDefault();
      if (readOnly) return;
      const textarea = textareaRef.current;
      if (!textarea) return;

      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const newValue = value.substring(0, start) + "  " + value.substring(end);
      onChange(newValue);

      // Set cursor position after the inserted spaces
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

  return (
    <div
      data-testid="code-editor"
      className={`flex flex-col border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden bg-white dark:bg-gray-900 shadow-sm ${className}`}
    >
      {/* Editor Main Canvas */}
      <div className="relative flex flex-1 h-[560px] overflow-hidden">
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
          className="w-14 h-[560px] py-4 pr-3 pl-2 m-0 select-none bg-gray-50 dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800 text-right font-mono text-sm leading-6 whitespace-pre text-gray-400 dark:text-gray-500 overflow-hidden"
        >
          {Array.from({ length: lineCount }, (_, i) => i + 1).join("\n")}
        </pre>

        {/* Editing Surface: Dedicated Scroll Wrapper with Anchored Scrollbars */}
        <div
          ref={scrollContainerRef}
          data-testid="editor-scroll-container"
          onScroll={handleScroll}
          className="relative flex-1 h-[560px] overflow-auto"
        >
          <div className="relative min-w-full w-max min-h-full">
            {/* Syntax-highlighted underlay */}
            <pre
              ref={preRef}
              aria-hidden="true"
              className="p-4 m-0 font-mono text-sm leading-6 whitespace-pre pointer-events-none text-gray-800 dark:text-gray-200 bg-transparent select-none"
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
              spellCheck={false}
              autoCapitalize="off"
              autoComplete="off"
              autoCorrect="off"
              className="absolute inset-0 w-full h-full p-4 m-0 font-mono text-sm leading-6 bg-transparent text-transparent caret-gray-900 dark:caret-white resize-none outline-none overflow-hidden border-none focus:ring-0 selection:bg-blue-500/25 dark:selection:bg-blue-500/35"
            />
          </div>
        </div>
      </div>

      {/* Status Bar Footer */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 text-xs text-gray-500 dark:text-gray-400 select-none">
        <div className="flex items-center gap-4">
          <span className="font-medium text-gray-700 dark:text-gray-300">
            {LANGUAGE_LABELS[language]}
          </span>
          <span>
            Ln {cursorPos.line}, Col {cursorPos.col}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span>{lineCount} lines</span>
          <span>{value.length} characters</span>
        </div>
      </div>
    </div>
  );
};
