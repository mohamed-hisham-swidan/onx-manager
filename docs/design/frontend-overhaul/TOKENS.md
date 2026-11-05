# Design Tokens Architecture & Taxonomy

This document describes the design token architecture implemented in `frontend/src/index.css` and exposed via Tailwind CSS v4 `@theme`.

---

## 1. Token Taxonomy

Tokens are organized into functional tiers:
1. **Surfaces**: Page base, cards, elevated modals/flyouts, muted wells, overlays, and hover/active states.
2. **Text**: Primary, secondary, muted, inverse, and accent links.
3. **Borders**: Subtle dividers, default component borders, strong boundaries, and active focus rings.
4. **Accents**: Brand primary, hover, active, contrast text, and subtle tinted backgrounds.
5. **Status**: Triplets (text, background, border) for Success, Warning, Danger, and Info states.
6. **Density**: Padding, row height, and font scale variations for Compact vs. Comfortable modes.
7. **Motion**: Durations, standard easing cubic-bezier curves, and reduced-motion zeroing.

---

## 2. Surface Hierarchy (The Elevation Ladder)

Surfaces establish visual depth and hierarchy. The elevation ladder guarantees that containers resting on top of other surfaces are visually distinct and readable without reliance on harsh drop-shadows:

| Surface Token | Purpose | Graphite Dark | Azure Dark |
|---|---|---|---|
| `--surface-page` | Main viewport background / base backdrop | `#141414` | `#0b1222` |
| `--surface-card` | Content cards, table bodies, navigation shells | `#1a1a1a` | `#0f172a` |
| `--surface-muted` | Muted containers, code blocks, secondary wells | `#1e1e1e` | `#131c31` |
| `--surface-hover` | Interactive row or button hover overlay | `#222222` | `#1e293b` |
| `--surface-elevated` | Modals, dropdown popovers, slide-overs | `#262626` | `#1e293b` |
| `--surface-active` | Selected list items or pressed state | `#2b2b2b` | `#334155` |
| `--surface-overlay` | Modal backdrop scrim | `rgba(0, 0, 0, 0.8)` | `rgba(0, 0, 0, 0.75)` |

---

## 3. Typography & Text Hierarchy

Text tokens are calibrated to satisfy WCAG AA contrast (minimum 4.5:1 against their respective surface backgrounds):

| Text Token | Purpose | Graphite Dark | Azure Dark |
|---|---|---|---|
| `--text-primary` | Main titles, table headers, high-emphasis content | `#f0f0f0` | `#f8fafc` |
| `--text-secondary` | Body text, descriptions, regular navigation items | `#b8b8b8` | `#cbd5e1` |
| `--text-muted` | Metadata, timestamps, helper hints, placeholders | `#9e9e9e` | `#a0b4cc` |
| `--text-inverse` | Text on solid accent or high-contrast surfaces | `#141414` | `#0b1222` |
| `--text-accent` | Inline text links, highlighted terms | `#60a5fa` | `#38bdf8` |

---

## 4. Border & Focus System

Borders provide structural boundaries and hierarchy across interface elements. Under the project's border contrast policy, structural borders (`--border-default`, `--border-strong`, `--border-focus`) are guaranteed to meet or exceed WCAG AA non-text contrast (**minimum 3.0:1**) against all primary structural surfaces (`--surface-page`, `--surface-card`, `--surface-elevated`, `--surface-muted`) across all skins and modes:

| Border Token | Purpose | Token Value / Visual Role |
|---|---|---|
| `--border-subtle` | Fine divider lines between table rows or card headers | 1px low-contrast separator |
| `--border-default` | Input fields, standard card outlines, buttons | 1px balanced component border (>= 3.0:1 against structural surfaces) |
| `--border-strong` | Active state outlines, modal boundaries | 1px high-visibility boundary (>= 3.0:1 against structural surfaces) |
| `--border-focus` | Keyboard `:focus-visible` ring | 2px solid primary accent with outline offset (>= 3.0:1 against structural surfaces) |

### Contrast Policy Exclusions
- `--border-subtle` is intentionally excluded from the 3.0:1 threshold because it serves as an unobtrusive, decorative divider; enforcing high contrast would introduce visual clutter.
- `--surface-hover` and `--surface-active` are excluded as transient interactive states; feedback in these states is delivered via surface luminosity shifts and active depress styling rather than perimeter boundary contrast.

---

## 5. Status Triplets

Each status severity (Success, Warning, Danger, Info) consists of a semantic triplet:
- `text`: Foreground label or icon color (minimum 4.5:1 contrast against surface).
- `bg`: Low-opacity or tinted container background.
- `border`: High-visibility border defining the pill, badge, or banner container (minimum 3:1 contrast).

```css
/* Success (Online, Passed, Healthy) */
--status-success: #22c55e;
--status-success-bg: rgba(34, 197, 94, 0.12);
--status-success-border: rgba(34, 197, 94, 0.35);

/* Warning (Starting, Stopping, Updating, Degraded) */
--status-warning: #f59e0b;
--status-warning-bg: rgba(245, 158, 11, 0.12);
--status-warning-border: rgba(245, 158, 11, 0.35);

/* Danger (Crashed, Failed, Error, Offline) */
--status-danger: #ef4444;
--status-danger-bg: rgba(239, 68, 68, 0.12);
--status-danger-border: rgba(239, 68, 68, 0.35);

/* Info (Idle, Creating, Notice) */
--status-info: #38bdf8;
--status-info-bg: rgba(56, 189, 248, 0.12);
--status-info-border: rgba(56, 189, 248, 0.35);
```

---

## 6. Density Control Tokens

Density is managed via CSS custom properties scoped to containers or toggled globally via `data-density="compact | comfortable"`:

```css
:root, [data-density="comfortable"] {
  --density-padding-row: 0.75rem;
  --density-padding-card: 1.25rem;
  --density-font-size-base: 0.875rem;
  --density-control-height: 2.5rem;   /* 40px */
}

[data-density="compact"] {
  --density-padding-row: 0.375rem;
  --density-padding-card: 0.875rem;
  --density-font-size-base: 0.8125rem;
  --density-control-height: 2.0rem;   /* 32px */
}
```

---

## 7. Motion & Animation Tokens

Animations are kept restrained and respectful of system accessibility preferences:
- `--motion-duration-fast`: `100ms` (hover states, button press)
- `--motion-duration-normal`: `200ms` (modals, dropdowns, tab transitions)
- `--motion-duration-slow`: `300ms` (drawer slide-overs, page transitions)
- `--motion-ease-standard`: `cubic-bezier(0.16, 1, 0.3, 1)` (natural deceleration)

### Reduced Motion Override
When `@media (prefers-reduced-motion: reduce)` is active, all durations are collapsed to `0ms` and transition curves are disabled globally:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

---

## 8. Tailwind CSS v4 `@theme` Integration

All CSS variables are registered in `@theme` at the top of `src/index.css`:
```css
@theme {
  --color-surface-page: var(--surface-page);
  --color-surface-card: var(--surface-card);
  --color-surface-hover: var(--surface-hover);
  --color-surface-active: var(--surface-active);
  --color-surface-elevated: var(--surface-elevated);
  --color-surface-overlay: var(--surface-overlay);
  --color-surface-muted: var(--surface-muted);

  --color-text-primary: var(--text-primary);
  --color-text-secondary: var(--text-secondary);
  --color-text-muted: var(--text-muted);
  --color-text-inverse: var(--text-inverse);
  --color-text-accent: var(--text-accent);

  --color-border-subtle: var(--border-subtle);
  --color-border-default: var(--border-default);
  --color-border-strong: var(--border-strong);
  --color-border-focus: var(--border-focus);

  --color-accent-primary: var(--accent-primary);
  --color-accent-hover: var(--accent-hover);
  --color-accent-active: var(--accent-active);
  --color-accent-contrast-text: var(--accent-contrast-text);

  --color-status-success: var(--status-success);
  --color-status-warning: var(--status-warning);
  --color-status-danger: var(--status-danger);
  --color-status-info: var(--status-info);
  --color-status-neutral: var(--status-neutral);

  --color-status-success-bg: var(--status-success-bg);
  --color-status-success-border: var(--status-success-border);
  --color-status-warning-bg: var(--status-warning-bg);
  --color-status-warning-border: var(--status-warning-border);
  --color-status-danger-bg: var(--status-danger-bg);
  --color-status-danger-border: var(--status-danger-border);
  --color-status-info-bg: var(--status-info-bg);
  --color-status-info-border: var(--status-info-border);

  --color-terminal-bg: var(--terminal-bg);
  --color-terminal-text: var(--terminal-text);
  --color-terminal-cursor: var(--terminal-cursor);

  --spacing-density-card: var(--density-padding-card);
  --spacing-density-row: var(--density-padding-row);
  --spacing-density-input: var(--density-height-input);
}
```
This enables full Tailwind utility classes throughout the app: `bg-surface-card`, `bg-surface-page`, `text-text-primary`, `border-border-default`, `ring-border-focus`.
