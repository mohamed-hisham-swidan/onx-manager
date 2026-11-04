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
