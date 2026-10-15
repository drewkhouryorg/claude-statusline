// What `statusline.py --json` prints for scenarios/2-bad-day.json at 100
// columns, days starting 7am New York time, which leaves the week a day to
// come: a red 5h tank, failing CI, a failed deploy, a dirty repo, memory
// pressure and two alerts. Written by tools/pane_fixture.py (make
// pane-fixture); tests/test_view.py fails when it is out of date.
import type { View } from '../../types'

export const BAD_DAY: View = {
  "schema": 1,
  "now": 1759400000,
  "tanks": [
    {
      "label": "ctx",
      "pct": 91,
      "tone": "brick",
      "elapsed": null,
      "size": 200000
    },
    {
      "label": "5h",
      "pct": 94,
      "tone": "brick",
      "elapsed": 0.31333333333333335,
      "to_reset": 12360,
      "to_full": 360.0,
      "projected": 300.0
    },
    {
      "label": "wk",
      "pct": 71,
      "tone": "sage",
      "elapsed": 0.8571428571428572,
      "to_reset": 86400,
      "to_full": 211740.84507042254,
      "projected": 82.83333333333333
    }
  ],
  "repo": {
    "git": true,
    "name": "acme-shop",
    "worktree": null,
    "branch": "feat/rewards",
    "sha": null,
    "state": null,
    "marks": [
      {
        "kind": "staged",
        "glyph": "●",
        "count": 7,
        "tone": "sage"
      },
      {
        "kind": "modified",
        "glyph": "✚",
        "count": 4,
        "tone": "olive"
      },
      {
        "kind": "ahead",
        "glyph": "↑",
        "count": 5,
        "tone": "cyan"
      },
      {
        "kind": "behind",
        "glyph": "↓",
        "count": 2,
        "tone": "terra"
      }
    ],
    "status_unknown": false,
    "commit_age": 11400,
    "commit_tone": "terra",
    "pr": {
      "number": 142,
      "url": "https://github.com/acme/acme-shop/pull/142",
      "checks": {
        "text": "✗ 2/12",
        "tone": "brick"
      },
      "review": {
        "text": "⟲ changes",
        "tone": "brick"
      }
    }
  },
  "ship": {
    "ci": [
      {
        "name": "main",
        "url": "https://github.com/acme/acme-shop/actions",
        "runs": [
          "ok",
          "ok",
          "fail",
          "fail",
          "fail"
        ],
        "stale_age": null
      }
    ],
    "deploys": [
      {
        "env": "prod",
        "url": null,
        "status": "fail",
        "version": "v1.43",
        "age": 720,
        "behind": 9,
        "behind_tone": "olive",
        "stale_age": null
      },
      {
        "env": "stg",
        "url": null,
        "status": "running",
        "version": "v1.44",
        "age": null,
        "behind": 0,
        "behind_tone": "olive",
        "stale_age": null
      }
    ],
    "prs": {
      "url": null,
      "open": 4,
      "needs_review": 2,
      "items": [
        {
          "number": "412",
          "url": null,
          "checks": "fail",
          "draft": false
        },
        {
          "number": "409",
          "url": null,
          "checks": "pass",
          "draft": false
        },
        {
          "number": "405",
          "url": null,
          "checks": "pending",
          "draft": false
        },
        {
          "number": "398",
          "url": null,
          "checks": "fail",
          "draft": false
        }
      ],
      "stale_age": 10800
    }
  },
  "session": {
    "model": "Opus 5.5",
    "effort": "xhigh",
    "fast": false,
    "duration": 11400.0,
    "name": "statusline redesign",
    "id": "a1b2c3d4",
    "added": 1200,
    "removed": 480
  },
  "five": {
    "used": 94,
    "state": "out",
    "tone": "brick",
    "to_reset": 12360,
    "to_full": 360.0
  },
  "week": {
    "used": 71,
    "tone": "sage",
    "to_reset": 86400,
    "projected": 82.83333333333333,
    "days": [
      {
        "name": "Fri",
        "pct": 12,
        "number": 12,
        "tone": "sage",
        "when": "past"
      },
      {
        "name": "Sat",
        "pct": 9,
        "number": 9,
        "tone": "sage",
        "when": "past"
      },
      {
        "name": "Sun",
        "pct": 12,
        "number": 12,
        "tone": "sage",
        "when": "past"
      },
      {
        "name": "Mon",
        "pct": 14,
        "number": 14,
        "tone": "sage",
        "when": "past"
      },
      {
        "name": "Tue",
        "pct": 13,
        "number": 13,
        "tone": "sage",
        "when": "past"
      },
      {
        "name": "Wed",
        "pct": 11,
        "number": 11,
        "tone": "sage",
        "when": "now"
      },
      {
        "name": "Thu",
        "pct": 29.0,
        "number": 29,
        "tone": "grey",
        "when": "later"
      }
    ],
    "lines": [
      {
        "text": "71% now",
        "tone": null
      },
      {
        "text": "~83% by Fri 6am",
        "tone": null
      },
      {
        "text": "29% left for Thu",
        "tone": "dim"
      }
    ]
  },
  "system": {
    "cpu": {
      "usage": 100,
      "tone": "brick",
      "waiting": 3,
      "top": "node"
    },
    "memory": {
      "used_pct": 63,
      "pressure": "warn",
      "tone": "terra",
      "comp_mb": 6656,
      "comp_trend": "up",
      "swap_mb": 1843,
      "swap_trend": "up",
      "top": {
        "name": "Chrome",
        "mb": 8294
      }
    },
    "battery": {
      "pct": 22,
      "tone": "terra"
    }
  },
  "alerts": [
    {
      "text": "⚠ migration pending",
      "tone": "olive"
    },
    {
      "text": "cache cold",
      "tone": "olive"
    }
  ],
  "ansi": "\u001b[2m▕\u001b[0m\u001b[1;38;5;16;48;5;131m91\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[1;38;5;16;48;5;131m94\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;108m71\u001b[0m◂   acme-shop             \u001b[2m┃ \u001b[0m\u001b[2m\u001b]8;;https://github.com/acme/acme-shop/actions\u001b\\main  \u001b]8;;\u001b\\\u001b[0m\u001b[38;5;108m✓\u001b[0m\u001b[38;5;108m✓\u001b[0m\u001b[38;5;131m✗\u001b[0m\u001b[38;5;131m✗\u001b[0m\u001b[38;5;131m✗\u001b[0m                   \u001b[2m┃ \u001b[0mOpus 5.5 \u001b[2mxhigh\u001b[0m\u001b[2m · \u001b[0m3h10m\n\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;108m██\u001b[0m\u001b[2m▏\u001b[0m   \u001b[38;5;37mfeat/rewards\u001b[0m          \u001b[2m┃ \u001b[0m\u001b[2mprod  \u001b[0m\u001b[38;5;131m✗ deploy failed\u001b[0m\u001b[2m · \u001b[0m\u001b[2m12m\u001b[0m\u001b[2m \u001b[0m\u001b[2m…\u001b[0m \u001b[2m┃ \u001b[0mstatusline redesign\n\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m◂\u001b[2m▕\u001b[0m\u001b[38;5;108m██\u001b[0m\u001b[2m▏\u001b[0m   \u001b[38;5;108m●7\u001b[0m \u001b[38;5;143m✚4\u001b[0m \u001b[38;5;37m↑5\u001b[0m \u001b[38;5;173m↓2\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;173m3h\u001b[0m      \u001b[2m┃ \u001b[0m\u001b[2mstg   \u001b[0m\u001b[38;5;179m⟳ deploying\u001b[0m             \u001b[2m┃ \u001b[0m\u001b[2ma1b2c3d4\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;108m+1.2k\u001b[0m \u001b[38;5;131m−480\u001b[0m\n\u001b[2mctx  5h  wk \u001b[0m   \u001b[38;5;37m\u001b]8;;https://github.com/acme/acme-shop/pull/142\u001b\\#142\u001b]8;;\u001b\\\u001b[0m \u001b[38;5;131m✗ 2/12\u001b[0m \u001b[38;5;131m⟲ changes\u001b[0m \u001b[2m┃ \u001b[0m\u001b[2mPRs   \u001b[0m\u001b[2m#412\u001b[0m\u001b[2m✗\u001b[0m\u001b[2m \u001b[0m\u001b[2m#409\u001b[0m\u001b[2m✓\u001b[0m\u001b[2m \u001b[0m\u001b[2m#405\u001b[0m\u001b[2m⟳\u001b[0m\u001b[2m \u001b[0m\u001b[2m#398\u001b[0m\u001b[2m…\u001b[0m \u001b[2m┃ \u001b[0m\u001b[38;5;131m5h out ~6m\u001b[0m\u001b[2m · \u001b[0mwk \u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[38;5;108m█\u001b[0m\u001b[2m…\u001b[0m\n\u001b[38;5;143m⚠ \u001b[0m\u001b[38;5;143mmigration pending\u001b[0m\u001b[2m  ·  \u001b[0m\u001b[38;5;143mcache cold\u001b[0m\u001b[2m  ·  \u001b[0m\u001b[38;5;173mbatt 22%\u001b[0m\u001b[2m  ·  \u001b[0m\u001b[38;5;131mcpu ▮▮▮▮▮▮▮▮ 100%\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;131m3 cpu wait\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;131mnode\u001b[0m\u001b[2m  ·  \u001b[0m\u001b[38;5;173mmem p\u001b[0m\u001b[2m…\u001b[0m",
  "blocks": [
    {
      "name": "tanks",
      "lines": [
        "\u001b[2m▕\u001b[0m\u001b[1;38;5;16;48;5;131m91\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[1;38;5;16;48;5;131m94\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;108m71\u001b[0m◂",
        "\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;108m██\u001b[0m\u001b[2m▏\u001b[0m",
        "\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m\u001b[2m▏\u001b[0m\u001b[2m▕\u001b[0m\u001b[38;5;131m██\u001b[0m◂\u001b[2m▕\u001b[0m\u001b[38;5;108m██\u001b[0m\u001b[2m▏\u001b[0m",
        "\u001b[2mctx  5h  wk \u001b[0m"
      ]
    },
    {
      "name": "repo",
      "lines": [
        "acme-shop",
        "\u001b[38;5;37mfeat/rewards\u001b[0m",
        "\u001b[38;5;108m●7\u001b[0m \u001b[38;5;143m✚4\u001b[0m \u001b[38;5;37m↑5\u001b[0m \u001b[38;5;173m↓2\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;173m3h\u001b[0m",
        "\u001b[38;5;37m\u001b]8;;https://github.com/acme/acme-shop/pull/142\u001b\\#142\u001b]8;;\u001b\\\u001b[0m \u001b[38;5;131m✗ 2/12\u001b[0m \u001b[38;5;131m⟲ changes\u001b[0m"
      ]
    },
    {
      "name": "ship",
      "lines": [
        "\u001b[2m\u001b]8;;https://github.com/acme/acme-shop/actions\u001b\\main  \u001b]8;;\u001b\\\u001b[0m\u001b[38;5;108m✓\u001b[0m\u001b[38;5;108m✓\u001b[0m\u001b[38;5;131m✗\u001b[0m\u001b[38;5;131m✗\u001b[0m\u001b[38;5;131m✗\u001b[0m",
        "\u001b[2mprod  \u001b[0m\u001b[38;5;131m✗ deploy failed\u001b[0m\u001b[2m · \u001b[0m\u001b[2m12m\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;143m9 behind\u001b[0m",
        "\u001b[2mstg   \u001b[0m\u001b[38;5;179m⟳ deploying\u001b[0m",
        "\u001b[2mPRs   \u001b[0m\u001b[2m#412\u001b[0m\u001b[2m✗\u001b[0m\u001b[2m \u001b[0m\u001b[2m#409\u001b[0m\u001b[2m✓\u001b[0m\u001b[2m \u001b[0m\u001b[2m#405\u001b[0m\u001b[2m⟳\u001b[0m\u001b[2m \u001b[0m\u001b[2m#398\u001b[0m\u001b[2m✗\u001b[0m\u001b[2m · \u001b[0m\u001b[2m2 need review\u001b[0m\u001b[2m · 3h old\u001b[0m"
      ]
    },
    {
      "name": "session",
      "lines": [
        "Opus 5.5 \u001b[2mxhigh\u001b[0m\u001b[2m · \u001b[0m3h10m",
        "statusline redesign",
        "\u001b[2ma1b2c3d4\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;108m+1.2k\u001b[0m \u001b[38;5;131m−480\u001b[0m"
      ]
    },
    {
      "name": "week",
      "lines": [
        "\u001b[38;5;108m   \u001b[0m\u001b[38;5;108m   \u001b[0m\u001b[38;5;108m   \u001b[0m\u001b[38;5;108m   \u001b[0m\u001b[38;5;108m   \u001b[0m\u001b[38;5;108m   \u001b[0m\u001b[38;5;244m ██\u001b[0m  71% now",
        "\u001b[38;5;108m ▇▇\u001b[0m\u001b[38;5;108m ▅▅\u001b[0m\u001b[38;5;108m ▇▇\u001b[0m\u001b[38;5;108m ██\u001b[0m\u001b[38;5;108m ▇▇\u001b[0m\u001b[38;5;108m ▆▆\u001b[0m\u001b[38;5;244m ██\u001b[0m  ~83% by Fri 6am",
        "\u001b[38;5;108m 12\u001b[0m\u001b[38;5;108m  9\u001b[0m\u001b[38;5;108m 12\u001b[0m\u001b[38;5;108m 14\u001b[0m\u001b[38;5;108m 13\u001b[0m\u001b[38;5;108m 11\u001b[0m\u001b[2m 29\u001b[0m  \u001b[2m29% left for Thu\u001b[0m",
        "\u001b[38;5;108m Fr\u001b[0m\u001b[38;5;108m Sa\u001b[0m\u001b[38;5;108m Su\u001b[0m\u001b[38;5;108m Mo\u001b[0m\u001b[38;5;108m Tu\u001b[0m\u001b[38;5;108m We\u001b[0m\u001b[38;5;244m Th\u001b[0m  \u001b[38;5;131m5h out ~6m\u001b[0m"
      ]
    },
    {
      "name": "system",
      "lines": [
        "\u001b[38;5;131mcpu ▮▮▮▮▮▮▮▮ 100%\u001b[0m",
        "    \u001b[38;5;131m3 cpu wait\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;131mnode\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;173mbatt 22%\u001b[0m",
        "\u001b[38;5;173mmem ▮▮▮▮▮▯▯▯ 63%\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;173mcomp 6.5G\u001b[0m \u001b[38;5;173m↑\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;173mswap 1.8G ↑\u001b[0m",
        "    \u001b[38;5;173mpressure warn\u001b[0m\u001b[2m · \u001b[0m\u001b[38;5;173mChrome 8.1G\u001b[0m"
      ]
    },
    {
      "name": "alerts",
      "lines": [
        "\u001b[38;5;143m⚠ \u001b[0m\u001b[38;5;143mmigration pending\u001b[0m\u001b[2m  ·  \u001b[0m\u001b[38;5;143mcache cold\u001b[0m"
      ]
    }
  ],
  "version": "v0.1.0+041e552*"
}
