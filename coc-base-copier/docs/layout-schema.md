# CoC Base Copier — Canonical Layout Schema

`schema_version: "1.1.0"`

> **v1.1.0** — vision now returns building **pixel centers only**; the detector
> converts them to tiles via the calibrated grid, centers each type's
> **footprint** (`BUILDING_FOOTPRINTS` in `schema.py`) on that center tile, and
> resolves overlaps by clamping/nudging or skipping. Each object gains
> `pixel_x`, `pixel_y` (raw vision output) and `footprint_w`, `footprint_h`.

This document defines the JSON produced by the **detector** (`src/copy/detect.py`)
and consumed by the future **paster**. It is the contract between the two halves
of the base-copier. Treat it as append-only: add fields, never silently
repurpose existing ones, and bump `schema_version` on any breaking change.

The reference Python implementation of this schema lives in
[`src/copy/schema.py`](../src/copy/schema.py). The dataclasses there are the
source of truth; this document explains the *why*.

---

## 1. The 44×44 tile grid

Clash of Clans villages are built on a square playable area. We model it as a
**44×44 grid of tiles**, `tile_x ∈ [0, 43]` and `tile_y ∈ [0, 43]` (1936 tiles
total). A 1×1 building occupies exactly one `(tile_x, tile_y)`; larger buildings
are anchored at their **lowest-indexed (top) tile** (see `footprint`).

### Origin convention

On screen the village is an isometric **diamond**. Its four pixel corners are,
clockwise from the top: **top → right → bottom → left**. We bind them to the
grid like this:

```
                 top corner
              (tile 0,0)  *
                        /   \
                      /       \
      left corner   *           *   right corner
   (tile 0,43)        \       /        (tile 43,0)
                        \   /
                          *
                  bottom corner
                   (tile 43,43)
```

- **Origin `(0,0)` is the TOP corner** of the diamond.
- **`tile_x` increases toward the RIGHT corner** (visually down-and-right).
- **`tile_y` increases toward the LEFT corner** (visually down-and-left).
- The **bottom** corner is `(43,43)`.

This is a right-handed grid in "screen-isometric" space and is fully defined by
the homography from the four detected corners (see `src/copy/grid.py`). Any
producer/consumer that agrees on these four corner->tile bindings will agree on
every tile. **Pixel coordinates never appear in the layout JSON** — only tiles —
so the layout is resolution-independent and idempotent.

> Why the top corner? It is the unambiguous minimum of both axes, so
> `(0,0)` is always the same physical place regardless of zoom or screenshot
> crop. The paster reverses the same homography in the village editor.

---

## 2. Top-level object

```jsonc
{
  "schema_version": "1.1.0",
  "source": {
    "kind": "screenshot",              // screenshot | device | clan_chat | war | fc
    "image_id": "sha256:ab12...",      // stable hash of the source image, for dedupe/idempotency
    "captured_at": "2026-06-22T12:00:00Z",
    "image_width": 1920,
    "image_height": 1080
  },
  "town_hall_level": 15,               // best-effort; null if not detected
  "grid": {
    "size": 44,                         // always 44 for current game versions
    "corners_px": {                     // the 4 detected diamond corners, debug-only
      "top":    [960, 120],
      "right":  [1700, 540],
      "bottom": [960, 960],
      "left":   [220, 540]
    },
    "corner_confidence": 0.94           // 0..1 from grid registration; <0.7 => rejected
  },
  "objects": [ /* Object[] — see section 3 */ ],
  "wall_chains": [ /* WallChain[] — see section 4 */ ],
  "warnings": [ /* string[] — non-fatal: low-confidence drops, occlusions, etc. */ ],
  "stats": {
    "object_count": 87,
    "wall_piece_count": 250,
    "trap_count": 12,
    "low_confidence_count": 3
  }
}
```

`source.image_id` makes the pipeline **idempotent**: re-running the detector on
the same bytes yields the same `image_id` and (with `temperature=0`) the same
layout.

---

## 3. Object (building / trap / obstacle / decoration)

Every non-wall placeable is one `Object`. **Walls are NOT listed here** — they
go in `wall_chains` (section 4), because the paster places wall *segments*, not
pieces.

```jsonc
{
  "id": "obj_0007",                 // stable within a layout; "obj_%04d" in detection order
  "category": "defense",            // defense | resource | army | trap | obstacle | decoration
  "type": "cannon",                 // canonical snake_case type key (see section 6)
  "level": 14,                      // integer; null if unreadable (logged in warnings)
  "pixel_x": 812,                   // raw vision output: object center X in image pixels
  "pixel_y": 460,                   // raw vision output: object center Y in image pixels
  "tile_x": 20,                     // 0..43, footprint anchor (top tile), computed from pixel+grid
  "tile_y": 17,                     // 0..43, footprint anchor (top tile)
  "footprint": [3, 3],              // [w, h] in tiles (from BUILDING_FOOTPRINTS)
  "footprint_w": 3,                 // mirror of footprint[0]
  "footprint_h": 3,                 // mirror of footprint[1]
  "rotation": 0,                    // degrees, one of 0|90|180|270. Most buildings: 0.
  "is_trap": false,                 // convenience mirror of category=="trap"
  "confidence": 0.91,               // 0..1 model confidence for this detection
  "notes": null                     // optional free text (e.g. "partially occluded")
}
```

### Field rules

| field        | required | notes |
|--------------|----------|-------|
| `id`         | yes | unique within the layout |
| `category`   | yes | one of the 6 enums; drives paster behavior |
| `type`       | yes | canonical key; unknown types allowed but flagged in `warnings` |
| `level`      | no  | `null` allowed, never invented — a guessed level is worse than a known gap |
| `pixel_x/y`  | yes | raw vision center in image pixels; the detector's input to `grid.pixel_to_tile` |
| `tile_x/y`   | yes | integer, `0..43`, **footprint anchor (top tile)** = center tile minus `(footprint-1)//2`, clamped/nudged in-bounds |
| `footprint`  | yes | `[w,h]` tiles from `BUILDING_FOOTPRINTS`; the footprint is centered on the detected center tile |
| `footprint_w/h` | yes | scalar mirrors of `footprint` for convenience |
| `rotation`   | yes | `0/90/180/270`; only a few objects (e.g. some traps, x-bows) use non-zero |
| `confidence` | yes | detections `< 0.7` are re-asked, then either resolved or surfaced in `warnings` — **never silently dropped** |

### Coordinate pipeline & collision robustness (v1.1.0)

Vision reports only **pixel centers** (`pixel_x`, `pixel_y`) — it never does tile
or footprint math (it's unreliable at that). The detector then, per object:

1. `grid.pixel_to_tile(pixel_x, pixel_y)` -> the **center tile** (clamped 0..43);
2. looks up `(footprint_w, footprint_h)` from `BUILDING_FOOTPRINTS`;
3. anchors the footprint **centered** on the center tile
   (`anchor = center - (footprint-1)//2`), clamped so it stays fully in-bounds;
4. resolves overlaps: try the spot, then nudge up to 3 tiles; if still blocked,
   **skip** the building and log a warning;
5. **walls** are 1x1 — any wall tile that lands on a building tile is skipped
   (logged), never failing the whole layout.

The run only fails if **more than 10%** of buildings had to be skipped. This
makes the detector tolerant of vision's imperfect centering instead of
rejecting an entire otherwise-good layout over one overlap.

### Categories

- **defense** — cannon, archer_tower, mortar, wizard_tower, air_defense, x_bow,
  inferno_tower, eagle_artillery, scattershot, air_sweeper, bomb_tower,
  monolith, spell_tower, town_hall (TH is `defense` because it shoots in modern
  versions), builder_hut.
- **resource** — gold_mine, elixir_collector, dark_elixir_drill, gold_storage,
  elixir_storage, dark_elixir_storage, clan_castle.
- **army** — barracks, dark_barracks, army_camp, laboratory, spell_factory,
  dark_spell_factory, pet_house, blacksmith, hero altars (king/queen/warden/
  champion/minion_prince).
- **trap** — see section 5.
- **obstacle** — tree, bush, rock, gem_box, log, trunk (removable scenery).
- **decoration** — flags, statues, cosmetics (never functional).

---

## 4. Wall chains

The paster needs **segments**, not 250 individual wall pieces, so it can drag a
continuous wall in one gesture. The detector groups connected wall tiles into
chains.

```jsonc
{
  "id": "wall_03",
  "level": 15,                       // dominant level along the chain; per-piece overrides below
  "tiles": [[10,10],[11,10],[12,10],[12,11]],  // ordered path of (tile_x, tile_y)
  "closed": false,                   // true if it forms a loop (last connects to first)
  "piece_levels": null,              // optional int[]: per-tile level when mixed; else null
  "confidence": 0.88
}
```

### Rules

- Each `tiles` entry is a single 1×1 wall tile in `0..43`.
- Tiles in a chain are **8-connected** (orthogonal or diagonal adjacency).
- `tiles` is ordered as a walk along the chain so the paster can stroke it;
  branch points split into multiple chains that share an endpoint tile.
- A chain's tile must not also appear as an `Object` tile.
- `level` is the most common piece level; when pieces differ, populate
  `piece_levels` (same length/order as `tiles`).
- Total wall tiles across all chains must be sane (see section 7).

---

## 5. Traps (flagged separately)

Traps are **invisible in the normal village view** but visible in the editor.
The detector therefore:

1. Lists each detected trap as an `Object` with `category:"trap"` and
   `is_trap:true`.
2. Always sets `confidence` honestly — traps are low-signal in a normal
   screenshot and will frequently be `< 0.7`, which routes them to a re-ask and,
   if still unsure, into `warnings` rather than being dropped.

Trap types: `bomb`, `spring_trap`, `giant_bomb`, `air_bomb`, `seeking_air_mine`,
`skeleton_trap`, `tornado_trap`.

> If the source screenshot is a **normal** (non-editor) view, traps are usually
> not recoverable. The detector records this explicitly in `warnings`
> (`"traps not visible in normal view; supply an editor/layout-edit screenshot"`)
> so the paster never assumes a trap-free base.

---

## 6. Canonical type keys

Types are lowercase `snake_case` singular. The reference list lives in
`src/copy/schema.py::KNOWN_TYPES` with default footprints. Examples:
`town_hall`, `cannon`, `archer_tower`, `mortar`, `wizard_tower`, `air_defense`,
`x_bow`, `inferno_tower`, `eagle_artillery`, `scattershot`, `bomb_tower`,
`air_sweeper`, `monolith`, `spell_tower`, `gold_mine`, `elixir_collector`,
`dark_elixir_drill`, `gold_storage`, `elixir_storage`, `dark_elixir_storage`,
`clan_castle`, `army_camp`, `barracks`, `dark_barracks`, `laboratory`,
`spell_factory`, `pet_house`, `blacksmith`, `king_altar`, `queen_altar`,
`warden_altar`, `champion_altar`, `minion_prince_altar`, `builder_hut`,
`wall` (chains only).

Unknown/new types are allowed: the detector keeps the model's best string and
adds a `warnings` entry so nothing is lost.

---

## 7. Validator-enforced invariants

`src/copy/validate.py` rejects a layout (triggering a vision re-run, max 2
retries) if any of these fail:

1. **No tile collisions** — no two objects' footprints overlap; no object tile
   coincides with a wall tile.
2. **In-bounds** — every tile `0 <= x,y <= 43`.
3. **Exactly one Town Hall** — `type=="town_hall"` count must equal 1.
4. **Reasonable wall count** — total wall tiles `< 275` (TH15 cap is 250 plus a
   few; 275 leaves margin without accepting nonsense).
5. **Confidence floor** — anything `< 0.7` must already have been re-asked; if it
   survives, it is moved to `warnings`, not silently kept.
6. **Schema conformance** — required fields present, enums valid, rotations in
   `{0,90,180,270}`.

Failures are **explicit**: the validator returns the list of reasons, and the
detector logs them and surfaces them to the caller — it never returns a quietly
broken layout.
