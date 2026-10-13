"""Checks on the repo itself, before anything is published.

Personal words: list any words that must never appear (your name, private
project names) one per line in .private-words at the repo root. It's
gitignored, so the list itself is never published; without it, that check
skips."""
import re
import subprocess
import unittest

from support import ROOT

SKIP_DIRS = {".git", "__pycache__", "node_modules", "cache"}
TEXT = {".py", ".sh", ".md", ".json", ".txt", ".ansi", ".ts", ".tsx", ".yml", ".yaml", ".toml", ""}
# home folders the scenarios and docs may use; a real one is a leak
HOME_PATH = re.compile(r"/(?:Users|home)/(?!dev\b|runner\b|you\b|me\b)[A-Za-z0-9_.-]+")


def files():
    """Every text file git would publish: tracked, or new and not ignored.
    Outside a git checkout (a downloaded copy), every file."""
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, text=True)
    paths = ([ROOT / line for line in listed.stdout.splitlines()] if listed.returncode == 0
             else [p for p in ROOT.rglob("*") if not SKIP_DIRS & set(p.relative_to(ROOT).parts)])
    for path in sorted(paths):
        if path.is_file() and path.suffix in TEXT and path.name not in (".private-words", ".DS_Store"):
            yield path, path.relative_to(ROOT)


class Hygiene(unittest.TestCase):
    def test_no_real_home_folders(self):
        for path, rel in files():
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                with self.subTest(file=str(rel), line=n):
                    self.assertIsNone(HOME_PATH.search(line), line.strip()[:120])

    def test_no_private_words(self):
        listed = ROOT / ".private-words"
        if not listed.exists():
            self.skipTest("no .private-words file")
        words = [w.strip() for w in listed.read_text().splitlines() if w.strip() and not w.startswith("#")]
        pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", re.I)
        for path, rel in files():
            found = pattern.findall(path.read_text(errors="replace")) + pattern.findall(str(rel))
            with self.subTest(file=str(rel)):
                self.assertEqual(found, [])

    def test_private_words_stay_unpublished(self):
        self.assertIn(".private-words", (ROOT / ".gitignore").read_text().split())


if __name__ == "__main__":
    unittest.main()
