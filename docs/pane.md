# The side pane

The side pane draws the status line's parts in a pane of their own, with more room than one line under the prompt. It's a Claude Code mod in [`pane/`](../pane). The installer sets it up, and it stays closed until you open it.

Where it appears:

- **In a fullscreen terminal** (Claude Code's default), beside the transcript, once the terminal is 144 columns wide. From 34 columns across, it spells each part out with bigger tanks, the week chart across the pane, and labels that say what each number is. Narrower than that, it stacks the status line's own parts.
- **In a terminal that isn't fullscreen**, such as tmux, above the prompt, showing the status line itself.
- **In the Claude desktop app's Code tab, and the mobile app**, as a card for each part, with the tanks and the week drawn as charts.

## Opening it

`./install.sh` puts the pane in `~/.claude/claude-statusline/pane`, beside the status line it runs, and adds that folder to `CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json`. Every Claude Code session you start after that has it, in the terminal and in the desktop app's Code tab.

Type `/statusline-pane` to open it, and close it with its close mark, as any pane. To open it in every new session, turn on "Open the status pane by itself" in `/config`.

Mods are an early-access part of Claude Code, so the pane depends on the version you run. It's tested with 2.1.295, the version the desktop app ships with today, and with 2.1.299.

## What it costs

While the pane is on screen, it runs the installed `statusline.py` once every 10 seconds, about 50 ms of CPU each time, in each session that shows it. A closed pane, one waiting for a wider terminal, and a `claude -p` run cost nothing.

It reads git and the machine through the status line's own cache, so those reads still happen at most once every 10 seconds for each folder, however many sessions ask. They're the reads in [what it runs in your repo](../README.md#what-it-runs-in-your-repo). The desktop app runs no status line, so in its sessions the pane is the only thing that runs them.

The pane doesn't write the [usage files](usage-files.md). The status line Claude Code runs writes those.

## What it can't show

Claude Code tells a mod less than it tells the status line. The pane has no way to know a session's name, its effort level, the lines added and removed, the PR Claude Code found for the branch, or whether the prompt cache is cold, so it leaves those out.

Before a session's first reply, the context tank shows Claude Code's own estimate of what the conversation holds. The 5-hour and weekly tanks fill once Claude Code has a reading for them, which needs a Claude Pro or Max plan, as for the status line.

## Upgrading and turning it off

To upgrade, `git pull` and run `./install.sh` again: the pane and the status line it runs come from the same install, so they stay the same version. A pane from an older install, before the pane had its own layouts, shows the status line's strip and says to run `./install.sh` again.

`./install.sh --uninstall` removes the pane with the status line. To keep the status line and stop loading the pane, take its folder out of `CLAUDE_CODE_PLUGIN_DIRS`; running `./install.sh` again puts it back.

## Working on it

`./install.sh --link` links the pane to your checkout, so sessions pick up an edit as you save it. They also run whatever branch the checkout is on, so link only a checkout whose code you trust.

The pane's tests run under Claude Code itself, so `make test` doesn't include them:

```sh
claude plugin test pane    # with each Claude Code you use, the desktop app's copy too
make pane-fixture          # after changing what statusline.py --json prints
```

The pane reads `statusline.py --json`: the same parts as data, the colour judgements the terminal makes as names, and the terminal drawing beside them. Its shape is written down in [`pane/types/index.d.ts`](../pane/types/index.d.ts). `make test` fails when the pane's test fixture no longer matches what `--json` prints, and `make pane-fixture` rewrites it.
