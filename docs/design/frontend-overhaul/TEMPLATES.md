# Standardized Page Templates & Layout Guidelines

To eliminate ad-hoc layouts and fragmented design, the ONX Manager frontend organizes all views into **seven standardized page templates**.

---

## Template Matrix

| Template | Primary Pages | Density | Key Components |
|---|---|---|---|
| **1. Fleet / List** | `ServersPage`, `PluginListPage`, `BackupListPage`, `ServerModsPage` | Compact | `PageHeader`, `Table`, `Pagination`, `StatusBadge`, `ConfirmDialog` |
| **2. Server Console & Overview** | `ServerConsole`, `ServerDetailPage` | Mixed | `ServerShell`, Identity Strip, Quick Actions, Metric Sparklines, Live Log Terminal |
| **3. Master-Detail / Explorer** | `ServerFilesPage`, `ServerVersioningPage` | Compact | Path Breadcrumb, Dual-pane/Drawer, Split View, Toolbar |
| **4. Settings / Form** | `SettingsPage`, `ServerSettingsPage`, `ApiKeysPage` | Comfortable | Card Sections, Descriptive Form Groups, Toggle Switches, Save Banners |
| **5. Step-by-Step Wizard** | `CreateServerPage`, `ImportServerPage` | Comfortable | Progress Stepper, Form Cards, Collapsible Disclosure Sections, Sticky Bottom Actions |
| **6. Marketplace & Catalog** | `PluginMarketplacePage`, `PluginDetailPage` | Mixed | Search Filter Bar, Multi-column Cards Grid, Detail Readme Viewer |
| **7. Authentication** | `LoginPage`, `RegisterPage` | Comfortable | Centered Auth Card, Vortex Brand Header, Clean Form Controls, Legal Disclaimer |

---

## 1. Fleet / List Template

### Purpose
High-density overview of multi-instance fleets, add-ons, or backups, optimized for quick scanning and batch operations.

### Structure
1. **`PageHeader`**: Clear page title, entity count badge, contextual actions (e.g. "Create Server", "Add Backup") in the right action slot.
2. **Filter & Search Bar**: Integrated search input, status pills (Online, Starting, Crashed, Stopped), and sort controls.
3. **Density-Aware Table**:
   - Compact row height (`32px` in compact mode).
   - Columns: Status indicator + name, essential metadata (software, port, version), and right-aligned quick actions.
   - Truncated text with full titles available on hover.
4. **Standard `Pagination`**: Centered or justified pagination controls when records exceed page size (10–25 items).
5. **State Handling**:
   - `Skeleton`: Displays animated rows matching table columns during data fetch.
   - `EmptyState`: Contextual illustration, friendly title, and primary creation button when 0 items match.
   - `ErrorState`: Clear error description with a "Retry" button.

---

## 2. Server Console & Live Overview Template

### Purpose
Real-time monitoring, telemetry, and live interactive control of an individual Minecraft server instance.

### Structure
1. **`ServerShell` Identity Strip**:
   - Server name, active status badge, software/version chip, connection address chip.
   - Power action bar: Start, Stop, Restart buttons with loading spinners during state transitions.
   - Essential facts summary: Port, uptime, memory, CPU load.
2. **Unified Navigation**: Left-hand sidebar categorizing server operations (Overview, Console, Files, Add-ons, Versioning, Settings).
3. **Console Terminal**:
   - Full-height ANSI terminal container (`bg-[#0c0d0e]` canvas).
   - WebSocket streaming logs with automatic reconnect and auto-scroll locking.
   - **Visibility Re-tail**: When navigating back from another tab or resuming a background window, the console immediately repaints missed lines from the HTTP log cache.
   - Quick command input bar at the bottom with command history traversal.

---

## 3. Master-Detail / Explorer Template

### Purpose
Navigating hierarchical data structures (directory trees, Git version history, file trees).

### Structure
1. **Top Path Toolbar**: Interactive directory breadcrumb with direct jump navigation and search query filter.
2. **Explorer View**:
   - Table view with file type icons, name, file size, modification timestamp, and actions (Download, Rename, Delete).
   - Instant client-side search filtering by filename.
   - Client-side pagination preventing DOM bloat in directories with 100+ files.
3. **Slide-over / Modal Detail**:
   - In-house syntax-highlighted `CodeEditor` slide-over for quick configuration editing without leaving the directory view.
   - Unsaved change warning modal before navigation.

---

## 4. Settings / Form Template

### Purpose
System and server configuration, account security, API key management, and integration controls.

### Structure
1. **Header**: Section title and scope indicator.
2. **Grouped Card Sections**: Each setting domain is encapsulated in an individual `surface-card` with:
   - Section title and secondary helper explanation.
   - Well-spaced input fields (`comfortable` density, `40px` touch targets).
   - Contextual toggle switches, select dropdowns, and file pickers.
3. **Action Footer / Sticky Save Bar**:
   - "Save Changes" and "Reset to Defaults" buttons.
   - Immediate feedback via inline toast notification.

---

## 5. Step-by-Step Wizard Template

### Purpose
Multi-phase onboarding and creation flows (e.g., creating a server from scratch or importing an existing archive).

### Structure
1. **Header Stepper**: Visual step indicator showing completed, active, and upcoming stages.
2. **Focused Step View**:
   - Step 1: Software & Version selection.
   - Step 2: System sizing & Port assignment.
   - Step 3: Server properties & EULA acceptance (advanced settings collapsed by default).
   - Step 4: Final review card before execution.
3. **Navigation Footer**:
   - "Back" button on the left.
   - "Next" / "Create" primary button on the right with validation checks disabled until required inputs are valid.

---

## 6. Marketplace & Catalog Template

### Purpose
Discovering, browsing, and installing plugins, mods, and add-ons from external ecosystems (SpigotMC, Modrinth, PaperMC).

### Structure
1. **Search & Filter Header**: Platform toggle (Paper/Purpur vs Fabric/Forge), category filter chips, search input.
2. **Card Grid**: Responsive 1/2/3-column card grid displaying addon icon, title, description, download counter, and "Install" button.
3. **Detail Modal / Drawer**: Markdown readme viewer, version compatibility checklist, and changelog history.

---

## 7. Authentication Template

### Purpose
User login, initial instance registration, and invite token redemption.

### Structure
1. **Centering Viewport**: Minimalist backdrop centered both horizontally and vertically.
2. **Brand Lockup**: Prominent vortex logo mark and "ONX Manager" wordmark.
3. **Auth Card**: Elevated surface card with clean input fields, password reveal toggle, and primary submit button.
4. **Legal Footer**: Official disclaimer notice: *"Unofficial. Not affiliated with or endorsed by Mojang or Microsoft."*

---

## 8. Application Shells & Landmark Accessibility Architecture

### Purpose
Provide a unified, accessible structural scaffolding for all views across `AppShell` (global application routes) and `ServerShell` (contextual server instance routes).

### Structure & Accessibility Contracts
1. **Skip-to-Content Link**:
   - Both `AppShell` and `ServerShell` render `<a href="#main-content">` as the **first focusable element** in the DOM.
   - Visually hidden via Tailwind `sr-only` until keyboard focused (`focus:not-sr-only focus:fixed focus:inset-block-start-3 focus:inset-inline-start-3 focus:z-50`).
   - Uses token styling (`bg-surface-elevated text-accent-primary focus-visible:ring-2 focus-visible:ring-border-focus`).
   - Targets `<main id="main-content" tabIndex={-1}>` and programmatically transfers focus on activation.
2. **Distinct Navigation Landmarks**:
   - Every `<nav>` in the application exposes a distinct `aria-label`:
     - Global navigation in Sidebar: `aria-label="Main"`.
     - Contextual server navigation in Sidebar: `aria-label="Server sections"`.
     - Breadcrumbs in ServerShell: `aria-label="Breadcrumb"`.
     - Breadcrumbs in PageHeader: `aria-label="Breadcrumbs"`.
     - Pagination controls: `aria-label="Pagination"`.
     - Editor breadcrumbs in ServerFilesPage: `aria-label="Editor breadcrumb"`.
   - Active links in Sidebar render `aria-current="page"`.
3. **Sidebar Off-Canvas (Mobile Drawer)**:
   - On mobile viewports (`< 1024px`), opening the drawer activates `useBodyScrollLock(mobileSidebarOpen)` via `frontend/src/hooks/useBodyScrollLock.ts`.
   - On open: captures `document.activeElement` (the opener toggle button) and moves focus to the first focusable navigation item inside the drawer.
   - On close: dismisses on `Escape` key press or backdrop click, restores body scroll, and returns focus to the opener element.
   - On desktop (`lg:w-56`, `>= 1024px`): drawer is persistently docked; does not trigger body scroll locks or register `Escape` key dismissal.
4. **Overlay Note**:
   - Non-primitive overlays have since been consolidated to `Modal` / `ConfirmDialog` (verified by `overlayRatchet.test.ts`).

