# ONX Manager Frontend Design System & Overhaul

Welcome to the comprehensive documentation for the **ONX Manager Frontend Overhaul**. This project modernizes the entire user interface and architecture of the ONX Minecraft Server Manager web application, transitioning from ad-hoc styling and monolithic views into a clean, token-driven, multi-skin design system.

---

## 1. Executive Summary & Goals

The overhaul addresses fundamental UI/UX and architectural challenges identified during the Stage 2 UX/IA audit:
1. **Unification & Consistency**: Replaced scattered inline patterns with 18 reusable, accessible UI primitives and standardized page templates.
2. **Design Tokens & Skin Architecture**: Introduced a comprehensive semantic CSS variable layer with dark/light mode support and two complete first-class skins: **Graphite** (deep neutral black, 0% blue chroma) and **Azure** (modern slate blue).
3. **Monolith Decomposition**: Decomposed massive single-file components (such as `ServerVersioningPage.tsx` from 1,280 LOC and `CreateServerPage.tsx` from 811 LOC) into focused, single-responsibility components with strict LOC budgets.
4. **Information Architecture Overhaul**: Replaced the cluttered 10-card rainbow grid on the dashboard with a clean, density-aware Fleet Status Bar. Added client-side search and directory pagination to the File Browser.
5. **Brand & Visual Identity**: Established an original brand identity featuring a geometric vortex logo, abstract isometric voxel banners, and custom domain icons—strictly adhering to non-Mojang IP guardrails.
6. **Accessibility & Contrast**: Enforced WCAG AA contrast ratios (>= 4.5:1 text, >= 3:1 UI boundaries) across all skins through automated programmatic testing, complete with visible focus rings and ARIA dialog semantics.
7. **Production Performance**: Reduced main bundle size through route-level code-splitting with React `lazy` and `Suspense`.

---

## 2. Architecture & File Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── brand/               # Brand identity (BrandLogo, VoxelBanner, SplashScreen)
│   │   ├── guards/              # Route protection (AuthGuard, SystemStatusGuard)
│   │   ├── layout/              # App shells & navigation (AppShell, ServerShell, TopBar, Sidebar)
│   │   └── ui/                  # 18 Reusable design primitives (Modal, Button, Table, etc.)
│   ├── operations/              # Global long-running background task drawer & stepper
│   ├── server_manager/
│   │   ├── components/          # Domain-specific components
│   │   │   ├── versioning/      # Decomposed Git-like versioning sub-components
│   │   │   └── wizard/          # Decomposed server creation wizard steps
│   │   ├── hooks/               # Domain custom hooks (useServerMetrics, etc.)
│   │   ├── pages/               # Top-level route pages
│   │   └── utils/               # Domain utilities (capabilities, forge, motd, etc.)
│   ├── services/                # API client and backend service wrappers
│   ├── stores/                  # Zustand state stores (uiStore, authStore)
│   ├── tokens/                  # Token contracts, WCAG contrast tests, palette ratchet
│   ├── websocket/               # Real-time WebSocket event client and subscription hub
│   ├── App.tsx                  # Main router with code-splitting
│   ├── index.css                # Semantic CSS custom property definitions & @theme
│   └── main.tsx                 # Pre-paint DOM theme initialization & React entry
docs/design/frontend-overhaul/
├── README.md                    # This document (system overview)
├── TOKENS.md                    # Token taxonomy, surfaces, text, borders, motion
├── SKINS.md                     # Skin system guide & custom skin JSON validator contract
├── TEMPLATES.md                 # 7 Standard page templates & layout guidelines
├── PRIMITIVES.md                # 18 Shared UI primitives API & accessibility
├── BRAND.md                     # Logo lockup, typography, voxel art, legal disclaimers
├── MINECRAFT-FLAVOR-GUARDRAILS.md# IP boundaries & abstract voxel guidelines
├── CHANGELOG.md                 # Chronological log of overhaul batches (B0 to B9)
├── DECISIONS-NEEDED.md          # Architectural decisions & deferred items
└── BACKEND-DEPENDENT.md         # UI features pending backend API capabilities
```

---

## 3. Core Design Principles

### Principle 1: Semantic Token First
Raw Tailwind colors (`bg-gray-800`, `text-blue-500`, `#1a202c`) are forbidden in application code. All styling uses semantic tokens (`bg-surface-panel`, `text-text-primary`, `border-border-default`, `text-accent-primary`). This enables dynamic runtime skinning, automated contrast verification, and zero regression during theme updates.

### Principle 2: Respect Developer & Operator Focus
ONX Manager is an administrative tool for server operators. The interface prioritizes density, clarity, and rapid status assessment over flashy animations. High-throughput views (Fleet, Files, Activity) default to **compact density**, while forms and wizards use **comfortable density**.

### Principle 3: Zero Mojang IP Infringement
All game-related imagery uses original geometric voxel artwork and custom SVG domain icons. No copyrighted textures, logos, mob faces, or tool assets are ever included.

### Principle 4: Rigorous Automated Verification
Every aspect of the design system is guarded by tests:
- WCAG AA contrast ratio computation across all skin/mode pairs (`contrast.test.ts`).
- Palette ratchet test forbidding raw colors outside the token engine (`paletteRatchet.test.ts`).
- Motion and accessibility tests enforcing reduced-motion overrides and ARIA contracts (`accessibilityMotion.test.tsx`).
- Schema validation for custom skins (`skinValidator.test.ts`).

---

## 4. How to Navigate the Documentation

- To understand or modify CSS variables and theme values: See [TOKENS.md](./TOKENS.md).
- To create a new skin or validate third-party theme JSON: See [SKINS.md](./SKINS.md).
- To build a new page or understand page structures: See [TEMPLATES.md](./TEMPLATES.md).
- To use or extend shared components: See [PRIMITIVES.md](./PRIMITIVES.md).
- To review brand rules and legal requirements: See [BRAND.md](./BRAND.md) and [MINECRAFT-FLAVOR-GUARDRAILS.md](./MINECRAFT-FLAVOR-GUARDRAILS.md).
- To inspect execution history and commits: See [CHANGELOG.md](./CHANGELOG.md).
