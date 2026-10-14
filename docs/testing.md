# Testing

```sh
make test          # everything but the side pane's own tests, about 35 seconds
make test-linux    # the same in Linux containers (needs Docker)
make test-bash     # the same under bash 3.2, 4.4 and 5.2 (needs Docker)
```

`make test` is `python3 -m unittest discover -s tests`. It needs only Python, git and bash. A few tests skip themselves when what they need isn't there, and the skip says why.

The [side pane](pane.md) is a Claude Code mod, and its tests run under Claude Code itself: `claude plugin test pane`. They aren't in `make test` or CI, which have no Claude Code to run them. `make test` does check that the pane's test fixture matches what `statusline.py --json` prints, so a change to that shape fails here first.

## What runs

| File | What it checks | Real or simulated |
| - | - | - |
| `test_statusline.py` | Rendering and each reading: tanks, pace, the week chart and forecast, columns, ship rows, git status parsing, CPU and memory, the cleaning of `project-info.json`, settings. | Pure functions fed plain values. The macOS kernel calls run for real on a Mac. |
| `test_view.py` | `statusline.py --json`: each part as data, carrying the same numbers and colour judgements the terminal draws, and the pane's fixture kept in step with it. | The scenarios, fed to the view. |
| `test_scenarios.py` | Every scenario at seven widths against recorded snapshots. No line is ever wider than the terminal, from 30 to 260 columns. Columns line up. Junk in any field of `project-info.json`, or odd values from Claude Code (missing fields, a window that has just reset, percentages past 100, escape codes in a session name), never breaks the line, widens it or passes escape codes through. | The scenarios are made-up sessions. The junk and odd values are seeded random changes, 400 to `project-info.json`, and 40 per scenario plus 400 of the wrong type to Claude Code's input, the same on every run. |
| `test_linux.py` | The Linux readers. | `/proc` files recorded from a Linux VM, plus hand-made ones for a machine under pressure (see `tests/data/linux/README.md`). On Linux, it also reads the real machine. |
| `test_live.py` | The real `statusline.sh` and `install.sh`, run as Claude Code would. | A throwaway git repo, home folder and install folder. Real git, bash and Python. Your own `~/.claude` is never touched. |
| `test_docs.py` | Every command in the docs' `sh` blocks runs without an error, or is listed with the reason it doesn't run here. The JSON examples parse, the `project-info.json` example draws every part, and the usage hook example blocks at 95%. Every link and `#anchor` resolves. The ship column's Makefile and hooks publish what GitHub says, ask GitHub nothing while fresh, keep going and wait after a failure, and ask once when several sessions run at once. | Real commands in this checkout, with an empty home folder. A new command in the docs fails the test until it's listed. The ship column tests use a fake `gh` that replays output recorded from real `gh` (`tests/data/gh/`) through the Makefile's own `--jq` filters, so they need `jq`. |
| `test_hygiene.py` | No real home folders, and none of your private words, in anything git would publish. | Runs on the repo itself. |

## Snapshots

`tests/snapshots/` holds what each scenario looks like at 60, 80, 100, 120, 160, 200 and 240 columns. Each scenario has two files:

- `<name>.txt` is the plain text, easy to read in a diff.
- `<name>.ansi` has the colours too. `cat` it in a terminal to see it.

When you change how something looks, the snapshot test fails and shows the difference. If the change is what you meant, record new snapshots and read the diff before you commit:

```sh
UPDATE_SNAPSHOTS=1 make test
git diff tests/snapshots
```

Clock times in snapshots are in UTC, and the scenarios' days start at 7am, so they match on every machine.

## Your private words

`test_hygiene.py` stops your own details from slipping into the repo. List words that must never appear in it, one per line, in `.private-words` at the repo root: your name, private project names, internal hostnames. Matching is by whole word and ignores case. The file is gitignored, so the list itself is never published. Without it, that check skips.

## Linux

`make test-linux` runs the whole suite in two containers: Python 3.8 on Alpine (BusyBox) and Python 3.13 on Debian (GNU coreutils). That covers the oldest supported Python and both kinds of `stat`, which the wrapper uses. CI runs the suite on macOS and Ubuntu (see `.github/workflows/test.yml`).

## Bash versions

`make test-bash` runs the whole suite under bash 3.2, 4.4 and 5.2, using the official `bash` images. macOS still ships 3.2 as `/bin/bash`, and it can be far slower than newer versions: one find and replace in the wrapper once took half a second a call there, and a few milliseconds in 5.2. CI runs all three on every push.

## Screenshots

The docs' pictures are drawn from the scenarios:

```sh
make screenshots   # needs pillow and fonttools; the Makefile runs them through uv
```
