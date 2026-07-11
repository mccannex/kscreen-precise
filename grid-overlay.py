#!/usr/bin/env python3
"""Click-through measurement grid overlaid on every monitor, for fine-tuning
per-monitor scale/position in monitor-layout.conf.

Uses native Wayland layer-shell surfaces (one per output) rather than
XWayland, so each surface is drawn and scaled by KWin using that output's
real logical coordinate space -- no manual per-output scale math needed.
As you tune scale values toward correct, grid cells of the same *logical*
size should converge toward looking like the same physical size on every
screen.

Run it, look at your screens, Ctrl+C in this terminal to dismiss.

Usage:
  grid-overlay.py [--cell PX] [--major N] [--no-labels] [--timeout SEC]
"""
import argparse
import os
import signal
import sys

os.environ.setdefault("GDK_BACKEND", "wayland")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
import cairo

MINOR_RGBA = (0.1, 0.9, 0.9, 0.35)
MAJOR_RGBA = (1.0, 0.85, 0.1, 0.8)
BORDER_RGBA = (1.0, 0.15, 0.15, 0.9)
LABEL_RGBA = (1.0, 1.0, 1.0, 0.95)


def output_name_for(monitor, monitor_index):
    # GTK3's Wayland Gdk.Monitor doesn't reliably expose the connector name
    # across versions; fall back to whatever GTK does give us.
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

        # clear to fully transparent first so this is a real see-through
        # overlay, not just a dimmed window
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # vertical lines, phased so they land on global multiples of `cell`
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

        # horizontal lines
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

        # this output's own boundary, thick, for spotting gaps/overlaps
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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cell", type=int, default=100, help="minor grid spacing in logical px (default 100)")
    p.add_argument("--major", type=int, default=5, help="draw a labeled major line every N cells (default 5)")
    p.add_argument("--no-labels", action="store_true")
    p.add_argument("--timeout", type=float, default=None, help="auto-quit after this many seconds")
    args = p.parse_args()

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


if __name__ == "__main__":
    main()
