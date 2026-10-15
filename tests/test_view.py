"""statusline.py --json: each part as data, for a surface that draws it
itself. It must carry the same numbers and judgements the terminal draws."""
import json
import os
import sys
import time
import unittest

from support import ROOT, plain, scenario, sl, visible

_tz = None


def setUpModule():
    # the week's days end at the day-start hour in local time: the scenarios
    # were written for UTC, as test_scenarios runs them
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


def view(name, **changes):
    inp = scenario(name)
    inp.update(changes)
    return sl.view(inp, 200)


class View(unittest.TestCase):
    def test_every_scenario_is_plain_json(self):
        for name in ("1-healthy", "2-bad-day", "5-first-render", "6-api-key", "13-memory-pressure", "14-offline"):
            with self.subTest(name):
                json.dumps(view(name))

    def test_tanks_carry_the_pace_colour_not_just_the_level(self):
        # bad day: 5h at 94% and on course for 300% is red; the week at 71%
        # but ending near 83% is still green
        tanks = {t["label"]: t for t in view("2-bad-day")["tanks"]}
        self.assertEqual((tanks["ctx"]["pct"], tanks["ctx"]["tone"]), (91, "brick"))
        self.assertEqual((tanks["5h"]["pct"], tanks["5h"]["tone"]), (94, "brick"))
        self.assertEqual((tanks["wk"]["pct"], tanks["wk"]["tone"]), (71, "sage"))
        self.assertAlmostEqual(tanks["5h"]["elapsed"], 1 - 12360 / sl.FIVE_HOUR)

    def test_without_readings_tanks_are_empty_not_zero(self):
        tanks = view("5-first-render")["tanks"]
        self.assertEqual([t["pct"] for t in tanks], [None, None, None])

    def test_the_five_hour_window_says_it_runs_out_before_the_reset(self):
        five = view("2-bad-day")["five"]
        self.assertEqual((five["state"], five["to_full"]), ("out", 360))

    def test_week_days_match_the_numbers_under_the_terminal_chart(self):
        m = sl.build_model(scenario("1-healthy"))
        days = view("1-healthy")["week"]["days"]
        # the chart is DAY_WIDTH cells a day; the words beside it come after
        under_bars = plain(sl.week_column(m)[2])[:sl.DAY_WIDTH * len(days)].split()
        self.assertEqual([str(d["number"]) for d in days if d["number"] is not None], under_bars)

    def test_week_days_say_which_are_done_today_and_to_come(self):
        # the bad day falls on the week's last day; the healthy one has three to come
        self.assertEqual([d["when"] for d in view("2-bad-day")["week"]["days"]], ["past"] * 6 + ["now"])
        days = view("1-healthy")["week"]["days"]
        self.assertEqual([d["when"] for d in days], ["past"] * 3 + ["now"] + ["later"] * 3)
        self.assertEqual({d["tone"] for d in days if d["when"] == "later"}, {"grey"})

    def test_week_lines_are_the_words_beside_the_chart(self):
        lines = [l["text"] for l in view("2-bad-day")["week"]["lines"]]
        self.assertEqual(lines[0], "71% now")
        self.assertTrue(lines[1].startswith("~83% by "))

    def test_repo_marks_and_the_branchs_pr(self):
        repo = view("2-bad-day")["repo"]
        self.assertEqual([(m["kind"], m["count"]) for m in repo["marks"]],
                         [("staged", 7), ("modified", 4), ("ahead", 5), ("behind", 2)])
        self.assertEqual(repo["commit_tone"], "terra")  # dirty for over three hours
        self.assertEqual(repo["pr"]["checks"], {"text": "✗ 2/12", "tone": "brick"})

    def test_ship_keeps_failures_and_says_how_old_stale_data_is(self):
        ship = view("2-bad-day")["ship"]
        self.assertEqual(ship["ci"][0]["runs"], ["ok", "ok", "fail", "fail", "fail"])
        self.assertEqual(ship["deploys"][0]["status"], "fail")
        self.assertEqual(ship["prs"]["stale_age"], 10800)

    def test_system_names_whats_waiting_only_when_it_is(self):
        bad, calm = view("2-bad-day")["system"], view("1-healthy")["system"]
        self.assertEqual((bad["cpu"]["waiting"], bad["cpu"]["top"]), (3, "node"))
        self.assertEqual(bad["memory"]["top"]["name"], "Chrome")
        self.assertIsNone(calm["cpu"]["top"])
        self.assertIsNone(calm["memory"]["top"])

    def test_alerts_are_what_comes_and_goes(self):
        self.assertEqual([a["text"] for a in view("2-bad-day")["alerts"]], ["⚠ migration pending", "cache cold"])
        self.assertEqual(view("1-healthy")["alerts"], [])

    def test_blocks_are_each_part_as_the_terminal_draws_it(self):
        blocks = {b["name"]: [visible(l) for l in b["lines"]] for b in view("2-bad-day")["blocks"]}
        self.assertEqual(list(blocks), ["tanks", "repo", "ship", "session", "week", "system", "alerts"])
        self.assertEqual(blocks["tanks"][3].rstrip(), "ctx  5h  wk")
        self.assertEqual(blocks["repo"][:2], ["acme-shop", "feat/rewards"])
        self.assertTrue(blocks["week"][-1].endswith("5h out ~6m"))  # the week carries the 5h line

    def test_blocks_leave_out_parts_and_rows_with_nothing_to_show(self):
        blocks = {b["name"]: [visible(l) for l in b["lines"]] for b in view("5-first-render")["blocks"]}
        self.assertEqual(list(blocks), ["tanks", "repo", "session", "system"])
        self.assertTrue(all(l.strip() for lines in blocks.values() for l in lines))

    def test_the_panes_fixture_is_what_the_view_prints_now(self):
        # pane/ draws from this snapshot in its own tests, which CI can't run;
        # a field renamed here would otherwise vanish from the pane unseen
        sys.path.insert(0, str(ROOT / "tools"))
        import pane_fixture
        committed = pane_fixture.FIXTURE.read_text()
        self.assertEqual(committed, pane_fixture.fixture(),
                         "pane/tests/fixtures/bad-day.ts is out of date: run make pane-fixture")

    def test_the_terminal_drawing_rides_along(self):
        inp = scenario("1-healthy")
        self.assertEqual(visible(sl.view(inp, 120)["ansi"]), visible(sl.render(inp, 120)))


if __name__ == "__main__":
    unittest.main()
