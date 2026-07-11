# kscreen-precise

Precise per-monitor scale and position tuning for KWin/KDE, for setups where
the Displays KCM isn't precise enough — its scale slider only offers ~5%
steps, and monitor position can only be set by dragging/snapping rectangles,
with no field for an exact pixel offset.

`kscreen-doctor` (the CLI KWin already ships) supports arbitrary-precision
scale and position values, it's just not exposed in the GUI. This repo wraps
it in a small edit/apply loop, plus a live grid overlay for visually
verifying the result.

## Requirements

- KDE Plasma on Wayland (`kscreen-doctor`, part of `kscreen`)
- Python 3
- `gtk-layer-shell` with GObject introspection, for the grid overlay
  (`sudo dnf install gtk-layer-shell` on Fedora)

## monitor-layout.py

Dumps, edits, and applies exact per-output scale/position.

```bash
./monitor-layout.py dump          # seed ~/.config/monitor-layout.conf from your current live layout
$EDITOR monitor-layout.conf       # edit the symlink dump created in this directory
./monitor-layout.py --dry-run     # print the kscreen-doctor command it would run, without applying
./monitor-layout.py               # apply it live, then print the resulting layout
```

Changes apply immediately via the same D-Bus call the Displays KCM uses
under the hood (`kscreen-doctor` → KWin → `~/.config/kwinoutputconfig.json`),
so there's no login/logout needed, and persistence works exactly like a
GUI-driven change would.

### Config format

Plain `output.key=value` lines, one output per pair of lines:

```
# laptop panel, tuned for readability at this density
eDP-1.scale=2.058333333333333
eDP-1.pos=2297,994          # top-left corner in the virtual screen

HDMI-A-1.scale=1.15
HDMI-A-1.pos=1920,54
```

- Order doesn't matter — `kscreen-doctor` applies all settings in one atomic
  call, and the parser keys by output name regardless of line order.
- Scale accepts any decimal `kscreen-doctor` accepts, no rounding to 5% or
  any other step.
- `#` starts a comment, either on its own line or trailing after a value.

## grid-overlay.py

Draws a click-through measurement grid across every monitor, for fine-tuning
`pos` (do adjacent monitors' grid lines stay continuous across the bezel
gap?) and `scale` (do same-size grid cells look the same physical size on
every screen?).

```bash
./grid-overlay.py                     # default 100px minor grid, major line every 5 cells
./grid-overlay.py --cell 50 --major 4
./grid-overlay.py --timeout 15        # auto-dismiss after 15s
```

Ctrl+C in the terminal to dismiss (windows are click-through, so they won't
grab input from whatever's underneath).

It uses native Wayland layer-shell surfaces — one per output, anchored
directly to that output — rather than routing through XWayland. XWayland
renders the whole virtual screen through its own internal supersampling
scale, which is a separate coordinate space from KWin's real per-output
logical layout; layer-shell surfaces avoid that entirely, since each one is
scaled correctly by the compositor for its own output with no manual math.

## Iteration loop

1. `./monitor-layout.py dump`
2. `./grid-overlay.py` — look for discontinuities at monitor edges, and
   compare cell size by eye across screens
3. Edit `monitor-layout.conf`
4. `./monitor-layout.py`
5. Repeat 2–4 until it looks right
