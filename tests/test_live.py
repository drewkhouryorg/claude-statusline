"""The real thing, end to end: statusline.sh and statusline.py as Claude Code
runs them, against a throwaway git repo, home folder and install folder.
Nothing here touches your own ~/.claude."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from support import ROOT, scenario, visible

needs = unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "needs git and bash")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"})


@needs
class Live(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # an install folder of our own, so the wrapper's cache lands here
        self.install = self.tmp / "install"
        shutil.copytree(ROOT / "statusline", self.install, ignore=shutil.ignore_patterns("cache", "__pycache__"))
        self.data = self.tmp / "data"
        self.repo = self.tmp / "shop"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print('hi')\n")
        git(self.repo, "add", "app.py")
        git(self.repo, "commit", "-q", "-m", "first")
        git(self.repo, "switch", "-q", "-c", "feat/cart")
        (self.repo / "app.py").write_text("print('cart')\n")  # one modified file
        (self.repo / "notes.txt").write_text("x\n")           # one untracked

    def claude(self, **changes):
        c = scenario("1-healthy")["claude"]
        now = int(time.time())
        c["rate_limits"] = {"five_hour": {"used_percentage": 40, "resets_at": now + 3 * 3600},
                            "seven_day": {"used_percentage": 30, "resets_at": now + 4 * 86400}}
        c["workspace"] = {"current_dir": str(self.repo)}
        c.pop("pr")
        c.update(changes)
        return c

    def run_sh(self, claude, bash="bash", **env):
        """claude is a dict, or the exact text Claude Code would send."""
        text = claude if isinstance(claude, str) else json.dumps(claude)
        out = subprocess.run([bash, str(self.install / "statusline.sh")], input=text,
                             capture_output=True, text=True, timeout=30,
                             env={**os.environ, "HOME": str(self.tmp), "COLUMNS": "200",
                                  "CLAUDE_STATUSLINE_DATA": str(self.data), **env})
        self.assertEqual(out.returncode, 0, out.stderr)
        return visible(out.stdout)

    def pi(self, *args):
        return subprocess.run([str(self.install / "project-info"), *args], cwd=self.repo,
                              capture_output=True, text=True, check=True)

    def test_shows_the_repo_branch_and_changes(self):
        lines = self.run_sh(self.claude()).split("\n")
        self.assertIn("shop", lines[0])
        self.assertIn("feat/cart", lines[1])
        self.assertIn("✚1 ?1", lines[2])
        self.assertTrue(lines[3].startswith("ctx  5h  wk"))

    def test_project_info_from_the_helper_shows_in_the_ship_column(self):
        self.pi("set", "ci", "main", '{"runs": ["ok", "ok", "fail"]}')
        self.pi("set", "deploy", "prod", '{"version": "v9.1", "status": "ok"}')
        out = self.run_sh(self.claude())
        self.assertIn("main  ✓✓✗", out)
        self.assertIn("prod  ✓ v9.1", out)

    def test_json_gives_each_part_as_data_beside_the_drawing(self):
        # what the desktop app's pane reads: the same repo, as data
        out = subprocess.run([sys.executable, str(self.install / "statusline.py"), "--json"],
                             input=json.dumps(self.claude()), capture_output=True, text=True, timeout=30,
                             env={**os.environ, "HOME": str(self.tmp), "COLUMNS": "200",
                                  "CLAUDE_STATUSLINE_DATA": str(self.data)})
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertEqual((got["repo"]["name"], got["repo"]["branch"]), ("shop", "feat/cart"))
        self.assertEqual([(m["kind"], m["count"]) for m in got["repo"]["marks"]], [("modified", 1), ("untracked", 1)])
        self.assertEqual(visible(got["ansi"]), self.run_sh(self.claude()))

    def test_writes_this_sessions_usage_file_and_week_log(self):
        claude = self.claude()
        self.run_sh(claude)
        reading = json.loads((self.data / f"{claude['session_id']}.json").read_text())
        self.assertEqual(reading["five_hour"]["used_percentage"], 40)
        log = (self.data / "history.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(log[0])["pct"], 30)

    def test_usage_file_can_be_turned_off(self):
        claude = self.claude()
        self.run_sh(claude, CLAUDE_STATUSLINE_SENSOR="0")
        self.assertFalse((self.data / f"{claude['session_id']}.json").exists())

    def python_that_logs(self):
        """A stand-in for python3 that notes each time it's started, then runs the real one."""
        log, stub = self.tmp / "python-ran.log", self.tmp / "python-stub"
        stub.write_text(f'#!/bin/bash\necho ran >> "{log}"\nexec {sys.executable} "$@"\n')
        stub.chmod(0o755)
        return str(stub), log

    def test_a_second_call_within_ten_seconds_reprints_without_python(self):
        claude = self.claude()
        first = self.run_sh(claude)
        stub, log = self.python_that_logs()
        again = self.run_sh(claude, CLAUDE_STATUSLINE_PYTHON=stub)
        self.assertEqual(again, first)
        self.assertFalse(log.exists())

    def test_new_numbers_from_claude_code_redraw_at_once(self):
        # after a reply the context jumps; the line must not show the old number for 10s
        claude = self.claude()
        self.run_sh(claude)
        claude["context_window"] = {"used_percentage": 91}
        self.assertIn("91", self.run_sh(claude).split("\n")[0])

    def test_a_new_width_redraws_at_once(self):
        claude = self.claude()
        self.run_sh(claude, COLUMNS="200")
        narrow = self.run_sh(claude, COLUMNS="100")
        self.assertLessEqual(max(len(line) for line in narrow.split("\n")), 98)

    def test_only_the_session_clock_moving_reuses_the_drawing(self):
        # Claude Code sends both clocks on every call; only their values move
        claude = self.claude()
        claude["cost"] = dict(claude.get("cost") or {}, total_duration_ms=5_040_000, total_api_duration_ms=2_300)
        self.run_sh(claude)
        claude["cost"] = dict(claude["cost"], total_duration_ms=5_041_000, total_api_duration_ms=2_345)
        stub, log = self.python_that_logs()
        self.run_sh(claude, CLAUDE_STATUSLINE_PYTHON=stub)
        self.assertFalse(log.exists())

    def test_clocks_sent_without_spaces_or_with_decimals_still_reuse_the_drawing(self):
        compact = {"separators": (",", ":")}  # how Claude Code's JSON.stringify writes it
        claude = self.claude()
        claude["cost"] = dict(claude.get("cost") or {}, total_duration_ms=5_040_000.5, total_api_duration_ms=2_300.25)
        self.run_sh(json.dumps(claude, **compact))
        claude["cost"] = dict(claude["cost"], total_duration_ms=5_041_000.75, total_api_duration_ms=2_345.5)
        stub, log = self.python_that_logs()
        self.run_sh(json.dumps(claude, **compact), CLAUDE_STATUSLINE_PYTHON=stub)
        self.assertFalse(log.exists())

    def test_other_fields_ending_in_ms_still_redraw(self):
        # only the two session clocks are left out of the comparison
        claude = self.claude()
        near_misses = ("api_duration_ms", "total_duration_ms_p50", "total_wait_ms")
        claude["cost"] = dict(claude.get("cost") or {}, **{name: 100 for name in near_misses})
        self.run_sh(claude)
        for name in near_misses:
            with self.subTest(name=name):
                claude["cost"] = dict(claude["cost"], **{name: claude["cost"][name] + 1})
                stub, log = self.python_that_logs()
                self.run_sh(claude, CLAUDE_STATUSLINE_PYTHON=stub)
                self.assertTrue(log.exists())
                log.unlink()

    def test_dropping_the_clocks_stays_quick_in_macos_bash_3_2(self):
        # an extglob substitution here once took half a second a call in bash 3.2,
        # and grew with the cube of the input; Claude Code calls it every few seconds
        claude = self.claude()
        claude["cost"] = dict(claude.get("cost") or {}, total_duration_ms=5_040_000, total_api_duration_ms=2_300)
        claude["a_field_claude_code_adds_later"] = "x" * 6000  # inputs grow as Claude Code sends more
        start = time.monotonic()
        self.run_sh(claude, bash="/bin/bash" if Path("/bin/bash").exists() else "bash")
        self.assertLess(time.monotonic() - start, 5)

    def test_a_terminal_that_isnt_utf8_still_draws(self):
        out = self.run_sh(self.claude(), PYTHONIOENCODING="latin-1")
        self.assertNotIn("statusline error", out)
        self.assertIn("▕", out)

    def test_an_old_error_log_goes_once_it_draws_again(self):
        subprocess.run(["bash", str(self.install / "statusline.sh")], input="{not json", capture_output=True,
                       text=True, env={**os.environ, "HOME": str(self.tmp)})
        self.assertTrue((self.install / "error.log").exists())
        self.run_sh(self.claude())
        self.assertFalse((self.install / "error.log").exists())

    def test_a_render_dated_in_the_future_is_redrawn(self):
        # after the clock steps back, an old render must not look fresh for hours
        claude = self.claude()
        self.run_sh(claude)
        cached = self.install / "cache" / f"render-{claude['session_id']}.txt"
        future = time.time() + 3600
        os.utime(cached, (future, future))
        stub, log = self.python_that_logs()
        self.run_sh(claude, CLAUDE_STATUSLINE_PYTHON=stub)
        self.assertTrue(log.exists())

    def test_without_python_it_says_so_and_leaves_nothing_behind(self):
        out = self.run_sh(self.claude(), CLAUDE_STATUSLINE_PYTHON="/nonexistent/python3")
        self.assertIn("statusline: couldn't run /nonexistent/python3", out)
        self.assertEqual(sorted(p.name for p in (self.install / "cache").glob("*.txt.*")), [])

    def test_an_install_folder_it_cannot_write_still_draws(self):
        self.install.chmod(0o555)
        self.addCleanup(self.install.chmod, 0o755)
        out = self.run_sh(self.claude())
        self.assertIn("feat/cart", out)

    def test_an_old_render_is_redrawn(self):
        claude = self.claude()
        self.run_sh(claude)
        cached = self.install / "cache" / f"render-{claude['session_id']}.txt"
        past = time.time() - 60
        os.utime(cached, (past, past))
        (self.repo / "more.txt").write_text("y\n")
        time.sleep(0.01)
        # git readings are cached for 10s too, by the time stamped inside; age those
        for f in (self.install / "cache").glob("*.json"):
            reading = json.loads(f.read_text())
            if "data" in reading:
                f.write_text(json.dumps(dict(reading, at=past)))
        self.assertIn("?2", self.run_sh(claude))

    def test_sessions_keep_separate_renders(self):
        a = self.run_sh(self.claude(session_id="aaaaaaaa-0000-0000-0000-000000000000", session_name="one"))
        b = self.run_sh(self.claude(session_id="bbbbbbbb-0000-0000-0000-000000000000", session_name="two"))
        self.assertIn("one", a)
        self.assertIn("two", b)

    def test_width_follows_columns_or_the_override(self):
        def widest(**env):
            out = self.run_sh(self.claude(session_id=f"w{len(env)}-{'-'.join(env.values())}"), **env)
            return max(len(line) for line in out.split("\n"))
        self.assertLessEqual(widest(COLUMNS="100"), 98)
        self.assertLessEqual(widest(COLUMNS="200", CLAUDE_STATUSLINE_COLUMNS="82"), 80)

    def test_outside_git_it_says_so(self):
        plain_dir = self.tmp / "scratch"
        plain_dir.mkdir()
        out = self.run_sh(self.claude(workspace={"current_dir": str(plain_dir)}))
        self.assertIn("no git", out)

    def test_usage_files_follow_claude_config_dir(self):
        config = self.tmp / "config"
        claude = self.claude()
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_STATUSLINE_DATA"}
        subprocess.run(["bash", str(self.install / "statusline.sh")], input=json.dumps(claude), capture_output=True,
                       text=True, env={**env, "HOME": str(self.tmp), "CLAUDE_CONFIG_DIR": str(config)})
        self.assertTrue((config / "usage-sensor" / f"{claude['session_id']}.json").exists())

    def test_input_of_the_wrong_shape_still_draws(self):
        out = subprocess.run(["bash", str(self.install / "statusline.sh")], input="[]",
                             capture_output=True, text=True, cwd=self.repo,
                             env={**os.environ, "HOME": str(self.tmp), "COLUMNS": "200"})
        self.assertNotIn("statusline error", out.stdout)
        self.assertIn("ctx", visible(out.stdout))

    def test_bad_input_prints_an_error_instead_of_nothing(self):
        out = subprocess.run(["python3", str(self.install / "statusline.py")], input="{not json",
                             capture_output=True, text=True, env={**os.environ, "HOME": str(self.tmp)})
        self.assertEqual(out.returncode, 0)
        self.assertIn("statusline error: JSONDecodeError", visible(out.stdout))
        self.assertTrue((self.install / "error.log").exists())


@needs
class Preview(unittest.TestCase):
    """tools/preview.py --live, run in a throwaway repo."""

    def test_live_draws_this_repo_with_a_current_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "trunk")
            out = subprocess.run(["python3", str(ROOT / "tools/preview.py"), "--live", "--no-color"],
                                 cwd=repo, capture_output=True, text=True, timeout=30,
                                 env={**os.environ, "COLUMNS": "200", "HOME": tmp})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("trunk", out.stdout)
        self.assertIn("% now", out.stdout)  # the week chart, so its times are current


@needs
class Installer(unittest.TestCase):
    """install.sh, against a throwaway HOME."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".claude").mkdir()

    def install(self, *args):
        out = subprocess.run(["bash", str(ROOT / "install.sh"), *args], capture_output=True, text=True,
                             env={**os.environ, "HOME": str(self.home)}, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def settings(self):
        return json.loads((self.home / ".claude" / "settings.json").read_text())

    def test_fresh_install_sets_the_status_line(self):
        self.install()
        dest = self.home / ".claude" / "claude-statusline"
        self.assertTrue((dest / "statusline.sh").exists())
        self.assertTrue(os.access(dest / "project-info", os.X_OK))
        self.assertEqual(self.settings()["statusLine"],
                         {"type": "command", "command": str(dest / "statusline.sh"), "refreshInterval": 5})

    def test_installing_again_keeps_the_interval_set_on_this_computer(self):
        self.install()
        path = self.home / ".claude" / "settings.json"
        s = self.settings()
        s["statusLine"].update(refreshInterval=10, padding=1)
        path.write_text(json.dumps(s))
        self.assertIn("already points at", self.install())
        self.assertEqual((self.settings()["statusLine"]["refreshInterval"], self.settings()["statusLine"]["padding"]), (10, 1))

    def test_replacing_someone_elses_status_line_uses_the_default_interval(self):
        path = self.home / ".claude" / "settings.json"
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": "~/bin/my-line.sh", "refreshInterval": 30}}))
        self.install()
        self.assertEqual(self.settings()["statusLine"]["refreshInterval"], 5)

    def test_keeps_everything_else_in_settings_and_backs_it_up(self):
        path = self.home / ".claude" / "settings.json"
        path.write_text(json.dumps({"model": "opus", "statusLine": {"type": "command", "command": "old.sh"},
                                    "env": {"A": "1"}}, indent=2))
        self.install()
        s = self.settings()
        self.assertEqual((s["model"], s["env"]), ("opus", {"A": "1"}))
        self.assertTrue(s["statusLine"]["command"].endswith("statusline.sh"))
        backups = list((self.home / ".claude").glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text())["statusLine"]["command"], "old.sh")

    def test_running_it_twice_changes_nothing_more(self):
        self.install()
        first = self.settings()
        self.install()
        self.assertEqual(self.settings(), first)

    def test_dry_run_writes_nothing(self):
        out = self.install("--dry-run")
        self.assertIn("would", out)
        self.assertFalse((self.home / ".claude" / "settings.json").exists())
        self.assertFalse((self.home / ".claude" / "claude-statusline").exists())

    def checkout(self):
        """A copy of the repo's installer and status line, for tests that could damage them."""
        copy = self.home / "checkout"
        shutil.copytree(ROOT / "statusline", copy / "statusline", ignore=shutil.ignore_patterns("cache", "__pycache__", "error.log"))
        shutil.copy(ROOT / "install.sh", copy)
        return copy

    def test_refuses_to_install_onto_its_own_files(self):
        # ~/.claude/claude-statusline already links to the checkout
        copy = self.checkout()
        os.symlink(copy / "statusline", self.home / ".claude" / "claude-statusline")
        for args in ([], ["--link"]):
            with self.subTest(args=args):
                out = subprocess.run(["bash", str(copy / "install.sh"), *args], capture_output=True, text=True,
                                     env={**os.environ, "HOME": str(self.home)})
                self.assertNotEqual(out.returncode, 0)
                self.assertIn("already", out.stderr)
                for f in ("statusline.py", "statusline.sh", "project-info"):
                    self.assertFalse((copy / "statusline" / f).is_symlink(), f)
                    self.assertGreater((copy / "statusline" / f).stat().st_size, 0, f)
                self.assertFalse((self.home / ".claude" / "settings.json").exists())

    def test_a_linked_settings_file_stays_linked_and_private(self):
        # settings.json kept in a dotfiles repo, readable only by its owner
        real = self.home / "dotfiles" / "settings.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"model": "opus"}))
        real.chmod(0o600)
        link = self.home / ".claude" / "settings.json"
        os.symlink(real, link)
        self.install()
        self.assertTrue(link.is_symlink())
        self.assertIn("statusLine", json.loads(real.read_text()))
        self.assertEqual(real.stat().st_mode & 0o777, 0o600)

    def test_says_which_status_line_it_replaced(self):
        path = self.home / ".claude" / "settings.json"
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": "~/bin/my-line.sh", "padding": 2}}))
        self.assertIn("~/bin/my-line.sh", self.install())

    def test_with_link_its_log_and_cache_stay_in_the_install_folder(self):
        copy = self.checkout()
        subprocess.run(["bash", str(copy / "install.sh"), "--link"], check=True, capture_output=True,
                       env={**os.environ, "HOME": str(self.home)})
        dest = self.home / ".claude" / "claude-statusline"
        out = subprocess.run(["bash", str(dest / "statusline.sh")], input="{not json", capture_output=True,
                             text=True, env={**os.environ, "HOME": str(self.home)})
        self.assertIn(str(dest / "error.log"), out.stdout)
        self.assertFalse((copy / "statusline" / "error.log").exists())
        self.assertFalse((copy / "statusline" / "cache").exists())

    def run_installer(self, *args, home=None, **env):
        return subprocess.run(["bash", str(ROOT / "install.sh"), *args], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(home or self.home), **env}, timeout=60)

    def test_a_home_with_spaces_and_accents_works_end_to_end(self):
        home = self.home / "home dir Zoë 'q'"
        (home / ".claude").mkdir(parents=True)
        self.assertEqual(self.run_installer(home=home).returncode, 0)
        command = json.loads((home / ".claude" / "settings.json").read_text())["statusLine"]["command"]
        # Claude Code runs the command through a shell
        out = subprocess.run(["sh", "-c", command], input=json.dumps({"session_id": "s1"}), capture_output=True,
                             text=True, env={**os.environ, "HOME": str(home), "COLUMNS": "120"})
        self.assertIn("ctx", visible(out.stdout), out.stderr)

    def test_claude_config_dir_is_where_it_installs(self):
        config = self.home / "elsewhere"
        self.assertEqual(self.run_installer(CLAUDE_CONFIG_DIR=str(config)).returncode, 0)
        settings = json.loads((config / "settings.json").read_text())
        self.assertEqual(settings["statusLine"]["command"], str(config / "claude-statusline" / "statusline.sh"))
        self.assertFalse((self.home / ".claude" / "settings.json").exists())

    def test_it_records_the_python_it_checked(self):
        self.install()
        recorded = (self.home / ".claude" / "claude-statusline" / "python").read_text().strip()
        self.assertEqual(recorded, shutil.which("python3"))

    def test_a_version_managers_shim_is_resolved_to_the_real_python(self):
        # pyenv, asdf and mise pick a python by the folder you're in; the
        # status line runs in every project, so it records the real one
        shims = self.home / ".pyenv" / "shims"
        shims.mkdir(parents=True)
        (shims / "python3").write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n')
        (shims / "python3").chmod(0o755)
        self.run_installer(PATH=f"{shims}{os.pathsep}{os.environ['PATH']}")
        recorded = (self.home / ".claude" / "claude-statusline" / "python").read_text().strip()
        self.assertNotIn("shims", recorded)
        self.assertTrue(os.access(recorded, os.X_OK))

    def test_uninstall_puts_back_the_status_line_you_had(self):
        path = self.home / ".claude" / "settings.json"
        mine = {"type": "command", "command": "~/bin/my-line.sh", "padding": 2}
        path.write_text(json.dumps({"model": "opus", "statusLine": mine}))
        self.install()
        out = self.install("--uninstall")
        self.assertEqual(self.settings(), {"model": "opus", "statusLine": mine})
        self.assertFalse((self.home / ".claude" / "claude-statusline").exists())
        self.assertIn("usage-sensor", out)  # says where the usage data is, and leaves it

    def test_uninstall_without_an_earlier_status_line_removes_the_setting(self):
        self.install()
        self.install("--uninstall")
        self.assertNotIn("statusLine", self.settings())

    def test_uninstall_leaves_a_status_line_you_set_since(self):
        self.install()
        path = self.home / ".claude" / "settings.json"
        path.write_text(json.dumps({"statusLine": {"type": "command", "command": "other.sh"}}))
        self.install("--uninstall")
        self.assertEqual(self.settings()["statusLine"]["command"], "other.sh")

    def test_runs_when_started_with_sh(self):
        out = subprocess.run(["sh", str(ROOT / "install.sh"), "--dry-run"], capture_output=True, text=True,
                             env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_refuses_settings_it_cannot_parse(self):
        path = self.home / ".claude" / "settings.json"
        path.write_text("{ broken")
        out = subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True,
                             env={**os.environ, "HOME": str(self.home)})
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(path.read_text(), "{ broken")


if __name__ == "__main__":
    unittest.main()
