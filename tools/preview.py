#!/usr/bin/env python3
"""See the status line in your terminal without starting Claude Code.

  python3 tools/preview.py                      list the scenarios
  python3 tools/preview.py healthy              one scenario, at your terminal's width
  python3 tools/preview.py bad-day -w 80,120    at several widths
  python3 tools/preview.py --all                every scenario at its own width
  python3 tools/preview.py --live               this folder's real git, project-info.json
                                                and machine, with made-up Claude numbers
  python3 tools/preview.py --live --watch       the same, redrawn every two seconds

A scenario is a file in scenarios/; a name matches any part of its file
name, so `bad` finds 2-bad-day. Scenarios draw as the pictures in docs/ do:
days starting at 7am, clock times in UTC. --live uses your own settings and
time zone, and writes no usage files or week log. It does keep the readings
it compares between redraws (CPU ticks, memory trend) in statusline/cache.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statusline"))
sl = None  # imported in main(), once it knows whose settings to use

SCENARIOS = ROOT / "scenarios"
DIM, RESET = "\033[2m", "\033[0m"


def scenarios():
    return sorted(SCENARIOS.glob("*.json"), key=lambda f: int(f.stem.split("-")[0]))


def find(name):
    hits = [f for f in scenarios() if name == f.stem or name in f.stem]
    if not hits:
        sys.exit(f"no scenario matches {name!r}; run with no arguments to list them")
    return hits


def show(title, text, color):
    print(f"{DIM}── {title} ──{RESET}" if color else f"── {title} ──")
    print(text)
    print()


def live_input(cwd):
    """What gather() would return, from this folder and machine, without
    gather()'s writes: no usage file and no week log."""
    healthy = json.loads((SCENARIOS / "1-healthy.json").read_text())
    now = time.time()
    # the scenario's times, moved so its windows are as far along now as they were then
    shift = lambda r: {**r, "resets_at": r["resets_at"] + now - healthy["now"]}
    claude = {**healthy["claude"], "workspace": {"current_dir": cwd}, "cwd": cwd, "session_name": "preview",
              "rate_limits": {k: shift(w) for k, w in healthy["claude"]["rate_limits"].items()}}
    claude.pop("pr", None)
    history = [{**shift(r), "at": r["at"] + now - healthy["now"]} for r in healthy["week_history"]]
    git, common = sl.gather_git(cwd)
    return {"claude": claude, "git": git, "project": sl.gather_project(common) if common else None,
            "system": sl.gather_system(), "week_history": history, "now": now}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="scenarios to show (part of a file name)")
    ap.add_argument("-w", "--width", help="comma-separated widths, default: your terminal's")
    ap.add_argument("--all", action="store_true", help="every scenario at its own width")
    ap.add_argument("--live", action="store_true", help="this folder and machine, made-up Claude numbers")
    ap.add_argument("--watch", action="store_true", help="with --live, redraw every two seconds")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args(argv)
    global sl
    if not args.live:  # as the snapshots and pictures were drawn
        os.environ["CLAUDE_STATUSLINE_DAY_START"] = "7"
        os.environ["TZ"] = "UTC"
        time.tzset()
    import statusline as sl
    color = not args.no_color and sys.stdout.isatty() or os.environ.get("FORCE_COLOR")
    term = shutil.get_terminal_size((120, 24)).columns
    widths = [int(w) for w in args.width.split(",")] if args.width else None

    if args.live:
        while True:
            inp = live_input(os.getcwd())
            text = "\n".join(sl.render(inp, w, color) + "\n" for w in widths or [term - 2])
            if not args.watch:
                print(text)
                return
            print("\033[H\033[2J" + text + f"{DIM}redrawn every 2s · ctrl-c to stop{RESET}", flush=True)
            try:
                time.sleep(2)
            except KeyboardInterrupt:
                return

    if not args.names and not args.all:
        for f in scenarios():
            about = json.loads(f.read_text()).get("_about", "")
            print(f"  {f.stem:<22} {about}")
        print("\nShow one with: python3 tools/preview.py <name>   (see --help)")
        return

    files = scenarios() if args.all else [f for n in args.names for f in find(n)]
    for f in files:
        inp = json.loads(f.read_text())
        for w in widths or [inp.get("columns") if args.all else min(term - 2, 240)]:
            show(f"{f.stem} · {w} columns", sl.render(inp, w, color), color)


if __name__ == "__main__":
    main(sys.argv[1:])
