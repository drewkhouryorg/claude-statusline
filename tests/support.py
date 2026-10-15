"""Shared by every test module: puts statusline/ on the path, pins the
settings the scenarios were written for, and holds small helpers."""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"

# The scenarios' weeks were written with days starting at 7am; pinning it
# here lets the shipped default change without rewriting them.
# The rest of the settings go: run from inside Claude Code, the tests would
# otherwise inherit yours, and CLAUDE_STATUSLINE_DEST could point the
# installer tests at your real install.
for name in [n for n in os.environ if n.startswith("CLAUDE_STATUSLINE_") or n in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_PLUGIN_DIRS")]:
    del os.environ[name]
os.environ["CLAUDE_STATUSLINE_DAY_START"] = "7"
sys.path.insert(0, str(ROOT / "statusline"))

import statusline as sl  # noqa: E402

N = 1759400000  # the scenarios' clock
ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")


def scenario(name):
    return json.loads((SCENARIOS / f"{name}.json").read_text())


def visible(text):
    return ANSI.sub("", text)


def plain(segs):
    return "".join(t for t, _, _ in segs)
