# ONX Manager — Brand Identity & Visual Guidelines (Phase 7)

## 1. Brand Mark & Wordmark

### The Vortex Swirl Mark
The ONX Manager brand mark is an abstract geometric vortex representing centralized orchestration, dynamic event flow, and server lifecycle convergence.

- **Geometry**: Constructed from two reciprocal logarithmic spiral arms rotating around a core singularity node with 4 orbital data points.
- **Form**: Pure mathematical SVG curves. Scalable from 16px favicon up to billboards without loss of clarity.
- **Coloration**:
  - Themed adaptively through semantic tokens (`var(--accent-primary)`, `var(--border-focus)`, `var(--text-accent)`).
  - Responsive to runtime skins: Deep Indigo/Blue in Azure, Neutral Electric Blue in Graphite.
  - Supports strict `monochrome` mode via `fill="currentColor"` and `stroke="currentColor"`.

### The Wordmark
- **"ONX"**: Bold, geometric, uppercase, tight tracking, `font-black text-text-primary`.
- **"Manager"**: Clean, geometric, light weight, open tracking, `font-light text-text-secondary`.

### Permitted Lockups
1. **Full Lockup (`variant="full"`)**: Vortex mark preceding the "ONX Manager" typography. Used in TopBar, authentication headers, and splash screens.
2. **Mark Only (`variant="mark"`)**: Solo vortex mark. Used in collapsed sidebars, browser favicon, and compact avatars.
3. **Wordmark Only (`variant="wordmark"`)**: Pure typographical wordmark for dense inline text contexts.

---

## 2. Abstract Voxel Artwork & Minecraft Flavor Guardrails

### Core Philosophy
ONX Manager is built for the Minecraft server ecosystem, but **must never infringe upon or copy Mojang/Microsoft intellectual property**. We invoke the blocky, voxel-based architectural spirit through **original abstract geometric pixel/voxel art**.

### Strict Negative Constraints (NON-NEGOTIABLE)
- **NO Creeper faces or silhouettes**
- **NO Grass block or dirt block pixel textures**
- **NO Swords, pickaxes, axes, or tools from Minecraft**
- **NO Mob art (zombies, skeletons, endermen, pigs, etc.)**
- **NO Minecraft logo look-alike lettering or stone-block fonts**
- **NO Redstone wire, TNT, or potion graphics**

### Permitted Abstract Voxel Design Rules
1. **Grid-Aligned Rectangles**: All voxel art is composed of pure crisp rectangles or isometric rhombi (`shapeRendering="crispEdges"`).
2. **Abstract Topography & Strata**: Geometric ridges, floating island silhouettes, and tiered data spires.
3. **Token Palette Shading**: Voxels are rendered with opacity gradients (`0.10` to `0.80`) over `currentColor` and accent tokens, adapting cleanly to Graphite Dark, Azure, and Light modes.

---

## 3. Domain Icon Set

The following 9 core domain concepts have dedicated, themed icons integrated into the unified `@/components/ui/Icon`:

| Domain Concept | Icon Name | Metaphor |
|---|---|---|
| Server Node | `server` | Tiered rack blade server with status LED indicators |
| World Materialization | `world` | Geometric global grid sphere with orbital latitude/longitude lines |
| Plugin Extension | `plugin` | Interlocking plug prongs / dynamic socket bridge |
| Mod Modification | `mod` | Isometric 3D voxel block cube with faceted faces |
| Server Backup | `backup` | Tiered cylindrical database disks with snapshot retention curve |
| Live Terminal | `console` | Command-line chevron prompt (`>`) with active cursor line |
| File Explorer | `files` | Overlapping document leaves with folded corner geometry |
| Network & Exposure | `network` | Distributed 3-node topology connected by bidirectional data links |
| Git Versioning | `version-branch` | Source commit timeline forking into an active feature branch |

---

## 4. Legal Attribution & Suggested README Wording

Per governance requirements and trademark policies, the following disclaimer is displayed across the application footer and sidebar:

> **"Unofficial. Not affiliated with or endorsed by Mojang or Microsoft."**

### Suggested README Placement (Do Not Edit Root README Directly)
When updating documentation or public distribution packages, include the following block in the repository README:

```markdown
### Legal Disclaimer
ONX Manager is an open-source, independent server management platform.
Minecraft is a trademark of Mojang Synergies AB / Microsoft Corporation.
ONX Manager is unofficial software and is NOT affiliated with, endorsed by, or sponsored by Mojang, Microsoft, or any Minecraft brand partners.
```
