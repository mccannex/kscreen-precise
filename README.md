# kscreen-precise

Precise per-monitor scale and position for KWin/KDE, for setups where the
Displays KCM isn't precise enough (5%-step scale slider, drag-to-snap
positioning only). `kscreen-precise.py` edits a plain-text config and pushes
it live via `kscreen-doctor`, auto-fixes small gaps/overlaps between
neighboring monitors, and can overlay a measurement grid across all screens
for visually verifying the result.

## Requirements

- KDE Plasma on Wayland (`kscreen-doctor`, part of `kscreen`)
- Python 3
- `gtk-layer-shell` with GObject introspection, for the `grid` command
  (`sudo dnf install gtk-layer-shell` on Fedora)

## Usage

```bash
./kscreen-precise.py dump               # seed ~/.config/monitor-layout.conf from your current live layout
$EDITOR monitor-layout.conf             # edit the symlink dump created in this directory
./kscreen-precise.py fix                # snap small gaps/overlaps flush, quantize scale to what KWin allows
./kscreen-precise.py grid               # click-through measurement grid across all monitors
./kscreen-precise.py apply --dry-run    # print the kscreen-doctor command it would run, without applying
./kscreen-precise.py apply              # fix, then apply live, then print the resulting layout
./kscreen-precise.py tune               # guided loop through all of the above
```

Changes apply immediately (same D-Bus call the Displays KCM uses under the
hood), no login/logout needed. `apply` always runs `fix` first, so a stale
or hand-edited conf can never be pushed with a gap, overlap, or invalid
scale left in it.

### Config format

Plain `output.key=value` lines, one output per pair of lines. Order doesn't
matter, and `#` starts a comment (own line or trailing).

```
# laptop panel, tuned for readability at this density
eDP-1.scale=2.058333333333333
eDP-1.pos=2297,994          # top-left corner in the virtual screen

HDMI-A-1.scale=1.15
HDMI-A-1.pos=1920,54
```

> **Why `fix` exists:** KDE rejects layouts with gaps between displays, and
> overlaps cause visible duplicate rendering at the seam. Both usually come
> from changing one output's `scale` without recalculating its neighbors'
> `pos` (logical size is `native pixels / scale`, so a scale change moves
> where that edge actually falls). `fix` also quantizes scale to the
> nearest multiple of **1/120** — confirmed against KDE 6.5.4 source and
> live testing that KWin silently rounds to this regardless of what you
> ask for (e.g. a requested `1.0231` comes back as `1.025`), far finer than
> the GUI's 5% but still a hard floor, not a free double. It iterates to a
> fixed point (closing one gap can open another elsewhere), rounds position
> remainders up rather than down (a sub-pixel gap is harmless; a sub-pixel
> overlap duplicates rendering), and only touches the `scale=`/`pos=` lines
> that need it, leaving comments and formatting alone.

## grid

Click-through measurement grid across every monitor, for checking that
adjacent monitors' grid lines stay continuous across the bezel gap (`pos`)
and that same-size cells look the same physical size on every screen
(`scale`). Ctrl+C to dismiss.

```bash
./kscreen-precise.py grid                     # default 100px minor grid, major line every 5 cells
./kscreen-precise.py grid --cell 50 --major 4
./kscreen-precise.py grid --timeout 15        # auto-dismiss after 15s
```

> Uses native Wayland layer-shell surfaces (one per output) rather than
> XWayland, which renders the whole virtual screen through its own internal
> supersampling scale — a separate coordinate space from KWin's real
> per-output layout. Layer-shell surfaces sidestep that: each one is scaled
> correctly by the compositor for its own output, no manual math needed.

## tune

Guided loop: dump if there's no config yet, prompt you to edit it, run
`fix`, show the grid, ask whether to apply, apply and show the grid again,
then ask if it looks good or if you want to keep iterating.
