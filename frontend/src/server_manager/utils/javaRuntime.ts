export function resolveJavaMajorForMcVersion(mcVersion: string): number {
  const cleaned = (mcVersion || "").trim().split("-")[0] ?? "";
  const parts = cleaned.split(".");
  const major = Number.parseInt(parts[0] ?? "", 10);
  const minor = Number.parseInt(parts[1] ?? "0", 10);
  const patch = Number.parseInt(parts[2] ?? "0", 10);
  if (!Number.isFinite(major)) return 21;
  if (major >= 26) return 25;
  if (major === 1) {
    if (minor > 20 || (minor === 20 && patch >= 5)) return 21;
    if (minor >= 18) return 17;
    if (minor >= 17) return 16;
    return 8;
  }
  return 21;
}
