#!/usr/bin/env bash
# Fast front for statusline.py. With "refreshInterval": 1, Claude Code calls
# this every second; most calls reprint the last render without starting
# python. python runs when the render is older than MAX_AGE seconds, when
# there is none yet for this session, or when what Claude Code sent or the
# terminal width has changed since (a reply, a /model switch, a resize).

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MAX_AGE=${CLAUDE_STATUSLINE_MAX_AGE:-10}
# the python install.sh checked and recorded, unless you name another
PYTHON=${CLAUDE_STATUSLINE_PYTHON:-}
[[ -z $PYTHON && -f $HERE/python ]] && IFS= read -r PYTHON < "$HERE/python"
PYTHON=${PYTHON:-python3}

input=$(cat)
sid=default
re='"session_id" *: *"([A-Za-z0-9-]+)"'
[[ $input =~ $re ]] && sid=${BASH_REMATCH[1]}
out=$HERE/cache/render-$sid.txt

# what the drawing depends on, minus the session clocks that tick every call.
# =~ uses the system regex and stays fast; an extglob ${input//...} took
# half a second a call in macOS's bash 3.2, and longer as the input grew.
clock='"total_(api_)?duration_ms"[[:space:]]*:[[:space:]]*[0-9.]+'
rest=$input
key="${COLUMNS:-}|${CLAUDE_STATUSLINE_COLUMNS:-}|"
while [[ $rest =~ $clock ]]; do
  before=${rest%%"${BASH_REMATCH[0]}"*}
  key+=$before
  rest=${rest:${#before}+${#BASH_REMATCH[0]}}
done
key+=$rest
prev=
[[ -f $out.key ]] && IFS= read -r -d '' prev < "$out.key"

if [[ -f $out && $prev == "$key" ]]; then
  # GNU stat (Linux) first: BSD stat (macOS) has no -c, so it fails cleanly
  mtime=$(stat -c %Y "$out" 2>/dev/null || stat -f %m "$out" 2>/dev/null || echo 0)
  age=$(( $(date +%s) - mtime ))
  # a render from the future means the clock stepped back: don't trust it
  if (( age >= 0 && age < MAX_AGE )); then
    printf '%s' "$(<"$out")"
    exit 0
  fi
fi

# print the render first; saving it for the next call is a bonus that may fail
render=$(printf '%s' "$input" | "$PYTHON" "$HERE/statusline.py" 2>/dev/null)
if [[ $? -ne 0 || -z $render ]]; then
  printf '\033[2mstatusline: couldn'"'"'t run %s (run install.sh again, or set CLAUDE_STATUSLINE_PYTHON)\033[0m' "$PYTHON"
  exit 0
fi
printf '%s' "$render"
tmp=$out.$$
trap 'rm -f "$tmp"' EXIT
mkdir -p "$HERE/cache" 2>/dev/null && printf '%s' "$render" > "$tmp" 2>/dev/null && mv -f "$tmp" "$out" 2>/dev/null \
  && printf '%s' "$key" > "$tmp" 2>/dev/null && mv -f "$tmp" "$out.key" 2>/dev/null
exit 0
