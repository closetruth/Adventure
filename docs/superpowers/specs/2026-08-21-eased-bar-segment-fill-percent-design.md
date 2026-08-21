# Eased bar segment fill percent (growing)

## Goal

On the continuous eased progress bar (`EasedProgressBar`), each entered segment shows a **growing** completion percent for that segment (not static segment width). Text uses rarity color with a **white** outline.

## Behavior

Segments are `0 → chest1`, `chest1 → chest2`, `chest2 → chest3` using eased checkpoint positions `_points`.

For segment `i` with `prev` / `pt`:

| Condition | Label |
|-----------|--------|
| `eased ≤ prev` | Hidden (not entered) |
| `prev < eased < pt` | `round((eased - prev) / (pt - prev) * 100)%` (clamped 0–100) |
| `eased ≥ pt` | `100%` |

Position: midpoint of the segment, drawn on the track (existing scheme B; no bar height change).

Style: fill = rarity glow from `_RARITY_PALETTE`; stroke = white (offset draw then center glyph).

## Scope

- **In:** `src/ui_roll_bar.py` — `EasedProgressBar.paintEvent` percent drawing only.
- **Out:** Ease math, chest claim, segmented roll bar, inventory badge, persistence.

## Testing

Existing widget smoke / paint regression tests still pass; no new test required for paint-only label math unless a pure helper is extracted.
