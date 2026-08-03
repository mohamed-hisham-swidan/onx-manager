const COLOR_CODE_RE = /\u00a7[0-9a-fk-orA-FK-OR]/g;
const AMPERSAND_CODE_RE = /&[0-9a-fk-orA-FK-OR]/g;
const DOLLAR_CODE_RE = /\$[0-9a-fk-orA-FK-OR]/g;
const SECTION_HEX_RE = /(?:\u00a7x)(?:\u00a7[0-9a-fA-F]){6}/g;
const AMPERSAND_HEX_RE = /&x([0-9a-fA-F]{6})/g;
const HASH_HEX_RE = /&#([0-9a-fA-F]{6})/g;
const NEWLINE_RE = /\\n/g;

export function stripMinecraftFormatting(motd: string): string {
  return motd
    .replace(SECTION_HEX_RE, "")
    .replace(AMPERSAND_HEX_RE, "")
    .replace(HASH_HEX_RE, "")
    .replace(COLOR_CODE_RE, "")
    .replace(AMPERSAND_CODE_RE, "")
    .replace(DOLLAR_CODE_RE, "")
    .replace(NEWLINE_RE, " ")
    .trim();
}
