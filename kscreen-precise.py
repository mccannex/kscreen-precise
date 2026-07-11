#!/usr/bin/env python3
"""Precise per-monitor scale & position for KWin, bypassing the 5%-step
Displays GUI, plus a grid overlay for visually verifying the result.

Config lives at ~/.config/monitor-layout.conf as plain 'output.key=value'
lines; a symlink to it is kept next to this script for convenience.

Usage:
  kscreen-precise.py dump                 write current live layout to the config file
  kscreen-precise.py fix                  snap small gaps/overlaps between neighbors flush
  kscreen-precise.py apply [--dry-run]    apply the config file to the live session
  kscreen-precise.py grid [options]       click-through measurement grid across all monitors
  kscreen-precise.py tune                 guided loop: edit, fix, preview, apply, repeat
"""
import argparse
import json
import math
import os
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/monitor-layout.conf")
SYMLINK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor-layout.conf")

# Force wayland QPA even if some shell has QT_QPA_PLATFORM=xcb lingering in
# its env (seen in sandboxed tool shells) -- harmless no-op on a normal
# interactive terminal already running under wayland.
ENV = {**os.environ, "QT_QPA_PLATFORM": "wayland"}

FIX_THRESHOLD = 200  # logical px; snap gaps/overlaps smaller than this -- bigger
# than that and it's probably intentional space between unrelated outputs


def fmt_num(x):
    if float(x) == int(x):
        return str(int(x))
    return repr(float(x))


def kscreen_json():
    out = subprocess.run(
        ["kscreen-doctor", "-j"], env=ENV, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def native_sizes():
    """Current mode's native pixel size per output name, from live state."""
    cfg = kscreen_json()
    sizes = {}
    for o in cfg["outputs"]:
        for m in o.get("modes", []):
            if m["id"] == o.get("currentModeId"):
                sizes[o["name"]] = (m["size"]["width"], m["size"]["height"])
                break
    return sizes


def cmd_dump(args):
    cfg = kscreen_json()
    lines = []
    for o in sorted(cfg["outputs"], key=lambda o: o["name"]):
        if not o.get("connected") or not o.get("enabled"):
            continue
        name = o["name"]
        pos = o["pos"]
        lines.append(f"{name}.scale={fmt_num(o['scale'])}")
        lines.append(f"{name}.pos={pos['x']},{pos['y']}")
    text = "\n".join(lines) + "\n"
    with open(CONFIG, "w") as f:
        f.write(text)

    if os.path.islink(SYMLINK) or not os.path.exists(SYMLINK):
        if os.path.lexists(SYMLINK):
            os.remove(SYMLINK)
        os.symlink(CONFIG, SYMLINK)

    print(f"wrote {CONFIG}:\n")
    print(text)
    print("next steps:")
    print(f"  1. edit {SYMLINK} (symlink to the config above)")
    print("  2. ./kscreen-precise.py apply --dry-run   # preview the kscreen-doctor command")
    print("  3. ./kscreen-precise.py apply             # apply it live")


def load_config():
    outputs = {}
    with open(CONFIG) as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line or "." not in line.split("=", 1)[0]:
                sys.exit(f"{CONFIG}:{lineno}: bad line, expected 'name.key=value': {line}")
            key, value = line.split("=", 1)
            name, setting = key.rsplit(".", 1)
            outputs.setdefault(name, {})[setting] = value.strip()
    return outputs


SCALE_STEP = 1 / 120  # KWin silently quantizes scale to multiples of this,
# confirmed empirically (e.g. a requested 1.0231 comes back as 1.025); using
# anything else here just means our gap math doesn't match what's really
# on screen.


def quantize_scale(scale):
    return round(scale / SCALE_STEP) * SCALE_STEP


def find_scale_quantizations(outputs):
    updates = {}
    for name, settings in outputs.items():
        if "scale" not in settings:
            continue
        old = float(settings["scale"])
        new = quantize_scale(old)
        if abs(new - old) > 1e-9:
            updates[name] = fmt_num(new)
    return updates


def logical_rects(outputs, sizes):
    rects = {}
    for name, settings in outputs.items():
        if name not in sizes or "pos" not in settings or "scale" not in settings:
            continue
        w, h = sizes[name]
        scale = quantize_scale(float(settings["scale"]))
        x, y = (float(v) for v in settings["pos"].split(","))
        rects[name] = [x, y, x + w / scale, y + h / scale]  # left, top, right, bottom
    return rects


def find_fixes(rects):
    fixes = {}  # name -> (new_x, new_y)
    names = sorted(rects)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ra, rb = rects[a], rects[b]
            y_overlap = min(ra[3], rb[3]) - max(ra[1], rb[1])
            x_overlap = min(ra[2], rb[2]) - max(ra[0], rb[0])
            if y_overlap > 50 and y_overlap >= x_overlap:
                left, right = (a, b) if ra[0] <= rb[0] else (b, a)
                gap = rects[right][0] - rects[left][2]
                if 1e-6 < abs(gap) <= FIX_THRESHOLD:
                    old_x = round(rects[right][0])
                    # ceil, never round down -- rounding down would leave the
                    # two outputs overlapping by a fraction of a pixel instead
                    # of just short of touching. A fractional anchor edge can
                    # never land exactly on an integer position, so compare
                    # against the *previous* integer position, not the gap
                    # itself, or this never converges (see find_all_fixes).
                    new_x = math.ceil(rects[left][2] - 1e-9)
                    if new_x != old_x:
                        rects[right][2] += new_x - rects[right][0]
                        rects[right][0] = new_x
                        fixes[right] = (new_x, round(rects[right][1]))
            elif x_overlap > 50:
                top, bottom = (a, b) if ra[1] <= rb[1] else (b, a)
                gap = rects[bottom][1] - rects[top][3]
                if 1e-6 < abs(gap) <= FIX_THRESHOLD:
                    old_y = round(rects[bottom][1])
                    new_y = math.ceil(rects[top][3] - 1e-9)
                    if new_y != old_y:
                        rects[bottom][3] += new_y - rects[bottom][1]
                        rects[bottom][1] = new_y
                        fixes[bottom] = (round(rects[bottom][0]), new_y)
    return fixes


def apply_updates_to_text(text, updates):
    """updates: dict of (name, setting) -> new value string."""
    lines = text.splitlines(keepends=True)
    for i, raw in enumerate(lines):
        body, _, comment = raw.partition("#")
        stripped = body.strip()
        if "=" not in stripped or "." not in stripped.split("=", 1)[0]:
            continue
        key, _ = stripped.split("=", 1)
        name, setting = key.rsplit(".", 1)
        if (name, setting) in updates:
            ending = "\n" if raw.endswith("\n") else ""
            suffix = f"  #{comment.rstrip(chr(10))}" if comment else ""
            lines[i] = f"{name}.{setting}={updates[(name, setting)]}{suffix}{ending}"
    return "".join(lines)


def find_all_fixes(outputs, sizes, max_passes=10):
    """Repeatedly snap pairs flush until a full pass makes no changes.

    A single pass can leave new violations in its wake -- moving one output
    to close a gap on one side can open or widen one on its other side (see
    find_fixes). Iterating to a fixed point guarantees the final layout has
    no pairwise gap/overlap left within FIX_THRESHOLD, however it got there.
    """
    outputs = {name: dict(settings) for name, settings in outputs.items()}
    all_fixes = {}
    for _ in range(max_passes):
        fixes = find_fixes(logical_rects(outputs, sizes))
        if not fixes:
            break
        for name, (x, y) in fixes.items():
            outputs[name]["pos"] = f"{x},{y}"
        all_fixes.update(fixes)
    else:
        print(f"warning: layout still unresolved after {max_passes} passes", file=sys.stderr)
    return all_fixes


def fix_layout(outputs):
    """Quantize scales to what KWin will really honor (1/120 steps), then
    snap positions flush against those real sizes. Returns a combined
    (name, setting) -> new value string update dict; empty if nothing to do.
    """
    scale_updates = find_scale_quantizations(outputs)
    outputs = {name: dict(settings) for name, settings in outputs.items()}
    for name, new_scale in scale_updates.items():
        outputs[name]["scale"] = new_scale

    pos_fixes = find_all_fixes(outputs, native_sizes())

    updates = {(name, "scale"): v for name, v in scale_updates.items()}
    updates.update({(name, "pos"): f"{x},{y}" for name, (x, y) in pos_fixes.items()})
    return updates


def cmd_fix(args):
    if not os.path.exists(CONFIG):
        sys.exit(f"{CONFIG} not found -- run 'kscreen-precise.py dump' first")
    outputs = load_config()
    updates = fix_layout(outputs)
    if not updates:
        print("no gaps, overlaps, or off-grid scales found")
        return
    for (name, setting), new_value in updates.items():
        print(f"{name}.{setting}: {outputs[name][setting]} -> {new_value}")
    with open(CONFIG) as f:
        text = f.read()
    with open(CONFIG, "w") as f:
        f.write(apply_updates_to_text(text, updates))
    print(f"\nwrote {CONFIG} -- review it, then ./kscreen-precise.py apply --dry-run / apply")


def build_kscreen_args(outputs):
    args = []
    for name, settings in outputs.items():
        if "scale" in settings:
            args.append(f"output.{name}.scale.{settings['scale']}")
        if "pos" in settings:
            args.append(f"output.{name}.position.{settings['pos']}")
    return args


def cmd_apply(args):
    if not os.path.exists(CONFIG):
        sys.exit(f"{CONFIG} not found -- run 'kscreen-precise.py dump' first")
    outputs = load_config()

    # Mandatory pre-flight: never push a config with a pairwise gap/overlap,
    # or a scale KWin will silently round to something else, no matter how
    # it got that way (stale edits, hand-tuning that broke a boundary, etc).
    updates = fix_layout(outputs)
    if updates:
        print("pre-flight: correcting before applying:")
        for (name, setting), new_value in updates.items():
            print(f"  {name}.{setting}: {outputs[name][setting]} -> {new_value}")
        with open(CONFIG) as f:
            text = f.read()
        with open(CONFIG, "w") as f:
            f.write(apply_updates_to_text(text, updates))
        outputs = load_config()
        print()

    kscreen_args = build_kscreen_args(outputs)
    cmd = ["kscreen-doctor"] + kscreen_args
    if args.dry_run:
        print(" ".join(cmd))
        return
    subprocess.run(cmd, env=ENV, check=True)
    print("applied. current state:\n")
    subprocess.run(["kscreen-doctor", "-o"], env=ENV)


def cmd_grid(args):
    # Imported lazily: dump/fix/apply don't need GTK or gtk-layer-shell at all.
    # Force (not setdefault) -- some shells (seen in sandboxed tool shells)
    # preset GDK_BACKEND=x11, which silently falls back to one merged XDG
    # shell window instead of real per-output layer-shell surfaces, collapsing
    # every monitor's overlay onto a single screen.
    os.environ["GDK_BACKEND"] = "wayland"
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
    import cairo
    import signal

    MINOR_RGBA = (0.1, 0.9, 0.9, 0.35)
    MAJOR_RGBA = (1.0, 0.85, 0.1, 0.8)
    BORDER_RGBA = (1.0, 0.15, 0.15, 0.9)
    LABEL_RGBA = (1.0, 1.0, 1.0, 0.95)

    def output_name_for(monitor, monitor_index):
        # GTK3's Wayland Gdk.Monitor doesn't reliably expose the connector
        # name across versions; fall back to whatever GTK does give us.
        for attr in ("get_connector", "get_model"):
            fn = getattr(monitor, attr, None)
            if fn:
                name = fn()
                if name:
                    return name
        return f"monitor {monitor_index}"

    def make_overlay(monitor, index, cell, major_every, show_labels):
        geom = monitor.get_geometry()
        name = output_name_for(monitor, index)

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_monitor(window, monitor)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(window, -1)
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
        for edge in (
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        ):
            GtkLayerShell.set_anchor(window, edge, True)
            GtkLayerShell.set_margin(window, edge, 0)

        screen = window.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            window.set_visual(visual)
        window.set_app_paintable(True)
        window.set_decorated(False)

        def on_draw(widget, cr):
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()

            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)

            first_x = (-geom.x) % cell
            x = first_x
            while x <= w:
                global_x = geom.x + x
                major = (global_x % (cell * major_every)) == 0
                cr.set_line_width(1.4 if major else 0.6)
                cr.set_source_rgba(*(MAJOR_RGBA if major else MINOR_RGBA))
                cr.move_to(x + 0.5, 0)
                cr.line_to(x + 0.5, h)
                cr.stroke()
                if major and show_labels:
                    cr.set_source_rgba(*LABEL_RGBA)
                    cr.move_to(x + 3, 12)
                    cr.show_text(str(global_x))
                x += cell

            first_y = (-geom.y) % cell
            y = first_y
            while y <= h:
                global_y = geom.y + y
                major = (global_y % (cell * major_every)) == 0
                cr.set_line_width(1.4 if major else 0.6)
                cr.set_source_rgba(*(MAJOR_RGBA if major else MINOR_RGBA))
                cr.move_to(0, y + 0.5)
                cr.line_to(w, y + 0.5)
                cr.stroke()
                if major and show_labels:
                    cr.set_source_rgba(*LABEL_RGBA)
                    cr.move_to(3, y - 3)
                    cr.show_text(str(global_y))
                y += cell

            cr.set_line_width(3)
            cr.set_source_rgba(*BORDER_RGBA)
            cr.rectangle(1.5, 1.5, w - 3, h - 3)
            cr.stroke()

            if show_labels:
                cr.set_source_rgba(*LABEL_RGBA)
                cr.move_to(10, h - 12)
                cr.show_text(f"{name}  pos={geom.x},{geom.y}  {w}x{h} logical")

            return False

        window.connect("draw", on_draw)
        window.input_shape_combine_region(cairo.Region())
        window.set_default_size(geom.width, geom.height)
        window.show_all()
        return window

    display = Gdk.Display.get_default()
    if display is None:
        sys.exit("no Gdk display -- is this running under a live Wayland session?")

    windows = [
        make_overlay(display.get_monitor(i), i, args.cell, args.major, not args.no_labels)
        for i in range(display.get_n_monitors())
    ]

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: Gtk.main_quit())
    if args.timeout:
        GLib.timeout_add(int(args.timeout * 1000), lambda: Gtk.main_quit())

    print(f"overlaying {len(windows)} monitor(s), cell={args.cell}px, major every {args.major} cells")
    print("Ctrl+C in this terminal to dismiss")
    Gtk.main()


def cmd_tune(args):
    if not os.path.exists(CONFIG):
        cmd_dump(args)

    while True:
        input(f"\nedit {SYMLINK}, then press Enter to preview...")
        cmd_fix(args)

        outputs = load_config()
        print("\nwould apply:")
        print(" ".join(["kscreen-doctor"] + build_kscreen_args(outputs)))

        grid_args = argparse.Namespace(cell=100, major=5, no_labels=False, timeout=12)
        print("\nshowing grid for 12s -- check edges are flush and cells look consistent...")
        subprocess.run([sys.executable, os.path.abspath(__file__), "grid", "--timeout", "12"])

        choice = input("\napply this layout now? [y/N/q]  (q to quit without applying) ").strip().lower()
        if choice == "q":
            return
        if choice != "y":
            continue

        cmd_apply(argparse.Namespace(dry_run=False))
        subprocess.run([sys.executable, os.path.abspath(__file__), "grid", "--timeout", "8"])
        if input("\nlooks good? [Y/n] ").strip().lower() != "n":
            return


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("dump", help="write current live layout to the config file")
    sub.add_parser("fix", help="snap small gaps/overlaps flush")

    p_apply = sub.add_parser("apply", help="apply the config file to the live session")
    p_apply.add_argument("--dry-run", action="store_true", help="print the kscreen-doctor command, don't run it")

    p_grid = sub.add_parser("grid", help="click-through measurement grid across all monitors")
    p_grid.add_argument("--cell", type=int, default=100, help="minor grid spacing in logical px (default 100)")
    p_grid.add_argument("--major", type=int, default=5, help="labeled major line every N cells (default 5)")
    p_grid.add_argument("--no-labels", action="store_true")
    p_grid.add_argument("--timeout", type=float, default=None, help="auto-quit after this many seconds")

    sub.add_parser("tune", help="guided loop: edit, fix, preview, apply, repeat")

    args = p.parse_args()
    {"dump": cmd_dump, "fix": cmd_fix, "apply": cmd_apply, "grid": cmd_grid, "tune": cmd_tune}[args.command](args)


if __name__ == "__main__":
    main()
