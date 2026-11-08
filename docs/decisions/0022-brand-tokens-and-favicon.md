# ADR 0022: Brand Tokens and Favicon Architecture

## Status
Accepted

## Context
The application branding required unification across the web application, browser chrome, mobile touch icons, web app manifest, and project documentation. The brand mark consists of two thematic components:
- Mark 1: Primary structural geometry / strokes.
- Mark 2: The accent countertile / circular focal geometry.
- Wordmark: Brand text ink.

Previously, individual components and templates used divergent visual assets or hardcoded color values. Furthermore, switching skin themes (e.g., Graphite, Azure, Emerald, Amethyst, Amber, Crimson) or toggling light and dark modes required the brand mark to harmonize dynamically with the selected active palette and meet WCAG AA contrast standards.

## Decision
1. **Three-Token Brand System**:
   - Introduced `--brand-mark-1`, `--brand-mark-2`, and `--brand-ink` tokens defined across all active skins in both dark and light modes.
   - Configured tokens in `@theme` in `src/index.css` and added to `ALLOWED_TOKEN_KEYS` in `src/tokens/skinValidator.ts`.
   - Guaranteed contrast against background surface tokens exceeds WCAG AA standards (minimum 3:1 for graphic elements, >= 4.5:1 for wordmarks).

2. **Inline Theme-Aware Component (`BrandLogo`)**:
   - Created `frontend/src/components/brand/BrandLogo.tsx` rendering SVG geometry directly.
   - Geometry references `var(--brand-mark-1)`, `var(--brand-mark-2)`, and `var(--brand-ink)`.
   - Supports `"mark"`, `"full"`, and `"wordmark"` variants with predefined size tokens (`xs`, `sm`, `md`, `lg`, `xl`).
   - Accessible by default via `aria-label="ONX Manager"`.
   - Source vector preserved at `frontend/src/assets/brand/logo-source.svg`.

3. **Dynamic Favicon & Manifest**:
   - Static default icons generated for production and offline caching:
     - `public/favicon.svg` with dark/light `prefers-color-scheme` CSS.
     - `public/favicon.ico` (multi-resolution 32x32).
     - `public/apple-touch-icon.png` (180x180).
     - `public/icon-192.png` and `public/icon-512.png`.
     - `public/site.webmanifest` referencing standard PWA icon specs.
   - Runtime dynamic favicon synchronization in `src/tokens/dynamicFavicon.ts`:
     - Reads computed `--brand-mark-1` and `--brand-mark-2` from the DOM root.
     - Dynamically generates an SVG data URI icon linked to `<link rel="icon">`.
     - Triggered automatically when skin or color mode changes via `useUIStore`.

4. **Documentation & Readme Assets**:
   - Clean SVG asset placed at `docs/assets/logo.svg`.
   - Top-level `README.md` updated with the vector logo.

## Consequences
- Single source of truth for brand mark rendering.
- Seamless appearance across all 12 skin mode combinations without visual discordance or illegibility.
- Zero external runtime image requests for brand logos in the UI.
