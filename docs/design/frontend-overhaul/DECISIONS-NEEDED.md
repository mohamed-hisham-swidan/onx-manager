# Frontend Overhaul: Decisions Needed

This document records non-blocking decisions, conservative choices made during autonomous execution, and architectural items logged for future owner review.

---

## 1. RegisterPage vs InvitePage Token Verification Consolidation
- **Status**: SPEC-WORTHY ITEM / LOGGED & DEFERRED
- **Context**: The Stage 2 audit suggested merging invite-token redemption in `RegisterPage.tsx` into `InvitePage.tsx`.
- **Finding**: Merging invite-token redemption alters the public-facing authentication and invitation registration flow.
- **Decision Taken**: Per prompt non-negotiables, this flow is **NOT merged** during this overhaul. Both `RegisterPage.tsx` and `InvitePage.tsx` retain their existing routing and registration contracts. A dedicated spec is recommended before altering auth behaviors.

---

## 2. Default Density for Application Routes
- **Status**: CONSERVATIVE CHOICE TAKEN
- **Decision**: Per D8, density is mapped per-template:
  - Tables & high-throughput explorers (Servers Fleet, File Explorer, Activity Log): **Compact** (`--density-padding-row: 0.375rem`, 32px height).
  - Forms, Wizards, and Editors (Settings, Create Server Wizard, Auth): **Comfortable** (`--density-padding-card: 1.25rem`, 40px input height).
  - Global default at root: `comfortable`, with component templates overriding via CSS variables or `data-density` contexts without mixing densities on a single action surface.
- **Alternative**: Global toggle in user menu allowing user preference override. The architecture provides the `data-density` attribute on `<html>` to support this seamlessly.

---

## 3. Monaco Editor vs In-House CodeEditor
- **Status**: RESOLVED PER ADR-0021 D3
- **Decision**: Keep the lightweight in-house `CodeEditor.tsx` (syntax-highlighted textarea overlay, ~332 LOC) instead of adding Monaco Editor. Monaco adds ~2.5–4.5MB uncompressed payload, requiring complex Web Worker bundling and breaking the zero-new-dependencies rule.

---

## 4. System Font Stacks vs External Fonts
- **Status**: CONSERVATIVE CHOICE TAKEN
- **Decision**: Use robust modern system font stacks behind tokens (`font-sans`: `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`, `font-mono`: `'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace`). Avoid external runtime downloads to ensure zero external network calls and 100% offline self-hosted operation.

---

## 5. Border Contrast Policy & Token Calibrations
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: Non-text contrast compliance (WCAG AA 2.1 SC 1.4.11) requires a minimum 3.0:1 contrast ratio between functional boundaries and adjacent background surfaces.
- **Decision Taken**: Enforced a strict minimum 3.0:1 contrast ratio for all structural border tokens (`--border-default`, `--border-strong`, `--border-focus`) against all structural background surfaces (`--surface-page`, `--surface-card`, `--surface-elevated`, `--surface-muted`) across all skin (`graphite`, `azure`) and mode (`dark`, `light`) combinations. Calibrated `--border-default` in dark mode:
  - Graphite dark `--border-default`: adjusted from `#686868` (2.72:1 vs elevated) to `#707070` (3.06:1 vs elevated, preserving pure neutral $R=G=B=112$).
  - Azure dark `--border-default`: adjusted from `#606b7d` (2.71:1 vs elevated) to `#687385` (3.05:1 vs elevated).
  - Explicitly excluded decorative `--border-subtle` (low-contrast dividers to prevent visual noise) and transient `--surface-hover` / `--surface-active` surfaces (where interactive luminosity shifts provide feedback).
- **Alternative for Owner**: The owner may opt to leave borders as is (restoring `#686868` / `#606b7d`) if softer visual outlines are preferred, or adjust the dark surface elevation ladder instead of the border tokens.

---

## 6. Palette Ratchet Allowlist Cap Adjustments (F2-2)
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: In review fix F2-2, `paletteRatchet.test.ts` was expanded to inspect all CSS property prefixes (`bg|text|border|ring|fill|stroke|outline|divide|from|via|to|shadow|accent|caret|decoration`) across all 22 Tailwind color families (gray, slate, zinc, neutral, stone, red, orange, amber, yellow, lime, green, emerald, teal, cyan, sky, blue, indigo, violet, purple, fuchsia, pink, rose).
- **Decision Taken**: The expanded regex captured pre-existing raw color classes that previous scans did not detect (e.g. gradient stops `to-gray-900`, `from-stone-900`, SVG fill `fill-gray-400`). To keep the ratchet passing without altering UI visuals or raising caps silently, caps were adjusted in `ALLOWLIST`:
  - `LoaderBadge.tsx`: 45 -> 60 (SVG animation spinner and multi-stop gradient classes).
  - `StartingMonitorBanner.tsx`: 35 -> 55 (multi-stage progress bar gradient stops and markers).
  - `ServerModsPage.tsx`: 15 -> 25 (mod-type badge color accents and category tag indicators).
- **Alternative for Owner**: The owner may choose to lower these caps by refactoring the inline SVG gradients, complex spinner animations, and mod badges to use tokenized CSS variables or SVGs referencing CSS custom properties.
