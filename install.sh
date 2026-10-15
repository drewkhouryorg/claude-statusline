#!/usr/bin/env bash
# Install the status line and point Claude Code at it.
#
#   ./install.sh              copy the files and set up settings.json
#   ./install.sh --link       symlink instead of copy, so a `git pull` here updates it
#   ./install.sh --dry-run    say what would change, change nothing
#   ./install.sh --no-settings   copy the files only; change no settings
#   ./install.sh --uninstall  remove it, and put back the statusLine you had before
#
# It installs into Claude Code's config folder: $CLAUDE_CONFIG_DIR, or
# ~/.claude. In settings.json it sets statusLine, and adds the side pane to
# CLAUDE_CODE_PLUGIN_DIRS; the pane stays closed until you open it. Every
# other setting is kept, and the file is backed up first. Running this again
# is safe.
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
    -h|--help) awk 'NR > 1 && !/^#/ { exit } NR > 1 { sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is needed (3.8 or later)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || { echo "python3 is too old: 3.8 or later" >&2; exit 1; }

# The status line runs in every project. A version manager's shim (pyenv,
# asdf, mise) would pick each project's pinned python, so record the real one.
PYTHON=$(command -v python3)
case $PYTHON in */shims/*) PYTHON=$(python3 -c 'import sys; print(sys.executable)') ;; esac

show() { case $1 in "$HOME"/*) printf '~%s\n' "${1#"$HOME"}" ;; *) printf '%s\n' "$1" ;; esac; }  # ~ for home

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
DIRS = "CLAUDE_CODE_PLUGIN_DIRS"


def show(p):  # ~ for home, as the shell half prints it
    p, home = str(p), os.path.expanduser("~")
    return "~" + p[len(home):] if p.startswith(home + os.sep) else p


# Claude Code runs the command through a shell: quote a path with spaces
want = {"type": "command", "command": shlex.quote(script), "refreshInterval": 5}
ours = (want["command"], script)
previous = dest / "previous-statusline.json"
pane = show(dest / "pane")  # Claude Code expands ~ in this list
try:
    current = json.loads(path.read_text()) if path.exists() else {}
except ValueError as e:
    sys.exit(f"{path} isn't valid JSON ({e}); fix it, or rerun with --no-settings")
if not isinstance(current, dict):
    sys.exit(f"{path} isn't a JSON object; fix it, or rerun with --no-settings")
env = current.get("env", {})
if not isinstance(env, dict) or not isinstance(env.get(DIRS, ""), str):
    sys.exit(f'"env" in {path} isn\'t what Claude Code expects; fix it, or rerun with --no-settings')
if step == "check":
    sys.exit(0)


def said(line):  # a status line as its command, when it has one
    return line["command"] if isinstance(line, dict) and isinstance(line.get("command"), str) else json.dumps(line)


def is_pane(entry):
    return os.path.normpath(os.path.expanduser(entry)) == os.path.normpath(str(dest / "pane"))


dirs = [d for d in env.get(DIRS, "").split(":") if d]
old = current.get("statusLine")
mine = isinstance(old, dict) and old.get("command") in ours
rows = []  # (setting, what happens to it)
if step == "write":
    if mine:  # installing again keeps the interval or padding you set on this computer
        want = {**old, "type": "command", "command": want["command"]}
    if old == want:
        rows.append(("statusLine", "already set"))
    else:
        every = f" every {want['refreshInterval']}s" if want.get("refreshInterval") else ""
        rows.append(("statusLine", f"runs {show(script)}{every}"))
        if old and not mine:
            rows.append(("", f"replaces: {said(old)} (--uninstall puts it back)"))
            if not dry:
                previous.write_text(json.dumps(old, indent=2) + "\n")
        current["statusLine"] = want
    if any(is_pane(d) for d in dirs):
        rows.append((DIRS, "already has the side pane"))
    else:
        env[DIRS] = ":".join(dirs + [pane])
        current["env"] = env
        rows.append((DIRS, f"adds {pane}"))
else:  # uninstall
    if not mine:
        rows.append(("statusLine", "isn't this one, so it's left alone" if old else "not set by this install"))
    elif previous.exists():
        current["statusLine"] = json.loads(previous.read_text())
        rows.append(("statusLine", f"back to: {said(current['statusLine'])}"))
    else:
        del current["statusLine"]
        rows.append(("statusLine", "removed"))
    if any(is_pane(d) for d in dirs):
        kept = [d for d in dirs if not is_pane(d)]
        if kept:
            env[DIRS] = ":".join(kept)
        else:
            del env[DIRS]
            if not env:
                del current["env"]
        rows.append((DIRS, f"removes {pane}"))

changes = [r for r in rows if not r[1].startswith(("already", "isn't", "not set"))]
if not changes:
    print(f"{show(path)} is already set up." if step == "write" else f"Nothing to change in {show(path)}.")
    sys.exit(0)
stamp = time.strftime('%Y%m%d-%H%M%S')
backup = path.with_name(f"{path.name}.bak-{stamp}")
n = 1
while backup.exists():  # two runs in one second keep both backups
    n += 1
    backup = path.with_name(f"{path.name}.bak-{stamp}-{n}")
if not path.exists():
    print(f"{'Would create' if dry else 'Creating'} {show(path)}:")
elif dry:
    print(f"Would change {show(path)}, backing it up first:")
else:
    shutil.copy2(path, backup)
    print(f"Changing {show(path)}, backed up to {backup.name}:")
width = max(len(r[0]) for r in rows)
for name, what in rows:
    print(f"  {name:<{width}}   {what}")
if dry:
    sys.exit(0)
# write where a linked settings.json really lives, keeping its permissions
target = path.resolve()
target.parent.mkdir(parents=True, exist_ok=True)
tmp = target.with_name(target.name + ".tmp")
tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
if target.exists():
    os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
tmp.replace(target)
PY
}

[[ $dry == yes ]] && { echo "Dry run: nothing is changed."; echo; }

if [[ $action == uninstall ]]; then
  # settings first, so Claude Code never points at files that are gone
  [[ $settings == yes ]] && settings_step uninstall
  if [[ -e $DEST/statusline.sh || -L $DEST/statusline.sh ]]; then
    echo
    if [[ $dry == yes ]]; then
      echo "Would remove $(show "$DEST")."
    else
      rm -rf "$DEST"
      echo "Removed $(show "$DEST")."
    fi
  fi
  cat <<EOF

Left for you to remove if you want:
  - usage files and the week log: $(show "${CLAUDE_STATUSLINE_DATA:-$CONFIG/usage-sensor}")
  - settings.json backups: $(show "$SETTINGS").bak-*
  - the ship column's setup in your repos (docs/ship-column.md)
EOF
  exit 0
fi

# settings first: if they can't be read, stop before touching anything
[[ $settings == yes ]] && settings_step check

how="as copies"; [[ $mode == link ]] && how="as links to this checkout"
[[ $dry == yes ]] && verb="Would install" || verb=Installing
cat <<EOF
$verb to $(show "$DEST") ($how):
  statusline.sh, statusline.py   the status line, run with $(show "$PYTHON")
  project-info                   the ship column's helper
  pane/                          the side pane

EOF
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

# and settings last, so they never point at files that failed to install
if [[ $settings == yes ]]; then
  settings_step write
else
  echo "$(show "$SETTINGS") is left alone (--no-settings). docs/install.md says what to set."
fi

[[ $dry == yes ]] && exit 0
cat <<EOF

Next:
  - Start a new Claude Code session to see it. If it doesn't show, run /status
    in Claude Code.
  - Type /statusline-pane to open the side pane. To open it in every session,
    turn on "Open the status pane by itself" in /config.
  - To show CI, deploys and PRs for a repo, see docs/ship-column.md.
EOF
