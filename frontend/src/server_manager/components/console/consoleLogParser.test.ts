import { describe, it, expect } from "vitest";
import {
  classifyConsoleLineLevel,
  getLevelTagClass,
  getLevelTextClass,
  mergeDeduplicatedLines,
  parseConsoleLine,
  parseOnlinePlayersList,
  stripAnsiAndMcFormatting,
  tokenizeConsoleLine,
} from "./consoleLogParser";

describe("consoleLogParser", () => {
  it("strips ANSI escape sequences and Minecraft section codes", () => {
    const raw = "\u001b[32m§aPlugins (2): §fVeinMiner\u001b[0m";
    expect(stripAnsiAndMcFormatting(raw)).toBe("Plugins (2): VeinMiner");
  });

  it("strips Docker RFC3339 nanosecond prefix when Minecraft already logged [HH:MM:SS]", () => {
    const raw =
      '2026-11-24T09:51:16.206710177Z [09:51:16 INFO]: Done (2.412s)! For help, type "help"';
    const parsed = parseConsoleLine(raw, 1);
    expect(parsed.isoTimestamp).toBe("2026-11-24T09:51:16.206710177Z");
    expect(parsed.shortTime).toBe("09:51:16");
    expect(parsed.display).toBe('[09:51:16 INFO]: Done (2.412s)! For help, type "help"');
    expect(parsed.level).toBe("info");
  });

  it("condenses Docker RFC3339 prefix to [HH:MM:SS] when inner line has no timestamp", () => {
    const raw = "2026-11-24T09:51:16.206710177Z Starting net.minecraft.server.Main";
    const parsed = parseConsoleLine(raw, 2);
    expect(parsed.isoTimestamp).toBe("2026-11-24T09:51:16.206710177Z");
    expect(parsed.display).toBe("[09:51:16] Starting net.minecraft.server.Main");
    expect(parsed.level).toBe("default");
  });

  it("classifies Minecraft, Log4j2, command, and Java stacktrace lines accurately", () => {
    expect(classifyConsoleLineLevel("> list")).toBe("command");
    expect(classifyConsoleLineLevel("[09:51:16 INFO]: Starting minecraft server")).toBe("info");
    expect(classifyConsoleLineLevel("[Server thread/INFO]: Loaded 12 recipes")).toBe("info");
    expect(classifyConsoleLineLevel("[09:51:16 WARN]: Can't keep up!")).toBe("warn");
    expect(classifyConsoleLineLevel("[Server thread/WARN]: Ambiguity between arguments")).toBe("warn");
    expect(classifyConsoleLineLevel("[09:51:16 ERROR]: Failed to save chunk")).toBe("error");
    expect(classifyConsoleLineLevel("[Server thread/FATAL]: Crash")).toBe("error");
    expect(classifyConsoleLineLevel("java.lang.NullPointerException: Cannot invoke")).toBe("error");
    expect(classifyConsoleLineLevel("Caused by: java.io.IOException: Disk full")).toBe("error");
    expect(classifyConsoleLineLevel("\tat net.minecraft.server.Main.main(Main.java:120)")).toBe(
      "error",
    );
    expect(classifyConsoleLineLevel("Plain stdout line")).toBe("default");
  });

  it("tokenizes Paper, Vanilla, plugin source tags, milestones, and user commands accurately", () => {
    const pluginInfo = tokenizeConsoleLine(
      "[09:51:16 INFO]: [Veinminer] Loaded 12 vein blocks",
      "info",
    );
    expect(pluginInfo).toEqual({
      isoPrefix: null,
      headerPrefix: "[09:51:16 ",
      levelTag: "INFO",
      headerSuffix: "]: ",
      commandPrompt: null,
      sourceTag: "[Veinminer]",
      sourceSeparator: " ",
      message: "Loaded 12 vein blocks",
      isMilestone: false,
    });

    const vanillaInfo = tokenizeConsoleLine(
      '[09:51:20] [Server thread/INFO]: Done (2.412s)! For help, type "help"',
      "info",
    );
    expect(vanillaInfo.headerPrefix).toBe("[09:51:20] [Server thread/");
    expect(vanillaInfo.levelTag).toBe("INFO");
    expect(vanillaInfo.headerSuffix).toBe("]: ");
    expect(vanillaInfo.message).toBe('Done (2.412s)! For help, type "help"');
    expect(vanillaInfo.isMilestone).toBe(true);

    const cmd = tokenizeConsoleLine("> say hello world", "command");
    expect(cmd.commandPrompt).toBe("> ");
    expect(cmd.message).toBe("say hello world");
  });

  it("maps level tags and message bodies to neutral INFO vs highlighted milestones", () => {
    expect(getLevelTagClass("INFO")).toContain("text-terminal-info");
    expect(getLevelTagClass("WARN")).toContain("text-terminal-warn");
    expect(getLevelTagClass("ERROR")).toContain("text-terminal-error");

    expect(getLevelTextClass("command")).toContain("text-terminal-command");
    expect(getLevelTextClass("error")).toContain("text-terminal-error");
    expect(getLevelTextClass("warn")).toContain("text-terminal-warn");
    expect(getLevelTextClass("info", false)).toContain("text-terminal-text");
    expect(getLevelTextClass("info", true)).toContain("text-terminal-success");
    expect(getLevelTextClass("default")).toContain("text-terminal-text");
  });

  it("merges overlapping tail buffers without duplicating or wiping existing lines and enforces cap", () => {
    const existing = ["line-1", "line-2", "line-3"];
    const incoming = ["line-2", "line-3", "line-4", "line-5"];
    expect(mergeDeduplicatedLines(existing, incoming, 10)).toEqual([
      "line-1",
      "line-2",
      "line-3",
      "line-4",
      "line-5",
    ]);

    expect(mergeDeduplicatedLines(existing, incoming, 3)).toEqual(["line-3", "line-4", "line-5"]);
  });

  it("parses vanilla, Paper, and slash-format RCON list outputs", () => {
    expect(
      parseOnlinePlayersList("There are 2 of a max of 20 players online: Steve, Alex"),
    ).toEqual({ online: 2, max: 20, names: ["Steve", "Alex"] });

    expect(parseOnlinePlayersList("There are 0 of a max of 20 players online:")).toEqual({
      online: 0,
      max: 20,
      names: [],
    });

    expect(parseOnlinePlayersList("§a2/20 players online: §fHerobrine, Notch")).toEqual({
      online: 2,
      max: 20,
      names: ["Herobrine", "Notch"],
    });

    expect(parseOnlinePlayersList("Unknown command")).toBeNull();
  });
});
