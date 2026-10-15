#!/usr/bin/env python3
"""A status line for Claude Code.

Layout B (columns), falling back to layout A (rows) in narrow terminals:

  tanks (ctx / 5h / wk) | repo | ship (project-info.json) | session | system

The system column (cpu and mem meters) only appears when every other column
fits beside it at full width. Without room, cpu and mem fall back to alert-only
text at the end of the session column.

Gathering (stdin JSON, git, project-info.json, battery, cpu, memory) is kept
apart from rendering so the renderer can be driven from fixtures:

  statusline.py                 live: reads Claude Code's JSON on stdin
  statusline.py --json          live, but each part as data (see `view`)
  statusline.py --version       which version this is (see `version_label`)
  statusline.py --scenario F    renders one scenario file (see scenarios/)

The status line never runs repo code. Project data comes only from
<git-common-dir>/project-info.json, which the repo writes (see docs/project-info.md).

Settings are environment variables, so they can go in the "env" block of
~/.claude/settings.json:

  CLAUDE_STATUSLINE_DAY_START   hour (0-23) a day begins in the week chart, default 4
  CLAUDE_STATUSLINE_DATA        where usage readings are kept, default ~/.claude/usage-sensor
  CLAUDE_STATUSLINE_SENSOR      0 to stop writing a usage file per session, default 1
  CLAUDE_STATUSLINE_COLUMNS     how wide to draw, when $COLUMNS is missing or wrong
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent  # the install folder, even when its files link elsewhere
HOME = Path.home()


def env_int(name, default, lo, hi):
    """An integer setting from the environment, or `default` when it's unset or out of range."""
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if lo <= value <= hi else default


CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude").expanduser()  # Claude Code's own
DATA_DIR = Path(os.environ.get("CLAUDE_STATUSLINE_DATA") or CONFIG_DIR / "usage-sensor").expanduser()
SENSOR = os.environ.get("CLAUDE_STATUSLINE_SENSOR", "1") != "0"

# ---- palette (256-color) -----------------------------------------------------
RESET = "\033[0m"
DIM = "dim"
SAGE, OLIVE, TERRA, BRICK, AMBER, CYAN = 108, 143, 173, 131, 179, 37
GREY, PURPLE = 244, 134  # the week's forecast or what's left, and running out
TIERS = [SAGE, OLIVE, TERRA, BRICK]

FIVE_HOUR = 5 * 3600
SEVEN_DAY = 7 * 86400
DEFAULT_STALE_AFTER = 900  # project-info sections older than this render dim
WIDE_MIN = 95              # below this many columns, fall back to rows
SYSTEM_WIDTH = 36          # the system column reserves this, so an alert row never resizes it
CACHE_DIR = HERE / "cache"  # git and system readings between refreshes
SLOW_TTL = 10              # seconds those readings stay good

# ---- styled text -------------------------------------------------------------
# A line is a list of segments: (text, style, link). style is None, DIM, a
# 256-color int, or ("bg", color) for text on a colored fill.


def seg(text, style=None, link=None):
    # every piece of text on screen passes here, so nothing from Claude Code,
    # git or a repo can move the cursor, retitle the terminal or add a line
    return (text if text.isprintable() else printable(text), style, link)


def printable(text):
    """`text` without control characters, keeping the joiner inside emoji."""
    return "".join(c for c in text if c.isprintable() or c == "\u200d")


def cells(ch):
    """Screen cells one character takes: two for a wide one such as an emoji, none for a joiner or selector."""
    if ch == "\u200d" or "\ufe00" <= ch <= "\ufe0f" or unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(segs):
    return sum(cells(c) for t, _, _ in segs for c in t)


def truncate(segs, limit):
    """Cut a line to `limit` visible columns, ending in … when anything is cut."""
    if width(segs) <= limit:
        return segs
    out, used = [], 0
    for text, style, link in segs:
        kept = ""
        for ch in text:
            if used + cells(ch) > limit - 1:
                break
            kept += ch
            used += cells(ch)
        if kept:
            out.append((kept, style, link))
        if len(kept) < len(text):
            break
    out.append(("…", DIM, None))
    return out


def pad(segs, w):
    return segs + [(" " * (w - width(segs)), None, None)] if width(segs) < w else segs


def ansi(segs, color=True):
    parts = []
    for text, style, link in segs:
        if not text:
            continue
        if link and color and link.startswith(("https://", "http://")):
            text = f"\033]8;;{sanitize(link, 500)}\033\\{text}\033]8;;\033\\"
        if not color or style is None:
            parts.append(text)
        elif style == DIM:
            parts.append(f"\033[2m{text}{RESET}")
        elif isinstance(style, tuple):
            parts.append(f"\033[1;38;5;16;48;5;{style[1]}m{text}{RESET}")
        else:
            parts.append(f"\033[38;5;{style}m{text}{RESET}")
    return "".join(parts)


def join(items, sep=" · "):
    """Join non-empty segment lists with a dim separator."""
    out = []
    for item in (i for i in items if i):
        if out:
            out.append(seg(sep, DIM))
        out.extend(item)
    return out


def sanitize(value, limit=80):
    """Strip control characters from text that came from a repo's file."""
    if not isinstance(value, str):
        value = str(value)
    return printable(value)[:limit]


# ---- formatting ------------------------------------------------------------


def fmt_age(secs):
    secs = max(0, int(secs))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def fmt_dur(secs):
    secs = max(0, int(secs))
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m" if m else f"{secs}s"


def fmt_count(n):
    n = int(n)
    if n >= 10000:
        return f"{n // 1000}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# ---- tiers and pace ----------------------------------------------------------


def raw_tier(pct):
    """0..3 by fixed thresholds: <25, <50, <75, else."""
    return 0 if pct < 25 else 1 if pct < 50 else 2 if pct < 75 else 3


def pace(used, resets_at, window, now):
    """How a rate-limit window is tracking.

    Returns (tier, projected_pct, secs_to_full, secs_to_reset). The tier
    follows where usage lands at reset if the current rate holds, so a heavy
    but sustainable day stays green. Early in a window the projection is
    noise, so the raw percentage decides instead. Near the top, raw usage
    wins regardless of pace.
    """
    to_reset = max(0, resets_at - now) if resets_at else None
    if to_reset is None or to_reset > window:
        return raw_tier(used), None, None, to_reset
    elapsed = max(1, window - to_reset)
    rate = used / elapsed
    projected = used / elapsed * window
    to_full = (100 - used) / rate if rate > 0 else None
    tier = raw_tier(used) if elapsed < 0.15 * window else projected_tier(used, projected)
    return tier, projected, to_full, to_reset


def projected_tier(used, projected):
    """0..3 by where usage lands at reset; near the top, raw usage wins."""
    tier = 0 if projected < 90 else 1 if projected < 110 else 2 if projected < 140 else 3
    if used >= 97:
        return 3
    return max(tier, 2) if used >= 90 else tier


# ---- tanks -----------------------------------------------------------------
BLOCKS = " ▁▂▃▄▅▆▇█"


def tank_rows(pct, tier, elapsed=None, height=3):
    """`height` rows top-down. The top row carries the number and turns into a
    colored fill once the level reaches it. `elapsed` (0..1, how far through
    its window the clock is) puts a ◂ on the right wall at that height, one
    row per 1/height: fill above the marker means burning faster than time."""
    if pct is None:
        return [[seg("▕--▏", DIM)]] + [[seg("▕  ▏", DIM)]] * (height - 1)
    color = TIERS[tier]
    level = round(max(0, min(100, pct)) / 100 * 8 * height)
    fills = [min(8, max(0, level - 8 * i)) for i in range(height)]  # bottom up
    num = "!!" if pct >= 100 else f"{int(pct):>2d}"
    top_style = ("bg", color) if fills[-1] >= 4 else color
    rows = [[seg("▕", DIM), seg(num, top_style), seg("▏", DIM)]]
    rows += [[seg("▕", DIM), seg(BLOCKS[f] * 2, color), seg("▏", DIM)]
             for f in reversed(fills[:-1])]
    if elapsed is not None:
        e = max(0, min(1, elapsed))
        rows[height - 1 - min(height - 1, int(e * height))][-1] = seg("◂")
    return rows


def tanks(model):
    cols = [tank_rows(*t) for t in (model["ctx_tank"], model["five_tank"], model["week_tank"])]
    return [[s for col in cols for s in col[r]] for r in range(3)] + [[seg("ctx  5h  wk ", DIM)]]


# ---- model: raw inputs -> what to show -------------------------------------


def build_model(inp):
    """Reduce the gathered inputs to plain values the layouts render."""
    c = clean_claude(inp.get("claude"))
    now = inp.get("now") or time.time()

    ctx = (c.get("context_window") or {}).get("used_percentage")
    ctx_tank = (None, 0) if ctx is None else (ctx, raw_tier(ctx))

    rl = c.get("rate_limits") or {}
    windows = {}
    for key, span in (("five_hour", FIVE_HOUR), ("seven_day", SEVEN_DAY)):
        w = rl.get(key) or {}
        used = w.get("used_percentage")
        if used is None:
            windows[key] = None
            continue
        tier, projected, to_full, to_reset = pace(used, w.get("resets_at"), span, now)
        elapsed = None if to_reset is None or to_reset > span else 1 - to_reset / span
        windows[key] = {"used": used, "tier": tier, "projected": projected,
                        "to_full": to_full, "to_reset": to_reset, "elapsed": elapsed}
    five, week = windows["five_hour"], windows["seven_day"]
    if week and week["to_reset"] is not None and week["to_reset"] <= SEVEN_DAY:
        resets_at = rl["seven_day"]["resets_at"]
        week["resets_at"] = resets_at
        # one forecast for the tank's colour, the bar and the chart
        week["avg"] = week_avg(inp.get("week_history") or [], week["used"], resets_at, now)
        if week["avg"] is not None:
            week["projected"] = week["used"] + week["avg"] * week["to_reset"] / 86400
            week["tier"] = projected_tier(week["used"], week["projected"])

    return {
        "now": now,
        "ctx_tank": ctx_tank,
        "five_tank": (None, 0) if not five else (five["used"], five["tier"], five["elapsed"]),
        "week_tank": (None, 0) if not week else (week["used"], week["tier"], week["elapsed"]),
        "five": five,
        "week": week,
        "claude": c,
        "git": inp.get("git"),
        "project": clean_project(inp.get("project")),
        "system": inp.get("system") or {},
        "week_history": inp.get("week_history") or [],
        "version": sanitize(inp["version"], 40) if isinstance(inp.get("version"), str) else None,
    }


# ---- project-info.json, cleaned ----------------------------------------------
# The repo you're in writes this file, so nothing in it is trusted: each field
# is kept only when it has the type and range docs/project-info.md gives it,
# and anything else is dropped. A bad field costs that field, never the line.

RUN_STATES = ("ok", "fail", "running", "cancelled")
DEPLOY_STATES = ("ok", "fail", "running")
CHECK_STATES = ("pass", "fail", "pending", "none")


def number(v, lo=0):
    """`v` if it's a finite number of at least `lo` (not a bool), else None."""
    try:
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= lo
    except OverflowError:  # an int too big for a float
        return None
    return v if ok else None


def text(v):
    """A string as it is, a number as a string, anything else None."""
    if isinstance(v, str):
        return v
    return str(v) if number(v, -math.inf) is not None else None


def pick(d, fields):
    """{key: cleaned value} for each of `fields` (key -> cleaner) that survives."""
    if not isinstance(d, dict):
        return None
    out = {}
    for key, clean in fields.items():
        if key in d:
            v = clean(d[key])
            if v is not None:
                out[key] = v
    return out


def named(d, clean):
    """A {name: section} map, keeping string names whose section cleans."""
    if not isinstance(d, dict):
        return None
    out = {k: clean(v) for k, v in d.items() if isinstance(k, str)}
    return {k: v for k, v in out.items() if v is not None} or None


def listed(v, clean):
    if not isinstance(v, list):
        return None
    return [x for x in map(clean, v) if x is not None]


def one_of(states):
    return lambda v: v if isinstance(v, str) and v in states else None


# every section may carry these; error and tried_at come from `project-info refresh`
STAMPS = {"updated_at": number, "stale_after": lambda v: number(v, 1), "url": text, "error": text, "tried_at": number}


def clean_project(p):
    """project-info.json reduced to what the status line can draw safely, or
    None when it isn't schema 1."""
    if not isinstance(p, dict) or p.get("schema") != 1:
        return None
    count = lambda v: number(v) if isinstance(v, int) else None
    out = pick(p, {
        "stale_after": lambda v: number(v, 1),
        "ci": lambda v: named(v, lambda c: pick(c, {"runs": lambda r: listed(r, one_of(RUN_STATES)), **STAMPS})),
        "deploy": lambda v: named(v, lambda d: pick(d, {
            "version": text, "status": one_of(DEPLOY_STATES), "deployed_at": number, "behind": count, **STAMPS})),
        "prs": lambda v: pick(v, {
            "open": count, "needs_review": count, **STAMPS,
            "items": lambda i: listed(i, lambda x: pick(x, {
                "number": lambda n: n if count(n) is not None or isinstance(n, str) else None,
                "checks": one_of(CHECK_STATES), "draft": lambda b: b if isinstance(b, bool) else None,
                "url": text}))}),
        "branches": lambda v: named(v, lambda b: pick(b, {
            "checks": lambda c: pick(c, {"pass": count, "fail": count, "pending": count}), **STAMPS})),
        "extra": lambda v: listed(v, lambda e: pick(e, {"icon": text, "text": text, "state": text, **STAMPS})),
    })
    out["schema"] = 1
    return out


def clean_claude(c):
    """Claude Code's input reduced to the fields the status line reads, each
    of the type it expects. A field of another type is dropped, so if a new
    Claude Code version changes one, that field goes missing, not the line."""
    word = lambda v: v if isinstance(v, str) else None
    window = lambda w: pick(w, {"used_percentage": number, "resets_at": number})
    out = pick(c, {
        "session_id": word, "session_name": word, "cwd": word,
        "fast_mode": lambda v: v if isinstance(v, bool) else None,
        "model": lambda v: pick(v, {"id": word, "display_name": word}),
        "effort": lambda v: pick(v, {"level": word}),
        "workspace": lambda v: pick(v, {"current_dir": word, "git_worktree": word,
                                        "repo": lambda r: pick(r, {"host": word, "owner": word, "name": word})}),
        "cost": lambda v: pick(v, {"total_duration_ms": number, "total_lines_added": number,
                                   "total_lines_removed": number}),
        "context_window": lambda v: pick(v, {"used_percentage": number, "context_window_size": number}),
        "rate_limits": lambda v: pick(v, {"five_hour": window, "seven_day": window}),
        "prompt_cache": lambda v: pick(v, {"warm": lambda b: b if isinstance(b, bool) else None}),
        "pr": lambda v: pick(v, {"number": lambda n: n if isinstance(n, str) or number(n) is not None else None,
                                 "url": word, "review_state": word}),
    })
    return out or {}


# ---- columns -----------------------------------------------------------------


MARKS = (("conflicts", "✖", BRICK), ("staged", "●", SAGE), ("modified", "✚", OLIVE),
         ("untracked", "?", DIM), ("ahead", "↑", CYAN), ("behind", "↓", TERRA))


def commit_age_style(g, age):
    """Uncommitted work getting old is worth a nudge; a clean tree is not."""
    dirty = any(g.get(k) for k in ("conflicts", "staged", "modified", "untracked"))
    return TERRA if dirty and age > 3 * 3600 else OLIVE if dirty and age > 3600 else DIM


def repo_column(m):
    c, g = m["claude"], m["git"]
    ws = c.get("workspace") or {}
    cwd = ws.get("current_dir") or c.get("cwd") or os.getcwd()
    if not g:
        return [[seg(Path(cwd).name or cwd)], [seg("no git", DIM)]]

    name = (ws.get("repo") or {}).get("name") or g.get("repo") or Path(cwd).name
    first = [seg(name)]
    wt = ws.get("git_worktree")
    if wt:
        first += [seg(" wt:", DIM), seg(wt, DIM)]

    branch = g.get("branch")
    name = branch or g.get("rebasing")
    second = [seg(name, CYAN)] if name else [seg(f"detached {g.get('sha', '')[:7]}", OLIVE)]
    if g.get("state"):
        second += [seg(" "), seg(g["state"], OLIVE)]

    marks = []
    for key, glyph, style in MARKS:
        if g.get(key):
            marks.append(seg(f"{glyph}{g[key]}", style))
            marks.append(seg(" "))
    third = marks[:-1] if marks else [seg("git slow" if g.get("status_unknown") else "clean", DIM)]
    if g.get("last_commit"):
        age = m["now"] - g["last_commit"]
        third = third + [seg(" · ", DIM), seg(fmt_age(age), commit_age_style(g, age))]

    rows = [first, second, third]
    pr = pr_line(c.get("pr"), m)
    if pr:
        rows.append(pr)
    return rows


# short, since the widest PR row sets the repo column's width
REVIEW = {"approved": ("lgtm", SAGE), "changes_requested": ("⟲ changes", BRICK),
          "pending": ("in review", DIM), "draft": ("draft", DIM)}


def branch_checks(m):
    """(words, colour) for this branch's checks from project-info, or None:
    `✗ 2/9` when any failed, `⟳ 5/9` while some run, `✓` when all passed."""
    branch = (m["git"] or {}).get("branch")
    info = ((m["project"] or {}).get("branches") or {}).get(branch) or {}
    checks = info.get("checks") or {}
    p, f, w = (int(checks.get(k) or 0) for k in ("pass", "fail", "pending"))
    total = p + f + w
    if f:
        return f"✗ {f}/{total}", BRICK  # the red ✗ says fail
    if w:
        return f"⟳ {p}/{total}", AMBER
    return ("✓", SAGE) if total else None


def pr_line(pr, m):
    if not pr or not pr.get("number"):
        return None
    out = [seg(f"#{pr['number']}", CYAN, pr.get("url"))]
    checks = branch_checks(m)
    if checks:
        out += [seg(" "), seg(*checks)]
    review = REVIEW.get(pr.get("review_state"))
    if review:
        out += [seg(" "), seg(*review)]
    return out


RUN = {"ok": ("✓", SAGE), "fail": ("✗", BRICK), "running": ("⟳", AMBER), "cancelled": ("○", DIM)}


def stale(section, project, now):
    limit = section.get("stale_after") or project.get("stale_after") or DEFAULT_STALE_AFTER
    at = section.get("updated_at")
    return at is not None and now - at > limit


def dim_if_stale(line, section, project, now):
    if not stale(section, project, now):
        return line
    age = fmt_age(now - section["updated_at"])
    return [(t, DIM, l) for t, _, l in line] + [seg(f" · {age} old", DIM)]


def ship_column(m):
    """Rows from project-info.json, or [] when the repo publishes none. Its
    extra notices go on the alerts line instead (see alerts_line)."""
    p, now = m["project"], m["now"]
    if not p:
        return []
    rows = []

    for name, ci in list((p.get("ci") or {}).items())[:2]:
        runs = (ci.get("runs") or [])[-5:]
        line = [seg(f"{sanitize(name, 5):<6}", DIM, ci.get("url"))]
        line += [seg(*RUN.get(r, ("?", DIM))) for r in runs]
        rows.append(dim_if_stale(line, ci, p, now))

    for env, d in (p.get("deploy") or {}).items():
        line = [seg(f"{sanitize(env, 5):<6}", DIM, d.get("url"))]
        status = d.get("status")
        if status == "fail":
            line.append(seg("✗ deploy failed", BRICK))
        elif status == "running":
            line.append(seg("⟳ deploying", AMBER))
        else:
            line += [seg("✓ ", SAGE), seg(sanitize(d.get("version", "?"), 20))]
        if d.get("deployed_at") and status != "running":
            line += [seg(" · ", DIM), seg(fmt_age(now - d["deployed_at"]), DIM)]
        behind = d.get("behind")
        if behind:
            line += [seg(" · ", DIM), seg(f"{behind} behind", OLIVE if behind < 10 else TERRA)]
        rows.append(dim_if_stale(line, d, p, now))

    prs = p.get("prs")
    if prs:
        line = [seg("PRs   ", DIM, prs.get("url"))] + pr_checks(prs)
        if prs.get("needs_review"):
            line += [seg(" · ", DIM), seg(f"{prs['needs_review']} need review", OLIVE)]
        rows.append(dim_if_stale(line, prs, p, now))

    # four rows fit beside the tanks; when there are more, healthy rows go
    # first so a failure or warning is never the one cut
    while len(rows) > 4:
        quiet = [i for i, r in enumerate(rows) if not alarming(r)]
        rows.pop(quiet[-1] if quiet else -1)
    return rows


NOTICE_ICONS = {"alert": "⚠", "info": "ℹ", "pr": "#", "ci": "⚙", "deploy": "⇪", "issue": "●"}
NOTICE_STATES = {"ok": SAGE, "warn": OLIVE, "bad": BRICK, "info": CYAN, "muted": DIM}


def notice_rows(m):
    """project-info's extra notices, one row each: `⚠ migration pending`."""
    p, now = m["project"] or {}, m["now"]
    rows = []
    for e in p.get("extra") or []:
        style = NOTICE_STATES.get(e.get("state"), None)
        line = [seg(NOTICE_ICONS.get(e.get("icon"), "·") + " ", style), seg(sanitize(e.get("text", "")), style)]
        rows.append(dim_if_stale(line, e, p, now))
    return rows


def refresh_alert(m):
    """`⚠ can't refresh CI, PRs: <error>` when refreshing has failed for
    sections that are now stale or were never fetched. One failed try while
    the data is still recent says nothing: the next try may well work."""
    p, now = m["project"] or {}, m["now"]
    branch = (m["git"] or {}).get("branch")
    sections = [("CI", c) for c in (p.get("ci") or {}).values()]
    sections += [(env, d) for env, d in (p.get("deploy") or {}).items()]
    sections += [("PRs", p.get("prs")), ("checks", (p.get("branches") or {}).get(branch))]
    failing = [(label, s["error"]) for label, s in sections
               if s and s.get("error") and (s.get("updated_at") is None or stale(s, p, now))]
    if not failing:
        return []
    labels = list(dict.fromkeys(sanitize(label, 12) for label, _ in failing))
    return [seg(f"⚠ can't refresh {', '.join(labels)}: ", OLIVE), seg(sanitize(failing[0][1], 60), OLIVE)]


CHECKS = {"pass": ("✓", SAGE), "fail": ("✗", BRICK), "pending": ("⟳", AMBER), "none": ("·", DIM)}
PR_ITEMS_MAX = 4  # past this many open PRs, show counts per state instead of each one


def pr_checks(prs):
    """Each open PR as #N plus its checks glyph, or counts per state when there
    are many. Without `items` (an older feed), just the open count."""
    items = [i for i in prs.get("items") or [] if isinstance(i, dict)]
    if not items:
        return [seg(f"{prs.get('open', 0)} open")]
    if len(items) <= PR_ITEMS_MAX:
        out = []
        for i in items:
            glyph, style = CHECKS.get(i.get("checks"), CHECKS["none"])
            if out:
                out.append(seg(" "))
            out += [seg(f"#{sanitize(i.get('number', '?'), 6)}", DIM if i.get("draft") else None, i.get("url")),
                    seg(glyph, style)]
        return out
    out = [seg(f"{len(items)} open")]
    for word in ("pass", "pending", "fail"):
        n = sum(1 for i in items if i.get("checks") == word)
        if n:
            glyph, style = CHECKS[word]
            out += [seg(" "), seg(f"{glyph}{n}", style)]
    return out


def alarming(line):
    return any(style in (BRICK, AMBER, OLIVE, TERRA) for _, style, _ in line)


def session_column(m, week=True, five=True):
    """`week=False` and `five=False` when the week column shows them."""
    c, now = m["claude"], m["now"]
    model = (c.get("model") or {}).get("display_name") or "?"
    first = [seg(model)]
    effort = (c.get("effort") or {}).get("level")
    if effort:
        first += [seg(" "), seg(effort, DIM)]
    if c.get("fast_mode"):
        first += [seg(" "), seg("fast", AMBER)]
    dur = (c.get("cost") or {}).get("total_duration_ms")
    if dur:
        first += [seg(" · ", DIM), seg(fmt_dur(dur / 1000))]

    name = c.get("session_name")
    second = [seg(sanitize(name, 30) if len(name) <= 30 else sanitize(name, 29) + "…")] if name else [seg("untitled", DIM)]

    third = [seg((c.get("session_id") or "--------")[:8], DIM)]
    cost = c.get("cost") or {}
    added, removed = cost.get("total_lines_added"), cost.get("total_lines_removed")
    if added or removed:
        third += [seg(" · ", DIM), seg(f"+{fmt_count(added or 0)}", SAGE),
                  seg(" "), seg(f"−{fmt_count(removed or 0)}", BRICK)]

    return [first, second, third, runway_line(m, week, five)]


def runway_line(m, show_week=True, show_five=True):
    """The 5h window and the week bar. Whatever is news goes on the alerts line."""
    five, week = m["five"], m["week"]
    week = week if show_week else None
    five = five if show_five else None
    items = []
    if five:
        if five["used"] >= 100:
            items.append([seg("5h full", BRICK)] + reset_hint(five))
        elif five["to_full"] is not None and five["to_reset"] is not None and five["to_full"] < five["to_reset"]:
            items.append([seg(f"5h out ~{fmt_dur(five['to_full'])}", TIERS[five["tier"]])])
        elif five["to_reset"] is not None:
            items.append([seg("5h", DIM)] + reset_hint(five))
    if week:
        if week["used"] >= 100:
            items.append([seg("wk full", BRICK)] + reset_hint(week))
        else:
            items.append(week_bar(m))
    return join(items)


WEEK_CELLS = 20


def clock(ts):
    """`Mon 8am`: local day and nearest hour, all a projection days out can promise."""
    t = time.localtime(ts + 1800)
    return f"{time.strftime('%a', t)} {t.tm_hour % 12 or 12}{'am' if t.tm_hour < 12 else 'pm'}"


def week_bar(m, cells=WEEK_CELLS):
    """The week chart on one line, for when it has no column:
    `wk ████████▓▓▓▓░░░░░░░░ ~59% by Mon 7pm`. Each █ is 5% of the week in the
    colour of the day that spent it, ▓ the rest of the week at the 7-day
    average in grey, ░ left over at reset; past 100% a purple ▶ says when it
    runs out. No forecast in the window's first ~day."""
    week, now = m["week"], m["now"]
    used, avg = week["used"], week.get("avg")
    filled = round(min(100, used) / 100 * cells)
    bar = [seg("wk ")]
    if week.get("resets_at"):
        days, at, _, _ = week_days(m)
        for i in range(filled):
            mid = (i + 0.5) * 100 / cells
            # the first day whose running total passes this cell's middle
            tone = next((c for a, b, c in days if a <= now and at(min(b, now)) >= mid), SAGE)
            bar.append(seg("█", tone))
    else:
        bar.append(seg("█" * filled))
    words, style = forecast(week, now)
    if avg is None or week["to_reset"] is None or used >= 100:
        return bar + [seg("░" * (cells - filled), DIM)] + ([seg(" "), seg(words, style)] if words else [])
    projected = used + avg * week["to_reset"] / 86400
    ahead = round(min(100, projected) / 100 * cells) - filled
    bar += [seg("▓" * ahead, GREY), seg("░" * (cells - filled - ahead), DIM)]
    return bar + ([seg("▶ " + words, PURPLE)] if style == PURPLE else [seg(" " + words)])


# ---- week column ---------------------------------------------------------------
# The week as a chart: one bar per day, its height what that day alone spent,
# with the number under it. A past day takes its colour from that spend against
# its share of the week; days still to come are grey, splitting all that's
# unspent by their length, so the numbers add up to 100.

DAY_START = env_int("CLAUDE_STATUSLINE_DAY_START", 4, 0, 23)  # pick an hour you're asleep, so no session is split
DAY_SLIVER = 6 * 3600
DAY_WIDTH = 3       # a gap and a two-wide bar
CHART_ROWS = 2
CHART_FLOOR = 150 / 7  # the scale's least top: half again a day's share, so a quiet week isn't all tall bars


def usage_at(history, resets_at, t):
    """The window's percentage at time t: its highest reading by then, or 0."""
    start = resets_at - SEVEN_DAY
    return max((r["pct"] for r in history
                if r.get("resets_at") == resets_at and start <= r["at"] <= t), default=0)


def week_avg(history, used, resets_at, now):
    """Percent per day over the last 7 days. That reaches back into the
    previous window, so it needs a reading from there at least 7 days old;
    without one it is this window's own average, or None in the window's
    first ~day, when that is a few hours of use."""
    start = resets_at - SEVEN_DAY
    cutoff = now - SEVEN_DAY
    prev = [r for r in history if r.get("resets_at") == start and r["at"] >= start - SEVEN_DAY]
    then = [r["pct"] for r in prev if r["at"] <= cutoff]
    if then:
        return (used + max(r["pct"] for r in prev) - max(then)) / 7
    elapsed = (now - start) / SEVEN_DAY
    return used / (elapsed * 7) if elapsed >= 0.15 else None


def day_cuts(start, end, hour=DAY_START):
    """[(a, b)] covering start..end, cut at `hour` local time each day. A
    piece under 6 hours at either end joins its neighbour, so no day's bar
    stands for a few minutes."""
    # each cut is made from its own date, so a clock change doesn't shift the rest
    at = lambda day: time.mktime(time.localtime(start)[:2] + (time.localtime(start)[2] + day, hour, 0, 0, 0, 0, -1))
    day = 0
    while at(day) <= start:
        day += 1
    cuts = [start]
    while at(day) < end:
        cuts.append(at(day))
        day += 1
    if len(cuts) > 2 and cuts[1] - start < DAY_SLIVER:
        del cuts[1]
    if len(cuts) > 2 and end - cuts[-1] < DAY_SLIVER:
        cuts.pop()
    return list(zip(cuts, cuts[1:] + [end]))


def day_name(a, b):
    """`Mon`: the date the day's middle falls on, counting days from DAY_START,
    so 1am Friday is Thursday's and a joined sliver doesn't rename it."""
    return time.strftime("%a", time.localtime((a + b) / 2 - DAY_START * 3600))


def day_tone(spent, share):
    r = spent / share
    return SAGE if r <= 1 else OLIVE if r < 1.3 else TERRA if r < 1.8 else BRICK


def week_days(m):
    """The window's days and how to read them: ([(start, end, colour)],
    usage-at-time, what a day spent, when the log starts). A past or current
    day's colour is what it spent against its share; later days grey."""
    week, now = m["week"], m["now"]
    resets_at = week["resets_at"]
    start = resets_at - SEVEN_DAY
    # the live reading counts even before the log has caught up with it
    history = m["week_history"] + [{"at": now, "pct": week["used"], "resets_at": resets_at}]
    at = lambda t: usage_at(history, resets_at, t)
    logged = [r["at"] for r in m["week_history"] if r.get("resets_at") == resets_at and r["at"] >= start]
    since = min(logged, default=now)
    # usage from before the log's first reading can't be put on a day (on a
    # fresh install that's the whole week so far), so the day the log starts
    # in counts from that reading
    spent = lambda a, b: at(min(b, now)) - at(max(a, since))
    days = [(a, b, day_tone(spent(a, b), 100 / 7 * (b - a) / 86400) if a <= now else GREY)
            for a, b in day_cuts(start, resets_at)]
    return days, at, spent, since


def forecast(week, now):
    """(words, colour) for where the week ends up: `~59% by Mon 7pm`, purple
    `out Thu 9pm` when it would pass 100%, `out until Mon 7pm` at the cap,
    (None, None) before there is a forecast."""
    used, avg, to_reset = week["used"], week.get("avg"), week["to_reset"]
    reset = clock(week["resets_at"]) if week.get("resets_at") else fmt_dur(to_reset or 0)
    if used >= 100:
        return f"out until {reset}", BRICK
    if avg is None or to_reset is None:
        return None, None
    ends = used + avg * to_reset / 86400
    if ends > 100:
        return f"out {clock(now + (100 - used) / avg * 86400)}", PURPLE
    return f"~{round(ends)}% by {reset}", None


def whole(parts, total):
    """`parts` as whole numbers that add up to round(total): each rounds down,
    then the biggest remainders take what that left over."""
    out = [int(p) for p in parts]
    for i in sorted(range(len(parts)), key=lambda i: out[i] - parts[i])[:round(total) - sum(out)]:
        out[i] += 1
    return out


def week_column(m):
    """The week chart: two rows of daily bars, each day's percent under its
    bar, and a row of day names, with four short lines beside it: used now,
    where the week ends up, what each day to come gets if today stops here,
    and the 5h window. [] without a week window, or once it has reset."""
    week, now = m["week"], m["now"]
    # Claude Code can send the old window for a moment after it resets
    if not week or not week.get("resets_at") or not week["to_reset"]:
        return []
    days, bars, numbers = week_bars(m)
    band = max(CHART_FLOOR, *(v for v, _ in bars if v is not None)) / CHART_ROWS
    rows = []
    for row in reversed(range(CHART_ROWS)):
        line = []
        for v, style in bars:
            if v is None:  # no reading yet: dim dots along the floor
                line.append(seg(" ··" if row == 0 else "   ", DIM))
            else:
                line.append(seg(" " + BLOCKS[max(0, min(8, round((v - row * band) / band * 8)))] * 2, style))
        rows.append(line)
    rows.append([seg(" " * DAY_WIDTH if n is None else f"{n:>{DAY_WIDTH}}", DIM if style == GREY else style)
                 for n, (_, style) in zip(numbers, bars)])
    rows.append([seg(" " + day_name(a, b)[:2], style) for a, b, style in days])

    side = [[seg(words, style)] for words, style in week_words(m, days)]
    side += [[]] * (3 - len(side)) + [runway_line(m, show_week=False)]
    return [r + ([seg("  ")] + t if t else []) for r, t in zip(rows, side)]


def week_bars(m):
    """The chart's days, its bars and the number under each: (days from
    week_days, [(percent or None before the log, colour)], [whole number or
    None]). Past days show what they spent; days to come split all that's
    unspent by their length, and their numbers round so the week adds to 100."""
    week, now = m["week"], m["now"]
    # before the log's first reading in this window there is nothing to draw
    days, at, spent, since = week_days(m)
    left = max(0, 100 - week["used"])
    ahead = sum(b - a for a, b, _ in days if a > now)
    bars = []
    for a, b, style in days:
        if a > now:  # all that's unspent, over the days to come by their length
            bars.append((left * (b - a) / ahead, GREY))
        elif b <= since:
            bars.append((None, DIM))
        else:
            bars.append((spent(a, b), style))
    # past days are whole readings apart; the days to come round so they add up to what's left
    shares = iter(whole([v for v, style in bars if style == GREY], left))
    numbers = [None if v is None else next(shares) if style == GREY else round(v) for v, style in bars]
    return days, bars, numbers


def week_words(m, days):
    """The lines beside the chart, as (words, colour): used now, where the
    week ends up, and what each day to come gets. A line with nothing to
    say is left out, so there's no gap."""
    week, now = m["week"], m["now"]
    used = week["used"]
    left = max(0, 100 - used)
    ahead = sum(b - a for a, b, _ in days if a > now)
    words, style = forecast(week, now)
    lines = [(f"{round(used)}% now", None), (words, style) if words else None]
    # as if today stops here, like the grey bars. A rate only reads right
    # over whole days, so one day left, or none after today, is named
    if used < 100:
        lines.append((f"{left / (ahead / 86400):.0f}%/day to use it all", DIM) if ahead > 86400 else
                     (f"{round(left)}% left for {day_name(*days[-1][:2])}", DIM) if ahead else
                     (f"{round(left)}% left today", DIM))
    return [line for line in lines if line]


# ---- cpu and mem -------------------------------------------------------------
# Drawn two ways: as the system column's meters when there's room, or as
# alert-only text on the runway line when there isn't. Same words in both.


def meter(label, pct, style, cells=8):
    """`cpu ▮▮▮▮▮▯▯▯ 62%`, or a dim empty meter before there's a reading."""
    if pct is None:
        return [seg(f"{label} {'▯' * cells} --", DIM)]
    filled = max(0, min(cells, round(pct / 100 * cells)))
    return [seg(f"{label} {'▮' * filled}{'▯' * (cells - filled)} {int(pct):>2d}%", style)]


def fmt_mb(mb):
    return f"{mb / 1024:.1f}G" if mb >= 1024 else f"{int(mb)}M"


def cpu_state(cpu):
    """(usage, waiting, style). Orange from 70% busy. Red when the cores are
    saturated (90%+) and load is past the core count, which is how many are
    waiting. macOS load runs high on idle machines (a VM's threads count), so
    load alone never turns it red."""
    usage = (cpu or {}).get("usage")
    if usage is None:
        return None, 0, DIM
    waiting = int(float(cpu["load"]) - cpu["cores"] + 0.5) if usage >= 90 else 0
    return usage, waiting, BRICK if waiting >= 1 else TERRA if usage >= 70 else SAGE


def cpu_detail(cpu):
    """`2 cpu wait · node` while tasks queue for a core, else nothing."""
    _, waiting, _ = cpu_state(cpu)
    if waiting < 1:
        return []
    out = [seg(f"{waiting} cpu wait", BRICK)]
    if cpu.get("top"):
        out += [seg(" · ", DIM), seg(cpu["top"], BRICK)]
    return out


def cpu_segs(cpu):
    """Alert-only form: the meter from 50% busy, plus the queue when saturated."""
    usage, _, style = cpu_state(cpu)
    if usage is None or usage < 50:
        return []
    detail = cpu_detail(cpu)
    return meter("cpu", usage, style) + ([seg(" · ", DIM)] + detail if detail else [])


# macOS's own pressure levels, the same as Activity Monitor's graph
PRESSURE = ((4, "crit", BRICK), (2, "warn", TERRA), (0, "normal", SAGE))


def pressure(mem):
    """(word, color) for kern.memorystatus_vm_pressure_level: 1, 2 or 4."""
    level = (mem or {}).get("pressure") or 1
    return next((word, style) for floor, word, style in PRESSURE if level >= floor)


def app_segs(app, style, room=16):
    """`Chrome 8.1G`, the name shortened so the size always survives."""
    size = fmt_mb(app["mb"])
    name, room = app["name"], room - len(size) - 1
    if len(name) > room:
        name = name[:max(1, room - 1)] + "…"
    return [seg(f"{name} {size}", style)]


ARROWS = {"up": "↑", "down": "↓", "steady": "→"}


def flow_segs(mem):
    """`comp 6.5G ↑ · swap 2.8G ↑`. comp is RAM holding compressed pages:
    always shown, dim while pressure is normal, its arrow saying which way it
    moved in the last minute. swap only shows while pages are moving to or
    from disk; swap that just sits there is left over from earlier pressure."""
    word, style = pressure(mem)
    out = []
    if mem.get("comp_mb") is not None:
        out += [seg(f"comp {fmt_mb(mem['comp_mb'])}", DIM if word == "normal" else style)]
        trend = mem.get("comp_trend")
        if trend in ARROWS:
            out += [seg(" "), seg(ARROWS[trend], {"up": style, "down": SAGE}.get(trend, DIM))]
    swap = mem.get("swap_trend")
    if swap in ("up", "down") and mem.get("swap_mb") is not None:
        color = (BRICK if word == "crit" else TERRA) if swap == "up" else OLIVE
        if out:
            out.append(seg(" · ", DIM))
        out += [seg(f"swap {fmt_mb(mem['swap_mb'])} {ARROWS[swap]}", color)]
    return out


def mem_meter(mem):
    """`mem ▮▮▮▮▯▯▯▯ 49% · comp 4.4G →`. The fill is how full macOS says memory
    is; the color is its pressure level, which is the one to trust."""
    mem = mem or {}
    _, style = pressure(mem)
    flow = flow_segs(mem)
    return meter("mem", mem.get("used_pct"), style) + ([seg(" · ", DIM)] + flow if flow else [])


def mem_detail(mem, room):
    """`pressure warn · Chrome 8.1G` once pressure is past normal, else nothing."""
    word, style = pressure(mem)
    if word == "normal":
        return []
    out = [seg(f"pressure {word}", style)]
    if mem.get("top"):
        out += [seg(" · ", DIM)] + app_segs(mem["top"], style, room - width(out) - 3)
    return out


def mem_segs(mem):
    """Alert-only form: silent when normal, else `mem pressure warn · comp 6.5G ↑
    · swap 2.8G ↑ · Chrome 8.1G`, naming the app whose memory you'd get back
    by quitting it."""
    word, style = pressure(mem)
    if not mem or word == "normal":
        return []
    out = [seg(f"mem pressure {word}", style)]
    flow = flow_segs(mem)
    if flow:
        out += [seg(" · ", DIM)] + flow
    if mem.get("top"):
        out += [seg(" · ", DIM)] + app_segs(mem["top"], style)
    return out


def system_column(m):
    """Four rows: the cpu meter, its detail, the mem meter, its detail. Each
    detail sits indented under its meter and stays blank until there's trouble,
    so nothing moves when an alert appears."""
    s = m["system"]
    cpu, mem = s.get("cpu"), s.get("memory")
    if not cpu and not mem:
        return []
    indent = 4
    under = lambda segs: [seg(" " * indent)] + segs if segs else []
    usage, _, style = cpu_state(cpu)
    cpu_row = join([x for x in (cpu_detail(cpu), battery_segs(s.get("battery"))) if x])
    return [meter("cpu", usage, style), under(cpu_row),
            mem_meter(mem), under(mem_detail(mem or {}, SYSTEM_WIDTH - indent))]


def battery_segs(batt):
    """`batt 22%` on battery under 30%, else nothing."""
    if batt and batt.get("pct") is not None and not batt.get("ac") and batt["pct"] < 30:
        return [seg(f"batt {batt['pct']}%", BRICK if batt["pct"] < 15 else TERRA)]
    return []


def alerts_line(m, machine=False):
    """Layout B's fifth line: everything that comes and goes, so it never
    widens a column. Project notices and a cold cache always; the battery,
    cpu queue and memory pressure only when there is no machine column to
    hold them (`machine=False`). [] when there is nothing to say."""
    items = notice_rows(m) + [refresh_alert(m)]
    cache = m["claude"].get("prompt_cache")
    if cache and cache.get("warm") is False:  # warm is normal; only cold is news
        items.append([seg("cache cold", OLIVE)])
    if not machine:
        sysinfo = m["system"]
        items += [battery_segs(sysinfo.get("battery")), cpu_segs(sysinfo.get("cpu")), mem_segs(sysinfo.get("memory"))]
    return join(items, "  ·  ")


def reset_hint(window):
    return [] if window["to_reset"] is None else [seg(f" ↻{fmt_dur(window['to_reset'])}", DIM)]


# ---- layouts ---------------------------------------------------------------
RULE = [seg("┃ ", DIM)]


def layout_columns(m, cols):
    """Layout B: tanks, then one column per area separated by heavy rules,
    and under them the alerts line for whatever comes and goes. The week
    column and then the system column go after the session, each only when
    everything before it fits beside it; without room the week shrinks back
    to a bar on the session's last row, and the system column is the first
    thing given up. Returns (lines, whether the system column showed)."""
    week, system = week_column(m), system_column(m)
    # the system column reserves SYSTEM_WIDTH, so an alert row never resizes it
    span = lambda g: max(SYSTEM_WIDTH, max(width(r) for r in g)) if g is system else max(width(r) for r in g)
    for week_col, system_col in ((week, system), (week, []), ([], system), ([], [])):
        groups = [g for g in (repo_column(m), ship_column(m)) if g]
        groups.append(session_column(m, week=not week_col, five=not week_col))
        groups += [g for g in (week_col, system_col) if g]
        natural = [span(g) for g in groups]
        if 15 + sum(natural) + 3 * (len(groups) - 1) <= cols:
            break
    widths = fit(natural, cols - 15 - 3 * (len(groups) - 1))
    tank = tanks(m)
    lines = []
    for r in range(4):
        line = tank[r] + [seg("   ")]
        for i, (g, w) in enumerate(zip(groups, widths)):
            cell = truncate(g[r], w) if r < len(g) else []
            last = i == len(groups) - 1
            line += cell if last else pad(cell, w) + [seg(" ")] + RULE
        lines.append(truncate(line, cols))
    return lines, bool(system_col)


def fit(widths, room, floor=12):
    """Shrink the widest columns one step at a time until they fit in room."""
    widths = list(widths)
    while sum(widths) > room and max(widths) > floor:
        widths[widths.index(max(widths))] -= 1
    return widths


def layout_rows(m, cols):
    """Layout A: each area flattened onto one line beside the tanks."""
    repo = repo_column(m)
    # labels are padded for column alignment; flattened, one space is enough
    ship = [[(r[0][0].rstrip() + " ", r[0][1], r[0][2])] + r[1:] for r in ship_column(m)]
    sess = session_column(m)
    rows = [join(repo), join(ship), join(sess[:3]), sess[3]]
    rows = [r for r in rows if r]
    tank = tanks(m)
    # a row with nothing to say gets no rule either
    return [truncate(tank[i] + ([seg(" ")] + RULE + rows[i] if i < len(rows) else []), cols)
            for i in range(4)]


def render_lines(inp, cols=None):
    """The status line as styled segment lines (see `seg`), for tools that
    draw it some other way than a terminal, such as tools/screenshots.py."""
    cols = cols or inp.get("columns") or 200
    m = build_model(inp)
    lines, machine = layout_columns(m, cols)
    if max(width(l) for l in lines) > cols or cols < WIDE_MIN:
        lines, machine = layout_rows(m, cols), False
    lines = with_version(lines, m["version"], cols)
    news = alerts_line(m, machine)
    if news:
        lines.append(truncate(news, cols))
    return lines


def with_version(lines, label, cols):
    """The version, dim at the right edge of the bottom row, else of the
    second; left off when neither has room to spare beside what it says."""
    if not label:
        return lines
    tag = [seg(label, DIM)]
    for r in (3, 1):
        if r >= len(lines):
            continue
        line = list(lines[r])
        while line and not line[-1][0].strip():  # the padding after its last words
            line.pop()
        if line:
            line[-1] = (line[-1][0].rstrip(), *line[-1][1:])
        if width(line) + 3 + width(tag) <= cols:
            lines[r] = line + [seg(" " * (cols - width(line) - width(tag)))] + tag
            break
    return lines


def render(inp, cols=None, color=True):
    return "\n".join(ansi(l, color).rstrip() for l in render_lines(inp, cols))


# ---- view: the same model as plain data --------------------------------------
# For a surface that draws each part itself (the Claude desktop app's pane):
# the numbers, and every judgement the terminal drawing makes (a tank's pace
# colour, a day's tone, the forecast), so the two can't disagree. Colours are
# names; the surface picks the paint.

TONES = {SAGE: "sage", OLIVE: "olive", TERRA: "terra", BRICK: "brick", AMBER: "amber",
         CYAN: "cyan", GREY: "grey", PURPLE: "purple", DIM: "dim"}
VIEW_SCHEMA = 1


def tone(style):
    return TONES.get(style)


def view(inp, cols=None):
    m = build_model(inp)
    return scrubbed({
        "schema": VIEW_SCHEMA,
        "now": m["now"],
        "tanks": view_tanks(m),
        "repo": view_repo(m),
        "ship": view_ship(m),
        "session": view_session(m),
        "five": view_five(m),
        "week": view_week(m),
        "system": view_system(m),
        "alerts": [{"text": plain_text(line), "tone": next((tone(s) for _, s, _ in line if s), None)}
                   for line in notice_rows(m) + [refresh_alert(m)] + [cache_alert(m)] if line],
        "ansi": render(inp, cols),
        "blocks": view_blocks(m),
        "version": m["version"],
    })


def scrubbed(v, keep=("ansi", "blocks")):
    """Every string in the view as seg() would draw it: no control or format
    characters from git, a repo's file or Claude Code. `ansi` and `blocks`
    are drawings, already cleaned piece by piece, and keep their escapes."""
    if isinstance(v, str):
        return printable(v)
    if isinstance(v, list):
        return [scrubbed(x, ()) for x in v]
    if isinstance(v, dict):
        return {k: x if k in keep else scrubbed(x, ()) for k, x in v.items()}
    return v


def view_blocks(m):
    """Each part as the terminal draws it, apart: for a tall, narrow pane that
    stacks them rather than setting them side by side. A part with nothing
    to show is left out; the week takes the 5h line, so the session doesn't."""
    week = week_column(m)
    parts = [("tanks", tanks(m)), ("repo", repo_column(m)), ("ship", ship_column(m)),
             ("session", session_column(m, week=not week, five=not week)), ("week", week),
             ("system", system_column(m)), ("alerts", [alerts_line(m, machine=True)])]
    # a blank row only holds a column's place beside the others; stacked, it's a gap
    shown = lambda lines: [ansi(l).rstrip() for l in lines if plain_text(l).strip()]
    return [{"name": name, "lines": shown(lines)} for name, lines in parts if shown(lines)]


def plain_text(segs):
    return "".join(t for t, _, _ in segs)


def cache_alert(m):
    cache = m["claude"].get("prompt_cache")
    return [seg("cache cold", OLIVE)] if cache and cache.get("warm") is False else []


def view_tanks(m):
    ctx = (m["claude"].get("context_window") or {}).get("context_window_size")
    out = []
    for label, tank, window in (("ctx", m["ctx_tank"], None), ("5h", m["five_tank"], m["five"]),
                                ("wk", m["week_tank"], m["week"])):
        pct, tier = tank[0], tank[1]
        t = {"label": label, "pct": pct, "tone": None if pct is None else tone(TIERS[tier]),
             "elapsed": tank[2] if len(tank) > 2 else None}
        if window:
            t.update(to_reset=window["to_reset"], to_full=window["to_full"], projected=window["projected"])
        elif label == "ctx":
            t["size"] = ctx
        out.append(t)
    return out


def view_repo(m):
    c, g = m["claude"], m["git"]
    ws = c.get("workspace") or {}
    cwd = ws.get("current_dir") or c.get("cwd") or os.getcwd()
    if not g:
        return {"name": Path(cwd).name or cwd, "git": False}
    age = m["now"] - g["last_commit"] if g.get("last_commit") else None
    pr = c.get("pr") or {}
    checks = branch_checks(m)
    review = REVIEW.get(pr.get("review_state"))
    return {
        "git": True,
        "name": (ws.get("repo") or {}).get("name") or g.get("repo") or Path(cwd).name,
        "worktree": ws.get("git_worktree"),
        "branch": g.get("branch") or g.get("rebasing"),
        "sha": (g.get("sha") or "")[:7] or None,
        "state": g.get("state"),
        "marks": [{"kind": key, "glyph": glyph, "count": g[key], "tone": tone(style)}
                  for key, glyph, style in MARKS if g.get(key)],
        "status_unknown": bool(g.get("status_unknown")),
        "commit_age": age,
        "commit_tone": None if age is None else tone(commit_age_style(g, age)),
        "pr": None if not pr.get("number") else {
            "number": pr["number"], "url": pr.get("url"),
            "checks": None if not checks else {"text": checks[0], "tone": tone(checks[1])},
            "review": None if not review else {"text": review[0], "tone": tone(review[1])},
        },
    }


def view_ship(m):
    p, now = m["project"], m["now"]
    if not p:
        return None
    old = lambda s: now - s["updated_at"] if stale(s, p, now) else None
    deploys = []
    for env, d in (p.get("deploy") or {}).items():
        behind = d.get("behind")
        deploys.append({"env": sanitize(env, 12), "url": d.get("url"), "status": d.get("status") or "ok",
                        "version": sanitize(d.get("version", "?"), 20),
                        "age": now - d["deployed_at"] if d.get("deployed_at") else None,
                        "behind": behind or 0, "behind_tone": tone(OLIVE if (behind or 0) < 10 else TERRA),
                        "stale_age": old(d)})
    prs = p.get("prs")
    items = [i for i in (prs or {}).get("items") or [] if isinstance(i, dict)]
    return {
        "ci": [{"name": sanitize(name, 12), "url": ci.get("url"), "runs": (ci.get("runs") or [])[-5:],
                "stale_age": old(ci)} for name, ci in list((p.get("ci") or {}).items())[:2]],
        "deploys": deploys,
        "prs": None if not prs else {
            "url": prs.get("url"), "open": prs.get("open", len(items)), "needs_review": prs.get("needs_review") or 0,
            "items": [{"number": sanitize(i.get("number", "?"), 6), "url": i.get("url"),
                       "checks": i.get("checks") if i.get("checks") in CHECKS else "none",
                       "draft": bool(i.get("draft"))} for i in items],
            "stale_age": old(prs)},
    }


def view_session(m):
    c = m["claude"]
    cost = c.get("cost") or {}
    dur = cost.get("total_duration_ms")
    return {
        "model": (c.get("model") or {}).get("display_name"),
        "effort": (c.get("effort") or {}).get("level"),
        "fast": bool(c.get("fast_mode")),
        "duration": dur / 1000 if dur else None,
        "name": sanitize(c["session_name"], 60) if c.get("session_name") else None,
        "id": (c.get("session_id") or "")[:8] or None,
        "added": cost.get("total_lines_added"),
        "removed": cost.get("total_lines_removed"),
    }


def view_five(m):
    """The 5h window's state as runway_line words it: full, out before the reset, or fine."""
    five = m["five"]
    if not five:
        return None
    out = five["to_full"] is not None and five["to_reset"] is not None and five["to_full"] < five["to_reset"]
    state = "full" if five["used"] >= 100 else "out" if out else "ok"
    return {"used": five["used"], "state": state, "tone": tone(TIERS[five["tier"]]),
            "to_reset": five["to_reset"], "to_full": five["to_full"]}


def view_week(m):
    week, now = m["week"], m["now"]
    if not week:
        return None
    out = {"used": week["used"], "tone": tone(TIERS[week["tier"]]), "to_reset": week["to_reset"],
           "projected": week["projected"], "days": [], "lines": []}
    # Claude Code can send the old window for a moment after it resets
    if not week.get("resets_at") or not week["to_reset"]:
        return out
    days, bars, numbers = week_bars(m)
    out["days"] = [{"name": day_name(a, b), "pct": v, "number": n, "tone": tone(style),
                    "when": "later" if a > now else "now" if b > now else "past"}
                   for (a, b, _), (v, style), n in zip(days, bars, numbers)]
    out["lines"] = [{"text": words, "tone": tone(style)} for words, style in week_words(m, days)]
    return out


def view_system(m):
    s = m["system"]
    cpu, mem, batt = s.get("cpu"), s.get("memory"), s.get("battery")
    if not cpu and not mem:
        return None
    usage, waiting, cpu_style = cpu_state(cpu)
    mem = mem or {}
    word, mem_style = pressure(mem)
    swap = mem.get("swap_trend")
    low = battery_segs(batt)
    return {
        "cpu": {"usage": usage, "tone": tone(cpu_style), "waiting": waiting,
                "top": (cpu or {}).get("top") if waiting >= 1 else None},
        "memory": {"used_pct": mem.get("used_pct"), "pressure": word, "tone": tone(mem_style),
                   "comp_mb": mem.get("comp_mb"), "comp_trend": mem.get("comp_trend"),
                   # swap that just sits there is left over from earlier pressure
                   "swap_mb": mem.get("swap_mb") if swap in ("up", "down") else None,
                   "swap_trend": swap if swap in ("up", "down") else None,
                   "top": mem.get("top") if word != "normal" else None},
        "battery": None if not low else {"pct": batt["pct"], "tone": tone(low[0][1])},
    }


# ---- gathering (live mode only) ----------------------------------------------


def run(*args, cwd=None):
    try:
        out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=1.5)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


# A repo's own .git/config can name programs for git to run. These are the
# ones the reads below would trigger: a file monitor on every status, and a
# signature checker on log. Neither is needed to read state.
GIT = ("git", "-c", "core.fsmonitor=false", "-c", "log.showSignature=false", "--no-optional-locks")


def gather_git(cwd):
    paths = run(*GIT, "-C", cwd, "rev-parse", "--show-toplevel", "--git-common-dir", "--git-dir")
    if not paths:
        return None, None
    top, common, gitdir = (paths.strip().split("\n") + [""] * 3)[:3]
    common = (Path(cwd) / common).resolve()  # relative to cwd unless already absolute
    g = {"repo": common.parent.name if common.name == ".git" else Path(top).name}
    status = run(*GIT, "-C", cwd, "status", "--porcelain=v2", "--branch")
    if status is None:  # too slow or failed: say so, and still name the branch
        head = (run(*GIT, "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
        g.update(branch=None if head in ("", "HEAD") else head, status_unknown=True)
    else:
        g.update(parse_status(status))
    g.update(operation(Path(cwd) / gitdir))
    ct = run(*GIT, "-C", cwd, "log", "-1", "--format=%ct")
    if ct and ct.strip().isdigit():
        g["last_commit"] = int(ct.strip())
    return g, common


def operation(gitdir):
    """{"state": "rebasing", "rebasing": "feat/cart"} when git is part way
    through something, from the files it keeps in this worktree's git folder."""
    for folder in ("rebase-merge", "rebase-apply"):
        if (gitdir / folder).is_dir():
            try:
                head = (gitdir / folder / "head-name").read_text(errors="replace").strip()
            except OSError:
                head = ""
            return {"state": "rebasing", "rebasing": re.sub(r"^refs/heads/", "", head) or None}
    for file, state in (("MERGE_HEAD", "merging"), ("CHERRY_PICK_HEAD", "cherry-picking"),
                        ("REVERT_HEAD", "reverting"), ("BISECT_LOG", "bisecting")):
        if (gitdir / file).exists():
            return {"state": state}
    return {}


def parse_status(status):
    """Counts from `git status --porcelain=v2 --branch`."""
    g = {}
    for line in status.splitlines():
        if line.startswith("# branch.head "):
            head = line[14:]
            g["branch"] = None if head == "(detached)" else head
        elif line.startswith("# branch.oid "):
            g["sha"] = line[13:]
        elif line.startswith("# branch.ab "):
            a, b = line[12:].split()
            g["ahead"], g["behind"] = int(a), -int(b)
        elif line[:2] in ("1 ", "2 "):
            x, y = line[2], line[3]
            g["staged"] = g.get("staged", 0) + (x != ".")
            g["modified"] = g.get("modified", 0) + (y != ".")
        elif line.startswith("u "):
            g["conflicts"] = g.get("conflicts", 0) + 1
        elif line.startswith("? "):
            g["untracked"] = g.get("untracked", 0) + 1
    return g


def gather_project(common):
    try:
        data = json.loads((common / "project-info.json").read_text())
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == 1 else None


SYSCTL = "/usr/sbin/sysctl"  # by full path: a minimal PATH leaves out /usr/sbin


def gather_system():
    """Battery, cpu and memory readings: macOS's own measures on a Mac, /proc
    and /sys on Linux, and {} anywhere else, which hides the system column."""
    linux = sys.platform.startswith("linux")
    if not linux and sys.platform != "darwin":
        return {}
    out = {}
    batt = read_battery_linux() if linux else parse_pmset(run("pmset", "-g", "batt"))
    if batt:
        out["battery"] = batt
    load = (parse_load(read_text("/proc/loadavg"), os.cpu_count()) if linux else
            parse_load(run(SYSCTL, "-n", "vm.loadavg"), run(SYSCTL, "-n", "hw.ncpu")))
    if load:
        load["usage"] = cpu_usage_since_last()
        if (load["usage"] or 0) >= 90 and float(load["load"]) - load["cores"] >= 0.5:
            load["top"] = top_process(run("ps", "-eo", "pcpu,comm", "--sort=-pcpu") if linux else
                                      run("ps", "-Arco", "pcpu,comm"))
        out["cpu"] = load
    mem = (parse_memory_linux(read_text("/proc/meminfo"), read_text("/proc/pressure/memory"),
                              read_text("/proc/vmstat"), os.sysconf("SC_PAGE_SIZE")) if linux else
           parse_memory(run(SYSCTL, "-n", "kern.memorystatus_vm_pressure_level"),
                        run(SYSCTL, "-n", "kern.memorystatus_level"),
                        run("vm_stat"), run(SYSCTL, "-n", "vm.swapusage")))
    if mem:
        trend = mem_trend(mem)
        mem["comp_trend"], mem["swap_trend"] = trend.get("comp"), trend.get("swap")
        if mem["pressure"] >= 2:
            mem["top"] = biggest_app(named_footprints_linux() if linux else named_footprints())
        out["memory"] = mem
    return out


def read_text(path):
    try:
        return Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return None


def parse_pmset(batt):
    """`pmset -g batt` -> {"pct", "ac"}, or None on a Mac without a battery."""
    pct = re.search(r"(\d+)%", batt or "")
    return {"pct": int(pct.group(1)), "ac": "AC Power" in batt} if pct else None


def parse_load(loadavg, ncpu):
    """sysctl's `{ 1m 5m 15m }` and core count -> the 1m load reading, or None."""
    try:
        one = loadavg.strip("{} \n").split()[0]
        float(one)
        return {"load": one, "cores": int(ncpu)}
    except (AttributeError, IndexError, ValueError):
        return None


def parse_memory(level, free_pct, vm_stat, swapusage):
    """Pressure level (1 normal, 2 warn, 4 critical), how full memory is by
    macOS's measure (100 minus memory_pressure's free percentage), MB of RAM
    holding compressed pages (vm_stat's "occupied by compressor"), MB of swap
    in use, and the running totals of MB swapped out and in since boot."""
    try:
        out = {"pressure": int(level)}
    except (TypeError, ValueError):
        return None
    try:
        out["used_pct"] = 100 - int(free_pct)
    except (TypeError, ValueError):
        pass
    page = re.search(r"page size of (\d+) bytes", vm_stat or "")
    if page:
        for key, label in (("comp_mb", "Pages occupied by compressor"),
                           ("swapped_out_mb", "Swapouts"), ("swapped_in_mb", "Swapins")):
            found = re.search(label + r":\s+(\d+)", vm_stat)
            if found:
                out[key] = int(found.group(1)) * int(page.group(1)) / 2**20
    swap = re.search(r"used = ([\d.]+)M", swapusage or "")
    if swap:
        out["swap_mb"] = float(swap.group(1))
    return out


TREND_EVERY = 60       # seconds between the readings an arrow compares
TREND_STALE = 300      # an older reference (the Mac slept) starts over
COMP_STEADY_MB = 100   # comp moving less than this a minute counts as steady
SWAP_MOVING_MB = 10    # a quiet Mac trickles a few pages; less a minute is still


def mem_trend(reading, path=None, now=None):
    """Arrows for comp and swap: how they moved since a reference reading
    about a minute old. The reference and the arrows it gave are kept in one
    machine-wide file and replaced each minute, so arrows hold between.

    comp: "up", "down" or "steady". swap: "up" while pages are being written
    to disk, "down" while they're read back, None while swap sits still."""
    path = path or CACHE_DIR / "mem-trend.json"
    now = now or time.time()
    # comp is optional: Linux without zswap has no compressed memory to report
    keys = [k for k in ("comp_mb", "swapped_out_mb", "swapped_in_mb") if reading.get(k) is not None]
    if "swapped_out_mb" not in keys or "swapped_in_mb" not in keys:
        return {}
    try:
        saved = json.loads(path.read_text())
        ref, trend = saved["ref"], saved["trend"]
    except (OSError, ValueError, KeyError, TypeError):
        ref, trend = None, {}
    age = now - ref["at"] if ref else None
    if age is not None and age < TREND_EVERY:
        return trend
    if age is not None and age <= TREND_STALE and all(k in ref for k in keys):
        per_min = lambda key: (reading[key] - ref[key]) * 60 / age
        comp = per_min("comp_mb") if "comp_mb" in keys else None
        out, back = per_min("swapped_out_mb"), per_min("swapped_in_mb")
        trend = {"comp": None if comp is None else
                 "up" if comp >= COMP_STEADY_MB else "down" if comp <= -COMP_STEADY_MB else "steady",
                 "swap": "up" if out >= SWAP_MOVING_MB else "down" if back >= SWAP_MOVING_MB else None}
    else:
        trend = {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ref": {"at": now, **{k: reading[k] for k in keys}}, "trend": trend}))
    except OSError:
        pass
    return trend


VM_HOST = "com.apple.Virtualization.VirtualMachine"
APP_ALIASES = {"Google Chrome": "Chrome", "Visual Studio Code": "VS Code"}


def app_name(path):
    """Which app a process belongs to, from its executable path: the outermost
    .app bundle, so Chrome's dozens of helpers count as Chrome. Outside a
    bundle, the file name, except a versioned binary (claude's
    versions/2.1.296) takes the name of the tool that holds it. Chrome runs
    its main process from a code-signing copy named `Google Chrome.app.bundle`."""
    bundle = re.search(r"([^/]+)\.app(?:\.bundle)?/", path)
    if bundle:
        return APP_ALIASES.get(bundle.group(1), bundle.group(1))
    p = Path(path)
    if re.fullmatch(r"\d+(\.\d+)+", p.name):
        return p.parent.parent.name
    return p.name


def vm_name(args):
    """A VM runs as Apple's XPC service, so it's named after the process that
    launched it, from that process's command line. Colima drives Lima's
    hostagent with paths under ~/.colima."""
    if not args or not args.strip():
        return "VM"
    if "/.colima/" in args:
        return "colima"
    return Path(args.split()[0]).name


def biggest_app(named):
    """{"name", "mb"} for the app with the most footprint, from (name, bytes)
    pairs: its processes summed, compressed and swapped pages included."""
    totals = {}
    for name, size in named:
        totals[name] = totals.get(name, 0) + size
    if not totals:
        return None
    name = max(totals, key=totals.get)
    return {"name": name, "mb": totals[name] / 2**20}


# Processes that hold a virtual machine's memory: Apple's VM service (Colima,
# Lima, UTM and others) and OrbStack's helper.
VM_PROCESSES = (VM_HOST, "OrbStack Helper")


def memory_of(path, footprint, resident):
    """The bytes a process holds that quitting it would free. Footprint, as
    Activity Monitor shows, except for a VM: footprint counts pages the guest
    zeroed, which macOS stores for almost nothing, and misses OrbStack's VM
    entirely. Resident is closer for both, though it leaves out what macOS
    has compressed."""
    return resident if Path(path).name in VM_PROCESSES else footprint


def named_footprints():
    """(app name, bytes held) for every process this user may read."""
    out = []
    for pid, path, footprint, resident in process_footprints():
        if Path(path).name == VM_HOST:
            name = vm_name(run("ps", "-o", "args=", "-p", str(responsible_pid(pid))))
        else:
            name = app_name(path)
        out.append((name, memory_of(path, footprint, resident)))
    return out


def process_footprints():
    """(pid, path, footprint bytes, resident bytes) from the kernel. The
    footprint is the same as Activity Monitor's Memory column. Root's processes refuse to answer;
    they aren't the user's to quit anyway."""
    import ctypes

    class RusageInfoV0(ctypes.Structure):
        _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [(f, ctypes.c_uint64) for f in (
            "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins",
            "wired_size", "resident_size", "phys_footprint", "proc_start_abstime",
            "proc_exit_abstime")]
    try:
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        n = lib.proc_listallpids(None, 0)
        pids = (ctypes.c_int * (n + 64))()
        n = lib.proc_listallpids(pids, ctypes.sizeof(pids))
    except (OSError, AttributeError):
        return []
    out, info, buf = [], RusageInfoV0(), ctypes.create_string_buffer(4096)
    RUSAGE_INFO_V0 = 0
    for pid in pids[:max(0, n)]:
        if lib.proc_pid_rusage(pid, RUSAGE_INFO_V0, ctypes.byref(info)) != 0:
            continue
        if lib.proc_pidpath(pid, buf, ctypes.sizeof(buf)) <= 0:
            continue
        out.append((pid, buf.value.decode(errors="replace"), info.phys_footprint, info.resident_size))
    return out


def responsible_pid(pid):
    """The process macOS holds responsible for `pid`, e.g. the limactl that
    launched a VM service. Falls back to `pid` itself."""
    import ctypes
    try:
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        found = lib.responsibility_get_pid_responsible_for_pid(pid)
    except (OSError, AttributeError):
        return pid
    return found if found > 0 else pid


def top_process(ps_out, limit=16):
    """First command from a sorted `ps -Arco pcpu,comm`, short enough for the bar."""
    try:
        name = ps_out.splitlines()[1].split(None, 1)[1].strip()
    except (AttributeError, IndexError):
        return None
    if name.startswith(("com.", "org.", "io.")):  # com.apple.Foo.Bar -> Bar
        name = name.rsplit(".", 1)[-1]
    return name if len(name) <= limit else name[:limit - 1] + "…"


def cpu_ticks():
    """Whole-machine (user, system, idle, nice) CPU ticks: /proc/stat on
    Linux, the Mach kernel on a Mac."""
    if sys.platform.startswith("linux"):
        return parse_proc_stat(read_text("/proc/stat"))
    import ctypes
    try:
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        lib.mach_host_self.restype = ctypes.c_uint32
        info, count = (ctypes.c_uint32 * 4)(), ctypes.c_uint32(4)
        HOST_CPU_LOAD_INFO = 3
        if lib.host_statistics(lib.mach_host_self(), HOST_CPU_LOAD_INFO, info, ctypes.byref(count)):
            return None
        return list(info)
    except (OSError, AttributeError):
        return None


# ---- Linux -------------------------------------------------------------------
# The same readings from /proc and /sys, shaped like the Mac's so the
# renderer doesn't know which it got. Each parser takes the file's text, so
# the tests can feed it recorded files.


def parse_proc_stat(text):
    """/proc/stat's first line -> (user, system, idle, nice) ticks. irq,
    softirq and steal count as system time, iowait as idle."""
    try:
        f = [int(x) for x in text.splitlines()[0].split()[1:9]]
    except (AttributeError, IndexError, ValueError):
        return None
    f += [0] * (8 - len(f))
    user, nice, system, idle, iowait, irq, softirq, steal = f
    return [user, system + irq + softirq + steal, idle + iowait, nice]


def parse_meminfo(text):
    """/proc/meminfo -> {field: kB}."""
    out = {}
    for line in (text or "").splitlines():
        name, _, rest = line.partition(":")
        value = rest.split()
        if value and value[0].isdigit():
            out[name] = int(value[0])
    return out


# memory pressure stall: the share of the last 10 seconds that some task
# spent waiting on memory. Past these, the Mac's warn and critical levels.
PSI_WARN, PSI_CRIT = 10, 40
AVAIL_WARN, AVAIL_CRIT = 10, 5  # without PSI: percent of memory still available


def parse_memory_linux(meminfo, psi, vmstat, page_size):
    """The Mac's memory reading from Linux's files: the pressure level (1, 2
    or 4) from PSI, or from what's available on a kernel without PSI; how
    full memory is (what's not available); zswap's compressed pages as comp;
    swap in use; and the running totals of MB swapped out and in."""
    info = parse_meminfo(meminfo)
    total, avail = info.get("MemTotal"), info.get("MemAvailable")
    if not total or avail is None:
        return None
    free_pct = avail * 100 / total
    some = re.search(r"some avg10=([\d.]+)", psi or "")
    if some:
        stall = float(some.group(1))
        level = 4 if stall >= PSI_CRIT else 2 if stall >= PSI_WARN else 1
    else:
        level = 4 if free_pct < AVAIL_CRIT else 2 if free_pct < AVAIL_WARN else 1
    out = {"pressure": level, "used_pct": round(100 - free_pct)}
    if info.get("Zswap"):
        out["comp_mb"] = info["Zswap"] / 1024
    if info.get("SwapTotal"):
        out["swap_mb"] = (info["SwapTotal"] - info.get("SwapFree", 0)) / 1024
    for key, field in (("swapped_out_mb", "pswpout"), ("swapped_in_mb", "pswpin")):
        found = re.search(rf"^{field} (\d+)$", vmstat or "", re.M)
        if found:
            out[key] = int(found.group(1)) * page_size / 2**20
    return out


def read_battery_linux(root="/sys/class/power_supply"):
    """{"pct", "ac"} from the first battery under /sys, or None without one."""
    try:
        supplies = sorted(Path(root).iterdir())
    except OSError:
        return None
    read = lambda d, name: (read_text(d / name) or "").strip()
    for d in supplies:
        if read(d, "type") == "Battery" and read(d, "capacity").isdigit():
            return {"pct": int(read(d, "capacity")), "ac": read(d, "status") != "Discharging"}
    return None


def named_footprints_linux(proc="/proc"):
    """(app name, resident bytes) for every process this user may read. A
    process's name is its executable's file name, so Chrome's helpers count
    as chrome; the kernel's own threads have no memory and drop out."""
    out = []
    for d in Path(proc).iterdir():
        if not d.name.isdigit():
            continue
        status = read_text(d / "status")
        rss = re.search(r"^VmRSS:\s+(\d+) kB", status or "", re.M)
        name = re.search(r"^Name:\s+(.+)$", status or "", re.M)
        if rss and name:
            out.append((name.group(1).strip(), int(rss.group(1)) * 1024))
    return out


def cpu_usage(prev, cur):
    """Percent busy between two tick readings. The counters are 32-bit and
    wrap, so each delta is taken mod 2**32."""
    if not prev or not cur:
        return None
    user, system, idle, nice = ((c - p) % 2**32 for p, c in zip(prev, cur))
    total = user + system + idle + nice
    return round((total - idle) / total * 100) if total else None


def cpu_usage_since_last(path=None, now=None):
    """Busy % since the previous sample, which lives in one machine-wide file.
    A sample under 2s old is too short a window, so it is kept, not replaced;
    one over 2 minutes old would average across idle time, so it is ignored."""
    path = path or CACHE_DIR / "cpu-ticks.json"
    now = now or time.time()
    cur = cpu_ticks()
    try:
        prev = json.loads(path.read_text())
    except (OSError, ValueError):
        prev = None
    if prev and now - prev.get("at", 0) < 2:
        return prev.get("usage")
    fresh = prev and now - prev.get("at", 0) <= 120  # older is a stale average
    usage = cpu_usage(fresh and prev.get("ticks"), cur)
    if cur:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"at": now, "ticks": cur, "usage": usage}))
        except OSError:
            pass
    return usage


def write_sensor(c, now, sdir=None):
    """Persist this session's usage for hooks and agents, which never receive
    it: one file per session at DATA_DIR/<session_id>.json, so a hook reads
    its own session's numbers (see docs/usage-files.md)."""
    rl = c.get("rate_limits") or {}
    sid = c.get("session_id")
    if not SENSOR or not sid or not re.fullmatch(r"[A-Za-z0-9-]+", sid) \
            or (rl.get("five_hour") or {}).get("used_percentage") is None:
        return
    ws = c.get("workspace") or {}
    reading = json.dumps({
        "at": int(now),
        "session_id": c.get("session_id"),
        "cwd": ws.get("current_dir") or c.get("cwd"),
        "five_hour": rl.get("five_hour") or {},
        "seven_day": rl.get("seven_day") or {},
        "context_used": (c.get("context_window") or {}).get("used_percentage"),
    }, separators=(",", ":")) + "\n"

    def atomic(path):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(reading)
        tmp.replace(path)

    sdir = sdir or DATA_DIR
    try:
        sdir.mkdir(parents=True, exist_ok=True)
        atomic(sdir / f"{sid}.json")
        # about once a minute of renders, drop per-session files older than a week
        if int(now) % 60 == 0:
            for f in sdir.glob("*.json"):
                # only this sensor's files, named by session id, whatever else shares the folder
                if SESSION_FILE.fullmatch(f.stem) and now - f.stat().st_mtime > SEVEN_DAY:
                    f.unlink(missing_ok=True)
    except OSError:
        pass


SESSION_FILE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
WEEK_LOG = DATA_DIR / "history.jsonl"


def record_week(seven_day, now, path=None):
    """Append the week's percentage to a small log each time it reaches a new
    high, so the week bar can tell how fast it has moved lately. Kept forever
    for long-term stats; a week is a few KB. Returns the logged readings."""
    path = path or WEEK_LOG
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = []
    history = []
    for line in lines:
        try:
            r = json.loads(line)
            history.append({"at": r["at"], "pct": r["pct"], "resets_at": r.get("resets_at")})
        except (ValueError, KeyError, TypeError):
            continue
    pct, resets_at = (seven_day or {}).get("used_percentage"), (seven_day or {}).get("resets_at")
    if pct is None:
        return history
    # usage only rises within a window; an idle session still shows the
    # number from its last reply, so only a new high is news
    if any(r["resets_at"] == resets_at and r["pct"] >= pct for r in history):
        return history
    entry = {"at": int(now), "pct": pct, "resets_at": resets_at}
    history.append(entry)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return history


def cached(cwd, now, compute, ttl=SLOW_TTL):
    """git and system readings, reused for `ttl` seconds per directory.

    The status line can refresh every second; git status and the system
    readings don't need to run that often.
    """
    path = CACHE_DIR / (hashlib.sha1(cwd.encode()).hexdigest()[:16] + ".json")
    try:
        hit = json.loads(path.read_text())
        if 0 <= now - hit["at"] < ttl:  # a reading from the future means the clock moved
            return hit["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    data = compute()
    if data.get("common") is not None:
        data["common"] = str(data["common"])
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"at": now, "data": data}))
        tmp.replace(path)
        # readings and statusline.sh's per-session renders: a day unused is gone
        for f in CACHE_DIR.iterdir():
            if now - f.stat().st_mtime > 86400:
                f.unlink(missing_ok=True)
    except OSError:
        pass
    return data


def gather(c):
    now = time.time()
    write_sensor(c, now)
    week_history = record_week((c.get("rate_limits") or {}).get("seven_day"), now)
    ws = c.get("workspace") or {}
    cwd = ws.get("current_dir") or c.get("cwd") or os.getcwd()
    slow = cached(cwd, now, lambda: dict(zip(("git", "common"), gather_git(cwd)),
                                         system=gather_system()))
    git, common = slow.get("git"), slow.get("common")
    return {
        "claude": c,
        "git": git,
        "project": gather_project(Path(common)) if common else None,
        "system": slow.get("system") or {},
        "week_history": week_history,
        "now": now,
        "version": version_label(),
    }


# ---- version ---------------------------------------------------------------
INSTALLED = HERE / "installed.json"  # install.sh's record of what it installed


def checkout_head(root):
    """The commit a git checkout is on, read from its files rather than by
    running git on every refresh. None when they can't be read."""
    try:
        gitdir = root / ".git"
        if gitdir.is_file():  # a worktree: .git names its folder
            gitdir = root / gitdir.read_text().split("gitdir:", 1)[1].strip()
        head = (gitdir / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head[:7] or None
        ref = head[5:]
        common = gitdir / (gitdir / "commondir").read_text().strip() if (gitdir / "commondir").is_file() else gitdir
        for d in (gitdir, common):
            if (d / ref).is_file():
                return (d / ref).read_text().strip()[:7] or None
        for line in (common / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line[:7]
    except (OSError, IndexError, UnicodeDecodeError):
        pass
    return None


def version_label(script=None, record=None):
    """`v0.1.0` for a release, or with the commit for anything else:
    `v0.1.0+041e552` run from a checkout (linked, or in place), and from a
    copy installed out of one, `*` after it when it had uncommitted changes.
    None for an install from before versions."""
    root = Path(os.path.realpath(script or __file__)).parents[1]
    if (root / "VERSION").is_file() and (root / "install.sh").is_file():
        version = (read_text(root / "VERSION") or "").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            return None
        head = checkout_head(root)
        return f"v{version}+{head}" if head else f"v{version}"
    try:
        r = json.loads((record or INSTALLED).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(r, dict) or r.get("by") != "claude-statusline":
        return None
    version, commit = r.get("version"), r.get("commit")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return None
    if r.get("release") is True or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return f"v{version}"
    return f"v{version}+{commit[:7]}{'*' if r.get('dirty') is True else ''}"


# ---- entry -----------------------------------------------------------------


def main(argv):
    if argv[:1] == ["--version"]:
        print(version_label() or "unknown: installed before versions; run install.sh again")
        return
    if argv[:1] == ["--scenario"]:
        inp = json.loads(Path(argv[1]).read_text())
        print(render(inp))
        return

    raw = sys.stdin.read()
    c = clean_claude(json.loads(raw) if raw.strip() else {})
    cols = env_int("CLAUDE_STATUSLINE_COLUMNS", 0, 40, 1000) or env_int("COLUMNS", 200, 1, 10000)
    if argv[:1] == ["--json"]:  # each part as data, for a surface that draws it itself
        # its input isn't Claude Code's, so it says nothing about the error the
        # status line logged: leave that log for the person reading it
        print(json.dumps(view(gather(c), cols - 2), ensure_ascii=False))
        return
    print(render(gather(c), cols - 2))
    (HERE / "error.log").unlink(missing_ok=True)  # drawn fine: an old error no longer applies


if __name__ == "__main__":
    # Claude Code reads UTF-8, whatever the locale says
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main(sys.argv[1:])
    except Exception as e:  # a broken status line should say so, not go blank
        log = HERE / "error.log"
        import traceback
        try:
            log.write_text(traceback.format_exc())
        except OSError:
            pass
        print(f"\033[2mstatusline error: {type(e).__name__} (see {log})\033[0m")
