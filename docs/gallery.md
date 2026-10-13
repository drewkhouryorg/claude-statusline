# Gallery

Every scenario in [`scenarios/`](../scenarios), drawn at its own width. Run one yourself with
`python3 tools/preview.py <name>`. These pictures come from `tools/screenshots.py`, so they always match the code.

## Healthy

A normal working session: everything green, usage on pace. (120 columns.)

![Healthy](images/scenarios/1-healthy.png)

## Bad day

Everything wrong at once: ctx nearly full, 5h burning out in minutes, CI red, prod deploy failed, stale PR data, low battery, hot CPU. wk is 71% but on day 6, so pace keeps it green. (120 columns.)

![Bad day](images/scenarios/2-bad-day.png)

## No project

A repo that doesn't publish project-info.json: the ship column disappears, so the week chart and the system column fit at 200. (200 columns.)

![No project](images/scenarios/3-no-project.png)

## Narrow

The healthy session in an 80-column terminal: falls back to rows. (80 columns.)

![Narrow](images/scenarios/4-narrow.png)

## First render

First render of a new session outside git: no context, no rate limits, no name yet. (120 columns.)

![First render](images/scenarios/5-first-render.png)

## API key

Signed in with an API key: Claude Code sends no rate limits, so the 5h and wk tanks are empty and the week chart has nothing to draw. (160 columns.)

![API key](images/scenarios/6-api-key.png)

## Week running out

A heavy week: 82% used four days in. At the 7-day average it runs out before the reset, so the forecast turns purple and says when. (200 columns.)

![Week running out](images/scenarios/7-week-running-out.png)

## Limits hit

Both limits hit: the 5h window is full for another 50 minutes and the week until tomorrow afternoon. (200 columns.)

![Limits hit](images/scenarios/8-limits-hit.png)

## Stale project

No Claude turn for three hours, so project-info.json hasn't been refreshed: each section dims and says how old it is. (160 columns.)

![Stale project](images/scenarios/9-stale-project.png)

## Busy repo

A busy repo: a worktree mid-merge with conflicts, a PR with changes requested and checks still running, and seven open PRs, which collapse to counts. (160 columns.)

![Busy repo](images/scenarios/10-busy-repo.png)

## Detached

Checked out a tag to look around: detached HEAD, a clean tree, no PR. (120 columns.)

![Detached](images/scenarios/11-detached.png)

## Linux

A Linux box: no battery, no compressed memory unless zswap is on, so mem shows just how full it is. (200 columns.)

![Linux](images/scenarios/12-linux.png)

## Memory pressure

The Mac is struggling: memory pressure critical and swapping, every core busy with three tasks waiting. With room, the system column names who to blame. (240 columns.)

![Memory pressure](images/scenarios/13-memory-pressure.png)

## Offline

GitHub can't be reached, so each refresh fails: the ship rows dim with their age, and the line under the columns says why. (160 columns.)

![Offline](images/scenarios/14-offline.png)

## One session at five widths

The healthy session as the terminal widens. Below 95 columns it draws rows; from there, columns are added as they fit.

![80 columns](images/widths/healthy-80.png)

![120 columns](images/widths/healthy-120.png)

![160 columns](images/widths/healthy-160.png)

![200 columns](images/widths/healthy-200.png)

![240 columns](images/widths/healthy-240.png)
