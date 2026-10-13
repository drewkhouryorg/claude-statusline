"""Unit tests for statusline.py's rendering and readings. Run from the repo
root: python3 -m unittest discover -s tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from support import N, ROOT, plain, scenario as fixture, sl, visible



class Width(unittest.TestCase):
    # An emoji such as 🤖 takes two cells on screen; counting it as one pushes a column's ┃ a cell right.
    def test_wide_characters_count_two_cells(self):
        self.assertEqual(sl.width([sl.seg("lock 🤖 e2e-suite 24m")]), 21)
        self.assertEqual(sl.width([sl.seg("lock ▸ ⚠ ℹ")]), 10)

    def test_pad_fills_to_the_same_screen_width(self):
        a = sl.pad([sl.seg("lock 📁 e2e-suite 1m")], 30)
        b = sl.pad([sl.seg("PRs   3 open, all green")], 30)
        self.assertEqual(sl.width(a), sl.width(b))
        self.assertEqual(sum(len(t) for t, _, _ in a), 29)

    def test_truncate_never_splits_or_overruns_a_wide_character(self):
        out = sl.truncate([sl.seg("ab🤖cd")], 4)
        self.assertLessEqual(sl.width(out), 4)
        self.assertEqual("".join(t for t, _, _ in out), "ab…")


class Tanks(unittest.TestCase):
    def test_partial_fill_shows_number_on_top_and_blocks_below(self):
        top, middle, bottom = (plain(r) for r in sl.tank_rows(54, 2))
        self.assertEqual(top, "▕54▏")
        self.assertEqual(middle, "▕▅▅▏")  # 54% of 24 levels = 13 = 8 + 5
        self.assertEqual(bottom, "▕██▏")

    def test_number_sits_on_a_colored_fill_once_level_reaches_top_row(self):
        top = sl.tank_rows(91, 3)[0]
        self.assertEqual(top[1], ("91", ("bg", sl.BRICK), None))

    def test_number_stays_plain_below_top_row(self):
        top = sl.tank_rows(60, 2)[0]
        self.assertEqual(top[1][1], sl.TERRA)

    def test_full_and_missing(self):
        self.assertEqual(plain(sl.tank_rows(100, 3)[0]), "▕!!▏")
        self.assertEqual(plain(sl.tank_rows(None, 0)[0]), "▕--▏")

    def test_time_marker_sits_on_the_right_wall_at_elapsed_third(self):
        for elapsed, row in ((0.1, 2), (0.5, 1), (0.9, 0)):
            with self.subTest(elapsed=elapsed):
                rows = [plain(r) for r in sl.tank_rows(20, 0, elapsed)]
                self.assertTrue(rows[row].endswith("◂"))
                self.assertEqual(sum(r.endswith("◂") for r in rows), 1)

    def test_no_marker_without_a_window_clock(self):
        rows = [plain(r) for r in sl.tank_rows(20, 0)]
        self.assertFalse(any("◂" in r for r in rows))

    def test_model_gives_rate_tanks_elapsed_but_not_ctx(self):
        m = sl.build_model({"now": N, "claude": {
            "context_window": {"used_percentage": 40},
            "rate_limits": {
                "five_hour": {"used_percentage": 30, "resets_at": N + 2 * 3600},
                "seven_day": {"used_percentage": 10, "resets_at": N + 6 * 86400}}}})
        self.assertAlmostEqual(m["five_tank"][2], 3 / 5)
        self.assertAlmostEqual(m["week_tank"][2], 1 / 7)
        self.assertEqual(len(m["ctx_tank"]), 2)




class SlowReadings(unittest.TestCase):
    def test_git_and_system_rerun_only_after_ttl(self):
        calls = []
        def compute():
            calls.append(1)
            return {"git": {"branch": f"b{len(calls)}"}, "common": None, "system": {}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sl, "CACHE_DIR", Path(d)):
            first = sl.cached("/repo", N, compute)
            again = sl.cached("/repo", N + sl.SLOW_TTL - 1, compute)
            other = sl.cached("/elsewhere", N, compute)
            later = sl.cached("/repo", N + sl.SLOW_TTL, compute)
        self.assertEqual(again, first)                 # reused within the window
        self.assertEqual(other["git"]["branch"], "b2")  # each directory its own
        self.assertEqual(later["git"]["branch"], "b3")  # recomputed once stale

    def test_a_reading_from_the_future_is_not_trusted(self):
        # the clock stepped back an hour: the old reading is not 'fresh' for an hour
        calls = []
        compute = lambda: calls.append(1) or {"git": None, "common": None, "system": {}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sl, "CACHE_DIR", Path(d)):
            sl.cached("/repo", N + 3600, compute)
            sl.cached("/repo", N, compute)
        self.assertEqual(len(calls), 2)

    def test_files_unused_for_a_day_are_removed(self):
        compute = lambda: {"git": None, "common": None, "system": {}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sl, "CACHE_DIR", Path(d)):
            old, recent = Path(d, "render-old.txt"), Path(d, "render-recent.txt")
            for f, age in ((old, 2 * DAY), (recent, 60)):
                f.write_text("x")
                os.utime(f, (N - age, N - age))
            sl.cached("/repo", N, compute)
            self.assertEqual((old.exists(), recent.exists()), (False, True))


def runway(five=None, week=None, history=()):
    """The runway line's text for rate limits given as (used %, secs to reset).
    `history` is week readings as (hours ago, pct) in the current window."""
    rl = {k: {"used_percentage": u, "resets_at": N + r}
          for k, w in (("five_hour", five), ("seven_day", week)) if w for u, r in [w]}
    log = [{"at": N - h * 3600, "pct": pct, "resets_at": N + week[1]} for h, pct in history]
    m = sl.build_model({"now": N, "claude": {"rate_limits": rl}, "week_history": log})
    return plain(sl.runway_line(m))


DAY = 86400
# Saturday 1:45pm, 2026-10-10: 56% used, reset Monday 7pm, 53h15m away
SAT = (56, 53 * 3600 + 15 * 60)


class WeekBar(unittest.TestCase):
    # The one-line forecast, when the chart has no room. Same forecast as the
    # chart: the 7-day average, which before the log reaches into last week is
    # this window's own. SAT: 56% at 4.8 days in, 11.7 a day.
    # Clock times are in UTC, where N is Thursday 10:13am.

    def setUp(self):
        patch = mock.patch.dict(os.environ, {"TZ": "UTC"})
        patch.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(patch.stop)

    def test_under_100_says_where_the_week_ends_by_the_reset(self):
        self.assertEqual(runway(week=SAT), "wk ███████████▓▓▓▓▓░░░░ ~82% by Sat 3pm")

    def test_past_100_says_when_it_runs_out(self):
        # 90% in 4.8 days is 18.8 a day: the last 10 go in under 13 hours
        self.assertEqual(runway(week=(90, SAT[1])), "wk ██████████████████▓▓▶ out Thu 11pm")

    def test_forecast_is_grey_and_running_out_is_purple(self):
        def segs(used):
            return sl.week_bar(sl.build_model({"now": N, "claude": {"rate_limits": {"seven_day": {
                "used_percentage": used, "resets_at": N + SAT[1]}}}}))
        self.assertEqual(next(st for t, st, _ in segs(56) if "▓" in t), sl.GREY)
        self.assertEqual(segs(90)[-1][1], sl.PURPLE)

    def test_bar_and_chart_agree(self):
        m = sl.build_model({"now": N, "claude": {"rate_limits": {"seven_day": {
            "used_percentage": SAT[0], "resets_at": N + SAT[1]}}}})
        bar = plain(sl.week_bar(m))
        chart = plain(sl.week_column(m)[1])
        self.assertIn("~82% by Sat 3pm", bar)
        self.assertIn("~82% by Sat 3pm", chart)

    def test_tank_colour_follows_the_same_forecast(self):
        # 50% this window is 10.4 a day, landing at 73%: green. Last window
        # spent 80 in the part of it still inside the last 7 days, so the
        # 7-day average is 130 / 7 = 18.6 a day, landing at 91%: olive.
        resets = N + SAT[1]
        last = [{"at": N - 7 * DAY - 3600, "pct": 10, "resets_at": resets - 7 * DAY},
                {"at": resets - 7 * DAY - 60, "pct": 90, "resets_at": resets - 7 * DAY}]
        week = {"seven_day": {"used_percentage": 50, "resets_at": resets}}
        alone = sl.build_model({"now": N, "claude": {"rate_limits": week}})
        with_last = sl.build_model({"now": N, "claude": {"rate_limits": week}, "week_history": last})
        self.assertEqual(alone["week_tank"][1], 0)
        self.assertEqual(with_last["week_tank"][1], 1)

    def test_first_day_shows_usage_without_a_forecast(self):
        self.assertEqual(runway(week=(10, sl.SEVEN_DAY - 12 * 3600)),
                         "wk ██░░░░░░░░░░░░░░░░░░")

    def test_week_full_shows_reset(self):
        self.assertEqual(runway(week=(100, 30 * 3600)), "wk full ↻1d6h")

    def test_five_hour_and_week_both_show(self):
        self.assertEqual(runway(five=(30, 3 * 3600), week=SAT),
                         "5h ↻3h00m · wk ███████████▓▓▓▓▓░░░░ ~82% by Sat 3pm")


# A week opening Monday 7pm UTC, as this user's does in their own zone. N is
# the Thursday after, 10:13am: two and a half days in.
RESET = 1759777200  # 2025-10-06 19:00 UTC
OPENED = RESET - 7 * DAY
TUE7, WED7, THU7 = OPENED + 12 * 3600, OPENED + 36 * 3600, OPENED + 60 * 3600


def week_model(history, used, five=None):
    """The model for a week reading of `used` at N, with `history` as (at, pct)
    and the 5h window as (used %, secs to reset)."""
    log = [{"at": at, "pct": pct, "resets_at": RESET} for at, pct in history]
    rl = {"seven_day": {"used_percentage": used, "resets_at": RESET}}
    if five:
        rl["five_hour"] = {"used_percentage": five[0], "resets_at": N + five[1]}
    return sl.build_model({"now": N, "claude": {"rate_limits": rl}, "week_history": log})


def week_chart(history, used, five=None):
    """week_column's rows: two bar rows, numbers, day names, each followed by
    the words beside them."""
    return sl.week_column(week_model(history, used, five))


def chart(row):
    """A chart row's day cells, without the words beside it."""
    return row[:row.index(sl.seg("  "))] if sl.seg("  ") in row else row


def styles(row):
    """One colour per day."""
    return [style for _, style, _ in chart(row)]


def text(row):
    """The words beside a chart row."""
    return plain(row[len(chart(row)):]).strip()


class UTC(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"TZ": "UTC"})
        patch.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(patch.stop)


class WeekDays(UTC):
    def test_days_run_7am_to_7am_with_half_days_at_a_7pm_reset(self):
        cuts = sl.day_cuts(OPENED, RESET)
        self.assertEqual(len(cuts), 8)
        self.assertEqual(cuts[0], (OPENED, TUE7))           # Monday evening, 12h
        self.assertEqual(cuts[-1], (RESET - 12 * 3600, RESET))  # Monday daytime, 12h
        self.assertTrue(all(b - a == DAY for a, b in cuts[1:-1]))

    def test_a_few_minutes_at_either_end_join_the_next_day(self):
        # a window from 6:45am to 6:45am a week on: the first and last
        # quarter hours are not days of their own
        opened = TUE7 - 15 * 60
        cuts = sl.day_cuts(opened, opened + 7 * DAY)
        self.assertEqual(len(cuts), 7)
        self.assertEqual(cuts[0], (opened, TUE7 + DAY))
        self.assertEqual(cuts[-1][1], opened + 7 * DAY)

    def test_days_start_at_the_same_hour_across_a_clock_change(self):
        # New York leaves daylight saving on 1 November 2026
        with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
            time.tzset()
            start = time.mktime((2026, 10, 29, 19, 0, 0, 0, 0, -1))
            end = time.mktime((2026, 11, 5, 19, 0, 0, 0, 0, -1))
            hours = [time.localtime(a).tm_hour for a, _ in sl.day_cuts(start, end, hour=4)[1:]]
        self.assertEqual(hours, [4] * len(hours))

    def test_each_day_is_named_half_days_too(self):
        self.assertEqual(plain(week_chart([], 30)[3]), " Mo Tu We Th Fr Sa Su Mo")

    def test_a_day_is_named_for_the_date_it_starts_on(self):
        # a window opening at midnight going into Friday starts in Thursday's
        # 7am-to-7am day
        log = {"used_percentage": 10, "resets_at": RESET - 91 * 3600}
        m = sl.build_model({"now": N, "claude": {"rate_limits": {"seven_day": log}}})
        self.assertTrue(plain(chart(sl.week_column(m)[3])).startswith(" Th Fr Sa"))


class WeekChart(UTC):
    # logged from an hour after the week opened: Mon eve 4, Tue 9, Wed 20, Thu 3 so far
    WEEK = [(OPENED + 3600, 0), (TUE7, 4), (WED7, 13), (THU7, 33)]

    def test_each_bar_is_what_that_day_alone_spent(self):
        numbers = plain(chart(week_chart(self.WEEK, 36)[2]))
        self.assertEqual(numbers[:12], "  4  9 20  3")

    def test_each_past_day_takes_its_colour_from_its_spend_against_its_share(self):
        bars = styles(week_chart(self.WEEK, 36)[1])
        self.assertEqual(bars[:4], [sl.SAGE,    # 4 of a half day's 7
                                    sl.SAGE,    # 9 of 14
                                    sl.TERRA,   # 20 of 14: 1.4 times
                                    sl.SAGE])   # today, 3 so far

    def test_days_to_come_are_grey_and_split_all_thats_left(self):
        # 64 left, none of it kept for the rest of today: 84 hours of days to
        # come is 18.3 a whole day and 9.1 for Monday's half, and the odd one
        # goes to the first of the biggest remainders
        rows = week_chart(self.WEEK, 36)
        self.assertEqual(set(styles(rows[1])[4:]), {sl.GREY})
        self.assertEqual(plain(chart(rows[2]))[12:], " 19 18 18  9")

    def test_the_numbers_add_up_to_the_whole_week(self):
        for used in (36, 37, 41, 59):
            with self.subTest(used=used):
                numbers = plain(chart(week_chart(self.WEEK, used)[2])).split()
                self.assertEqual(sum(map(int, numbers)), 100)

    def test_the_busiest_day_reaches_the_top(self):
        rows = week_chart([(OPENED + 3600, 0), (TUE7, 4), (WED7, 39)], 40)
        self.assertEqual(plain(chart(rows[0]))[3:6], " ██")  # Tue 35: the top
        self.assertEqual(plain(chart(rows[0]))[:3], "   ")     # Mon eve 4: low

    def test_a_quiet_week_keeps_its_bars_low(self):
        # no day near its share: the scale stops at 1.5 shares, not at the
        # biggest day, so nothing reaches the top row
        rows = week_chart([(OPENED + 3600, 0), (TUE7, 2), (WED7, 7)], 10)
        self.assertEqual(plain(chart(rows[0]))[:12].strip(), "")

    def test_before_the_logs_first_reading_the_floor_is_dotted(self):
        rows = week_chart([(WED7, 13)], 36)
        self.assertEqual(plain(chart(rows[1]))[:6], " ·· ··")  # Monday evening and Tuesday
        self.assertEqual(plain(chart(rows[2]))[:6], "      ")  # and no number
        self.assertNotIn("·", plain(chart(rows[1]))[6:])

    def test_a_fresh_install_does_not_pin_the_week_so_far_on_today(self):
        # the first reading ever is 33% this morning: unknown days before it
        # are dotted, and today counts only what it spent since that reading
        rows = week_chart([(THU7 + 3600, 33)], 36)
        self.assertEqual(plain(chart(rows[1]))[:9], " ·· ·· ··")
        self.assertEqual(plain(chart(rows[2]))[9:12], "  3")

    def test_the_live_reading_counts_before_the_log_has_it(self):
        rows = week_chart(self.WEEK, 40)  # the log still says 33
        self.assertEqual(text(rows[0]), "40% now")
        self.assertEqual(plain(chart(rows[2]))[9:12], "  7")  # today

    def test_forecast_at_the_average_says_where_the_week_ends(self):
        # 36% over 2.63 days is 13.7 a day; 4.36 days more ends near 96%. The
        # 64 left over the 3.5 days after today, as the grey bars have it, is 18
        rows = week_chart(self.WEEK, 36)
        self.assertEqual([text(r) for r in rows[:3]],
                         ["36% now", "~96% by Mon 7pm", "18%/day to use it all"])

    def test_with_one_day_after_today_it_names_it_instead_of_a_rate(self):
        # Monday's 12 hours is all that comes after Sunday: 15% "per day" would
        # read as 30, so it says where the 15 goes
        sun = THU7 + 3 * DAY + 16 * 3600  # Sunday 11pm
        m = sl.build_model({"now": sun, "claude": {"rate_limits": {"seven_day": {
            "used_percentage": 85, "resets_at": RESET}}}})
        rows = sl.week_column(m)
        self.assertEqual(text(rows[2]), "15% left for Mon")
        self.assertEqual(plain(chart(rows[2]))[-3:], " 15")

    def test_on_the_last_day_it_says_what_today_has_left(self):
        rows = sl.week_column(sl.build_model({"now": N, "claude": {"rate_limits": {"seven_day": {
            "used_percentage": 70, "resets_at": N + 10 * 3600}}}}))
        self.assertEqual(text(rows[2]), "30% left today")

    def test_a_week_whose_reset_has_passed_draws_no_chart(self):
        # Claude Code can send the old window for a moment after it resets
        m = sl.build_model({"now": N, "claude": {"rate_limits": {"seven_day": {
            "used_percentage": 70, "resets_at": N - 3600}}}})
        self.assertEqual(sl.week_column(m), [])

    def test_forecast_past_100_turns_purple_and_says_when_it_runs_out(self):
        # 90% in 2.63 days is 34 a day: the last 10 go by about 5pm today
        rows = week_chart([(OPENED + 3600, 0), (THU7, 85)], 90)
        self.assertEqual(text(rows[1]), "out Thu 5pm")
        self.assertEqual(rows[1][-1][1], sl.PURPLE)

    def test_at_the_cap_it_says_until_when_and_no_day_has_any_left(self):
        rows = week_chart(self.WEEK, 100)
        self.assertEqual([text(r) for r in rows[:3]], ["100% now", "out until Mon 7pm", ""])
        self.assertEqual(plain(chart(rows[2]))[12:], "  0  0  0  0")

    def test_before_a_forecast_the_words_close_up(self):
        # first day of a window: no forecast, so the per-day line moves up.
        # 97 over the six days after today
        rows = sl.week_column(sl.build_model({"now": N, "claude": {"rate_limits": {"seven_day": {
            "used_percentage": 3, "resets_at": N + 7 * DAY - 3 * 3600}}}}))
        self.assertEqual([text(r) for r in rows[:3]], ["3% now", "16%/day to use it all", ""])

    def test_the_5h_window_sits_under_the_words(self):
        rows = week_chart(self.WEEK, 36, five=(30, 3 * 3600))
        self.assertEqual(text(rows[3]), "5h ↻3h00m")


class WeekBarColours(UTC):
    def test_each_block_takes_the_colour_of_the_day_that_spent_it(self):
        # Mon eve 4 and Tue 9 green, Wed 20 orange: 36% is seven 5% blocks
        m = week_model(WeekChart.WEEK, 36)
        blocks = [st for t, st, _ in sl.week_bar(m) if t == "█"]
        self.assertEqual(blocks, [sl.SAGE] * 3 + [sl.TERRA] * 4)


class WeekAverage(unittest.TestCase):
    def test_reaches_into_the_previous_window_once_the_log_does(self):
        # previous window: 50% eight days ago, 80% when it closed. 30 of those
        # fall in the last 7 days, plus this window's 36
        log = [{"at": N - 8 * DAY, "pct": 50, "resets_at": OPENED},
               {"at": OPENED - 3600, "pct": 80, "resets_at": OPENED}]
        self.assertAlmostEqual(sl.week_avg(log, 36, RESET, N), 66 / 7)

    def test_without_that_it_is_this_windows_own_average(self):
        days = (N - OPENED) / DAY
        self.assertAlmostEqual(sl.week_avg([], 36, RESET, N), 36 / days)

    def test_nothing_in_the_windows_first_day(self):
        self.assertIsNone(sl.week_avg([], 3, N + 6 * DAY + 3600, N))


class WeekColumnLayout(unittest.TestCase):
    def test_with_room_the_week_gets_a_column_and_takes_5h_with_it(self):
        lines = visible(sl.render(fixture("1-healthy"), cols=200)).split("\n")
        self.assertIn("30% now", lines[0])
        self.assertNotIn("wk █", "".join(lines))
        session, week = lines[3].split("┃")[2:4]
        self.assertNotIn("5h", session)
        self.assertIn("5h ↻1h30m", week)

    def test_without_room_the_week_is_a_bar_on_the_runway_line(self):
        lines = visible(sl.render(fixture("1-healthy"), cols=150)).split("\n")
        self.assertNotIn("% now", "".join(lines))
        self.assertIn("5h ↻1h30m · wk █", lines[3])


def with_alerts(name, **changes):
    inp = fixture(name)
    for key, value in changes.items():
        inp[key] = value
    return inp


NOTICE = {"icon": "info", "state": "info", "updated_at": N - 30,
        "text": "lock 🤖 e2e-suite ▸ checkout-flow-tests 0m"}


class AlertsLine(unittest.TestCase):
    def test_nothing_to_say_means_no_fifth_line(self):
        self.assertEqual(len(sl.render(fixture("1-healthy"), cols=200).split("\n")), 4)

    def test_a_project_notice_goes_under_the_columns_not_in_them(self):
        inp = fixture("1-healthy")
        inp["project"]["extra"] = [NOTICE]
        lines = visible(sl.render(inp, cols=200)).split("\n")
        self.assertEqual(lines[4], "ℹ lock 🤖 e2e-suite ▸ checkout-flow-tests 0m")
        self.assertNotIn("lock", "".join(lines[:4]))
        # and it no longer sets the ship column's width
        plain_width = visible(sl.render(fixture("1-healthy"), cols=200)).split("\n")[0].index("┃", 30)
        self.assertEqual(lines[0].index("┃", 30), plain_width)

    def test_machine_alerts_go_on_it_only_without_a_machine_column(self):
        inp = fixture("2-bad-day")
        narrow = visible(sl.render(inp, cols=150)).split("\n")
        self.assertIn("batt 22%", narrow[4])
        self.assertIn("mem pressure warn", narrow[4])
        roomy = visible(sl.render(inp, cols=240)).split("\n")
        self.assertNotIn("batt", roomy[4])

    OFFLINE = "error connecting to api.github.com"

    def with_sections(self, **sections):
        """The healthy scenario's alerts line with these project sections."""
        inp = fixture("1-healthy")
        inp["project"] = {"schema": 1, **sections}
        lines = visible(sl.render(inp, cols=200)).split("\n")
        return lines[4] if len(lines) > 4 else ""

    def test_a_refresh_that_keeps_failing_says_why_the_ship_column_is_old(self):
        failing = {"error": self.OFFLINE, "tried_at": N - 60, "updated_at": N - 3600}
        line = self.with_sections(ci={"main": {"runs": ["ok"], **failing}}, prs={"open": 2, **failing})
        self.assertEqual(line, f"⚠ can't refresh CI, PRs: {self.OFFLINE}")

    def test_one_failed_try_while_the_data_is_still_fresh_says_nothing(self):
        recent = {"error": self.OFFLINE, "tried_at": N - 60, "updated_at": N - 120}
        self.assertEqual(self.with_sections(prs={"open": 2, **recent}), "")

    def test_a_section_never_fetched_says_why(self):
        self.assertEqual(self.with_sections(prs={"error": "gh: command not found", "tried_at": N}),
                         "⚠ can't refresh PRs: gh: command not found")

    def test_only_this_branchs_checks_count(self):
        failed = {"error": self.OFFLINE, "tried_at": N}
        self.assertEqual(self.with_sections(branches={"some/other": failed}), "")
        branch = fixture("1-healthy")["git"]["branch"]
        self.assertEqual(self.with_sections(branches={branch: failed}), f"⚠ can't refresh checks: {self.OFFLINE}")

    def test_a_long_line_is_cut_to_the_terminal_counting_emoji_as_two(self):
        inp = fixture("1-healthy")
        inp["project"]["extra"] = [NOTICE, dict(NOTICE, text="🤖 " + "x" * 90)]  # each capped at 80
        line = sl.render(inp, cols=120, color=False).split("\n")[4]
        self.assertEqual(sl.width([sl.seg(line)]), 120)
        self.assertTrue(line.endswith("…"))


class WeekLog(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "history.jsonl"

    def record(self, pct, at, resets_at=N + DAY):
        return sl.record_week({"used_percentage": pct, "resets_at": resets_at}, at, self.path)

    def logged(self):
        return [json.loads(l)["pct"] for l in self.path.read_text().splitlines()]

    def test_logs_only_when_the_percentage_changes(self):
        for at, pct in ((N, 40), (N + 60, 40), (N + 120, 41), (N + 180, 41)):
            self.record(pct, at)
        self.assertEqual(self.logged(), [40, 41])

    def test_an_idle_session_reporting_an_older_lower_number_logs_nothing(self):
        for at, pct in ((N, 60), (N + 10, 41), (N + 20, 60), (N + 30, 41), (N + 40, 61)):
            self.record(pct, at)
        self.assertEqual(self.logged(), [60, 61])

    def test_a_new_window_logs_even_at_the_same_percentage(self):
        self.record(0, N)
        self.record(0, N + 60, resets_at=N + 8 * DAY)
        self.assertEqual(len(self.logged()), 2)

    def test_old_weeks_are_kept_for_long_term_stats(self):
        self.record(90, N - 30 * DAY, resets_at=N - 25 * DAY)
        self.record(20, N)
        self.assertEqual(self.logged(), [90, 20])

    def test_unreadable_lines_are_skipped(self):
        self.path.write_text("not json\n{}\n")
        self.record(5, N)
        self.assertEqual([r["pct"] for r in self.record(6, N + 60)], [5, 6])

    def test_no_week_reading_logs_nothing(self):
        self.assertEqual(sl.record_week(None, N, self.path), [])
        self.assertFalse(self.path.exists())


def system_line(**system):
    """The alerts line's text for the given system readings, when there is
    no system column to hold them."""
    return plain(sl.alerts_line(sl.build_model({"now": N, "claude": {}, "system": system})))


def cpu(usage, load="6.0", cores=12, top=None):
    return {"usage": usage, "load": load, "cores": cores, "top": top}


class Cpu(unittest.TestCase):
    def test_quiet_under_half_busy_or_without_a_sample(self):
        self.assertEqual(system_line(cpu=cpu(49)), "")
        self.assertEqual(system_line(cpu=cpu(None, "15.2")), "")

    def test_bar_fills_eight_cells_by_usage(self):
        self.assertEqual(system_line(cpu=cpu(50)), "cpu ▮▮▮▮▯▯▯▯ 50%")
        self.assertEqual(system_line(cpu=cpu(100)), "cpu ▮▮▮▮▮▮▮▮ 100%")

    def test_orange_from_seventy_percent_red_only_when_saturated_with_a_queue(self):
        style = lambda c: sl.cpu_segs(c)[0][1]
        self.assertEqual(style(cpu(69)), sl.SAGE)
        self.assertEqual(style(cpu(70)), sl.TERRA)
        self.assertEqual(style(cpu(100, load="12.4")), sl.TERRA)  # full, nothing waiting
        self.assertEqual(style(cpu(100, load="12.5")), sl.BRICK)

    def test_saturated_with_a_queue_says_how_many_wait_and_who_is_busiest(self):
        self.assertEqual(system_line(cpu=cpu(100, "15.2", top="node")),
                         "cpu ▮▮▮▮▮▮▮▮ 100% · 3 cpu wait · node")

    def test_high_load_on_a_mostly_idle_machine_is_not_a_queue(self):
        # seen live: a VM held load at 12.8 on 12 cores while top said 85% idle
        self.assertEqual(system_line(cpu=cpu(15, "12.84", top="claude")), "")
        self.assertEqual(system_line(cpu=cpu(80, "15.2", top="node")), "cpu ▮▮▮▮▮▮▯▯ 80%")

    def test_parse_load_reads_sysctl_output(self):
        self.assertEqual(sl.parse_load("{ 13.69 8.47 7.50 }\n", "12\n"), {"load": "13.69", "cores": 12})
        self.assertIsNone(sl.parse_load(None, "12"))
        self.assertIsNone(sl.parse_load("{ }", "12"))


class CpuUsage(unittest.TestCase):
    def test_busy_share_of_ticks_between_samples(self):
        # 30 user + 10 system + 60 idle ticks elapsed: 40% busy
        self.assertEqual(sl.cpu_usage([100, 100, 100, 0], [130, 110, 160, 0]), 40)

    def test_counter_wrapping_past_32_bits_still_gives_the_right_delta(self):
        near_top = 2**32 - 20
        self.assertEqual(sl.cpu_usage([0, 0, near_top, 0], [50, 0, 30, 0]), 50)

    def test_no_previous_sample_means_no_reading(self):
        self.assertIsNone(sl.cpu_usage(None, [1, 2, 3, 4]))

    def test_sample_file_keeps_short_windows_and_drops_stale_ones(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sl, "CACHE_DIR", Path(tmp)), \
                mock.patch.object(sl, "cpu_ticks") as ticks:
            path = Path(tmp) / "cpu-ticks.json"
            ticks.return_value = [0, 0, 100, 0]
            self.assertIsNone(sl.cpu_usage_since_last(path, now=1000))     # first sample
            ticks.return_value = [25, 0, 175, 0]
            self.assertEqual(sl.cpu_usage_since_last(path, now=1010), 25)  # 10s window
            ticks.return_value = [99, 0, 175, 0]
            self.assertEqual(sl.cpu_usage_since_last(path, now=1011), 25)  # too soon: reuse
            self.assertIsNone(sl.cpu_usage_since_last(path, now=1500))     # stale: restart

    def test_reads_real_kernel_counters(self):
        first = sl.cpu_ticks()
        self.assertEqual(len(first), 4)
        self.assertTrue(all(isinstance(t, int) for t in first))


# This machine on the morning of 2026-10-09: pressure at warn, 37% free,
# 6.5G of RAM holding compressed pages, and 31 Chrome tabs as the culprit.
WARN_MEM = {"pressure": 2, "used_pct": 63, "comp_mb": 6656, "top": {"name": "Chrome", "mb": 8294}}
# The same machine after closing the tabs.
NORMAL_MEM = {"pressure": 1, "used_pct": 49, "comp_mb": 4506}


class Memory(unittest.TestCase):
    def test_quiet_at_normal_pressure(self):
        self.assertEqual(system_line(memory=NORMAL_MEM), "")

    def test_warn_names_the_level_compressor_and_biggest_app(self):
        self.assertEqual(system_line(memory=WARN_MEM), "mem pressure warn · comp 6.5G · Chrome 8.1G")

    def test_critical_says_crit_in_red(self):
        line = sl.mem_segs({**WARN_MEM, "pressure": 4})
        self.assertEqual(plain(line), "mem pressure crit · comp 6.5G · Chrome 8.1G")
        self.assertEqual(line[0][1], sl.BRICK)

    def test_small_sizes_show_in_megabytes(self):
        self.assertEqual(system_line(memory={"pressure": 2, "comp_mb": 512.4}), "mem pressure warn · comp 512M")

    def test_parse_memory_reads_sysctl_and_vm_stat_output(self):
        vm_stat = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                   "Pages free:                                     4188.\n"
                   "Pages occupied by compressor:                 427199.\n"
                   "Swapins:                                   354384820.\n"
                   "Swapouts:                                  368972006.\n")
        swap = "total = 3072.00M  used = 1800.00M  free = 1272.00M  (encrypted)\n"
        mb = lambda pages: pages * 16384 / 2**20
        self.assertEqual(sl.parse_memory("2\n", "37\n", vm_stat, swap), {
            "pressure": 2, "used_pct": 63, "comp_mb": mb(427199), "swap_mb": 1800.0,
            "swapped_out_mb": mb(368972006), "swapped_in_mb": mb(354384820)})
        self.assertEqual(sl.parse_memory("1", None, None, None), {"pressure": 1})
        self.assertIsNone(sl.parse_memory(None, "37", vm_stat, swap))

    def test_fallback_carries_the_arrows_too(self):
        mem = {**WARN_MEM, "comp_trend": "up", "swap_mb": 2848, "swap_trend": "up"}
        self.assertEqual(system_line(memory=mem),
                         "mem pressure warn · comp 6.5G ↑ · swap 2.8G ↑ · Chrome 8.1G")


def flow(**mem):
    return plain(sl.flow_segs({"pressure": 1, "comp_mb": 4915, "swap_mb": 2848, **mem}))


class Flow(unittest.TestCase):
    def test_comp_arrow_says_which_way_it_moved(self):
        self.assertEqual(flow(comp_trend="steady"), "comp 4.8G →")
        self.assertEqual(flow(comp_trend="up"), "comp 4.8G ↑")
        self.assertEqual(flow(comp_trend="down"), "comp 4.8G ↓")
        self.assertEqual(flow(), "comp 4.8G")  # no minute-old reading yet

    def test_swap_shows_only_while_it_moves(self):
        self.assertEqual(flow(comp_trend="steady", swap_trend=None), "comp 4.8G →")
        self.assertEqual(flow(comp_trend="up", swap_trend="up"), "comp 4.8G ↑ · swap 2.8G ↑")
        self.assertEqual(flow(comp_trend="down", swap_trend="down"), "comp 4.8G ↓ · swap 2.8G ↓")

    def test_arrow_colors(self):
        color = lambda **m: {t: s for t, s, _ in sl.flow_segs({"comp_mb": 4915, "swap_mb": 2848, **m})}
        self.assertEqual(color(pressure=2, comp_trend="up")["↑"], sl.TERRA)
        self.assertEqual(color(pressure=1, comp_trend="down")["↓"], sl.SAGE)
        self.assertEqual(color(pressure=1, comp_trend="steady")["→"], sl.DIM)
        self.assertEqual(color(pressure=4, swap_trend="up")["swap 2.8G ↑"], sl.BRICK)
        self.assertEqual(color(pressure=2, swap_trend="up")["swap 2.8G ↑"], sl.TERRA)
        self.assertEqual(color(pressure=1, swap_trend="down")["swap 2.8G ↓"], sl.OLIVE)


def reading(comp, out, back):
    return {"comp_mb": comp, "swapped_out_mb": out, "swapped_in_mb": back}


class MemTrend(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(sl, "CACHE_DIR", Path(tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.path = Path(tmp.name) / "mem-trend.json"
        sl.mem_trend(reading(4000, 1000, 1000), self.path, now=1000)  # the reference

    def test_first_reading_has_no_arrows(self):
        self.path.unlink()
        self.assertEqual(sl.mem_trend(reading(4000, 1000, 1000), self.path, now=1000), {})

    def test_compressing_and_swapping_out_over_a_minute_point_up(self):
        self.assertEqual(sl.mem_trend(reading(4500, 1200, 1000), self.path, now=1060),
                         {"comp": "up", "swap": "up"})

    def test_freeing_and_reading_back_point_down(self):
        self.assertEqual(sl.mem_trend(reading(3500, 1000, 1200), self.path, now=1060),
                         {"comp": "down", "swap": "down"})

    def test_small_drift_is_steady_and_swap_still(self):
        self.assertEqual(sl.mem_trend(reading(4050, 1005, 1005), self.path, now=1060),
                         {"comp": "steady", "swap": None})

    def test_arrows_hold_until_the_next_minute(self):
        sl.mem_trend(reading(4500, 1200, 1000), self.path, now=1060)  # up, new reference
        self.assertEqual(sl.mem_trend(reading(3000, 1200, 1000), self.path, now=1090),
                         {"comp": "up", "swap": "up"})  # 30s on: still the last minute's answer
        self.assertEqual(sl.mem_trend(reading(3000, 1200, 1000), self.path, now=1120)["comp"], "down")

    def test_rate_is_per_minute_so_a_late_sample_is_not_exaggerated(self):
        # 150 MB over two and a half minutes is 60 a minute: steady
        self.assertEqual(sl.mem_trend(reading(4150, 1000, 1000), self.path, now=1150)["comp"], "steady")

    def test_a_reference_from_before_sleep_starts_over(self):
        self.assertEqual(sl.mem_trend(reading(9000, 5000, 1000), self.path, now=1000 + sl.TREND_STALE + 1), {})

    def test_missing_counters_give_no_arrows(self):
        self.assertEqual(sl.mem_trend({"comp_mb": 4000}, self.path, now=1060), {})


class BiggestApp(unittest.TestCase):
    CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    RENDERER = ("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/"
                "Versions/154.0.8037.98/Helpers/Google Chrome Helper (Renderer).app/Contents/MacOS/"
                "Google Chrome Helper (Renderer)")

    def test_helpers_count_as_the_outermost_app(self):
        self.assertEqual(sl.app_name(self.RENDERER), "Chrome")
        self.assertEqual(sl.app_name("/Applications/Visual Studio Code.app/Contents/Frameworks/"
                                     "Code Helper (Renderer).app/Contents/MacOS/Code Helper (Renderer)"), "VS Code")
        self.assertEqual(sl.app_name("/Applications/Discord.app/Contents/MacOS/Discord"), "Discord")

    def test_chromes_code_signing_copy_is_still_chrome(self):
        # seen live: Chrome's main process ran from here, splitting its total in two
        clone = ("/private/var/folders/xx/0000000000000000000000000000gn/X/com.google.Chrome.code_sign_clone/"
                 "code_sign_clone.tAggMU/Google Chrome.app.bundle/Contents/MacOS/Google Chrome")
        self.assertEqual(sl.app_name(clone), "Chrome")

    def test_command_line_tools_go_by_file_name(self):
        self.assertEqual(sl.app_name("/opt/homebrew/bin/node"), "node")
        self.assertEqual(sl.app_name("/Users/dev/.local/share/claude/versions/2.1.296"), "claude")

    def test_a_vm_is_named_after_what_launched_it(self):
        colima = ("/opt/homebrew/bin/limactl hostagent --pidfile /Users/dev/.colima/_lima/colima-vz/ha.pid "
                  "--socket /Users/dev/.colima/_lima/colima-vz/ha.sock")
        self.assertEqual(sl.vm_name(colima), "colima")
        self.assertEqual(sl.vm_name("/opt/homebrew/bin/limactl hostagent --pidfile /Users/dev/.lima/default/ha.pid"),
                         "limactl")
        self.assertEqual(sl.vm_name(None), "VM")

    def test_many_small_processes_outweigh_one_big_one(self):
        # 2026-10-09: no single Chrome process passed 523M, but 31 of them made
        # 8.1G, while the biggest single process by resident size was claude
        MB = 2**20
        named = [("Chrome", 262 * MB)] * 31 + [("claude", 380 * MB), ("colima", 7192 * MB)]
        top = sl.biggest_app(named)
        self.assertEqual((top["name"], round(top["mb"])), ("Chrome", 8122))
        self.assertIsNone(sl.biggest_app([]))

    ORBSTACK_VM = "/Applications/OrbStack.app/Contents/Frameworks/OrbStack Helper.app/Contents/MacOS/OrbStack Helper"
    COLIMA_VM = "/System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/" \
                "com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine"

    def test_a_vm_counts_what_it_holds_not_its_footprint(self):
        # measured 2026-10-10 and 11 (tmp-33's vm-memory runs): Colima's guest zeroes
        # all 7 GiB at boot, which footprint counts though macOS stores it for
        # almost nothing; OrbStack's VM memory isn't in its helper's footprint at all
        G = 2**30
        self.assertEqual(sl.memory_of(self.COLIMA_VM, footprint=7.0 * G, resident=3.6 * G), 3.6 * G)
        self.assertEqual(sl.memory_of(self.ORBSTACK_VM, footprint=0.1 * G, resident=0.6 * G), 0.6 * G)
        # every other app keeps the footprint Activity Monitor shows
        self.assertEqual(sl.memory_of(self.CHROME, footprint=0.3 * G, resident=0.5 * G), 0.3 * G)

    def test_orbstacks_vm_is_named_orbstack(self):
        self.assertEqual(sl.app_name(self.ORBSTACK_VM), "OrbStack")

    @unittest.skipUnless(sys.platform == "darwin", "macOS kernel call")
    def test_reads_real_footprints_from_the_kernel(self):
        procs = sl.process_footprints()
        self.assertIn(os.getpid(), [pid for pid, _, _, _ in procs])
        mine = next(foot for pid, _, foot, _ in procs if pid == os.getpid())
        self.assertGreater(mine, 1 * 2**20)  # this Python process holds at least a megabyte

    @unittest.skipUnless(sys.platform == "darwin", "macOS readings")
    def test_a_path_without_sbin_still_reads_memory(self):
        # people whose shell profile sets PATH to /usr/bin:/bin; sysctl is in /usr/sbin
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            system = sl.gather_system()
        self.assertIn("used_pct", system.get("memory") or {})
        self.assertIn("load", system.get("cpu") or {})


def column(cpu_reading=None, memory=None):
    """The system column's four rows as text."""
    m = sl.build_model({"now": N, "claude": {}, "system": {"cpu": cpu_reading, "memory": memory}})
    return [plain(r) for r in sl.system_column(m)]


class SystemColumn(unittest.TestCase):
    def test_normal_shows_both_meters_with_blank_detail_rows(self):
        self.assertEqual(column(cpu(9), NORMAL_MEM),
                         ["cpu ▮▯▯▯▯▯▯▯  9%", "", "mem ▮▮▮▮▯▯▯▯ 49% · comp 4.4G", ""])

    def test_comp_is_dim_at_normal_and_takes_the_pressure_color_after(self):
        comp = lambda mem: sl.mem_meter(mem)[-1][1]
        self.assertEqual(comp(NORMAL_MEM), sl.DIM)
        self.assertEqual(comp(WARN_MEM), sl.TERRA)

    def test_warn_puts_level_and_app_under_the_mem_meter(self):
        self.assertEqual(column(cpu(86), WARN_MEM),
                         ["cpu ▮▮▮▮▮▮▮▯ 86%", "", "mem ▮▮▮▮▮▯▯▯ 63% · comp 6.5G",
                          "    pressure warn · Chrome 8.1G"])

    def test_saturated_cpu_puts_the_queue_under_the_cpu_meter(self):
        crit = {**WARN_MEM, "pressure": 4, "used_pct": 88}
        rows = column(cpu(99, "13.9", top="node"), crit)
        self.assertEqual(rows[1], "    2 cpu wait · node")
        self.assertEqual(rows[3], "    pressure crit · Chrome 8.1G")

    def test_mem_color_follows_pressure_not_fill(self):
        style = lambda mem: sl.mem_meter(mem)[0][1]
        self.assertEqual(style({"pressure": 1, "used_pct": 80}), sl.SAGE)
        self.assertEqual(style({"pressure": 2, "used_pct": 50}), sl.TERRA)
        self.assertEqual(style({"pressure": 4, "used_pct": 50}), sl.BRICK)

    def test_a_long_app_name_is_cut_so_its_size_still_fits(self):
        mem = {**WARN_MEM, "pressure": 4, "top": {"name": "Microsoft Teams (work or school)", "mb": 3100}}
        row = column(cpu(9), mem)[3]
        self.assertEqual(len(row), sl.SYSTEM_WIDTH)
        self.assertTrue(row.endswith("… 3.0G"))

    def test_meters_without_a_reading_are_dim_placeholders(self):
        self.assertEqual(column(cpu(None), {"pressure": 1})[::2], ["cpu ▯▯▯▯▯▯▯▯ --", "mem ▯▯▯▯▯▯▯▯ --"])
        self.assertEqual(column(None, None), [])


class TopProcess(unittest.TestCase):
    def test_takes_the_first_row_and_shortens_it_for_the_bar(self):
        ps = " %CPU COMM\n244.8 com.apple.Virtualization.VirtualMachine\n 65.3 node\n"
        self.assertEqual(sl.top_process(ps), "VirtualMachine")
        self.assertEqual(sl.top_process("   RSS COMM\n294544 claude\n"), "claude")
        self.assertEqual(sl.top_process(" %CPU COMM\n 99.0 Google Chrome Helper (Renderer)\n"),
                         "Google Chrome H…")
        self.assertIsNone(sl.top_process(" %CPU COMM\n"))


class Pace(unittest.TestCase):
    def test_heavy_week_on_day_six_stays_green(self):
        tier, projected, _, _ = sl.pace(71, N + 86400, sl.SEVEN_DAY, N)
        self.assertEqual(tier, 0)
        self.assertAlmostEqual(projected, 71 / 6 * 7, places=1)

    def test_five_hour_burning_out_is_red_with_minutes_left(self):
        tier, _, to_full, _ = sl.pace(94, N + (300 - 94) * 60, sl.FIVE_HOUR, N)
        self.assertEqual(tier, 3)
        self.assertAlmostEqual(to_full / 60, 6, places=0)

    def test_early_in_window_uses_raw_percentage(self):
        # 10% used 5 minutes in projects to 600%, which is noise
        tier, _, _, _ = sl.pace(10, N + sl.FIVE_HOUR - 300, sl.FIVE_HOUR, N)
        self.assertEqual(tier, sl.raw_tier(10))

    def test_near_the_top_raw_usage_overrides_good_pace(self):
        tier, _, _, _ = sl.pace(92, N + 3600, sl.SEVEN_DAY, N)  # last hour of the week
        self.assertEqual(tier, 2)
        tier, _, _, _ = sl.pace(98, N + 3600, sl.SEVEN_DAY, N)
        self.assertEqual(tier, 3)


class Text(unittest.TestCase):
    def test_truncate_ends_in_ellipsis_at_exact_width(self):
        out = sl.truncate([sl.seg("acme-shop "), sl.seg("feat/rewards")], 14)
        self.assertEqual(plain(out), "acme-shop fea…")

    def test_truncate_leaves_short_lines_alone(self):
        line = [sl.seg("main")]
        self.assertIs(sl.truncate(line, 10), line)

    def test_fit_shrinks_widest_column_first(self):
        self.assertEqual(sl.fit([20, 40, 30], 80), [20, 30, 30])

    def test_fit_stops_at_floor(self):
        self.assertEqual(sl.fit([12, 12], 10), [12, 12])

    def test_sanitize_strips_terminal_escapes(self):
        self.assertEqual(sl.sanitize("v1\x1b[31m.42\n"), "v1[31m.42")


def pr_row(review=None, checks=None):
    m = sl.build_model({"now": N, "claude": {}, "git": {"branch": "feat/x"},
                        "project": {"schema": 1, "branches": {"feat/x": {"checks": checks}}} if checks else None})
    return plain(sl.pr_line({"number": 142, "review_state": review}, m))


class PrRow(unittest.TestCase):
    def test_each_review_state_has_a_short_word(self):
        self.assertEqual(pr_row("approved"), "#142 lgtm")
        self.assertEqual(pr_row("changes_requested"), "#142 ⟲ changes")
        self.assertEqual(pr_row("pending"), "#142 in review")
        self.assertEqual(pr_row("draft"), "#142 draft")
        self.assertEqual(pr_row("something new"), "#142")

    def test_checks_show_failures_running_or_all_passed(self):
        self.assertEqual(pr_row(checks={"pass": 10, "fail": 2, "pending": 0}), "#142 ✗ 2/12")
        self.assertEqual(pr_row(checks={"pass": 7, "fail": 0, "pending": 5}), "#142 ⟳ 7/12")
        self.assertEqual(pr_row(checks={"pass": 12, "fail": 0, "pending": 0}), "#142 ✓")

    def test_widest_row_stays_narrow(self):
        row = pr_row("changes_requested", {"pass": 10, "fail": 2, "pending": 0})
        self.assertEqual(row, "#142 ✗ 2/12 ⟲ changes")


class Ship(unittest.TestCase):
    def model(self, project):
        inp = fixture("1-healthy")
        inp["project"] = project
        return sl.build_model(inp)

    def test_no_project_info_means_no_column(self):
        self.assertEqual(sl.ship_column(self.model(None)), [])

    def test_links_open_only_web_pages(self):
        # a repo's file can't put a file:// or app link behind a label
        def links(url):
            inp = fixture("1-healthy")
            inp["project"] = {"schema": 1, "ci": {"main": {"runs": ["ok"], "url": url, "updated_at": N}}}
            return sl.render(inp, 200)
        self.assertIn("\x1b]8;;https://example.test/ci", links("https://example.test/ci"))
        for url in ("file:///Applications/Calculator.app", "x-man-page://ls", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertNotIn(url, links(url))

    def test_stale_section_is_dimmed_with_its_age(self):
        project = {"schema": 1, "prs": {"open": 4, "updated_at": N - 3 * 3600}}
        (row,) = sl.ship_column(self.model(project))
        self.assertTrue(all(style == sl.DIM for _, style, _ in row))
        self.assertTrue(plain(row).endswith("3h old"))

    def test_per_section_stale_after_overrides_default(self):
        project = {"schema": 1, "prs": {"open": 4, "updated_at": N - 120, "stale_after": 60}}
        (row,) = sl.ship_column(self.model(project))
        self.assertIn("2m old", plain(row))

    # a real feed: #126 running, #125 passed, #124 failed
    PRS = {"open": 3, "needs_review": 0, "updated_at": N, "items": [
        {"number": 126, "checks": "pending", "url": "https://example.test/pull/126"},
        {"number": 125, "checks": "pass", "url": "https://example.test/pull/125"},
        {"number": 124, "checks": "fail", "url": "https://example.test/pull/124"},
    ]}

    def test_each_open_pr_shows_whether_its_checks_passed_run_or_failed(self):
        (row,) = sl.ship_column(self.model({"schema": 1, "prs": self.PRS}))
        self.assertEqual(plain(row), "PRs   #126⟳ #125✓ #124✗")
        glyphs = {t: style for t, style, _ in row if t in "⟳✓✗"}
        self.assertEqual(glyphs, {"⟳": sl.AMBER, "✓": sl.SAGE, "✗": sl.BRICK})
        links = [link for t, _, link in row if t.startswith("#")]
        self.assertEqual(links, [i["url"] for i in self.PRS["items"]])

    def test_many_open_prs_collapse_to_counts_per_state(self):
        items = [{"number": n, "checks": c} for n, c in
                 enumerate(["pass", "pass", "fail", "pending", "pass", "none"], 100)]
        (row,) = sl.ship_column(self.model({"schema": 1, "prs": {"open": 6, "items": items, "updated_at": N}}))
        self.assertEqual(plain(row), "PRs   6 open ✓3 ⟳1 ✗1")

    def test_feed_without_items_still_shows_the_open_count(self):
        (row,) = sl.ship_column(self.model({"schema": 1, "prs": {"open": 4, "needs_review": 2, "updated_at": N}}))
        self.assertEqual(plain(row), "PRs   4 open · 2 need review")

    def test_a_failing_pr_survives_overflow_but_all_green_prs_do_not(self):
        project = fixture("1-healthy")["project"]
        project["deploy"]["prod"]["status"] = "fail"
        project["deploy"]["dev"] = {"version": "v1.45", "status": "ok", "updated_at": N}  # a fifth row
        project["prs"] = {**self.PRS, "items": self.PRS["items"][1:]}  # one passed, one failed
        rows = [plain(r) for r in sl.ship_column(self.model(project))]
        self.assertTrue(any("#124✗" in r for r in rows))
        project["prs"]["items"] = [self.PRS["items"][1]]  # only the passing one
        rows = [plain(r) for r in sl.ship_column(self.model(project))]
        self.assertFalse(any(r.startswith("PRs") for r in rows))

    def test_overflow_drops_healthy_rows_before_problems(self):
        project = fixture("1-healthy")["project"]
        project["deploy"]["prod"]["status"] = "fail"
        project["deploy"]["dev"] = {"status": "running", "updated_at": N}  # a fifth row
        rows = [plain(r) for r in sl.ship_column(self.model(project))]
        self.assertEqual(len(rows), 4)
        self.assertTrue(any("deploy failed" in r for r in rows))
        self.assertTrue(any("deploying" in r for r in rows))


class CleanProject(unittest.TestCase):
    """The repo writes project-info.json, so each field is checked against the schema."""

    def test_a_good_file_comes_through_whole(self):
        project = fixture("2-bad-day")["project"]
        self.assertEqual(sl.clean_project(project), project)

    def test_only_schema_1_is_read(self):
        for p in (None, [], {}, {"schema": 2}, {"schema": "1"}):
            with self.subTest(p=p):
                self.assertIsNone(sl.clean_project(p))

    def test_a_bad_field_drops_that_field_only(self):
        p = sl.clean_project({"schema": 1, "deploy": {"prod": {
            "version": "v2", "status": "exploded", "behind": "3", "deployed_at": True, "updated_at": N}}})
        self.assertEqual(p["deploy"]["prod"], {"version": "v2", "updated_at": N})

    def test_unknown_states_and_wrong_types_leave_the_list(self):
        p = sl.clean_project({"schema": 1, "ci": {"main": {"runs": ["ok", "maybe", 3, None, "fail"]}},
                              "prs": {"items": [{"number": 7, "checks": "pass"}, "junk", {"checks": "??"}]}})
        self.assertEqual(p["ci"]["main"]["runs"], ["ok", "fail"])
        self.assertEqual(p["prs"]["items"], [{"number": 7, "checks": "pass"}, {}])

    def test_counts_must_be_whole_and_not_negative(self):
        p = sl.clean_project({"schema": 1, "prs": {"open": 2.5, "needs_review": -1},
                              "branches": {"x": {"checks": {"pass": 3, "fail": False}}}})
        self.assertEqual(p["prs"], {})
        self.assertEqual(p["branches"]["x"]["checks"], {"pass": 3})

    def test_not_a_number_never_gets_through(self):
        p = sl.clean_project(json.loads('{"schema": 1, "stale_after": NaN, "prs": {"updated_at": Infinity}}'))
        self.assertEqual(p, {"schema": 1, "prs": {}})


class GitStatus(unittest.TestCase):
    PORCELAIN = (
        "# branch.oid 4f2a9c1d0e\n"
        "# branch.head feat/rewards\n"
        "# branch.upstream origin/feat/rewards\n"
        "# branch.ab +2 -1\n"
        "1 M. N... 100644 100644 100644 aaa bbb src/a.py\n"   # staged
        "1 .M N... 100644 100644 100644 aaa bbb src/b.py\n"   # modified
        "1 MM N... 100644 100644 100644 aaa bbb src/c.py\n"   # both
        "2 R. N... 100644 100644 100644 aaa bbb R100 new.py\told.py\n"
        "u UU N... 100644 100644 100644 100644 aaa bbb ccc conflict.py\n"
        "? notes.txt\n"
    )

    def test_parses_counts_branch_and_divergence(self):
        self.assertEqual(sl.parse_status(self.PORCELAIN), {
            "sha": "4f2a9c1d0e", "branch": "feat/rewards", "ahead": 2, "behind": 1,
            "staged": 3, "modified": 2, "conflicts": 1, "untracked": 1,
        })

    def test_detached_head_has_no_branch(self):
        g = sl.parse_status("# branch.oid abc\n# branch.head (detached)\n")
        self.assertIsNone(g["branch"])

    def repo(self, d):
        git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
        git("init", "-q", "-b", "trunk")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        return git

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_a_repos_own_git_config_cannot_run_commands(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo(d)("config", "core.fsmonitor", f"touch {d}/ran; false")
            Path(d, "a.txt").write_text("x")
            sl.gather_git(d)
            self.assertFalse(Path(d, "ran").exists())

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_a_branch_name_that_isnt_utf8_still_draws(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo(d)
            sha = Path(d, ".git/refs/heads/trunk").read_bytes().strip()
            Path(d, ".git/packed-refs").write_bytes(sha + b" refs/heads/feat-\xff\n")  # 0xff isn't UTF-8
            Path(d, ".git/HEAD").write_bytes(b"ref: refs/heads/feat-\xff\n")
            g, _ = sl.gather_git(d)
        self.assertTrue(g["branch"].startswith("feat-"))

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_a_slow_git_status_keeps_the_branch_and_says_it_doesnt_know(self):
        real = sl.run
        slow = lambda *a, **k: None if "status" in a else real(*a, **k)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sl, "run", slow):
            self.repo(d)
            g, _ = sl.gather_git(d)
            inp = dict(fixture("1-healthy"), git=g, project=None)
            out = visible(sl.render(inp, 200))
        self.assertEqual(g["branch"], "trunk")
        self.assertNotIn("clean", out)
        self.assertNotIn("detached", out)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_works_with_git_older_than_2_31(self):
        # git before 2.31 doesn't know --path-format and prints it back as output
        with tempfile.TemporaryDirectory() as d:
            self.repo(d)
            shim = Path(d, "bin")
            shim.mkdir()
            (shim / "git").write_text(f"""#!/bin/bash
args=(); for a in "$@"; do [[ $a == --path-format=* ]] && echo "$a" || args+=("$a"); done
exec {shutil.which("git")} "${{args[@]}}"
""")
            (shim / "git").chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}):
                g, common = sl.gather_git(d)
        self.assertEqual((g["branch"], common), ("trunk", Path(d).resolve() / ".git"))

    def conflict(self, d, how):
        """A repo stopped mid-`how` (rebase or merge) on a conflict in app.txt."""
        git = self.repo(d)
        commit = lambda text, msg: (Path(d, "app.txt").write_text(text), git("add", "app.txt"),
                                    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg))
        commit("one\n", "base")
        git("switch", "-q", "-c", "feat/cart")
        commit("cart\n", "cart")
        git("switch", "-q", "trunk")
        commit("other\n", "other")
        if how == "rebase":
            git("switch", "-q", "feat/cart")
        subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", how,
                        "trunk" if how == "rebase" else "feat/cart"], capture_output=True)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_a_rebase_in_progress_says_so_and_names_the_branch(self):
        with tempfile.TemporaryDirectory() as d:
            self.conflict(d, "rebase")
            g, _ = sl.gather_git(d)
            out = visible(sl.render(dict(fixture("1-healthy"), git=g, project=None), 200))
        self.assertIn("feat/cart rebasing", out)
        self.assertNotIn("detached", out)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_a_merge_in_progress_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            self.conflict(d, "merge")
            g, _ = sl.gather_git(d)
            out = visible(sl.render(dict(fixture("1-healthy"), git=g, project=None), 200))
        self.assertIn("trunk merging", out)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_against_a_real_repo(self):
        with tempfile.TemporaryDirectory() as d:
            git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
            git("init", "-q", "-b", "trunk")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
            Path(d, "staged.txt").write_text("x")
            git("add", "staged.txt")
            Path(d, "loose.txt").write_text("y")
            g, common = sl.gather_git(d)
        self.assertEqual(g["branch"], "trunk")
        self.assertEqual((g.get("staged"), g.get("untracked")), (1, 1))
        self.assertEqual(common.name, ".git")
        self.assertIn("last_commit", g)


class Render(unittest.TestCase):
    def test_wide_terminal_gets_columns(self):
        first = visible(sl.render(fixture("1-healthy"))).split("\n")[0]
        self.assertEqual(first.count("┃"), 2)  # repo | ship | session

    def test_a_narrow_row_with_nothing_to_say_has_no_rule(self):
        # no project info: three rows of words beside four rows of tanks
        last = visible(sl.render(fixture("3-no-project"), 40)).split("\n")[3]
        self.assertEqual(last.rstrip(), "ctx  5h  wk")

    def test_narrow_terminal_falls_back_to_rows(self):
        lines = visible(sl.render(fixture("4-narrow"))).split("\n")
        self.assertTrue(all(l.count("┃") == 1 for l in lines))
        self.assertIn("acme-shop · feat/rewards", lines[0])

    def test_repo_without_project_info_has_room_for_the_week_then_system_column(self):
        lines = visible(sl.render(fixture("3-no-project"), cols=130)).split("\n")
        self.assertEqual(lines[0].count("┃"), 2)  # repo | session | week
        self.assertIn("58% now", lines[0])
        lines = visible(sl.render(fixture("3-no-project"), cols=200)).split("\n")
        self.assertEqual(lines[0].count("┃"), 3)  # repo | session | week | system
        self.assertTrue(lines[0].endswith("cpu ▮▮▯▯▯▯▯▯ 23%"))
        self.assertIn("mem ▮▮▮▮▯▯▯▯ 49% · comp 4.4G", lines[2])

    def test_system_column_only_when_the_rest_fit_at_full_width(self):
        inp = fixture("2-bad-day")
        squeezed = visible(sl.render(inp)).split("\n")  # 120 columns: no room
        self.assertEqual(squeezed[0].count("┃"), 2)
        roomy = visible(sl.render(inp, cols=240)).split("\n")
        self.assertEqual(roomy[0].count("┃"), 4)  # the week column comes first
        self.assertIn("    pressure warn · Chrome 8.1G", roomy[3])
        self.assertIn("    3 cpu wait · node · batt 22%", roomy[1])
        # with the column showing, the alerts line leaves the machine to it
        self.assertEqual(roomy[4], "⚠ migration pending  ·  cache cold")

    def test_adding_the_column_never_shortens_another(self):
        inp = fixture("2-bad-day")
        without = visible(sl.render(inp, cols=240)).split("\n")
        for cols in range(120, 240):
            lines = visible(sl.render(inp, cols=cols)).split("\n")
            if lines[0].count("┃") == 3:
                with self.subTest(cols=cols):
                    self.assertNotIn("…", "".join(l.split("┃")[1] for l in lines[:4]))
                    # repo and ship; the session's runway line loses its week bar
                    # once the week has a column of its own, so it differs at 240
                    self.assertEqual(lines[0].split("┃")[:2], without[0].split("┃")[:2])

    def test_alerts_add_one_line_under_the_four(self):
        self.assertEqual(len(sl.render(fixture("2-bad-day")).split("\n")), 5)
        self.assertEqual(len(sl.render(fixture("1-healthy")).split("\n")), 4)

    def test_hostile_project_text_cannot_emit_escapes(self):
        inp = fixture("1-healthy")
        inp["project"]["deploy"]["prod"]["version"] = "\x1b]0;pwned\x07v1"
        inp["project"]["deploy"]["prod"]["url"] = "https://x\x1b\\\x1b[2J"
        out = sl.render(inp, color=False)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)


class Sensor(unittest.TestCase):
    """Hooks read DATA_DIR/<session_id>.json; see docs/usage-files.md."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_one_file_per_session_with_its_limits_and_context(self):
        claude = fixture("1-healthy")["claude"]
        sl.write_sensor(claude, N, self.dir)
        got = json.loads((self.dir / f"{claude['session_id']}.json").read_text())
        self.assertEqual(got["at"], N)
        self.assertEqual(got["five_hour"], claude["rate_limits"]["five_hour"])
        self.assertEqual(got["seven_day"], claude["rate_limits"]["seven_day"])
        self.assertEqual(got["context_used"], claude["context_window"]["used_percentage"])
        self.assertEqual(got["cwd"], claude["workspace"]["current_dir"])

    def test_nothing_written_without_rate_limits(self):
        claude = {k: v for k, v in fixture("1-healthy")["claude"].items() if k != "rate_limits"}
        sl.write_sensor(claude, N, self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_session_id_cannot_write_outside_the_folder(self):
        claude = dict(fixture("1-healthy")["claude"], session_id="../escape")
        sl.write_sensor(claude, N, self.dir / "inner")
        self.assertFalse((self.dir / "escape.json").exists())

    def test_the_weekly_cleanup_removes_only_old_session_files(self):
        # CLAUDE_STATUSLINE_DATA could point anywhere, even ~/.claude itself
        now = N - N % 60  # cleanup runs on a minute boundary
        week_old = now - 8 * DAY
        old_session = self.dir / "0f1e2d3c-4b5a-4968-8776-655443322110.json"
        keep = [self.dir / "settings.json", self.dir / "notes.json"]
        for f in [old_session, *keep]:
            f.write_text("{}")
            os.utime(f, (week_old, week_old))
        sl.write_sensor(fixture("1-healthy")["claude"], now, self.dir)
        self.assertFalse(old_session.exists())
        self.assertTrue(all(f.exists() for f in keep))

    def test_can_be_turned_off(self):
        with mock.patch.object(sl, "SENSOR", False):
            sl.write_sensor(fixture("1-healthy")["claude"], N, self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])


class Settings(unittest.TestCase):
    def test_day_start_is_an_hour_or_falls_back(self):
        for raw, want in (("6", 6), ("0", 0), ("23", 23), ("24", 4), ("-1", 4), ("early", 4)):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"X": raw}):
                self.assertEqual(sl.env_int("X", 4, 0, 23), want)


HELPER = ROOT / "statusline" / "project-info"


@unittest.skipUnless(shutil.which("git"), "git missing")
class ProjectInfoHelper(unittest.TestCase):
    """The helper repos use to write the file the status line reads."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        subprocess.run(["git", "init", "-q", self.repo], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def pi(self, *args):
        return subprocess.run([str(HELPER), *args], cwd=self.repo, capture_output=True, text=True)

    def test_set_merges_sections_and_stamps_time(self):
        self.pi("set", "deploy", "prod", '{"version": "v1.42", "status": "ok"}')
        self.pi("set", "deploy", "prod", '{"behind": 3}')
        prod = json.loads(self.pi("get", "deploy", "prod").stdout)
        self.assertEqual((prod["version"], prod["behind"]), ("v1.42", 3))
        self.assertIn("updated_at", prod)

    def test_branch_names_with_dots_and_slashes_are_single_keys(self):
        self.pi("set", "branches", "release/1.2", '{"checks": {"pass": 1}}')
        data = json.loads(self.pi("get").stdout)
        self.assertEqual(data["branches"]["release/1.2"]["checks"]["pass"], 1)
        self.assertEqual(data["schema"], 1)

    def test_file_lives_in_git_dir_where_the_status_line_looks(self):
        self.pi("set", "prs", '{"open": 4}')
        self.assertEqual(sl.gather_project(Path(self.repo) / ".git")["prs"]["open"], 4)

    def test_works_with_git_older_than_2_31(self):
        # git before 2.31 doesn't know --path-format and prints it back as output
        shim = Path(self.repo, "bin")
        shim.mkdir()
        (shim / "git").write_text(f"""#!/bin/bash
args=(); for a in "$@"; do [[ $a == --path-format=* ]] && echo "$a" || args+=("$a"); done
exec {shutil.which("git")} "${{args[@]}}"
""")
        (shim / "git").chmod(0o755)
        env = {**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}
        out = subprocess.run([str(HELPER), "set", "prs", '{"open": 1}'], cwd=self.repo, env=env,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(Path(self.repo, ".git", "project-info.json").exists())

    def test_set_refuses_a_time_that_isnt_a_number(self):
        out = self.pi("set", "ci", "main", '{"updated_at": "2026-10-12T10:00:00Z"}')
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("updated_at", out.stderr)

    def test_a_time_written_some_other_way_counts_as_missing(self):
        # another tool wrote the file by hand
        Path(self.repo, ".git", "project-info.json").write_text(
            json.dumps({"schema": 1, "prs": {"open": 1, "updated_at": "yesterday"}}))
        self.assertEqual(self.pi("fresh", "prs", "60").returncode, 1)
        out = subprocess.run([str(HELPER), "refresh", "prs", "60", "--", "echo", '{"open": 2}'],
                             cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_fresh_reports_age_against_threshold(self):
        self.assertEqual(self.pi("fresh", "prs", "60").returncode, 1)  # missing
        self.pi("set", "prs", '{"open": 4}')
        self.assertEqual(self.pi("fresh", "prs", "60").returncode, 0)
        self.pi("set", "prs", '{"updated_at": 1}')
        self.assertEqual(self.pi("fresh", "prs", "60").returncode, 1)  # stale


@unittest.skipUnless(shutil.which("git"), "git missing")
class ProjectInfoRefresh(unittest.TestCase):
    """`project-info refresh`, which hooks run after every turn from every
    session. The commands stand in for gh: each logs that it ran."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        self.log = Path(tmp.name) / "ran.log"
        subprocess.run(["git", "init", "-q", self.repo], check=True)

    def command(self, prints="", stderr="", code=0, sleep=0):
        """A command that logs a line, waits, prints, and exits with `code`."""
        script = (f"import sys, time; open({str(self.log)!r}, 'a').write('ran\\n'); time.sleep({sleep}); "
                  f"print({prints!r}); print({stderr!r}, file=sys.stderr); sys.exit({code})")
        return [sys.executable, "-c", script]

    def refresh(self, *args, **command):
        return subprocess.run([str(HELPER), "refresh", *args, "--", *self.command(**command)],
                              cwd=self.repo, capture_output=True, text=True)

    def runs(self):
        return len(self.log.read_text().splitlines()) if self.log.exists() else 0

    def section(self, *keys):
        out = subprocess.run([str(HELPER), "get", *keys], cwd=self.repo, capture_output=True, text=True)
        return json.loads(out.stdout) if out.returncode == 0 else None

    def test_a_missing_section_is_fetched_and_stamped(self):
        self.assertEqual(self.refresh("prs", "120", prints='{"open": 2}').returncode, 0)
        prs = self.section("prs")
        self.assertEqual(prs["open"], 2)
        self.assertAlmostEqual(prs["updated_at"], time.time(), delta=30)

    def test_what_it_prints_replaces_the_section(self):
        # a PR list that used to have items and now has none keeps none
        subprocess.run([str(HELPER), "set", "prs", '{"open": 1, "items": [{"number": 7}], "updated_at": 1}'],
                       cwd=self.repo, check=True)
        self.refresh("prs", "120", prints='{"open": 0}')
        self.assertNotIn("items", self.section("prs"))

    def test_a_fresh_section_runs_nothing(self):
        self.refresh("prs", "120", prints='{"open": 2}')
        self.refresh("prs", "120", prints='{"open": 3}')
        self.assertEqual((self.runs(), self.section("prs")["open"]), (1, 2))

    def test_a_failure_keeps_the_data_and_says_why(self):
        subprocess.run([str(HELPER), "set", "ci", "main", '{"runs": ["ok"], "updated_at": 1}'], cwd=self.repo, check=True)
        out = self.refresh("ci", "main", "120", stderr="error connecting to api.github.com", code=1)
        self.assertEqual(out.returncode, 1)
        self.assertIn("error connecting to api.github.com", out.stderr)
        ci = self.section("ci", "main")
        self.assertEqual((ci["runs"], ci["updated_at"]), (["ok"], 1))
        self.assertEqual(ci["error"], "error connecting to api.github.com")
        self.assertAlmostEqual(ci["tried_at"], time.time(), delta=30)

    def test_after_a_failure_it_waits_a_window_before_trying_again(self):
        self.refresh("prs", "120", code=1)
        self.refresh("prs", "120", code=1)
        self.assertEqual(self.runs(), 1)

    def test_force_runs_even_when_fresh_or_just_failed(self):
        self.refresh("prs", "120", prints='{"open": 2}')
        self.refresh("--force", "prs", "120", prints='{"open": 3}')
        self.assertEqual(self.section("prs")["open"], 3)
        self.refresh("--force", "prs", "120", code=1)
        self.refresh("--force", "prs", "120", prints='{"open": 4}')
        self.assertEqual(self.runs(), 4)

    def test_a_success_clears_the_last_error(self):
        self.refresh("prs", "120", stderr="offline", code=1)
        self.refresh("--force", "prs", "120", prints='{"open": 2}')
        self.assertNotIn("error", self.section("prs"))
        self.assertNotIn("tried_at", self.section("prs"))

    def test_json_counts_as_success_whatever_the_exit_code(self):
        # gh pr checks exits 8 while checks are pending, and still prints them
        self.assertEqual(self.refresh("prs", "120", prints='{"open": 2}', code=8).returncode, 0)
        self.assertEqual(self.section("prs")["open"], 2)

    def test_two_sessions_at_once_run_the_command_once(self):
        cmd = [str(HELPER), "refresh", "prs", "120", "--", *self.command(prints='{"open": 2}', sleep=1)]
        procs = [subprocess.Popen(cmd, cwd=self.repo) for _ in range(3)]
        for p in procs:
            p.wait(timeout=30)
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.section("prs")["open"], 2)

    def test_a_session_that_finished_while_this_one_waited_is_not_repeated(self):
        # B finds prs stale; before B takes the lock, A finishes the refresh
        import importlib.machinery, importlib.util, fcntl
        loader = importlib.machinery.SourceFileLoader("project_info", str(HELPER))
        pi = importlib.util.module_from_spec(importlib.util.spec_from_loader("project_info", loader))
        loader.exec_module(pi)
        path = Path(self.repo, ".git", "project-info.json")
        real_flock = fcntl.flock

        def a_finishes_first(f, op):
            if op & fcntl.LOCK_NB:
                pi.cmd_set(path, ["prs"], {"open": 9}, time.time())
            return real_flock(f, op)

        with mock.patch.object(pi.fcntl, "flock", a_finishes_first):
            pi.cmd_refresh(path, ["prs", "120", "--", *self.command(prints='{"open": 2}')])
        self.assertEqual((self.runs(), self.section("prs")["open"]), (0, 9))

    def test_a_missing_command_is_recorded_as_the_error(self):
        out = subprocess.run([str(HELPER), "refresh", "prs", "120", "--", "no-such-gh"], cwd=self.repo,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.section("prs")["error"], "no-such-gh: command not found")


if __name__ == "__main__":
    unittest.main()
