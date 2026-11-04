# Minecraft-Flavored Visual Guardrails & IP Policy

This document defines the visual boundaries and intellectual property guardrails for ONX Manager.

---

## 1. Aesthetic Philosophy: Abstract Voxel Architecture

ONX Manager is a professional server operations platform, not a toy. Its visual identity celebrates Minecraft's underlying computational and voxel nature through **abstract isometric geometry, crisp pixel grids, and high-contrast technical surfaces**, rather than kitschy cartoons or game rips.

### The Three Visual Pillars:
1. **Geometric Precision**: Clean 30-degree isometric angles, wireframes, and voxel grids.
2. **Crisp Edge Rendering**: Pure vector geometry (`shape-rendering="crispEdges"`) that looks sharp on high-DPI displays without pixel blur.
3. **Restrained Atmosphere**: Subtle glowing accent nodes and dark technical backdrops, prioritizing operator legibility over decorative clutter.

---

## 2. Absolute Non-Negotiables: Negative Constraints

To ensure zero intellectual property risk and maintain professional software standards, the following are **strictly forbidden**:

| Category | Strictly Forbidden Assets | Permitted Alternatives |
|---|---|---|
| **Logos & Marks** | Mojang AB logo, Microsoft logo, Minecraft logo, Minecraft Java/Bedrock edition badges. | Original ONX Manager vortex swirl wordmark. |
| **Mob & Character Art** | Creeper faces, Steve, Alex, Zombies, Endermen, Pigs, or any mob silhouette or face. | Abstract multi-tier server towers, isometric node clusters. |
| **Item & Tool Textures** | Swords, pickaxes, axes, shovels, bows, potions, chests, redstone dust, ingots. | Semantic domain icons (terminal console, Git branch, puzzle block, directory folder). |
| **Block Textures** | Grass block tops/sides, dirt, cobblestone, bedrock, obsidian, crafting table textures. | Geometric isometric cubes shaded with mathematically derived light angles. |
| **Typography** | Pixelated bitmap fonts mimicking the Minecraft in-game typography (e.g. "Minecraftia", Mojangles). | Clean modern system typography (`font-sans`, `font-mono`: JetBrains Mono / Cascadia Code). |
| **Audio** | Any in-game sound effects (level up, chest opening, anvil, hurt sound). | Completely silent operation; feedback via toasts and motion. |

---

## 3. Approved Graphic Standards

### 3.1 Abstract Isometric Voxel Banners
All decorative banners (e.g., `VoxelBanner.tsx` on the Dashboard and Auth pages) must follow these rules:
- Built strictly from SVG `<polygon>` or `<rect>` coordinates using standard isometric projections:
  - Top face: Diamond polygon with direct highlight lighting.
  - Left face: 30-degree sheared polygon with ambient fill.
  - Right face: 30-degree sheared polygon with shadowed fill.
- Uses semantic CSS variables or theme-derived color ramps (`accent-primary`, `surface-panel`, `border-subtle`).
- Zero raster PNG/JPEG images.

### 3.2 Themed Domain Icons
Domain icons in `Icon.tsx` evoke server operations through stylized, abstract modular motifs:
- **Server**: Multi-layer blade server chassis with isometric status indicator LEDs.
- **World**: Wireframe isometric globe grid denoting map and terrain storage.
- **Plugin**: Interlocking square socket unit denoting extensible API modules.
- **Mod**: Hexagonal module denoting client/server engine bytecode hooks.
- **Backup**: Hardened polygonal shield safeguarding archival data snapshots.
- **Console**: Monospace terminal bracket with interactive chevron cursor.

---

## 4. Mandatory Legal Disclaimer

Every public surface of ONX Manager must present the standard legal disclaimer:

> **"Unofficial. Not affiliated with or endorsed by Mojang or Microsoft."**

### Placement Requirements:
1. **Sidebar Navigation**: Rendered at the bottom of the navigation drawer in `frontend/src/components/layout/Sidebar.tsx`.
2. **Authentication Screens**: Centered in muted text at the footer of `LoginPage.tsx` and `RegisterPage.tsx`.
3. **Documentation & README**: Clearly stated in the project introductory documentation.
