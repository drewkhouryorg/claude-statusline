# Recorded gh output

What `gh` printed for public PRs and runs in `microsoft/vscode` on 12 and 13 October 2026, trimmed to the fields the ship column's Makefile asks for. The fake `gh` in `tests/test_docs.py` replays these through the Makefile's own `--jq` filters.

| File | Recorded with |
| - | - |
| `pr-list.json` | `gh pr list --json number,isDraft,reviewDecision,statusCheckRollup` |
| `pr-list-expected.json` | `gh pr checks` for each of those PRs, as one word: what the Makefile's PR row must match |
| `run-list.json` | `gh run list -b main -L 5 --json status,conclusion` |
| `pr-list-head.json` | `gh pr list --head <branch> --json statusCheckRollup` for a PR with passing, failing and running checks |
| `pr-list-head-none.json` | the same for a branch with no PR, which is an empty list |
| `pr-checks-expected.json` | `gh pr checks` for that same PR, counted by bucket: what the Makefile's count must match |

Before recording, the Makefile's check counting was compared with `gh pr checks` on 12 open PRs across `cli/cli` and `microsoft/vscode`, and matched on every one.

## handmade/

The same files, written by hand to cover what the recordings happened not to: an approved PR, a draft with no checks, failures from both kinds of check (`CheckRun` and the older `StatusContext`), errors, time-outs, skipped, neutral and cancelled checks, and every kind of CI run. The expected answers follow the buckets `gh pr checks` documents: skipped, neutral and cancelled checks count as neither passing nor failing.
