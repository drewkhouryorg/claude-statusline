#!/usr/bin/env bash
# Install the status line and point Claude Code at it.
#
#   ./install.sh              copy the files and set "statusLine" in settings.json
#   ./install.sh --link       symlink instead of copy, so a `git pull` here updates it
#   ./install.sh --dry-run    say what would change, change nothing
#   ./install.sh --no-settings   copy the files only; set statusLine yourself
#   ./install.sh --uninstall  remove it, and put back the statusLine you had before
#
# It installs into Claude Code's config folder: $CLAUDE_CONFIG_DIR, or
# ~/.claude, with the side pane mod beside it in pane/ (turned on by hand:
# see docs/pane.md). settings.json is backed up before it changes, and every
# other setting in it is kept. Running this again is safe.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi  # started with sh
set -euo pipefail

CONFIG=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=$REPO/statusline
DEST=${CLAUDE_STATUSLINE_DEST:-$CONFIG/claude-statusline}
SETTINGS=$CONFIG/settings.json
FILES=(statusline.py statusline.sh project-info)
action=install mode=copy settings=yes dry=no

for arg in "$@"; do
  case $arg in
    --link) mode=link ;;
    --dry-run) dry=yes ;;
    --no-settings) settings=no ;;
    --uninstall) action=uninstall ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is needed (3.8 or later)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || { echo "python3 is too old: 3.8 or later" >&2; exit 1; }

# The status line runs in every project. A version manager's shim (pyenv,
# asdf, mise) would pick each project's pinned python, so record the real one.
PYTHON=$(command -v python3)
case $PYTHON in */shims/*) PYTHON=$(python3 -c 'import sys; print(sys.executable)') ;; esac

say() { if [[ $dry == yes ]]; then echo "would $*"; else echo "$*"; fi; }

# an install folder that is (a link to) this checkout's own folder would
# have its files deleted or linked to themselves
if [[ -d $DEST && $(cd "$DEST" && pwd -P) == $(cd "$SRC" && pwd -P) ]]; then
  echo "$DEST already is $SRC (through a link). Remove the link $DEST and run this again." >&2
  exit 1
fi

settings_step() {  # check | write | uninstall
  python3 - "$1" "$SETTINGS" "$DEST" "$dry" <<'PY'
import json, os, shlex, shutil, stat, sys, time
from pathlib import Path

step, path, dest, dry = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4] == "yes"
script = str(dest / "statusline.sh")
# Claude Code runs the command through a shell: quote a path with spaces
want = {"type": "command", "command": shlex.quote(script), "refreshInterval": 5}
ours = (want["command"], script)
previous = dest / "previous-statusline.json"
try:
    current = json.loads(path.read_text()) if path.exists() else {}
except ValueError as e:
    sys.exit(f"{path} isn't valid JSON ({e}); fix it, or rerun with --no-settings")
if not isinstance(current, dict):
    sys.exit(f"{path} isn't a JSON object; fix it, or rerun with --no-settings")
if step == "check":
    sys.exit(0)

old = current.get("statusLine")
mine = isinstance(old, dict) and old.get("command") in ours
if step == "write":
    if mine:  # installing again keeps the interval or padding you set on this computer
        want = {**old, "type": "command", "command": want["command"]}
    if old == want:
        print(f"{path} already points at {script}")
        sys.exit(0)
    if old and not mine:
        print(f"{'would replace' if dry else 'replacing'} your statusLine: {json.dumps(old)}")
        if not dry:  # for --uninstall to put back
            previous.write_text(json.dumps(old, indent=2) + "\n")
    current["statusLine"] = want
else:  # uninstall
    if not mine:
        print(f"your statusLine in {path} isn't this one; left as it is" if old else
              f"{path} has no statusLine from this install; left as it is")
        sys.exit(0)
    if previous.exists():
        current["statusLine"] = json.loads(previous.read_text())
        print(f"{'would put' if dry else 'put'} back your earlier statusLine: {json.dumps(current['statusLine'])}")
    else:
        del current["statusLine"]
        print(f"{'would remove' if dry else 'removed'} statusLine from {path}")
if dry:
    if step == "write":
        print(f"would set statusLine in {path} to run {script}")
    sys.exit(0)
if path.exists():
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    print(f"backed up {path} to {backup.name}")
# write where a linked settings.json really lives, keeping its permissions
target = path.resolve()
target.parent.mkdir(parents=True, exist_ok=True)
tmp = target.with_name(target.name + ".tmp")
tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
if target.exists():
    os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
tmp.replace(target)
if step == "write":
    print(f"set statusLine in {path}")
PY
}

if [[ $action == uninstall ]]; then
  # settings first, so Claude Code never points at files that are gone
  [[ $settings == yes ]] && settings_step uninstall
  if [[ -e $DEST/statusline.sh || -L $DEST/statusline.sh ]]; then
    say "remove $DEST"
    [[ $dry == no ]] && rm -rf "$DEST"
  fi
  cat <<EOF

Left in place, for you to remove if you want:
  - your usage files and week log: ${CLAUDE_STATUSLINE_DATA:-$CONFIG/usage-sensor}
  - $DEST/pane in CLAUDE_CODE_PLUGIN_DIRS in settings.json, if you turned
    the side pane on (see docs/pane.md)
  - backups of settings.json next to it (settings.json.bak-*)
  - in repos you set up for the ship column: .git/project-info.json and the
    make target and hooks you added (see docs/install.md)
EOF
  exit 0
fi

# settings first: if they can't be read, stop before touching anything
[[ $settings == yes ]] && settings_step check

say "install to $DEST ($mode)"
if [[ $dry == no ]]; then
  mkdir -p "$DEST"
  for f in "${FILES[@]}"; do
    if [[ $mode == link ]]; then
      ln -sfn "$SRC/$f" "$DEST/$f"
    else
      rm -f "$DEST/$f"  # replaces a link from an earlier --link install
      cp "$SRC/$f" "$DEST/$f"
    fi
  done
  chmod +x "$DEST/statusline.sh" "$DEST/project-info" "$DEST/statusline.py"
  printf '%s\n' "$PYTHON" > "$DEST/python"  # the wrapper runs this one
  # the side pane: the mod and the status line it runs come from one install,
  # so they're always the same version. Its tests stay in the checkout.
  rm -rf "$DEST/pane"  # a link from an earlier --link install, or an older copy
  if [[ $mode == link ]]; then
    ln -sfn "$REPO/pane" "$DEST/pane"
  else
    mkdir -p "$DEST/pane/.claude-plugin" "$DEST/pane/types"
    cp "$REPO/pane/.claude-plugin/plugin.json" "$DEST/pane/.claude-plugin/"
    cp -R "$REPO/pane/hooks" "$DEST/pane/"
    cp "$REPO/pane/types/index.d.ts" "$DEST/pane/types/"
  fi
fi
say "run the status line with $PYTHON"

# and settings last, so they never point at files that failed to install
[[ $settings == yes ]] && settings_step write

cat <<EOF

Next:
  - Restart Claude Code, or start a new session, to see it. If it doesn't
    appear, run /status in Claude Code: your organization's managed settings
    can set statusLine for you, and "disableAllHooks" turns status lines off.
  - Preview it here without Claude Code:  python3 tools/preview.py --all
  - Show CI, deploys and PRs for a repo: see docs/ship-column.md
    (the helper is $DEST/project-info)
  - A side pane with the same parts, in the terminal and the desktop app:
    add $DEST/pane to CLAUDE_CODE_PLUGIN_DIRS (see docs/pane.md)
  - A plugin that says when it's a good moment to /compact:
    https://github.com/drewkhouryorg/claude-plugins
EOF
