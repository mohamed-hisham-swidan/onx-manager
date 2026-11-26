export const MAX_CONSOLE_LINES = 2000;

export type ConsoleLogLevel = "command" | "error" | "warn" | "info" | "default";

export type ConsoleLevelFilter = "all" | "info" | "warn" | "error";

export interface ParsedConsoleLine {
  id: number;
  raw: string;
  clean: string;
  display: string;
  isoTimestamp: string | null;
  shortTime: string | null;
  level: ConsoleLogLevel;
}

export interface ConsoleLineTokens {
  isoPrefix: string | null;
  headerPrefix: string | null;
  levelTag: string | null;
  headerSuffix: string | null;
  commandPrompt: string | null;
  sourceTag: string | null;
  sourceSeparator: string | null;
  message: string;
  isMilestone: boolean;
}

export interface ParsedPlayersList {
  online: number;
  max: number;
  names: string[];
}

// ANSI CSI (e.g. ESC[38;5;208m), OSC (ESC]...BEL), and 2-byte ESC sequences
const ESC = String.fromCharCode(0x1b);
const BEL = String.fromCharCode(0x07);
const ANSI_CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, "g");
const ANSI_OSC_RE = new RegExp(`${ESC}\\][^${BEL}${ESC}]*(?:${BEL}|${ESC}\\\\)`, "g");
const ANSI_SINGLE_RE = new RegExp(`${ESC}[@-Z\\\\-_]`, "g");
// Minecraft section-sign color/style codes (§0-§9, §a-§f, §k-§o, §r, §x)
const MC_SECTION_RE = /\u00a7[0-9a-fk-orx]/gi;

// Docker RFC3339 nanosecond timestamp prefix: "2026-11-24T09:51:16.206710177Z "
const DOCKER_ISO_PREFIX_RE = /^(\d{4}-\d{2}-\d{2}T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z)\s+(.*)$/;
// Minecraft / Log4j2 leading timestamp: "[09:51:16 ..."
const MC_TIME_PREFIX_RE = /^\[(\d{2}:\d{2}:\d{2})\b/;

const ERROR_LEVEL_RE =
  /\[(?:[^\]]*\/)?(?:ERROR|FATAL|SEVERE)\b|\[(?:\d{2}:\d{2}:\d{2}\s+)(?:ERROR|FATAL|SEVERE)\b|\b(?:ERROR|FATAL|SEVERE):|\b(?:[A-Za-z0-9_.$]*(?:Exception|Error))(?::|\s|$)|^\s*Caused by:|^\s+at\s+[\w.$]+\(/i;
const WARN_LEVEL_RE =
  /\[(?:[^\]]*\/)?(?:WARN|WARNING)\b|\[(?:\d{2}:\d{2}:\d{2}\s+)(?:WARN|WARNING)\b|\bWARN(?:ING)?:/i;
const INFO_LEVEL_RE =
  /\[(?:[^\]]*\/)?INFO\b|\[(?:\d{2}:\d{2}:\d{2}\s+)INFO\b|\bINFO:/i;

const INFO_MILESTONE_RE =
  /\bDone \(\d+(?:\.\d+)?s\)!|\bjoined the game\b|\bRCON running\b|\bAll events enabled\b/i;

// Structured header matchers preserving exact original character sequences
const HDR_TIME_THREAD_LEVEL_RE =
  /^(\[\d{2}:\d{2}:\d{2}\]\s+\[[^\]/]+\/)(INFO|WARN|WARNING|ERROR|FATAL|SEVERE)(\]:?\s*)(.*)$/i;
const HDR_TIME_LEVEL_RE =
  /^(\[\d{2}:\d{2}:\d{2}\s+)(INFO|WARN|WARNING|ERROR|FATAL|SEVERE)(\]:?\s*)(.*)$/i;
const HDR_THREAD_LEVEL_RE =
  /^(\[[^\]/]+\/)(INFO|WARN|WARNING|ERROR|FATAL|SEVERE)(\]:?\s*)(.*)$/i;
const HDR_BRACKET_LEVEL_RE = /^(\[)(INFO|WARN|WARNING|ERROR|FATAL|SEVERE)(\]:?\s*)(.*)$/i;
const HDR_COLON_LEVEL_RE = /^(INFO|WARN|WARNING|ERROR|FATAL|SEVERE)(:\s*)(.*)$/i;
const HDR_TIME_ONLY_RE = /^(\[\d{2}:\d{2}:\d{2}\]\s+)(.*)$/;
const SOURCE_TAG_RE = /^(\[[^\]\r\n]{1,96}\])(:?\s+)(.*)$/;

export function stripAnsiAndMcFormatting(text: string): string {
  return text
    .replace(ANSI_OSC_RE, "")
    .replace(ANSI_CSI_RE, "")
    .replace(ANSI_SINGLE_RE, "")
    .replace(MC_SECTION_RE, "");
}

export function classifyConsoleLineLevel(cleanLine: string): ConsoleLogLevel {
  if (cleanLine.startsWith("> ")) {
    return "command";
  }
  if (ERROR_LEVEL_RE.test(cleanLine)) {
    return "error";
  }
  if (WARN_LEVEL_RE.test(cleanLine)) {
    return "warn";
  }
  if (INFO_LEVEL_RE.test(cleanLine)) {
    return "info";
  }
  return "default";
}

export function parseConsoleLine(raw: string, id: number): ParsedConsoleLine {
  const clean = stripAnsiAndMcFormatting(raw);
  let isoTimestamp: string | null = null;
  let shortTime: string | null = null;
  let display = clean;

  const dockerMatch = clean.match(DOCKER_ISO_PREFIX_RE);
  if (dockerMatch) {
    isoTimestamp = dockerMatch[1];
    shortTime = dockerMatch[2];
    const rest = dockerMatch[3];
    if (MC_TIME_PREFIX_RE.test(rest)) {
      // Minecraft already logged its own [HH:MM:SS ...]; drop duplicate Docker nanosecond prefix
      display = rest;
    } else {
      display = `[${shortTime}] ${rest}`;
    }
  } else {
    const mcTimeMatch = clean.match(MC_TIME_PREFIX_RE);
    if (mcTimeMatch) {
      shortTime = mcTimeMatch[1];
    }
  }

  const level = classifyConsoleLineLevel(display);

  return {
    id,
    raw,
    clean,
    display,
    isoTimestamp,
    shortTime,
    level,
  };
}

function splitSourceTag(body: string): {
  sourceTag: string | null;
  sourceSeparator: string | null;
  message: string;
} {
  const match = body.match(SOURCE_TAG_RE);
  if (!match) {
    return { sourceTag: null, sourceSeparator: null, message: body };
  }
  return {
    sourceTag: match[1],
    sourceSeparator: match[2],
    message: match[3],
  };
}

/**
 * Split a normalized console line into semantic visual tokens so timestamps,
 * level tags, plugin/subsystem `[sourceTag]` prefixes, milestones, and
 * normal log message bodies can be styled independently.
 */
export function tokenizeConsoleLine(
  lineText: string,
  level: ConsoleLogLevel,
): ConsoleLineTokens {
  if (level === "command" || lineText.startsWith("> ")) {
    const prompt = lineText.startsWith("> ") ? "> " : null;
    const message = prompt ? lineText.slice(2) : lineText;
    return {
      isoPrefix: null,
      headerPrefix: null,
      levelTag: null,
      headerSuffix: null,
      commandPrompt: prompt,
      sourceTag: null,
      sourceSeparator: null,
      message,
      isMilestone: false,
    };
  }

  let isoPrefix: string | null = null;
  let remaining = lineText;
  const isoMatch = remaining.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+)(.*)$/);
  if (isoMatch) {
    isoPrefix = isoMatch[1];
    remaining = isoMatch[2];
  }

  let headerPrefix: string | null = null;
  let levelTag: string | null = null;
  let headerSuffix: string | null = null;
  let body = remaining;
  let hasStructuredHeader = false;

  const m1 = remaining.match(HDR_TIME_THREAD_LEVEL_RE);
  const m2 = !m1 ? remaining.match(HDR_TIME_LEVEL_RE) : null;
  const m3 = !m1 && !m2 ? remaining.match(HDR_THREAD_LEVEL_RE) : null;
  const m4 = !m1 && !m2 && !m3 ? remaining.match(HDR_BRACKET_LEVEL_RE) : null;

  const headerMatch = m1 || m2 || m3 || m4;
  if (headerMatch) {
    headerPrefix = headerMatch[1];
    levelTag = headerMatch[2];
    headerSuffix = headerMatch[3];
    body = headerMatch[4];
    hasStructuredHeader = true;
  } else {
    const colonMatch = remaining.match(HDR_COLON_LEVEL_RE);
    if (colonMatch) {
      levelTag = colonMatch[1];
      headerSuffix = colonMatch[2];
      body = colonMatch[3];
      hasStructuredHeader = true;
    } else {
      const timeOnlyMatch = remaining.match(HDR_TIME_ONLY_RE);
      if (timeOnlyMatch) {
        headerPrefix = timeOnlyMatch[1];
        body = timeOnlyMatch[2];
        hasStructuredHeader = true;
      }
    }
  }

  const { sourceTag, sourceSeparator, message } = hasStructuredHeader
    ? splitSourceTag(body)
    : { sourceTag: null, sourceSeparator: null, message: body };

  const isMilestone = level === "info" && INFO_MILESTONE_RE.test(message);

  return {
    isoPrefix,
    headerPrefix,
    levelTag,
    headerSuffix,
    commandPrompt: null,
    sourceTag,
    sourceSeparator,
    message,
    isMilestone,
  };
}

export function getLevelTagClass(levelTag: string | null): string {
  const upper = (levelTag ?? "").toUpperCase();
  if (upper === "ERROR" || upper === "FATAL" || upper === "SEVERE") {
    return "text-terminal-error font-bold";
  }
  if (upper === "WARN" || upper === "WARNING") {
    return "text-terminal-warn font-bold";
  }
  if (upper === "INFO") {
    return "text-terminal-info font-semibold";
  }
  return "text-terminal-timestamp";
}

export function getLevelTextClass(level: ConsoleLogLevel, isMilestone = false): string {
  switch (level) {
    case "command":
      return "text-terminal-command font-semibold";
    case "error":
      return "text-terminal-error font-semibold";
    case "warn":
      return "text-terminal-warn";
    case "info":
      return isMilestone ? "text-terminal-success font-medium" : "text-terminal-text";
    default:
      return "text-terminal-text";
  }
}

/**
 * Merge incoming tail lines onto existing buffer lines without duplicating
 * overlapping suffix/prefix windows and without wiping already-received live lines.
 */
export function mergeDeduplicatedLines(
  existing: string[],
  incoming: string[],
  maxLines = MAX_CONSOLE_LINES,
): string[] {
  if (incoming.length === 0) {
    return existing.length > maxLines ? existing.slice(-maxLines) : existing;
  }
  if (existing.length === 0) {
    return incoming.length > maxLines ? incoming.slice(-maxLines) : incoming;
  }

  // If existing ends with the entire incoming slice (no new lines), return existing
  const maxOverlap = Math.min(existing.length, incoming.length, 200);
  let overlap = 0;

  for (let len = maxOverlap; len >= 1; len--) {
    let matches = true;
    const startIdx = existing.length - len;
    for (let i = 0; i < len; i++) {
      if (existing[startIdx + i] !== incoming[i]) {
        matches = false;
        break;
      }
    }
    if (matches) {
      overlap = len;
      break;
    }
  }

  if (overlap > 0) {
    const appended = incoming.slice(overlap);
    if (appended.length === 0) {
      return existing.length > maxLines ? existing.slice(-maxLines) : existing;
    }
    return [...existing, ...appended].slice(-maxLines);
  }

  // Check if incoming is completely contained near the tail of existing
  if (incoming.length <= existing.length) {
    const tailWindow = existing.slice(-Math.min(existing.length, incoming.length + 50));
    const first = incoming[0];
    for (let idx = tailWindow.length - incoming.length; idx >= 0; idx--) {
      if (tailWindow[idx] !== first) continue;
      let allMatch = true;
      for (let j = 1; j < incoming.length; j++) {
        if (tailWindow[idx + j] !== incoming[j]) {
          allMatch = false;
          break;
        }
      }
      if (allMatch) {
        return existing.length > maxLines ? existing.slice(-maxLines) : existing;
      }
    }
  }

  // Fallback: append only lines from incoming that weren't in the last 30 lines
  const recentSet = new Set(existing.slice(-30));
  let firstNewIdx = 0;
  while (firstNewIdx < incoming.length && recentSet.has(incoming[firstNewIdx])) {
    firstNewIdx++;
  }
  const toAppend = incoming.slice(firstNewIdx);
  if (toAppend.length === 0) {
    return existing.length > maxLines ? existing.slice(-maxLines) : existing;
  }
  return [...existing, ...toAppend].slice(-maxLines);
}

/**
 * Given a watermark snapshot of lines that were visible when the user cleared
 * the console, return only newly arrived lines in `incoming` that occur after
 * the watermark so clearing is preserved across refetches and reconnects.
 */
export function sliceLinesAfterWatermark(watermark: string[], incoming: string[]): string[] {
  if (incoming.length === 0) return [];
  if (watermark.length === 0) return incoming;

  const maxOverlap = Math.min(watermark.length, incoming.length, 200);
  for (let len = maxOverlap; len >= 1; len--) {
    let matches = true;
    const startIdx = watermark.length - len;
    for (let i = 0; i < len; i++) {
      if (watermark[startIdx + i] !== incoming[i]) {
        matches = false;
        break;
      }
    }
    if (matches) {
      return incoming.slice(len);
    }
  }

  if (incoming.length <= watermark.length) {
    const tailWindow = watermark.slice(-Math.min(watermark.length, incoming.length + 50));
    const first = incoming[0];
    for (let idx = tailWindow.length - incoming.length; idx >= 0; idx--) {
      if (tailWindow[idx] !== first) continue;
      let allMatch = true;
      for (let j = 1; j < incoming.length; j++) {
        if (tailWindow[idx + j] !== incoming[j]) {
          allMatch = false;
          break;
        }
      }
      if (allMatch) {
        return [];
      }
    }
  }

  return incoming;
}

/**
 * Parse Minecraft vanilla / Paper / Fabric / Forge RCON `list` command output.
 * Examples:
 *  - "There are 2 of a max of 20 players online: Steve, Alex"
 *  - "There are 0 of a max of 20 players online:"
 *  - "There are 2/20 players online: Steve, Alex"
 */
export function parseOnlinePlayersList(rconOutput: string): ParsedPlayersList | null {
  const clean = stripAnsiAndMcFormatting(rconOutput).replace(/\r\n/g, "\n").trim();
  if (!clean) return null;

  const verboseMatch = clean.match(
    /There are\s+(\d+)\s+of a max(?:\s+of)?\s+(\d+)\s+players online\s*:?\s*(.*)$/is,
  );
  if (verboseMatch) {
    const online = Number.parseInt(verboseMatch[1], 10);
    const max = Number.parseInt(verboseMatch[2], 10);
    const tail = verboseMatch[3].trim();
    const names = tail
      ? tail
          .split(/[\n,]/)
          .map((s) => s.trim())
          .filter((s) => s.length > 0)
      : [];
    return { online, max, names };
  }

  const slashMatch = clean.match(/(\d+)\s*\/\s*(\d+)\s+players online\s*:?\s*(.*)$/is);
  if (slashMatch) {
    const online = Number.parseInt(slashMatch[1], 10);
    const max = Number.parseInt(slashMatch[2], 10);
    const tail = slashMatch[3].trim();
    const names = tail
      ? tail
          .split(/[\n,]/)
          .map((s) => s.trim())
          .filter((s) => s.length > 0)
      : [];
    return { online, max, names };
  }

  return null;
}
