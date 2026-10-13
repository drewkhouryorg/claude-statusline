# project-info.json

A repo publishes facts about itself (CI, deploys, PRs) to one JSON file. The
status line reads it, and so can hooks, agents and scripts. The status line
never runs repo code; it only reads this file. Each field is checked against
the schema below as it's read, so a wrong one is dropped instead of breaking
the line.

## Where it lives

`$(git rev-parse --git-common-dir)/project-info.json`, normally `.git/project-info.json`.
Git never commits it, nothing needs gitignoring, and all worktrees share it.
Run `project-info path` to print it.

## Schema 1

Every section is optional. Leave out what a project doesn't have.

```json
{
  "schema": 1,
  "stale_after": 900,
  "ci": {
    "main": { "runs": ["ok", "ok", "ok", "fail", "ok"], "url": "…", "updated_at": 1759398000 }
  },
  "deploy": {
    "prod": { "version": "v1.42", "status": "ok", "deployed_at": 1759392800,
              "behind": 3, "url": "…", "updated_at": 1759398000 },
    "stg":  { "version": "v1.43", "status": "running", "updated_at": 1759398000 }
  },
  "prs": { "open": 3, "needs_review": 1, "url": "…", "updated_at": 1759398000,
           "items": [{ "number": 126, "checks": "pending", "url": "…" },
                     { "number": 125, "checks": "pass", "draft": true },
                     { "number": 124, "checks": "fail" }] },
  "branches": {
    "feat/rewards": { "checks": { "pass": 12, "fail": 0, "pending": 0 }, "updated_at": 1759398000 }
  },
  "extra": [
    { "icon": "alert", "text": "migration pending", "state": "warn", "updated_at": 1759398000 }
  ]
}
```

| Field | Meaning |
| - | - |
| `updated_at` | Epoch seconds when this section was last fetched. The helper stamps it for you. |
| `stale_after` | Seconds before a section counts as stale and renders dimmed with its age. Top level sets the default (900); any section can override it. |
| `ci.<branch>.runs` | Up to the last 5 runs, oldest first. Each is `ok`, `fail`, `running` or `cancelled`. |
| `deploy.<env>.status` | `ok`, `fail` or `running`. Environments render in file order. |
| `deploy.<env>.deployed_at` | When that deploy happened, as distinct from when it was checked. |
| `deploy.<env>.behind` | Commits on main that aren't deployed yet. |
| `prs.items` | Optional. Each open PR, newest first, with its checks in one word: `pass`, `fail`, `pending` or `none` (no checks yet). One failed check makes the PR `fail` even while others run. Up to four render one by one (`#126⟳ #125✓ #124✗`); more collapse to counts per state. Without it the row shows only the open count. |
| `branches.<name>.checks` | Check counts for that branch's PR. The PR number and review state come from Claude Code itself. |
| `extra[].icon` | `alert`, `info`, `pr`, `ci`, `deploy` or `issue`. |
| `extra[].state` | `ok`, `warn`, `bad`, `info` or `muted`. |
| `url` | Optional. Makes the label clickable (Cmd+click on a Mac) in terminals that support links, such as iTerm2, WezTerm and kitty. Only `https://` and `http://` links are used. |
| `error`, `tried_at` | Written by `project-info refresh` when a refresh fails: what went wrong, and when. The old data stays. Once the section is stale, the status line shows the error under the columns. |

Other keys are allowed and ignored by the status line, so a repo can publish
whatever else its tools want to read.

Names of CI branches and deploy environments show as their first 5 characters, so `production` shows as `produ`. Up to two CI branches show.

Only four ship rows fit (CI, deploys and PRs). When there are more, healthy
rows are dropped first, so a failure or warning always shows. `extra` notices
don't take a ship row: they go on the alerts line under the columns.

## Writing it

`install.sh` puts the helper at `~/.claude/claude-statusline/project-info`.
Add that folder to your PATH, or call it by its full path as the
[ship column's Makefile](ship-column.md) does. It needs only python3 and git.

Use the helper rather than writing JSON by hand. It merges, stamps
`updated_at`, locks, and writes atomically. Keys are separate arguments, so
branch names with dots or slashes work as-is.

```sh
project-info set deploy prod '{"version": "v1.43", "status": "ok", "deployed_at": 1759400000}'
project-info get deploy prod
project-info fresh prs 120     # exit 0 when younger than 120s
```

For anything a hook refreshes often, use `refresh`. It runs a command only
when the section is older than the window you give, and what the command
prints replaces the section:

```sh
project-info refresh prs 120 -- gh pr list --json number --jq '{open: length}'
```

- A section that's still fresh starts nothing, so it's cheap to call after
  every turn.
- Only one process refreshes a section at a time. Other sessions skip it.
- The command succeeds when it prints a JSON object, whatever its exit
  code, because `gh pr checks` exits 8 while checks are pending.
- When it fails, the old data stays, and `error` and `tried_at` are saved.
  The next try waits a full window.
- `--force` skips the window, for refreshing right after a push.

To set a repo up with a Makefile and Claude Code hooks, see [setting up the ship column](ship-column.md).
