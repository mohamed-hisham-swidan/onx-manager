# Skin Architecture & Custom Skin Contract

ONX Manager features an extensible, multi-skin theme engine powered entirely by CSS custom properties and HTML data attributes.

---

## 1. How Skins Work

Theme state is tracked in `frontend/src/stores/uiStore.ts` and synchronized to the root `<html>` element as DOM attributes:
- `data-skin="graphite | azure | <custom-id>"`
- `data-mode="dark | light"`
- `data-density="compact | comfortable"`

CSS selectors in `src/index.css` target these attributes to redefine semantic tokens:
```css
/* Graphite Skin (Default) */
:root, [data-skin="graphite"] {
  /* Graphite dark tokens */
}
[data-skin="graphite"][data-mode="light"] {
  /* Graphite light tokens */
}

/* Azure Skin */
[data-skin="azure"] {
  /* Azure dark tokens */
}
[data-skin="azure"][data-mode="light"] {
  /* Azure light tokens */
}
```

### Pre-Paint Initialization (Flicker Prevention)
To eliminate white/dark flash on page reload, `frontend/src/main.tsx` reads stored preferences synchronously from `localStorage` and stamps `data-skin`, `data-mode`, and `data-density` onto `document.documentElement` **before** React mounts. This approach is 100% CSP-safe and requires no inline script tags.

---

## 2. Shipped First-Class Skins

### 1. Graphite (Default)
- **Aesthetic**: Pure neutral dark theme with 0% blue chroma (`R=G=B`, `max(R,G,B)-min(R,G,B) == 0`) across all neutral tokens (surfaces, text, borders, hover, active, muted, terminal). Accent (`#2563eb`) and status tokens retain their respective emerald/status hues.
- **Surface Elevation**: `#141414` (page) < `#1a1a1a` (card) < `#1e1e1e` (muted) < `#222222` (hover) < `#262626` (elevated) < `#2b2b2b` (active).
- **Accents**: Modern electric cobalt (`#2563eb`), tuned to satisfy WCAG AA (5.17:1 against white text).
- **Ideal For**: Server operators, dark room administration, high-density monitoring.

### 2. Azure (Legacy Preserved)
- **Aesthetic**: Classic deep ocean slate-blue theme.
- **Surface Elevation**: `#0b1222` (page) < `#0f172a` (card) < `#131c31` (muted) < `#1e293b` (hover/elevated) < `#334155` (active).
- **Accents**: Sky cyan/blue (`#0369a1`), meeting WCAG AA (5.93:1 against white text).
- **Ideal For**: Users who prefer the familiar original ONX blue aesthetic.

### 3. Border Contrast Policy
All structural borders (`--border-default`, `--border-strong`, `--border-focus`) must maintain a minimum contrast ratio of **3.0:1** (WCAG AA non-text contrast) against all standard structural surfaces across both dark and light modes for all shipped skins:
- `--surface-page`
- `--surface-card`
- `--surface-elevated`
- `--surface-muted`

In dark mode:
- **Graphite**: `--border-default` is `#707070`, achieving 3.06:1 against `--surface-elevated` while strictly adhering to neutral chroma ($R=G=B=112$).
- **Azure**: `--border-default` is `#687385`, achieving 3.05:1 against `--surface-elevated`.

**Explicit Exclusions:**
- `--border-subtle`: Decorative low-contrast divider (table rows, card headers) where 3.0:1 contrast would create excessive visual noise.
- `--surface-hover` and `--surface-active`: Transient interactive states where hover brightness shift or active depress styling provides feedback rather than boundary contrast.

---

## 3. How to Add a Skin from One File

To add a new built-in skin (e.g., `emerald` or `amber`):

### Step 1: Define CSS Token Values in `src/index.css`
Append the new skin block at the bottom of `frontend/src/index.css`:
```css
/* Emerald Dark */
[data-skin="emerald"] {
  --surface-page: #09120e;
  --surface-card: #0f1c16;
  --surface-elevated: #1e352a;
  --surface-muted: #15271e;
  --surface-hover: #172b20;
  --surface-active: #223c30;
  --surface-overlay: rgba(0, 0, 0, 0.8);

  --text-primary: #ecfdf5;
  --text-secondary: #a7f3d0;
  --text-muted: #6ee7b7;
  --text-inverse: #09120e;
  --text-accent: #34d399;

  --border-subtle: #172b20;
  --border-default: #2d5a42;
  --border-strong: #3e7b5a;
  --border-focus: #10b981;

  --accent-primary: #059669;
  --accent-hover: #047857;
  --accent-active: #065f46;
  --accent-contrast-text: #ffffff;
}

/* Emerald Light */
[data-skin="emerald"][data-mode="light"] {
  --surface-page: #f0fdf4;
  --surface-card: #ffffff;
  --surface-elevated: #dcfce7;
  --surface-muted: #f0fdf4;
  --surface-hover: #f7fee7;
  --surface-active: #e2fcd8;
  --surface-overlay: rgba(0, 0, 0, 0.5);

  --text-primary: #064e3b;
  --text-secondary: #065f46;
  --text-muted: #047857;
  --text-inverse: #ffffff;
  --text-accent: #059669;

  --border-subtle: #d1fae5;
  --border-default: #a7f3d0;
  --border-strong: #6ee7b7;
  --border-focus: #059669;

  --accent-primary: #059669;
  --accent-hover: #047857;
  --accent-active: #065f46;
  --accent-contrast-text: #ffffff;
}
```

### Step 2: Register the Skin in `src/stores/uiStore.ts`
Add the skin identifier to `SkinId`:
```typescript
export type SkinId = "graphite" | "azure" | "emerald";
```

### Step 3: Run the Contrast Verifier
Run the automated contrast suite to verify all tokens meet WCAG AA requirements:
```bash
npm run test -- contrast.test.ts
```

That's it! The skin immediately appears in the TopBar skin switcher and applies smoothly across the entire application.

---

## 4. Custom Skin JSON Contract & Validator

The frontend provides a strict, zero-dependency JSON validator contract (`src/tokens/skinValidator.ts`) designed to validate user-provided or community-shared custom skins safely before applying them to the DOM.

### 4.1 Schema Definition
A custom skin JSON payload must conform to the following schema:
```json
{
  "id": "obsidian",
  "name": "Obsidian Dark",
  "description": "Deep obsidian theme for night administration",
  "tokens": {
    "surface-page": "#0d0d0d",
    "surface-card": "#141414",
    "surface-elevated": "#222222",
    "surface-muted": "#181818",
    "surface-hover": "#1a1a1a",
    "surface-active": "#2b2b2b",
    "text-primary": "#f5f5f5",
    "text-secondary": "#cccccc",
    "text-muted": "#888888",
    "text-inverse": "#000000",
    "border-subtle": "#222222",
    "border-default": "#444444",
    "border-strong": "#666666",
    "border-focus": "#7c3aed",
    "accent-primary": "#7c3aed",
    "accent-hover": "#6d28d9",
    "accent-active": "#5b21b6",
    "accent-contrast-text": "#ffffff"
  }
}
```

### 4.2 Security & Grammar Rules
The validator (`validateSkinJson`) strictly rejects:
1. **Size Limit**: Payloads exceeding 32 KB (enforced for both string and object input via serialization) are rejected.
2. **Prototype Pollution Protection**: Rejects `__proto__`, `constructor`, and `prototype` keys at root and token levels via strict own-property checks.
3. **Root Key Allowlist**: Rejects unknown root keys; allows only `id`, `name`, `description`, and `tokens`.
4. **Forbidden Syntax**: Any occurrence of `url(`, `;`, `{`, `}`, `<`, `>`, `javascript:`, or `expression(` causes immediate validation failure to prevent CSS injection.
5. **Token Allowlist**: Only explicitly recognized token keys matching `--color-*` or semantic token names (`surface-page`, `text-primary`, etc.) are allowed.
6. **Color Value Grammar**: Values must match valid `#RGB`, `#RRGGBB`, `#RRGGBBAA`, `rgb(...)`, `rgba(...)`, `hsl(...)`, or `hsla(...)` syntax with valid numeric ranges.
7. **Duplicate Keys**: Per ECMAScript specification for `JSON.parse()`, duplicate property keys within a JSON payload resolve with last-wins semantics. The validator operates on the resulting parsed JavaScript object.

### 4.3 Validation API
```typescript
import { validateSkinJson } from "@/tokens/skinValidator";

const result = validateSkinJson(rawJsonString);
if (result.valid) {
  console.log("Skin is safe:", result.skin);
} else {
  console.error("Invalid skin:", result.errors);
}
```
All validation rules are tested in `src/tokens/skinValidator.test.ts`.
