#!/usr/bin/env python3
"""Write pane/tests/fixtures/bad-day.ts: what `statusline.py --json` prints
for scenarios/2-bad-day.json, for the pane's tests to draw from.

    make pane-fixture

tests/test_view.py fails when the committed file no longer matches what the
view prints, so a change to the view's shape shows up in the pane's tests."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "pane" / "tests" / "fixtures" / "bad-day.ts"
os.environ["CLAUDE_STATUSLINE_DAY_START"] = "7"  # the scenarios' days start at 7am
sys.path.insert(0, str(ROOT / "statusline"))

import statusline as sl  # noqa: E402

HEADER = """\
// What `statusline.py --json` prints for scenarios/2-bad-day.json at 100
// columns, days starting 7am New York time, which leaves the week a day to
// come: a red 5h tank, failing CI, a failed deploy, a dirty repo, memory
// pressure and two alerts. Written by tools/pane_fixture.py (make
// pane-fixture); tests/test_view.py fails when it is out of date.
import type { View } from '../../types'

"""


def fixture():
    # the week's days follow local time: pin one, so every machine writes the
    # same file, and one where the bad day's week still has a day to come
    tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        view = sl.view(json.loads((ROOT / "scenarios" / "2-bad-day.json").read_text()), 100)
    finally:
        if tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = tz
        time.tzset()
    return HEADER + "export const BAD_DAY: View = " + json.dumps(view, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    FIXTURE.write_text(fixture())
    print(f"wrote {FIXTURE.relative_to(ROOT)}")
