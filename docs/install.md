# Installing

## With the installer

```sh
./install.sh                 # copy the files and set statusLine
./install.sh --dry-run       # say what would change, change nothing
./install.sh --link          # symlink instead, so a git pull here updates your install
./install.sh --no-settings   # copy the files only; set statusLine yourself
./install.sh --uninstall     # remove it, and put back the statusLine you had
```

It installs into Claude Code's config folder: `~/.claude`, or `CLAUDE_CONFIG_DIR` if you've set it. Set `CLAUDE_STATUSLINE_DEST` to put the files somewhere else.

It copies `statusline.sh`, `statusline.py` and the `project-info` helper to `claude-statusline/` in that folder. It notes which `python3` it checked, and the status line always runs that one. If `python3` is a pyenv, asdf or mise shim, it notes the real interpreter instead, because a shim would pick each project's pinned version. If you remove that Python later, run the installer again.

Then it sets `statusLine` in `settings.json`, after saving a copy of that file next to it with the date in its name. Every other setting is kept. If you already had a `statusLine`, it's replaced, and the installer prints it and keeps it for `--uninstall` to put back. A `settings.json` that's a link, say into a dotfiles repo, stays a link, and keeps its permissions. Running it again changes nothing more. If `settings.json` isn't valid JSON, it stops without touching it.

## When it doesn't appear

- Run `/status` in Claude Code. Its `Setting sources` line names any managed settings from your organization, and those override your own `statusLine`.
- `"disableAllHooks": true` in your settings turns off status lines too.
- If the line says `statusline: couldn't run ...`, the Python the installer noted is gone. Run the installer again.

## Upgrading

`git pull`, then run `./install.sh` again. With `--link`, the `git pull` alone is enough.

## By hand

Copy `statusline/` anywhere and add this to `~/.claude/settings.json`:

```json
"statusLine": {
  "type": "command",
  "command": "/path/to/statusline/statusline.sh",
  "refreshInterval": 5
}
```

Claude Code runs the command through a shell, so put quotes around a path with spaces in it.

Claude Code runs the status line itself whenever the conversation changes, such as after a reply or a `/model` switch. `refreshInterval: 5` adds a run every 5 seconds for what changes on its own: git, CPU and memory, and the ship column. Most runs reprint the last drawing without starting Python. It draws afresh when Claude Code sends something new or the width changes, and otherwise once the drawing is 10 seconds old. The [side pane](pane.md), if you turn it on, runs Python itself, once every 10 seconds while it's on screen.

Running `install.sh` again keeps the `refreshInterval` you set, so each computer can have its own.

## Removing it

```sh
./install.sh --uninstall
```

It puts back the `statusLine` you had before installing, or removes the setting if you had none. If you've changed `statusLine` since, it leaves yours alone. Then it deletes the install folder.

It leaves these for you to remove if you want:

- your usage files and week log, in `~/.claude/usage-sensor/`
- the `settings.json.bak-*` copies the installer saved
- in each repo you set up for the ship column: `.git/project-info.json`, its `.lock` file and `project-info.locks/` folder beside it, and the `make info` target and hooks you added
