"""Every scenario, rendered at every width people use, against a recorded copy.

Each scenario has two snapshots in tests/snapshots/: <name>.txt, the plain
text, and <name>.ansi, the same with its colours (`cat` it to see them). A
change to how anything looks fails here until the snapshots are re-recorded:

  UPDATE_SNAPSHOTS=1 python3 -m unittest discover -s tests

then read the diff before committing it. Clock times print in UTC so the
snapshots are the same everywhere.
"""
import json
import os
import random
import time
import unittest

from support import ROOT, SCENARIOS, sl, visible

SNAPSHOTS = ROOT / "tests" / "snapshots"
WIDTHS = (60, 80, 100, 120, 160, 200, 240)
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"
_tz = None


def setUpModule():
    global _tz
    _tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()


def tearDownModule():
    if _tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _tz
    time.tzset()


def scenarios():
    return sorted(SCENARIOS.glob("*.json"), key=lambda f: int(f.stem.split("-")[0]))


def sheet(inp, color):
    return "".join(f"── {w} columns ──\n{sl.render(inp, w, color)}\n\n" for w in WIDTHS)


class Snapshots(unittest.TestCase):
    def test_every_scenario_looks_as_recorded(self):
        SNAPSHOTS.mkdir(exist_ok=True)
        for f in scenarios():
            inp = json.loads(f.read_text())
            for ext, color in (("txt", False), ("ansi", True)):
                path = SNAPSHOTS / f"{f.stem}.{ext}"
                got = sheet(inp, color)
                with self.subTest(snapshot=path.name):
                    if UPDATE:
                        path.write_text(got)
                        continue
                    # a new scenario's snapshot is recorded on purpose, then read and committed
                    self.assertTrue(path.exists(), f"{path.name} is missing; record it with UPDATE_SNAPSHOTS=1")
                    self.assertEqual(got, path.read_text(),
                                     f"{path.name} changed; if that's intended, re-record with UPDATE_SNAPSHOTS=1")

    def test_no_snapshot_is_left_without_its_scenario(self):
        names = {f.stem for f in scenarios()}
        for path in SNAPSHOTS.glob("*.*"):
            with self.subTest(snapshot=path.name):
                self.assertIn(path.stem, names)


class Fit(unittest.TestCase):
    def test_no_line_is_ever_wider_than_the_terminal(self):
        for f in scenarios():
            inp = json.loads(f.read_text())
            for cols in range(30, 261):
                lines = visible(sl.render(inp, cols)).split("\n")
                with self.subTest(scenario=f.stem, cols=cols):
                    self.assertGreaterEqual(len(lines), 4)
                    widest = max(sl.width([sl.seg(l)]) for l in lines)
                    self.assertLessEqual(widest, cols)

    def test_columns_line_up_on_every_row(self):
        # the heavy rules sit in the same screen column on all four rows
        for f in scenarios():
            inp = json.loads(f.read_text())
            lines = visible(sl.render(inp, inp["columns"])).split("\n")[:4]
            cells = lambda line: [sl.width([sl.seg(line[:i])]) for i, ch in enumerate(line) if ch == "┃"]
            with self.subTest(scenario=f.stem):
                rules = [cells(l) for l in lines]
                self.assertTrue(all(r == rules[0] for r in rules if len(r) == len(rules[0])), rules)


# Values a repo's project-info.json might hold by mistake, or on purpose.
JUNK = [None, "", 0, -1, 10**15, 10**400, 1.5, "x" * 500, "\x1b[2J\x1b]0;owned\x07", [], {}, ["ok"], {"a": 1},
        True, "🤖" * 60, "‮reversed"]


def clean_text(test, out):
    """Nothing in `out` a terminal would act on: no escapes, controls, or
    bidi and other format characters, apart from the joiner inside emoji."""
    for line in out.split("\n"):
        odd = [hex(ord(c)) for c in line if not c.isprintable() and c != "\u200d"]
        test.assertEqual(odd, [], line)


def strings(value):
    """Every string inside `value`, however deep."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def mutate(value, rng):
    """`value` with about a third of its leaves swapped for junk."""
    if isinstance(value, dict):
        return {k: mutate(v, rng) for k, v in value.items()}
    if isinstance(value, list):
        return [mutate(v, rng) for v in value]
    return rng.choice(JUNK) if rng.random() < 0.35 else value


class UntrustedProjectInfo(unittest.TestCase):
    """project-info.json is written by whatever repo you're in. Whatever it
    holds, the status line must still draw, and must not pass escapes through."""

    def test_junk_in_any_field_never_breaks_the_render(self):
        rng = random.Random(20261012)
        base = json.loads((SCENARIOS / "2-bad-day.json").read_text())
        for i in range(400):
            inp = dict(base, project=dict(mutate(base["project"], rng), schema=1))
            with self.subTest(case=i):
                try:
                    out = sl.render(inp, 160, color=False)
                except Exception as e:  # noqa: BLE001
                    self.fail(f"{type(e).__name__}: {e}\nproject={json.dumps(inp['project'])[:600]}")
                clean_text(self, out)

    def test_junk_never_reaches_the_view_raw(self):
        # the pane draws the view's strings itself, so they must be as clean
        # as the terminal's: a control character there blanks the pane, and a
        # bidi override reverses a branch name
        rng = random.Random(20261014)
        base = json.loads((SCENARIOS / "2-bad-day.json").read_text())
        hostile = "feat/‮gnp.exe\x9b31m\x1b]0;owned\x07"
        system = dict(base["system"], cpu=dict(base["system"]["cpu"], top=hostile),
                      memory=dict(base["system"]["memory"], top={"name": hostile, "mb": 8000}))
        for i in range(200):
            inp = dict(base, project=dict(mutate(base["project"], rng), schema=1),
                       git=dict(base["git"], branch=hostile, repo=hostile), system=system)
            with self.subTest(case=i):
                view = sl.view(inp, 160)
                json.dumps(view)
                for text in strings({k: v for k, v in view.items() if k not in ("ansi", "blocks")}):
                    clean_text(self, text)

    def test_wrong_shapes_for_whole_sections(self):
        base = json.loads((SCENARIOS / "1-healthy.json").read_text())
        for key in ("ci", "deploy", "prs", "branches", "extra"):
            for junk in JUNK:
                inp = dict(base, project=dict(base["project"], **{key: junk}))
                with self.subTest(section=key, value=repr(junk)[:30]):
                    sl.render(inp, 160, color=False)



def odd(value, now, rng):
    """A value Claude Code could plausibly send in place of `value`: the same
    type at the edges of its range, or null. Times land around `now`, so a
    window can have just reset, or reset far away."""
    if isinstance(value, bool):
        return rng.choice([None, not value])
    if isinstance(value, (int, float)):
        return rng.choice([None, 0, -1, 0.4, 99.6, 100, 101, 250, 10**12,
                           now - 7 * 86400, now - 1, now, now + 1, now + 30 * 86400])
    if isinstance(value, str):
        return rng.choice([None, "", "x" * 300, "\x1b[2J\x1b]0;owned\x07", "🤖" * 40, "‮reversed", "a\nb\tc"])
    return None


def vary(value, now, rng, rate=0.3):
    """`value` with about `rate` of its leaves made odd and some keys gone."""
    if isinstance(value, dict):
        return {k: vary(v, now, rng, rate) for k, v in value.items() if rng.random() > rate / 4}
    if isinstance(value, list):
        return [vary(v, now, rng, rate) for v in value]
    return odd(value, now, rng) if rng.random() < rate else value


class OddClaudeInput(unittest.TestCase):
    """What Claude Code sends changes between versions and edge cases: a field
    goes missing, a window has just reset, a percentage passes 100, a session
    name holds escape codes. The line must still draw, fit and stay clean."""

    def test_odd_values_in_any_field_never_break_the_render(self):
        rng = random.Random(20261013)
        for f in scenarios():
            base = json.loads(f.read_text())
            for i in range(40):
                inp = dict(base, claude=vary(base["claude"], base["now"], rng))
                cols = rng.choice((60, 120, 200))
                with self.subTest(scenario=f.stem, case=i, cols=cols):
                    try:
                        out = sl.render(inp, cols, color=False)
                    except Exception as e:  # noqa: BLE001
                        self.fail(f"{type(e).__name__}: {e}\nclaude={json.dumps(inp['claude'])[:800]}")
                    clean_text(self, out)
                    self.assertLessEqual(max(sl.width([sl.seg(l)]) for l in out.split("\n")), cols)

    def test_wrong_types_in_any_field_never_break_the_render(self):
        # a new Claude Code version could change a field's type
        rng = random.Random(20261014)
        base = json.loads((SCENARIOS / "1-healthy.json").read_text())
        for i in range(400):
            inp = dict(base, claude=mutate(base["claude"], rng))
            with self.subTest(case=i):
                try:
                    out = sl.render(inp, 160, color=False)
                except Exception as e:  # noqa: BLE001
                    self.fail(f"{type(e).__name__}: {e}\nclaude={json.dumps(inp['claude'], default=str)[:800]}")
                clean_text(self, out)

    def test_whole_input_of_the_wrong_shape_draws_a_line(self):
        for claude in ([], "x", 42, None, {"model": "Opus"}, {"rate_limits": []}, {"workspace": "x"}):
            with self.subTest(claude=claude):
                sl.render(dict(json.loads((SCENARIOS / "1-healthy.json").read_text()), claude=claude), 160)

    def test_every_section_can_be_missing_or_null(self):
        base = json.loads((SCENARIOS / "1-healthy.json").read_text())
        for key in base["claude"]:
            for gone in ("missing", None):
                claude = dict(base["claude"], **{key: gone})
                if gone == "missing":
                    del claude[key]
                with self.subTest(section=key, value=gone):
                    sl.render(dict(base, claude=claude), 160, color=False)


if __name__ == "__main__":
    unittest.main()
