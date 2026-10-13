"""The docs, checked as if a reader followed them: every shell command in a
```sh block is run, or listed below with the reason it isn't, and the
examples people copy (JSON, the usage hook, the project-info file) work.

A new command in the docs fails here until it's added to COMMANDS."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from support import ROOT, SCENARIOS, sl, visible
from test_hygiene import files
from test_live import git


# Each documented command, as written minus its comment, and how it's checked:
# ("run", where), ("watch", where) for one that keeps redrawing, or
# ("skip", why). `where` is "repo" (this checkout) or
# "scratch" (a throwaway git repo). Every run gets an empty home folder.
COMMANDS = {
    # README.md
    "git clone https://github.com/drewkhouryorg/claude-statusline.git": ("skip", "needs the network"),
    "cd claude-statusline": ("skip", "moves into the clone"),
    "./install.sh": ("run", "repo"),
    "python3 tools/preview.py": ("run", "repo"),
    "python3 tools/preview.py bad-day": ("run", "repo"),
    "python3 tools/preview.py healthy -w 80,120,200": ("run", "repo"),
    "python3 tools/preview.py --all": ("run", "repo"),
    "python3 tools/preview.py --live --watch": ("watch", "repo"),
    # docs/install.md
    "./install.sh --dry-run": ("run", "repo"),
    "./install.sh --link": ("run", "repo"),
    "./install.sh --no-settings": ("run", "repo"),
    "./install.sh --uninstall": ("run", "repo"),
    # docs/testing.md
    "make test": ("skip", "this is the suite that is running"),
    "make test-linux": ("skip", "needs Docker; run it by hand before a release"),
    "UPDATE_SNAPSHOTS=1 make test": ("skip", "rewrites the snapshots"),
    "git diff tests/snapshots": ("skip", "shows your own changes; nothing to check"),
    "make screenshots": ("skip", "needs pillow and fonttools, and rewrites docs/images"),
    # docs/project-info.md
    "project-info set deploy prod '{\"version\": \"v1.43\", \"status\": \"ok\", \"deployed_at\": 1759400000}'":
        ("run", "scratch"),
    "project-info get deploy prod": ("run", "scratch"),
    "project-info fresh prs 120": ("skip", "exits 1 by design when the section is missing"),
    "project-info refresh prs 120 -- gh pr list --json number --jq '{open: length}'":
        ("skip", "needs gh logged in; ShipColumnSetup runs refresh against recorded gh output"),
}

FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)
COMMENT = re.compile(r"\s+#\s.*$")


def docs():
    return [(path, rel) for path, rel in files() if path.suffix == ".md" and "snapshots" not in rel.parts]


def blocks(lang):
    """(file, block text) for every fenced block in `lang` across the docs."""
    return [(rel, text) for path, rel in docs() for kind, text in FENCE.findall(path.read_text()) if kind == lang]


def documented_commands():
    return {" ".join(COMMENT.sub("", line).split()): rel
            for rel, text in blocks("sh") for line in text.splitlines() if line.strip()}


def run_env(home):
    return {**os.environ, "HOME": home, "COLUMNS": "120",
            "PATH": f"{ROOT / 'statusline'}{os.pathsep}{os.environ['PATH']}"}


class DocumentedCommands(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.scratch = Path(tmp.name) / "scratch"
        self.scratch.mkdir()
        git(self.scratch, "init", "-q")
        self.where = {"repo": ROOT, "scratch": self.scratch}

    def test_every_command_is_run_or_says_why_not(self):
        found = documented_commands()
        self.assertEqual(sorted(set(found) - set(COMMANDS)), [], "new commands in the docs: add them to COMMANDS")
        self.assertEqual(sorted(set(COMMANDS) - set(found)), [], "COMMANDS lists commands the docs no longer have")

    def test_commands_run_without_errors(self):
        for command, (how, where) in COMMANDS.items():
            if how != "run":
                continue
            with self.subTest(command=command):
                out = subprocess.run(["bash", "-c", command], cwd=self.where[where], env=run_env(self.home),
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr[-2000:])
                self.assertNotIn("Traceback", out.stdout + out.stderr)
                self.assertNotIn("statusline error", out.stdout)

    def test_watching_commands_keep_redrawing(self):
        for command, (how, where) in COMMANDS.items():
            if how != "watch":
                continue
            with self.subTest(command=command):
                stdout, stderr = Path(self.home) / "out", Path(self.home) / "err"
                with open(stdout, "w") as o, open(stderr, "w") as e:
                    proc = subprocess.Popen(["bash", "-c", f"exec {command}"], cwd=self.where[where],
                                            env=run_env(self.home), stdout=o, stderr=e)
                # the first draw and one redraw, however slow the machine
                redraws = lambda: stdout.read_text().count("redrawn every 2s")
                deadline = time.time() + 15
                while redraws() < 2 and proc.poll() is None and time.time() < deadline:
                    time.sleep(0.2)
                still_running = proc.poll() is None
                proc.terminate()
                proc.wait(timeout=10)
                self.assertTrue(still_running, stderr.read_text()[-2000:])
                self.assertGreaterEqual(redraws(), 2)
                self.assertNotIn("statusline error", stdout.read_text())


class DocumentedExamples(unittest.TestCase):
    def test_json_examples_parse(self):
        for rel, text in blocks("json"):
            with self.subTest(doc=str(rel), start=text[:40]):
                # some show a piece of settings.json: a key and its value
                json.loads(text if text.lstrip().startswith("{") else "{" + text + "}")

    def test_the_project_info_example_draws_every_part(self):
        example = next(json.loads(t) for rel, t in blocks("json") if rel.name == "project-info.md" and '"schema"' in t)
        inp = dict(json.loads((SCENARIOS / "1-healthy.json").read_text()), project=example)
        out = visible(sl.render(inp, 240))
        for part in ("✓✓✓✗✓", "v1.42", "3 behind", "stg", "#126", "migration pending"):
            self.assertIn(part, out)

    def test_the_system_reading_example_has_the_shapes_the_renderer_draws(self):
        example = ast.literal_eval(next(t for rel, t in blocks("python") if rel.name == "platforms.md"))
        inp = dict(json.loads((SCENARIOS / "1-healthy.json").read_text()), system=example)
        out = visible(sl.render(inp, 240))
        # a charged battery and the busiest process only show when they matter
        for part in ("cpu ▮▮▮▯▯▯▯▯ 41%", "mem ▮▮▮▮▮▯▯▯ 58%", "comp 4.4G"):
            self.assertIn(part, out)


HEADING = re.compile(r"^#+ (.+)$", re.M)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def anchor(heading):
    """GitHub's id for a heading: lower case, punctuation dropped, spaces to dashes."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


class Links(unittest.TestCase):
    def test_every_link_and_anchor_in_the_docs_resolves(self):
        for path, rel in docs():
            text = FENCE.sub("", path.read_text())
            for target in LINK.findall(text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                file, _, frag = target.partition("#")
                dest = (path.parent / file).resolve() if file else path
                with self.subTest(doc=str(rel), link=target):
                    self.assertTrue(dest.exists(), f"{dest} doesn't exist")
                    if frag:
                        self.assertIn(frag, {anchor(h) for h in HEADING.findall(FENCE.sub("", dest.read_text()))})


GH_DATA = ROOT / "tests/data/gh"

# Stands in for the gh CLI: logs each call, then answers with output recorded
# from real gh (tests/data/gh), put through the call's own --jq filter. So the
# Makefile's filters run against what GitHub really sends.
# GH_MODE=nopr: the branch has no PR. GH_MODE=fail: GitHub can't be reached.
# GH_DELAY: seconds each call takes.
FAKE_GH = r"""#!/bin/bash
call="$1 $2"; for a in "$@"; do [[ $a == --head ]] && call="$call --head"; done
echo "$call" >> "$GH_LOG"
sleep "${GH_DELAY:-0}"
[[ $GH_MODE == fail ]] && { echo "error connecting to api.github.com" >&2; exit 1; }
case "$call" in
  "pr list --head") file=pr-list-head.json; [[ $GH_MODE == nopr ]] && file=pr-list-head-none.json ;;
  "pr list") file=pr-list.json ;;
  "run list") file=run-list.json ;;
  *) echo "fake gh: no recording for $call" >&2; exit 1 ;;
esac
jq=.; while [[ $# -gt 0 ]]; do [[ $1 == --jq ]] && jq=$2; shift; done
jq -c "$jq" "$GH_DATA/$file"
"""


@unittest.skipUnless(shutil.which("make") and shutil.which("git") and shutil.which("jq"), "needs make, git and jq")
class ShipColumnSetup(unittest.TestCase):
    """docs/ship-column.md's Makefile and hooks, in a throwaway repo, with a
    fake gh that counts what would have gone to GitHub."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home dir Zoë"  # spaces and accents, as some people's are
        helper = self.home / ".claude/claude-statusline"
        helper.mkdir(parents=True)
        shutil.copy(ROOT / "statusline/project-info", helper)
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin/gh").write_text(FAKE_GH)
        (self.tmp / "bin/gh").chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "feat/cart")
        page = (ROOT / "docs/ship-column.md").read_text()
        (self.repo / "Makefile").write_text(next(t for kind, t in FENCE.findall(page) if kind == "make"))
        self.hooks = json.loads(next(t for kind, t in FENCE.findall(page) if kind == "json"))["hooks"]
        self.log = self.tmp / "gh.log"

    def env(self, mode="ok", delay=0, data=GH_DATA, **extra):
        return {**os.environ, "HOME": str(self.home), "GH_LOG": str(self.log), "GH_MODE": mode,
                "GH_DELAY": str(delay), "GH_DATA": str(data),
                "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}", **extra}

    def make_info(self, mode="ok", *args, data=GH_DATA):
        self.log.write_text("")
        out = subprocess.run(["make", "-s", "info", *args], cwd=self.repo, env=self.env(mode, data=data),
                             capture_output=True, text=True, timeout=60)
        return out, sorted(self.log.read_text().splitlines())

    def published(self):
        return json.loads((self.repo / ".git/project-info.json").read_text())

    def test_first_run_publishes_what_github_says(self):
        out, calls = self.make_info()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(calls, ["pr list", "pr list --head", "run list"])
        info = self.published()
        self.assertEqual((info["prs"]["open"], info["prs"]["needs_review"]), (6, 5))
        # newest last; the second newest run was still going when recorded
        self.assertEqual(info["ci"]["main"]["runs"], ["ok", "ok", "ok", "running", "ok"])

    def items(self):
        return [{"number": i["number"], "checks": i["checks"]} for i in self.published()["prs"]["items"]]

    def test_each_open_pr_shows_its_checks_as_gh_pr_checks_sees_them(self):
        # pr-list-expected.json holds what `gh pr checks` said about each recorded PR
        for data in (GH_DATA, GH_DATA / "handmade"):
            with self.subTest(data=data.name):
                self.make_info("ok", "FORCE=1", data=data)
                self.assertEqual(self.items(), json.loads((data / "pr-list-expected.json").read_text()))

    def test_drafts_and_prs_waiting_for_review_are_marked(self):
        self.make_info(data=GH_DATA / "handmade")
        prs = self.published()["prs"]
        self.assertEqual(prs["needs_review"], 2)
        self.assertEqual([i["number"] for i in prs["items"] if i.get("draft")], [101])

    def test_this_branchs_checks_count_as_gh_pr_checks_counts_them(self):
        # pr-checks-expected.json is what `gh pr checks` said about the same PR
        for data in (GH_DATA, GH_DATA / "handmade"):
            with self.subTest(data=data.name):
                self.make_info("ok", "FORCE=1", data=data)
                expected = json.loads((data / "pr-checks-expected.json").read_text())
                self.assertEqual(self.published()["branches"]["feat/cart"]["checks"], expected)

    def test_every_kind_of_ci_run_is_named(self):
        self.make_info(data=GH_DATA / "handmade")
        self.assertEqual(self.published()["ci"]["main"]["runs"], ["ok", "running", "cancelled", "fail", "running"])

    def test_the_published_file_draws_the_pr_row(self):
        # six open PRs: more than four collapse to counts per state
        self.make_info(data=GH_DATA / "handmade")
        inp = dict(json.loads((ROOT / "scenarios/1-healthy.json").read_text()), project=self.published(),
                   now=time.time())
        self.assertIn("PRs   6 open ✓1 ⟳1 ✗2 · 2 need review", visible(sl.render(inp, 240)))

    def test_a_second_run_while_fresh_asks_github_nothing(self):
        self.make_info()
        _, calls = self.make_info()
        self.assertEqual(calls, [])

    def test_a_branch_without_a_pr_is_asked_about_once(self):
        self.make_info("nopr")
        self.assertNotIn("checks", self.published()["branches"]["feat/cart"])
        _, calls = self.make_info("nopr")
        self.assertEqual(calls, [])

    def test_when_github_fails_each_section_saves_the_error_and_waits(self):
        out, calls = self.make_info("fail")
        self.assertEqual(calls, ["pr list", "pr list --head", "run list"])  # one failure stops nothing
        info = self.published()
        for section in (info["prs"], info["ci"]["main"], info["branches"]["feat/cart"]):
            self.assertEqual(section["error"], "error connecting to api.github.com")
        _, calls = self.make_info("fail")
        self.assertEqual(calls, [])  # no retry until the window has passed

    def test_force_refreshes_everything_now(self):
        self.make_info()
        _, calls = self.make_info("ok", "FORCE=1")
        self.assertEqual(calls, ["pr list", "pr list --head", "run list"])

    def test_sessions_ending_turns_together_ask_github_once(self):
        self.log.write_text("")
        procs = [subprocess.Popen(["make", "-s", "info"], cwd=self.repo, env=self.env(delay=1),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(3)]
        for proc in procs:
            proc.wait(timeout=60)
        self.assertEqual(sorted(self.log.read_text().splitlines()), ["pr list", "pr list --head", "run list"])

    def run_hook(self, hook):
        """Run a hook's command as Claude Code would: from elsewhere, with the project dir set."""
        self.log.write_text("")
        out = subprocess.run(["bash", "-c", hook["command"]], cwd=self.tmp, timeout=60,
                             env=self.env(CLAUDE_PROJECT_DIR=str(self.repo)))
        self.assertEqual(out.returncode, 0)
        return sorted(self.log.read_text().splitlines())

    def test_claude_config_dir_finds_the_helper_there(self):
        config = self.tmp / "config"
        shutil.copytree(self.home / ".claude", config)
        shutil.rmtree(self.home / ".claude")
        self.log.write_text("")
        out = subprocess.run(["make", "-s", "info"], cwd=self.repo, capture_output=True, text=True, timeout=60,
                             env=self.env(CLAUDE_CONFIG_DIR=str(config)))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("prs", self.published())

    def test_session_and_turn_hooks_refresh_in_the_background(self):
        for event in ("SessionStart", "Stop"):
            hook = self.hooks[event][0]["hooks"][0]
            with self.subTest(event=event):
                self.assertTrue(hook["async"])
                self.run_hook(hook)
                self.assertIn("prs", self.published())

    def test_shipping_hooks_refresh_even_when_fresh(self):
        self.make_info()
        entry = self.hooks["PostToolUse"][0]
        self.assertEqual(entry["matcher"], "Bash")
        self.assertEqual([h["if"] for h in entry["hooks"]],
                         ["Bash(git push *)", "Bash(gh pr create *)", "Bash(gh pr merge *)"])
        for hook in entry["hooks"]:
            with self.subTest(hook=hook["if"]):
                self.assertTrue(hook["async"])
                self.assertEqual(self.run_hook(hook), ["pr list", "pr list --head", "run list"])


class UsageHookExample(unittest.TestCase):
    """The PreToolUse hook in docs/usage-files.md, run as Claude Code would."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.hook = self.home / "hook.py"
        self.hook.write_text(next(t for rel, t in blocks("python") if rel.name == "usage-files.md"))
        (self.home / ".claude/usage-sensor").mkdir(parents=True)

    def call(self, five=None, week=None):
        if five is not None or week is not None:
            soon = int(time.time()) + 3600
            reading = {"five_hour": {"used_percentage": five or 0, "resets_at": soon},
                       "seven_day": {"used_percentage": week or 0, "resets_at": soon}}
            (self.home / ".claude/usage-sensor/s1.json").write_text(json.dumps(reading))
        return subprocess.run([sys.executable, str(self.hook)], input=json.dumps({"session_id": "s1"}),
                              capture_output=True, text=True, env={**os.environ, "HOME": str(self.home)})

    def test_blocks_once_a_window_passes_95(self):
        out = self.call(five=96)
        self.assertEqual(out.returncode, 2)
        self.assertIn("five_hour limit at 96%", out.stderr)

    def test_lets_tools_run_below_95(self):
        self.assertEqual(self.call(five=60, week=94).returncode, 0)

    def test_never_blocks_without_a_reading(self):
        self.assertEqual(self.call().returncode, 0)


if __name__ == "__main__":
    unittest.main()
