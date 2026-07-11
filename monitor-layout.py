#!/usr/bin/env python3
"""Read/write exact per-monitor scale & position via kscreen-doctor, bypassing
the 5%-step GUI. Config lives at ~/.config/monitor-layout.conf as plain
'output.key=value' lines.

Usage:
  monitor-layout.py dump        write current live layout to the config file
  monitor-layout.py             apply the config file to the live session
  monitor-layout.py --dry-run   print the kscreen-doctor command, don't run it
"""
import json
import os
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/monitor-layout.conf")
SYMLINK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor-layout.conf")

# Force wayland QPA even if some shell has QT_QPA_PLATFORM=xcb lingering in
# its env (seen in sandboxed tool shells) -- harmless no-op on a normal
# interactive terminal already running under wayland.
ENV = {**os.environ, "QT_QPA_PLATFORM": "wayland"}


def fmt_num(x):
    if float(x) == int(x):
        return str(int(x))
    return repr(float(x))


def kscreen_json():
    out = subprocess.run(
        ["kscreen-doctor", "-j"], env=ENV, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def dump():
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
    print(f"next steps:")
    print(f"  1. edit {SYMLINK} (symlink to the config above)")
    print(f"  2. ./monitor-layout.py --dry-run   # preview the kscreen-doctor command")
    print(f"  3. ./monitor-layout.py             # apply it live")


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


def build_args(outputs):
    args = []
    for name, settings in outputs.items():
        if "scale" in settings:
            args.append(f"output.{name}.scale.{settings['scale']}")
        if "pos" in settings:
            args.append(f"output.{name}.position.{settings['pos']}")
    return args


def apply(dry_run=False):
    if not os.path.exists(CONFIG):
        sys.exit(f"{CONFIG} not found -- run 'monitor-layout.py dump' first")
    outputs = load_config()
    args = build_args(outputs)
    cmd = ["kscreen-doctor"] + args
    if dry_run:
        print(" ".join(cmd))
        return
    subprocess.run(cmd, env=ENV, check=True)
    print("applied. current state:\n")
    subprocess.run(["kscreen-doctor", "-o"], env=ENV)


def main():
    args = sys.argv[1:]
    if args == ["dump"]:
        dump()
    elif args == ["--dry-run"]:
        apply(dry_run=True)
    elif not args:
        apply()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
