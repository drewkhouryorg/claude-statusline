# Installing

## With the installer

```sh
./install.sh                 # copy the files and set up settings.json
./install.sh --dry-run       # say what would change, change nothing
./install.sh --link          # symlink instead, so a git pull here updates your install
./install.sh --no-settings   # copy the files only; change no settings
./install.sh --uninstall     # remove it, and put back the statusLine you had
```

It installs into Claude Code's config folder: `~/.claude`, or `CLAUDE_CONFIG_DIR` if you've set it. Set `CLAUDE_STATUSLINE_DEST` to put the files somewhere else.

It copies `statusline.sh`, `statusline.py`, the `project-info` helper and the side pane (`pane/`) to `claude-statusline/` in that folder. It notes which `python3` it checked, and the status line always runs that one. If `python3` is a pyenv, asdf or mise shim, it notes the real interpreter instead, because a shim would pick each project's pinned version. If you remove that Python later, run the installer again.

Then it saves a copy of `settings.json` next to it, with the date in its name, and changes two things. It sets `statusLine`, and adds the side pane's folder to `CLAUDE_CODE_PLUGIN_DIRS` in `env`, after any folders already there. Every other setting is kept. If you already had a `statusLine`, it's replaced, and kept for `--uninstall` to put back.

It also writes `installed.json` beside the files, recording the version, the commit, and whether the checkout had uncommitted changes. The status line shows the version from it, and the next run reads it to say what it's upgrading from.

Claude Code uses the `CLAUDE_CODE_PLUGIN_DIRS` in `settings.json` in place of one exported from your shell. If your shell sets it, the installer says so: add those folders to the setting to keep them. If your organization's managed settings turn plugin folders off (`disableSideloadFlags`), Claude Code won't start with that setting at all, so the installer leaves the side pane out.

If the install folder is already there with neither that file nor this project's `statusline.py` in it, it belongs to something else. The installer stops without changing anything, and `CLAUDE_STATUSLINE_DEST` can point it somewhere else.

A `settings.json` that's a link, say into a dotfiles repo, stays a link, and keeps its permissions. Running it again changes nothing more. If `settings.json` isn't valid JSON, it stops without touching it.

## When it doesn't appear

- Run `/status` in Claude Code. Its `Setting sources` line names any managed settings from your organization, and those override your own `statusLine`.
- `"disableAllHooks": true` in your settings turns off status lines too.
- If the line says `statusline: couldn't run ...`, the Python the installer noted is gone. Run the installer again.

## Upgrading

`git pull`, then run `./install.sh` again. Its first line says what changes, such as `Upgrading ~/.claude/claude-statusline from v0.1.0 to v0.2.0`. With `--link`, the `git pull` alone is enough.

## Versions

`VERSION` holds the version number, and each release is a git tag of it, such as `v0.1.0`. The side pane is released with the status line, under the same number in `pane/.claude-plugin/plugin.json`.

An install from a release's commit shows `v0.1.0`. From any other commit it shows `v0.1.0+<commit>`, with `*` after it when `statusline/` or `pane/` had uncommitted changes. A download without git, such as GitHub's ZIP, knows its commit from `.git_archival.txt`, which `git archive` fills in; with no way to tell, it shows `v0.1.0+?`. A `--link` install shows the commit the checkout is on now.

To release, change the number in both files, commit, and tag that commit `v<number>`.

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

For the [side pane](pane.md), add the `pane/` folder too:

```json
"env": {
  "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/pane"
}
```

If that variable already lists folders, join them with a `:`. The pane looks for the status line in the folder above its own first, so keep `pane/` beside `statusline.py`.

Claude Code runs the status line itself whenever the conversation changes, such as after a reply or a `/model` switch. `refreshInterval: 5` adds a run every 5 seconds for what changes on its own: git, CPU and memory, and the ship column. Most runs reprint the last drawing without starting Python. It draws afresh when Claude Code sends something new or the width changes, and otherwise once the drawing is 10 seconds old. The [side pane](pane.md) runs Python itself, once every 10 seconds while it's open on screen.

Running `install.sh` again keeps the `refreshInterval` you set, so each computer can have its own.

## Removing it

```sh
./install.sh --uninstall
```

It puts back the `statusLine` you had before installing, or removes the setting if you had none. If you've changed `statusLine` since, it leaves yours alone. It takes the side pane out of `CLAUDE_CODE_PLUGIN_DIRS`, and then deletes the files it installed. The folder goes too, unless something else has put files in it.

It leaves these for you to remove if you want:

- your usage files and week log, in `~/.claude/usage-sensor/`
- the `settings.json.bak-*` copies the installer saved
- in each repo you set up for the ship column: `.git/project-info.json`, its `.lock` file and `project-info.locks/` folder beside it, and the `make info` target and hooks you added
