# Usage files

Claude Code gives the status line your context and rate-limit numbers on every redraw, but it doesn't give them to hooks or agents. The status line writes them down so your own tools can read them.

Both files live in `~/.claude/usage-sensor/`, or in `usage-sensor/` under `CLAUDE_CONFIG_DIR` if you've set it. Set `CLAUDE_STATUSLINE_DATA` to keep them somewhere else.

## One file per session

`<session_id>.json` holds that session's latest reading, rewritten on each redraw:

```json
{"at": 1759400000, "session_id": "a1b2c3d4-...", "cwd": "/Users/you/code/shop",
 "five_hour": {"used_percentage": 62, "resets_at": 1759405400},
 "seven_day": {"used_percentage": 30, "resets_at": 1759745600},
 "context_used": 54}
```

- `at` is when it was written, in epoch seconds.
- `five_hour` and `seven_day` are the percent used and the reset time Claude Code sent.
- `context_used` is the context window's percent, or `null` early in a session.

Each session has its own file because a hook should read its own session's numbers. Two sessions on different accounts or plans can be at very different levels at the same moment.

A file is written only once Claude Code has sent rate limits, so not for API-key sessions. Files untouched for a week are removed. Set `CLAUDE_STATUSLINE_SENSOR=0` to stop writing them.

### Example: stop before a limit runs out

A `PreToolUse` hook gets the session ID on stdin, so it can find its session's file. This one blocks tool calls once a window passes 95%, and says nothing otherwise:

```python
#!/usr/bin/env python3
import json, os, sys, time

event = json.load(sys.stdin)
folder = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
path = os.path.join(folder, "usage-sensor", f"{event.get('session_id')}.json")
try:
    reading = json.load(open(path))
except (OSError, ValueError):
    sys.exit(0)  # no reading yet: never block on a missing file
now = time.time()
for name in ("five_hour", "seven_day"):
    window = reading.get(name) or {}
    if window.get("used_percentage", 0) >= 95 and window.get("resets_at", 0) > now:
        print(f"{name} limit at {window['used_percentage']}%: pausing until it resets", file=sys.stderr)
        sys.exit(2)  # blocks the tool call and tells Claude why
```

## The week log

`history.jsonl` gets one line each time the weekly percentage reaches a new high:

```json
{"at": 1759400000, "pct": 31, "resets_at": 1759745600}
```

The week chart uses it to tell which day spent what, and to forecast the week from your last 7 days. It's kept forever for your own long-term stats. A week takes a few KB.
