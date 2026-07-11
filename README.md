# kscreen-precise

Precise per-monitor scale and position tuning for KWin/KDE, for setups where
the Displays KCM isn't precise enough — its scale slider only offers ~5%
steps, and monitor position can only be set by dragging/snapping rectangles,
with no field for an exact pixel offset.

`kscreen-doctor` (the CLI KWin already ships) supports arbitrary-precision
scale and position values, it's just not exposed in the GUI. `kscreen-precise.py`
wraps it in a small edit/apply loop, an auto-fix for small gaps/overlaps
between neighboring monitors, and a live grid overlay for visually verifying
the result.

## Requirements

- KDE Plasma on Wayland (`kscreen-doctor`, part of `kscreen`)
- Python 3
- `gtk-layer-shell` with GObject introspection, for the `grid` command
  (`sudo dnf install gtk-layer-shell` on Fedora)

## Usage

```bash
./kscreen-precise.py dump               # seed ~/.config/monitor-layout.conf from your current live layout
$EDITOR monitor-layout.conf             # edit the symlink dump created in this directory
./kscreen-precise.py fix                # snap small gaps/overlaps between neighbors flush
./kscreen-precise.py grid               # click-through measurement grid across all monitors
./kscreen-precise.py apply --dry-run    # print the kscreen-doctor command it would run, without applying
./kscreen-precise.py apply              # apply it live, then print the resulting layout
./kscreen-precise.py tune               # guided loop through all of the above
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
- Scale accepts any decimal, but KWin silently quantizes whatever you set to
  the nearest multiple of **1/120** (confirmed empirically against KDE 6.5.4
  source and live testing — e.g. a requested `1.0231` comes back as `1.025`).
  That's much finer than the GUI's 5% steps, but it's a real floor, not a
  free-form double. `fix`/`apply` account for this automatically (see below).
- `#` starts a comment, either on its own line or trailing after a value.

## fix

KDE rejects layouts with gaps between displays ("Gaps between displays are
not supported"), and overlapping displays cause real visual glitches
(duplicate rendering where the overlap is). Both usually come from changing
one output's `scale` without recalculating its neighbors' `pos` — logical
size is `native pixels / scale`, so any scale change shifts where that
output's edge actually falls. `fix` corrects two things:

1. **Off-grid scale.** Any scale not already an exact multiple of 1/120 gets
   quantized to the value KWin will actually use — otherwise your `pos` math
   is computed against a size that isn't what ends up on screen.
2. **Gaps and overlaps.** For every pair of outputs, if two overlap
   substantially along one axis (they're meant to sit side by side or
   stacked) and are off by less than 200 logical px along the other axis, it
   snaps the second one flush against the first. Gaps larger than that are
   left alone, on the assumption they're deliberate space between unrelated
   monitors.

This runs to a fixed point — closing one gap can open or widen another one
elsewhere (moving a middle monitor to fix its left edge shifts its right
edge too), so it keeps re-checking every pair until a full pass makes no
further changes. It only rewrites the affected `scale=`/`pos=` lines, so
comments and everything else in the file are preserved.

Position rounding always goes *up* (ceiling), never down — a fractional
remainder that has to land on an integer position ends up as a sub-pixel gap
(invisible, and tolerated by KWin) rather than a sub-pixel overlap (which
causes visible duplicate rendering at the seam).

`apply` always runs this same check before pushing anything live, so a
stale or hand-edited conf file can never be applied with a gap, overlap, or
off-grid scale left in it.

## grid

Draws a click-through measurement grid across every monitor, for fine-tuning
`pos` (do adjacent monitors' grid lines stay continuous across the bezel
gap?) and `scale` (do same-size grid cells look the same physical size on
every screen?).

```bash
./kscreen-precise.py grid                     # default 100px minor grid, major line every 5 cells
./kscreen-precise.py grid --cell 50 --major 4
./kscreen-precise.py grid --timeout 15        # auto-dismiss after 15s
```

Ctrl+C in the terminal to dismiss (windows are click-through, so they won't
grab input from whatever's underneath).

It uses native Wayland layer-shell surfaces — one per output, anchored
directly to that output — rather than routing through XWayland. XWayland
renders the whole virtual screen through its own internal supersampling
scale, which is a separate coordinate space from KWin's real per-output
logical layout; layer-shell surfaces avoid that entirely, since each one is
scaled correctly by the compositor for its own output with no manual math.

## tune

Walks through the whole loop interactively: dump if there's no config yet,
prompt you to edit it, run `fix`, print the `apply` command it would run,
show the grid for a few seconds, ask whether to apply, apply and show the
grid again, then ask if it looks good or if you want to keep iterating.
