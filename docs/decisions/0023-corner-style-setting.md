# ADR 0023: Corner Style Setting and Radius Token Architecture

## Status
Accepted

## Context
The application visual design previously used standard curved corner radiuses across cards, modal containers, buttons, and inputs without a user-configurable style preference. Users who prefer a denser, technical, flat aesthetic requested a "Sharp" corner style (near-rectangular borders with minimal curvature), alongside the default "Rounded" style.

The styling system must satisfy several key requirements:
1. Default must remain pixel-identical to the current curved styling ("Rounded").
2. "Sharp" mode must apply universally to box-like containers (cards, panels, modals, dialogs, inputs, buttons, tables, toasts, banners) with a disciplined 1px–3px radius scale.
3. Intrinsically circular elements (avatars, status indicator dots, switches, toggles, radio circles, loaders/spinners) must remain fully circular in both modes.
4. Mode selection must be persisted across sessions without visual flash on page load.
5. The solution must integrate seamlessly with Tailwind CSS v4 token architecture without scattershot ad-hoc component overrides.

## Decision
1. **CSS Variable Radius Scale**:
   - Defined base CSS variables on `:root` and `[data-corners="rounded"]` mapping to standard Tailwind values:
     - `--radius-xs: 0.125rem` (2px)
     - `--radius-sm: 0.25rem` (4px)
     - `--radius-md: 0.375rem` (6px)
     - `--radius-lg: 0.5rem` (8px)
     - `--radius-xl: 0.75rem` (12px)
     - `--radius-2xl: 1rem` (16px)
     - `--radius-3xl: 1.5rem` (24px)
   - Defined sharp overrides on `[data-corners="sharp"]`:
     - `--radius-xs: 1px`
     - `--radius-sm: 2px`
     - `--radius-md: 2px`
     - `--radius-lg: 2px`
     - `--radius-xl: 3px`
     - `--radius-2xl: 3px`
     - `--radius-3xl: 4px`

2. **Tailwind v4 `@theme` Mapping**:
   - Mapped `--radius-xs` through `--radius-3xl` and `--radius: var(--radius-md)` in `@theme`.
   - Utility classes such as `rounded-sm`, `rounded-md`, `rounded-lg`, `rounded-xl`, `rounded-2xl`, and `rounded` now automatically resolve via these variables.
   - Kept `rounded-full` (`--radius-full: 9999px`) exempted and untouched so avatars, toggles, and status dots remain circular.

3. **State Management & Anti-Flash Initialization**:
   - Stored in `localStorage` under `onx_corner_style` with values `"rounded" | "sharp"`.
   - Synchronous head script in `frontend/index.html` sets `document.documentElement.dataset.corners = style` before first paint.
   - Integrated into `useUIStore` with actions `setCornerStyle` and `toggleCornerStyle`, and included in "Reset Appearance to Default".

4. **Appearance Studio UI**:
   - Added selectable "Corner style" option in `AppearanceSettingsSection.tsx` with side-by-side interactive radio cards ("Rounded" vs "Sharp") featuring visual preview boxes.

5. **Roadmap for Part 2**:
   - Audit remaining components for hardcoded inline radius styles or arbitrary `rounded-[...]` classes that bypass Tailwind scale tokens, standardizing them to tokenized utilities.

## Consequences
- Clean global control over UI geometry without performance overhead or runtime script recalculations.
- Zero layout shift or theme flashing during initial paint.
- Full preservation of circular status indicators and avatar ergonomics.
