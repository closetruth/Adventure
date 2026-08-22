# Top-bar gold/diamond count-up

## Goal

When backpack gold or diamond **increases**, the floating widget top-bar numbers ease toward the new value at a fixed rate so the gain is visible. Decreases snap. Inventory data still updates immediately.

## Scope

- **In:** `FloatingWidget` top-bar summary only (`format_global_summary_html` gold/diamond fields).
- **Out:** Inventory dialog big numbers, goal detail pending, roll history, operation counts, settings toggle, persistence.

## Display state

Keep two in-memory display values on the widget (not in `data.json`):

- `display_gold`, `display_diamond`

On widget construction / first paint: copy `state.inventory.gold` / `.diamond`. Never count up from 0 on launch.

`_paint_global_stats` formats the summary with **display** gold/diamond. Real inventory is unchanged.

## Motion

| Event | Behavior |
|--------|----------|
| Increase | Catch up at **1 unit per second**. Duration = remaining distance in those units. No min/max clamp. |
| Decrease | Snap display to inventory; stop that lane. |
| Both lanes | Independent. Parallel if both rose. |
| New hit while moving | Retarget to latest inventory. Remaining distance still 1 unit/s. No queue. |
| Window drag pause | Do not apply paused elapsed time as a lump when resume; next tick uses a normal small `Δt`. |

Existing 1s `_tick` is too coarse for typical +0.1–0.3 rolls. Use a **~50ms** QTimer that runs **only while** a lane is catching up; stop when both displays match inventory (within formatting epsilon, e.g. 0.05 so `format_amount` is stable).

Each tick: `display += min(remaining, 1.0 * Δt)` per lane that is below target. Then `format_amount` (max one decimal).

## Testing

Extract the catch-up step (gold/diamond independently, snap on decrease, retarget) as a small pure helper and cover with stdlib `unittest`. Existing offscreen widget geometry tests must still pass.

## Error handling

If a display lane exceeds its inventory target while catching up, clamp to the target. Full `refresh` / `_paint_global_stats` keep using display values and must not snap increases to inventory. Snap only on: widget init, a decrease in that lane, or tests resetting state.
