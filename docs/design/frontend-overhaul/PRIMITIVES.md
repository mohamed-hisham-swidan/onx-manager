# Shared UI Primitives Catalog & API Reference

All shared UI components reside in `frontend/src/components/ui/`. They are strictly token-driven, density-aware, and tested for accessibility and keyboard navigation.

---

## Catalog Overview

| Primitive | File | Key Role & Accessibility |
|---|---|---|
| `Button` | `Button.tsx` | Standard interactive button with primary, secondary, danger, and ghost variants. Native button semantics, focus rings. |
| `IconButton` | `Button.tsx` | Compact icon-only button. Requires explicit `aria-label` for screen reader accessibility. |
| `Chip` | `Chip.tsx` | Metadata badge with removable button or link support. |
| `StatusBadge` | `StatusBadge.tsx` | Server lifecycle status indicator combining icon, color, and text (never color alone). |
| `LoaderBadge` | `LoaderBadge.tsx` | Software / engine pill (Paper, Purpur, Fabric, Forge, NeoForge, Spigot, Vanilla). |
| `PageHeader` | `PageHeader.tsx` | Consistent layout header with title, subtitle, breadcrumbs, and right-aligned actions. |
| `Pagination` | `Pagination.tsx` | Accessible page switcher with Prev/Next buttons, active page indicators, and ellipses. |
| `Banner` | `Banner.tsx` | Contextual notification bar with success, warning, danger, and info variants. |
| `Table` | `Table.tsx` | Semantic HTML table (`<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`) supporting compact density. |
| `Tabs` | `Tabs.tsx` | Accessible tab switcher with `role="tablist"`, `role="tab"`, and keyboard navigation. |
| `Modal` | `Modal.tsx` | Accessible dialog with `role="dialog"`, `aria-modal="true"`, focus trap, and Escape key dismissal. |
| `ConfirmDialog` | `ConfirmDialog.tsx` | Specialized confirmation modal with danger/warning/info variants and default cancel focus. |
| `StatCard` | `StatCard.tsx` | Metric summary card displaying value, unit, change indicator, and optional sparkline. |
| `LoadingBar` | `LoadingBar.tsx` | Indeterminate or progress-driven top loading indicator during asynchronous operations. |
| `Toaster` | `Toaster.tsx` | Global toast notification container with auto-dismiss and stack management. |
| `EmptyState` | `States.tsx` | Empty container placeholder with voxel/domain icon, title, description, and action button. |
| `ErrorState` | `States.tsx` | Error container with retry button and error details. |
| `Skeleton` | `States.tsx` | Content placeholder skeleton with subtle pulse animation for loading states. |
| `ForbiddenState` | `States.tsx` | 403 Forbidden screen informing users of insufficient permissions. |
| `Icon` | `Icon.tsx` | Centralized SVG icon component with 40+ curated icons, including custom domain voxel icons. |

---

## Detailed Primitives Reference

### 1. `Button` & `IconButton`
```tsx
import { Button, IconButton } from "@/components/ui/Button";

// Primary action
<Button variant="primary" size="md" onClick={handleSave}>Save Changes</Button>

// Destructive action
<Button variant="danger" size="sm" onClick={handleDelete}>Delete Server</Button>

// Accessible icon-only button
<IconButton icon="settings" aria-label="Open server settings" onClick={openSettings} />
```
- **Variants**: `primary`, `secondary`, `danger`, `ghost`.
- **Sizes**: `sm` (32px), `md` (40px), `lg` (48px).
- **Accessibility**: Includes `:focus-visible` ring with `var(--border-focus)`. `IconButton` mandates `aria-label`.

---

### 2. `Modal` & `ConfirmDialog`
```tsx
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

// Standard dialog
<Modal open={isOpen} onClose={() => setIsOpen(false)} title="Edit Configuration" size="lg">
  <p>Modal body content</p>
</Modal>

// Destructive confirmation
<ConfirmDialog
  open={isConfirmOpen}
  title="Delete Server"
  description="This will permanently delete 'Survival SMP' and its world files. This action cannot be undone."
  variant="danger"
  confirmLabel="Delete Permanently"
  onConfirm={handleConfirmedDelete}
  onCancel={() => setIsConfirmOpen(false)}
/>
```
- **Modal Props**:
  | Prop | Type | Default | Description |
  |---|---|---|---|
  | `open` | `boolean` | **Required** | Controls dialog visibility and mounts/unmounts the modal container. |
  | `onClose` | `() => void` | **Required** | Callback triggered on Escape, close button click, or backdrop click. |
  | `title` | `ReactNode` | `undefined` | Header title string or element linked via `aria-labelledby`. |
  | `description` | `ReactNode` | `undefined` | Subtitle description linked via `aria-describedby`. |
  | `children` | `ReactNode` | **Required** | Dialog content and body controls. |
  | `footer` | `ReactNode` | `undefined` | Dialog footer containing primary/secondary actions. |
  | `size` | `"sm" \| "md" \| "lg" \| "xl" \| "2xl"` | `"md"` | Max width constraint (`sm` max-w-sm, `md` max-w-md, `lg` max-w-lg, `xl` max-w-2xl, `2xl` max-w-3xl). |
  | `closeOnBackdrop` | `boolean` | `true` | When `true`, clicking the backdrop invokes `onClose`. Set to `false` for multi-field forms or destructive flows where an accidental backdrop click would discard uncommitted user inputs. |
  | `closeOnEscape` | `boolean` | `true` | When `true`, pressing Escape key triggers `onClose`. Set to `false` (e.g. `closeOnEscape={!isPending}`) during active async mutations to guard against dismissal while an operation is in flight. |
  | `closeButtonAriaLabel`| `string` | `"Close dialog"` | Accessible name for the header close icon button (`aria-label`). |
- **Accessibility**: Rendered with `role="dialog"`, `aria-modal="true"`. Traps keyboard focus inside the dialog while open. Closes automatically on `Escape`. Restores focus to the triggering element upon close.
  - **Shared Body Scroll Lock (`useBodyScrollLock`)**: Automatically locks body scroll (`document.body.style.overflow = "hidden"`) while active via the shared hook `useBodyScrollLock(active)` in `frontend/src/hooks/useBodyScrollLock.ts`. Uses a module-level reference counter so nested or stacked dialogs and mobile off-canvas drawers only restore the previous body overflow after the last active consumer releases.
  - **ConfirmDialog Focus Safety**: For `variant="danger"`, initial focus is placed on the Cancel button to protect against accidental confirmation via Enter/Space. Non-danger variants (`warning`, `info`) keep initial focus on the Confirm button.

---

### 3. `StatusBadge`
```tsx
import { StatusBadge } from "@/components/ui/StatusBadge";

<StatusBadge status="running" />
<StatusBadge status="crashed" size="sm" />
```
- **Statuses Supported**: `running`, `online`, `stopped`, `offline`, `starting`, `stopping`, `crashed`, `error`, `creating`, `updating`.
- **Accessibility**: Always renders both an icon and a text label alongside the status color (satisfying WCAG 1.4.1 Use of Color).

---

### 4. `Table`
```tsx
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/Table";

<Table density="compact">
  <TableHeader>
    <TableRow>
      <TableHead>Server Name</TableHead>
      <TableHead>Software</TableHead>
      <TableHead>Port</TableHead>
      <TableHead className="text-right">Actions</TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    {servers.map((s) => (
      <TableRow key={s.id}>
        <TableCell className="font-medium text-text-primary">{s.name}</TableCell>
        <TableCell>{s.loader}</TableCell>
        <TableCell>{s.port}</TableCell>
        <TableCell className="text-right">...</TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```
- **Density**: Supports `density="compact"` (32px row height) and `density="comfortable"` (48px row height).
- **Semantics & Accessibility**:
  - Uses standard HTML table tags (`<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`).
  - All header cells include `scope="col"`.
  - Sortable headers expose `aria-sort="ascending" | "descending"` when active, and `aria-sort="none"` when inactive.
  - Sortable headers are fully keyboard operable (`tabIndex={0}`, toggling sort on `Enter` and `Space`) with `:focus-visible` ring indicators. Non-sortable headers omit `tabIndex` and `aria-sort`.

---

### 5. `Pagination`
```tsx
import { Pagination } from "@/components/ui/Pagination";

<Pagination
  currentPage={currentPage}
  totalPages={totalPages}
  onPageChange={(page) => setCurrentPage(page)}
  pageSize={20}
  totalItems={totalCount}
/>
```
- **Accessibility**: Wraps in `<nav aria-label="Pagination">`. Uses `aria-current="page"` on the active page button. Disables Prev/Next buttons on boundary pages.

---

### 6. `Tabs`
```tsx
import { Tabs } from "@/components/ui/Tabs";

<Tabs
  value={activeTab}
  onChange={setActiveTab}
  items={[
    { id: "overview", label: "Overview", icon: "dashboard" },
    { id: "files", label: "Files", icon: "folder", count: 12 },
    { id: "settings", label: "Settings", icon: "settings" },
  ]}
/>
```
- **Accessibility & Keyboard Navigation**:
  - Encapsulated in container with `role="tablist"` and configurable `ariaLabel`.
  - Individual tabs render `role="tab"` with `aria-selected` and roving `tabIndex` (`0` for selected tab, `-1` for unselected tabs).
  - Fully keyboard operable: `ArrowRight` and `ArrowLeft` cycle between enabled tabs; `Home` and `End` jump directly to the first and last enabled tab.
  - Omit dangling `aria-controls` references when consumer views manage their own panel transitions without coordinated ID tokens.

---

### 7. `States` (`EmptyState`, `ErrorState`, `Skeleton`, `ForbiddenState`)
```tsx
import { EmptyState, ErrorState, Skeleton, ForbiddenState } from "@/components/ui/States";

// Empty listing
<EmptyState
  icon="server"
  title="No servers found"
  description="You haven't created any Minecraft servers yet. Get started in minutes."
  action={<Button variant="primary" onClick={handleCreate}>Create Server</Button>}
/>

// Fetch error
<ErrorState
  message="Failed to load server files from disk."
  onRetry={fetchFiles}
/>

// Loading skeleton
<Skeleton className="h-10 w-full" count={5} />

// Permission error
<ForbiddenState description="You do not have administrative privileges to manage API keys." />
```

---

### 7. `Icon` & Domain Icons
```tsx
import { Icon } from "@/components/ui/Icon";

<Icon name="server" size={20} />
<Icon name="console" size={18} className="text-accent-primary" />
```
- Custom domain icons:
  - `server`: Voxel server rack node.
  - `world`: Isometric wireframe globe grid.
  - `plugin`: Interlocking modular puzzle unit.
  - `mod`: Hexagonal expansion module.
  - `backup`: Hardened archive shield.
  - `console`: Terminal shell prompt (`>_`).
  - `files`: Tabbed directory folder.
  - `network`: Multi-node port topology.
  - `version-branch`: Dual-node Git branch fork.
